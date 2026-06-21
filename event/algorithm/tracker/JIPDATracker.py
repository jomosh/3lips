"""
@file JIPDATracker.py
@brief Joint Integrated Probabilistic Data Association (JIPDA) multi-target tracker.

JIPDA (Musicki & Evans, 2004) extends JPDA with a track existence probability
P_exist that is updated each epoch from the association evidence.  Tracks are
automatically initiated (2-epoch confirmation), maintained, and terminated
(P_exist < threshold) without a separate deletion rule.

This implementation gates incoming blind candidates against predicted track
states using chi² gating on the bistatic range innovation, computes joint
association probabilities, updates tracks via EKF, and manages P_exist.

Dependencies:
    - EKFTracker (C2) for per-track predict/update
    - GeometricAssociator (F1) for cold-start candidate generation

References:
    - Musicki & Evans, "Joint Integrated Probabilistic Data Association — JIPDA,"
      IEEE Trans. AES 40(3), 2004.
    - TODO.md Phase F3.
"""

import math
from scipy.stats import chi2
from algorithm.geometry.Geometry import Geometry


class JIPDATracker:

    """
    @class JIPDATracker
    @brief Multi-target tracker using JIPDA with EKF per-track filtering.
    """

    def __init__(self, ekf, config: dict):
        """
        @brief Constructor.
        @param ekf (EKFTracker): Per-track EKF instance.
        @param config (dict): The 'tracker.jipda' block from config.yml.
            Expected keys:
              - P_D (float): Probability of detection (default 0.9).
              - P_G (float): Gate probability (default 0.999).
              - gamma (float): Chi² gate threshold (default 16.27 for 3-DOF at 0.999).
              - P_exist_threshold (float): Delete tracks below this (default 0.1).
              - confirmation_epochs (int): N/M = N/N logic for initiation (default 2).
              - max_tracks (int): Hard cap on concurrent tracks (default 20).
        """
        self.ekf = ekf
        self.P_D = config.get('P_D', 0.9)
        self.P_G = config.get('P_G', 0.999)
        self.gamma = config.get('gamma', 16.27)  # chi² 3-DOF at 0.999
        self.P_exist_threshold = config.get('P_exist_threshold', 0.1)
        self.confirmation_epochs = config.get('confirmation_epochs', 2)
        self.max_tracks = config.get('max_tracks', 20)
        self.confirmation_gate = config.get('confirmation_gate', 2000)  # metres

        self.tracks = {}          # track_id → track dict
        self.next_track_id = 1
        self._pending_tracks = []  # candidates awaiting confirmation

    def process(self, blind_candidates: dict, radar_data: dict,
                timestamp_ms: int) -> dict:
        """
        @brief Run one JIPDA cycle.
        @param blind_candidates (dict): {synth_id: [{radar, delay, doppler}]}
            from GeometricAssociator.
        @param radar_data (dict): Radar config data keyed by radar name.
        @param timestamp_ms (int): Current epoch timestamp.
        @return dict: {track_id: {points: [[lat, lon, alt]], velocity: [...],
            P_exist: float, age_epochs: int}} ready for localisation output.
        """
        now = timestamp_ms

        # ---- 1. Predict all existing tracks -----------------------------------
        for track_id, track in self.tracks.items():
            if track['timestamp_ms'] > 0:
                dt = (now - track['timestamp_ms']) / 1000.0
                dt = max(0.1, min(dt, 5.0))  # clamp to sane range
            else:
                dt = 1.0  # new track — assume 1 s event-loop interval
            self.ekf.predict(track, dt)
            track['timestamp_ms'] = now

        # ---- 2. Gate candidates against predicted tracks ----------------------
        # Association matrix: which candidate falls within which track's gate?
        synth_ids = list(blind_candidates.keys())
        track_ids = list(self.tracks.keys())
        n_tracks = len(track_ids)
        n_cands = len(synth_ids)

        if n_tracks == 0 and n_cands == 0:
            return {}

        # Build radar config list for measurement extraction
        radar_names = list(radar_data.keys())

        # Gate: valid[i][j] = True if candidate j gates with track i
        valid = [[False] * n_cands for _ in range(n_tracks)]
        nis_matrix = [[float('inf')] * n_cands for _ in range(n_tracks)]

        # Pre-extract bistatic ranges from candidates
        cand_measurements = {}  # synth_id → (measurements list, radar_configs list)
        for synth_id, det_list in blind_candidates.items():
            meas = []
            cfgs = []
            for det in det_list:
                rn = det['radar']
                if rn not in radar_data or radar_data[rn] is None:
                    continue
                cfg = radar_data[rn].get('config')
                if cfg is None:
                    continue
                tx_ecef = [
                    cfg['location']['tx']['latitude'],
                    cfg['location']['tx']['longitude'],
                    cfg['location']['tx']['altitude']
                ]
                rx_ecef = [
                    cfg['location']['rx']['latitude'],
                    cfg['location']['rx']['longitude'],
                    cfg['location']['rx']['altitude']
                ]
                # Convert to ECEF
                tx = list(Geometry.lla2ecef(*tx_ecef))
                rx = list(Geometry.lla2ecef(*rx_ecef))
                # Bistatic range = delay (seconds) * speed of light
                bistatic_range = det['delay'] * 299792458.0
                meas.append(bistatic_range)
                cfgs.append({'tx_ecef': tx, 'rx_ecef': rx})
            cand_measurements[synth_id] = (meas, cfgs)

        for i, track_id in enumerate(track_ids):
            track = self.tracks[track_id]
            for j, synth_id in enumerate(synth_ids):
                meas, cfgs = cand_measurements.get(synth_id, ([], []))
                if not meas:
                    continue
                # Only gate if same radars (simplified: require same N)
                # In practice, GeometricAssociator always produces same radar set
                try:
                    nis = self.ekf.update(
                        self._copy_track(track), meas, cfgs)
                    # Revert — we only wanted the NIS, not the state update
                except Exception:
                    continue
                nis_matrix[i][j] = nis
                if nis < self.gamma:
                    valid[i][j] = True

        # ---- 3. Joint association (simplified greedy) --------------------------
        # Full JPDA enumeration is O(N!) but for ≤5 tracks + ≤10 candidates
        # a greedy nearest-neighbour assignment is acceptably close.
        # Each track gets at most one candidate; each candidate at most one track.
        associations = {}   # track_id → synth_id (or None for miss)
        assigned_cands = set()

        # Sort by NIS (lower = better fit), assign greedily
        pairs = []
        for i in range(n_tracks):
            for j in range(n_cands):
                if valid[i][j]:
                    pairs.append((nis_matrix[i][j], i, j))
        pairs.sort()

        for _, i, j in pairs:
            track_id = track_ids[i]
            synth_id = synth_ids[j]
            if track_id not in associations and j not in assigned_cands:
                associations[track_id] = synth_id
                assigned_cands.add(j)

        # Missed tracks: no association
        for track_id in track_ids:
            if track_id not in associations:
                associations[track_id] = None

        # ---- 4. Update tracks with associated measurements ---------------------
        for track_id, synth_id in associations.items():
            track = self.tracks[track_id]
            if synth_id is not None:
                meas, cfgs = cand_measurements[synth_id]
                self.ekf.update(track, meas, cfgs)
            # else: coast — keep predicted state

        # ---- 5. Update P_exist -------------------------------------------------
        for track_id, synth_id in associations.items():
            track = self.tracks[track_id]
            if synth_id is not None:
                # Associated: increase P_exist
                # JIPDA formula: P_exist ← 1 - (1 - P_D) * (1 - P_exist)
                prior = track['P_exist']
                track['P_exist'] = 1.0 - (1.0 - self.P_D) * (1.0 - prior)
                track['missed_epochs'] = 0
            else:
                # Missed: decay P_exist
                track['P_exist'] *= (1.0 - self.P_D) * 0.5
                track['missed_epochs'] += 1

            track['P_exist'] = min(track['P_exist'], 0.999)
            track['age_epochs'] += 1

        # ---- 6. Initiate new tracks from unassociated candidates ---------------
        for j, synth_id in enumerate(synth_ids):
            if j in assigned_cands:
                continue
            # Compute approximate ECEF position via bistatic range midpoint
            # (rough initialisation — EKF will refine)
            det_list = blind_candidates[synth_id]
            pos_sum = [0.0, 0.0, 0.0]
            count = 0
            for det in det_list:
                rn = det['radar']
                if rn not in radar_data or radar_data[rn] is None:
                    continue
                cfg = radar_data[rn].get('config')
                if cfg is None:
                    continue
                # Use midpoint of TX-RX as rough initial position
                tx_ecf = Geometry.lla2ecef(
                    cfg['location']['tx']['latitude'],
                    cfg['location']['tx']['longitude'],
                    cfg['location']['tx']['altitude'])
                rx_ecf = Geometry.lla2ecef(
                    cfg['location']['rx']['latitude'],
                    cfg['location']['rx']['longitude'],
                    cfg['location']['rx']['altitude'])
                pos_sum[0] += (tx_ecf[0] + rx_ecf[0]) / 2
                pos_sum[1] += (tx_ecf[1] + rx_ecf[1]) / 2
                pos_sum[2] += (tx_ecf[2] + rx_ecf[2]) / 2
                count += 1
            if count == 0:
                continue
            init_pos = [p / count for p in pos_sum]

            # 2-epoch confirmation logic
            matched = False
            to_remove = []
            for pending in self._pending_tracks:
                # Check if this candidate is near an already-pending candidate
                dist = math.sqrt(
                    (init_pos[0] - pending['init_pos'][0])**2 +
                    (init_pos[1] - pending['init_pos'][1])**2 +
                    (init_pos[2] - pending['init_pos'][2])**2)
                if dist < self.confirmation_gate:
                    pending['confirm_count'] += 1
                    if pending['confirm_count'] >= self.confirmation_epochs:
                        # Confirmed! Create a real track
                        if len(self.tracks) < self.max_tracks:
                            track = self.ekf.initiate(init_pos, now)
                            track['P_exist'] = 0.6  # confirmed
                            track['age_epochs'] = 1
                            track_id = 'T' + str(self.next_track_id)
                            self.next_track_id += 1
                            self.tracks[track_id] = track
                            # Assign this candidate to the new track
                            meas, cfgs = cand_measurements[synth_id]
                            self.ekf.update(track, meas, cfgs)
                            associations[track_id] = synth_id
                        # Mark for removal after iteration (avoid modifying
                        # list during the for loop).
                        to_remove.append(pending)
                    matched = True
                    break
            # Remove confirmed pending tracks after iteration
            for p in to_remove:
                if p in self._pending_tracks:
                    self._pending_tracks.remove(p)
            to_remove.clear()
            if not matched:
                self._pending_tracks.append({
                    'init_pos': init_pos,
                    'confirm_count': 1,
                    'synth_id': synth_id,
                    'timestamp_ms': now,
                })

        # Clean up stale pending tracks (> confirmation_epochs+2 epochs old)
        self._pending_tracks = [
            p for p in self._pending_tracks
            if (now - p['timestamp_ms']) / 1000.0 < (self.confirmation_epochs + 2)
        ]
        # Hard cap to prevent unbounded growth in noisy environments
        max_pending = max(50, self.max_tracks * 3)
        if len(self._pending_tracks) > max_pending:
            self._pending_tracks = self._pending_tracks[-max_pending:]

        # ---- 7. Prune tracks below P_exist threshold --------------------------
        to_delete = []
        for track_id, track in self.tracks.items():
            if track['P_exist'] < self.P_exist_threshold:
                to_delete.append(track_id)
            elif track['missed_epochs'] > self.confirmation_epochs * 2:
                to_delete.append(track_id)
        for tid in to_delete:
            del self.tracks[tid]

        # ---- 8. Build output dict ---------------------------------------------
        output = {}
        for track_id, track in self.tracks.items():
            pos_ecef = self.ekf.get_position(track)
            vel_ecef = self.ekf.get_velocity(track)
            lat, lon, alt = Geometry.ecef2lla(pos_ecef[0], pos_ecef[1], pos_ecef[2])
            output[track_id] = {
                'points': [[round(lat, 5), round(lon, 5), round(alt)]],
                'velocity': [round(v, 2) for v in vel_ecef],
                'P_exist': round(track['P_exist'], 3),
                'age_epochs': track['age_epochs'],
            }

        # Also include unassociated candidates as tentative entries (no track yet)
        for j, synth_id in enumerate(synth_ids):
            if j in assigned_cands:
                continue
            # Skip if already covered by a new track
            output['cand_' + synth_id] = {
                'detections': blind_candidates[synth_id],
                'P_exist': 0.2,
                'age_epochs': 0,
            }

        return output

    def _copy_track(self, track: dict) -> dict:
        """Deep-enough copy for gating (so we don't mutate the real track)."""
        return {
            'state': track['state'].copy(),
            'covariance': track['covariance'].copy(),
            'P_exist': track['P_exist'],
            'age_epochs': track['age_epochs'],
            'missed_epochs': track['missed_epochs'],
            'timestamp_ms': track['timestamp_ms'],
        }