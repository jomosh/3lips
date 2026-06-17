"""
@file GeometricAssociator.py
@brief Blind (ADS-B-free) cross-radar detection association via geometric enumeration.

Each radar sees M bistatic (delay, Doppler) detections.  With N radars there are
M^N possible cross-radar detection tuples.  We enumerate them, verify that the
corresponding bistatic ellipses/ellipsoids mutually intersect within a spatial
threshold (geometric consistency), filter by Doppler sign consistency, deduplicate
survivors, and return {synthetic_id: [{radar, delay, doppler}]} in the same
schema as AdsbAssociator so localisation code is unchanged.

References:
  - Malanowski & Kulpa, "Two methods for target localization in multistatic
    passive radar," IEEE Trans. AES 48(1), 2012.
  - TODO.md Phase F1 (full specification).
"""

import itertools
import hashlib
import math
import numpy as np

from data.Ellipsoid import Ellipsoid
from algorithm.geometry.Geometry import Geometry


class GeometricAssociator:

    """
    @class GeometricAssociator
    @brief Associate detections from 2+ radars without ADS-B truth.
    @details Uses geometric enumeration: generate all cross-radar N-tuples
    of detections, test bistatic ellipse/ellipsoid intersection via sampled
    ECEF points, filter by Doppler sign consistency, and deduplicate.
    Produces output in the same {id: [{radar, delay, doppler}]} schema
    as AdsbAssociator.
    """

    def __init__(self, config: dict):
        """
        @brief Constructor.
        @param config (dict): The 'associate.geometric' block from config.yml.
            Expected keys: threshold, nSamples, doppler_tolerance, max_detections.
        """
        self.threshold = config.get('threshold', 500)          # metres
        self.nSamples = config.get('nSamples', 50)             # ellipse samples
        self.doppler_tolerance = config.get('doppler_tolerance', 5)  # Hz
        self.max_detections = config.get('max_detections', 20) # per-radar guard

    def process(self, radar_list: list, radar_data: dict,
                timestamp: int) -> dict:
        """
        @brief Associate detections from N radars.
        @param radar_list (list): List of radar names to associate.
        @param radar_data (dict): {radar_name: {"detection": {...}, "config": {...}}}.
        @param timestamp (int): Epoch timestamp in milliseconds (unused; accepted
            for API compatibility with AdsbAssociator).
        @return dict: {synthetic_hex: [{radar, delay, doppler}]}.
        """
        output = {}

        # ---- 1. Build per-radar detection lists --------------------------------
        detection_lists = []          # list of lists of (delay, doppler)
        radar_names_valid = []        # only radars with valid data
        for radar_name in radar_list:
            rd = radar_data.get(radar_name)
            if rd is None or rd.get("config") is None or rd.get("detection") is None:
                continue
            det = rd["detection"]
            delays = det.get("delay", [])
            dopplers = det.get("doppler", [])
            if not delays:
                continue
            # Clutter guard: skip epoch if too many detections per radar
            if len(delays) > self.max_detections:
                return {}
            det_pairs = list(zip(delays, dopplers))
            detection_lists.append(det_pairs)
            radar_names_valid.append(radar_name)

        # Need at least 3 radars for reliable blind association
        n_radars = len(detection_lists)
        if n_radars < 3:
            return {}

        # ---- 2. Enumerate all cross-radar N-tuples ----------------------------
        # Each tuple = ((delay_0, doppler_0), (delay_1, doppler_1), ...)
        candidates = list(itertools.product(*detection_lists))

        # ---- 3. Pre-compute ellipsoid & sample points for every detection ------
        # Key: (radar_idx, detection_idx) → ECEF point array (S, 3)
        sample_cache = {}
        for r_idx, radar_name in enumerate(radar_names_valid):
            rd = radar_data[radar_name]
            config = rd["config"]
            tx_ecef = Geometry.lla2ecef(
                config['location']['tx']['latitude'],
                config['location']['tx']['longitude'],
                config['location']['tx']['altitude'])
            rx_ecef = Geometry.lla2ecef(
                config['location']['rx']['latitude'],
                config['location']['rx']['longitude'],
                config['location']['rx']['altitude'])
            ellipsoid = Ellipsoid(tx_ecef, rx_ecef, radar_name)

            for d_idx, (delay, _) in enumerate(detection_lists[r_idx]):
                delay_ms = delay * 1000  # seconds → milliseconds for sample()
                key = (r_idx, d_idx)
                sample_cache[key] = self._sample_ellipsoid(
                    ellipsoid, delay_ms, self.nSamples)

        # ---- 4. Geometric intersection test ------------------------------------
        survivors = []  # list of (candidate_tuple, intersection_score)
        for cand in candidates:
            # Get sample arrays for each radar in this candidate
            sample_arrays = []
            skip = False
            for r_idx in range(n_radars):
                d_idx = detection_lists[r_idx].index(cand[r_idx])
                pts = sample_cache.get((r_idx, d_idx))
                if pts is None or len(pts) == 0:
                    skip = True
                    break
                sample_arrays.append(np.array(pts))
            if skip:
                continue

            # Pairwise distance check: for each pair of radars, verify at least
            # one pair of sample points is within threshold.
            passes = True
            for i in range(n_radars):
                for j in range(i + 1, n_radars):
                    dists = np.linalg.norm(
                        sample_arrays[i][:, None] - sample_arrays[j][None, :],
                        axis=2)
                    if not np.any(dists < self.threshold):
                        passes = False
                        break
                if not passes:
                    break

            if not passes:
                continue

            # Compute total minimum intersection distance (for scoring)
            total_min_dist = 0.0
            for i in range(n_radars):
                for j in range(i + 1, n_radars):
                    total_min_dist += np.min(np.linalg.norm(
                        sample_arrays[i][:, None] - sample_arrays[j][None, :],
                        axis=2))

            survivors.append((cand, total_min_dist))

        if not survivors:
            return {}

        # ---- 5. Doppler sign-consistency filter ---------------------------------
        filtered = []
        for cand, score in survivors:
            dopplers = [c[1] for c in cand]
            # All Doppler values must have the same sign (all positive or all negative)
            signs = [1 if d > 0 else (-1 if d < 0 else 0) for d in dopplers]
            non_zero = [s for s in signs if s != 0]
            if non_zero and len(set(non_zero)) == 1:
                filtered.append((cand, score))

        if not filtered:
            return {}

        # ---- 6. Deduplicate: keep best-scored candidate per cluster ------------
        # Sort by score (lower is better — less total intersection distance)
        filtered.sort(key=lambda x: x[1])
        assigned = set()  # indices of candidates already clustered
        final_candidates = []

        for i, (cand_i, score_i) in enumerate(filtered):
            if i in assigned:
                continue
            delays_i = np.array([c[0] for c in cand_i])
            final_candidates.append(cand_i)
            assigned.add(i)
            # Suppress other candidates with very similar delays (same target)
            for j in range(i + 1, len(filtered)):
                if j in assigned:
                    continue
                delays_j = np.array([c[0] for c in filtered[j][0]])
                delay_diff = np.linalg.norm(delays_i - delays_j)
                if delay_diff < 1e-6:
                    assigned.add(j)

        # ---- 7. Build output dict ---------------------------------------------
        for cand in final_candidates:
            delays_tuple = tuple(c[0] for c in cand)
            synth_id = hashlib.sha256(
                str(delays_tuple).encode()).hexdigest()[:8]
            output[synth_id] = []
            for r_idx in range(n_radars):
                output[synth_id].append({
                    "radar": radar_names_valid[r_idx],
                    "delay": cand[r_idx][0],
                    "doppler": cand[r_idx][1]
                })

        return output

    def _sample_ellipsoid(self, ellipsoid: Ellipsoid, bistatic_range_ms: float,
                          n: int) -> list:
        """
        @brief Generate ECEF sample points on a bistatic ellipsoid.
        @details Simplified version of EllipsoidParametric.sample() —
            samples at uniform angular spacing, converts to ECEF, filters
            above-ground points.
        @param ellipsoid (Ellipsoid): Pre-computed ellipsoid geometry.
        @param bistatic_range_ms (float): Bistatic range in millimetres (same
            convention as the existing sample() calls).
        @param n (int): Number of azimuth samples.
        @return list: ECEF [x, y, z] points that are above ground.
        """
        phi = ellipsoid.pitch
        theta = ellipsoid.yaw
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        cos_p = math.cos(phi)
        sin_p = math.sin(phi)

        # Rotate from ellipsoid-local to ENU
        # R as in EllipsoidParametric.sample()
        # Local ellipse: x = a cos(u), y = b sin(u) cos(v), z = b sin(u) sin(v)
        a = (bistatic_range_ms + ellipsoid.distance) / 2
        b_sq = a * a - (ellipsoid.distance / 2) ** 2
        if b_sq <= 0:
            return []
        b = math.sqrt(b_sq)

        n_v = max(int(n / 2), 1)
        u_vals = np.linspace(0, 2 * math.pi, n)
        v_vals = np.linspace(-math.pi / 2, math.pi / 2, n_v)
        u, v = np.meshgrid(u_vals, v_vals, indexing='ij')
        x_local = a * np.cos(u)
        y_local = b * np.sin(u) * np.cos(v)
        z_local = b * np.sin(u) * np.sin(v)

        # Apply rotation R
        x_rot = cos_t * x_local - sin_t * cos_p * y_local + sin_t * sin_p * z_local
        y_rot = sin_t * x_local + cos_t * cos_p * y_local - cos_t * sin_p * z_local
        z_rot = sin_p * y_local + cos_p * z_local

        # ENU → ECEF using midpoint reference
        out = []
        mid_lat, mid_lon, mid_alt = ellipsoid.midpoint_lla
        for i in range(x_rot.size):
            ex, ey, ez = Geometry.enu2ecef(
                float(x_rot.flat[i]), float(y_rot.flat[i]), float(z_rot.flat[i]),
                mid_lat, mid_lon, mid_alt)
            # Fast above-ground check via ENU up-component at midpoint
            # (the z_rot is already in the ENU "up" direction at the midpoint)
            if float(z_rot.flat[i]) + mid_alt > 0:
                out.append([round(ex, 3), round(ey, 3), round(ez)])

        return out