"""
@file EKFTracker.py
@brief Extended Kalman Filter for a single target tracked via bistatic range.

State vector (ECEF):
    [x, y, z, vx, vy, vz]   — position + velocity in metres, m/s

Process model: constant velocity with continuous white-noise acceleration
    xₖ = F · xₖ₋₁ + wₖ       where wₖ ~ N(0, Q)

Measurement model: N bistatic ranges (one per radar)
    zᵢ(x) = |x - txᵢ| + |x - rxᵢ|   with independent R per radar

References:
  - Bar-Shalom, Li, & Kirubarajan, "Estimation with Applications to Tracking
    and Navigation," Wiley, 2001, Chapter 6.
  - TODO.md Phase C2.
"""

import numpy as np
import math


class EKFTracker:

    """
    @class EKFTracker
    @brief Single-target EKF with constant-velocity process model and
    bistatic range measurement model.
    """

    def __init__(self, config: dict):
        """
        @brief Constructor.
        @param config (dict): The 'tracker.ekf' block from config.yml.
            Expected keys:
              - process_noise_q (float): m²/s³ — continuous white noise acceleration.
              - measurement_noise_r (float): m² — bistatic range variance.
        """
        self.q = config.get('process_noise_q', 1.0)       # m²/s³
        self.R = config.get('measurement_noise_r', 2500.0)  # m²
        self.state_dim = 6

    def initiate(self, ecef_position: list, timestamp_ms: int) -> dict:
        """
        @brief Create a new track from an initial position estimate.
        @param ecef_position (list): [x, y, z] in metres.
        @param timestamp_ms (int): Epoch timestamp.
        @return dict: Track object with state, covariance, existence probability,
            age, and timestamp.
        """
        P0 = np.eye(self.state_dim, dtype=float)
        # Position uncertainty ~500m, velocity uncertainty ~50 m/s
        P0[0, 0] = P0[1, 1] = P0[2, 2] = 250000.0   # 500²
        P0[3, 3] = P0[4, 4] = P0[5, 5] = 2500.0      # 50²

        return {
            'state': np.array([
                ecef_position[0], ecef_position[1], ecef_position[2],
                0.0, 0.0, 0.0
            ], dtype=float),
            'covariance': P0,
            'P_exist': 0.3,          # tentative — confirmed after 2 epochs
            'age_epochs': 0,
            'missed_epochs': 0,
            'timestamp_ms': timestamp_ms,
        }

    def predict(self, track: dict, dt: float) -> dict:
        """
        @brief Predict track state forward by dt seconds.
        @details Constant-velocity model.  F and Q are standard.
        @param track (dict): Track dict (mutated in-place).
        @param dt (float): Time step in seconds.
        """
        x = track['state']
        P = track['covariance']

        # State transition matrix F
        F = np.eye(self.state_dim, dtype=float)
        F[0, 3] = dt
        F[1, 4] = dt
        F[2, 5] = dt

        # Process noise covariance Q (continuous white noise acceleration)
        dt2 = dt * dt
        dt3 = dt2 * dt / 3.0
        dt2_2 = dt2 / 2.0
        Q = np.zeros((self.state_dim, self.state_dim), dtype=float)
        Q[0, 0] = Q[1, 1] = Q[2, 2] = self.q * dt3
        Q[0, 3] = Q[3, 0] = self.q * dt2_2
        Q[1, 4] = Q[4, 1] = self.q * dt2_2
        Q[2, 5] = Q[5, 2] = self.q * dt2_2
        Q[3, 3] = Q[4, 4] = Q[5, 5] = self.q * dt

        track['state'] = F @ x
        track['covariance'] = F @ P @ F.T + Q

    def update(self, track: dict, measurements: list,
               radar_configs: list) -> float:
        """
        @brief EKF update with bistatic range measurements from N radars.
        @details Each measurement = bistatic range in metres.
        @param track (dict): Track dict (mutated in-place).
        @param measurements (list): Bistatic range measurements (metres) in
            same order as radar_configs.
        @param radar_configs (list): List of dicts with tx_ecef and rx_ecef
            keys, each [x, y, z] in metres.
        @return float: Normalised innovation squared (NIS) — for gating.
        """
        x = track['state']
        P = track['covariance']

        n_meas = len(measurements)
        pos = x[:3]

        # Build measurement vector z, predicted h, Jacobian H
        z = np.array(measurements, dtype=float)
        h_pred = np.zeros(n_meas, dtype=float)
        H = np.zeros((n_meas, self.state_dim), dtype=float)

        for i, cfg in enumerate(radar_configs):
            tx = np.array(cfg['tx_ecef'], dtype=float)
            rx = np.array(cfg['rx_ecef'], dtype=float)
            d_tx = pos - tx
            d_rx = pos - rx
            r_tx = np.linalg.norm(d_tx)
            r_rx = np.linalg.norm(d_rx)

            if r_tx < 1e-3 or r_rx < 1e-3:
                # Target at or extremely near a radar site — degenerate
                r_tx = max(r_tx, 1e-3)
                r_rx = max(r_rx, 1e-3)

            h_pred[i] = r_tx + r_rx
            # Jacobian: ∂h/∂x = (x - tx)/|x - tx| + (x - rx)/|x - rx|
            #          ∂h/∂v = 0
            H[i, :3] = d_tx / r_tx + d_rx / r_rx

        # Innovation
        y = z - h_pred
        R_diag = np.full(n_meas, self.R, dtype=float)
        R = np.diag(R_diag)
        S = H @ P @ H.T + R
        K = P @ H.T @ np.linalg.inv(S)

        # Update state and covariance
        track['state'] = x + K @ y
        track['covariance'] = (np.eye(self.state_dim) - K @ H) @ P

        # Normalised innovation squared (chi² with n_meas DOF)
        nis = float(y @ np.linalg.inv(S) @ y)
        return nis

    def get_position(self, track: dict) -> list:
        """
        @brief Extract ECEF position from track state.
        @param track (dict): Track dict.
        @return list: [x, y, z] in metres.
        """
        return track['state'][:3].tolist()

    def get_velocity(self, track: dict) -> list:
        """
        @brief Extract ECEF velocity from track state.
        @param track (dict): Track dict.
        @return list: [vx, vy, vz] in m/s.
        """
        return track['state'][3:].tolist()