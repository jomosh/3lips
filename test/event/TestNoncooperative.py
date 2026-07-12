"""
@file TestNoncooperative.py
@brief Unit tests for non-cooperative target cross-reference logic.
"""
import unittest
import numpy as np
from algorithm.geometry.Geometry import Geometry


class TestNoncooperative(unittest.TestCase):

    def _classify_blind(self, blind_points, adsb_points, match_distance):
        """Replicate the cross-reference logic from event/event.py.

        For each blind target, find the nearest ADS-B target in ECEF.
        If distance > match_distance, classify as non-cooperative.

        Returns (cooperative, noncooperative) lists of track IDs.
        """
        noncoop = []
        coop = []
        for track_id, blind_lla in blind_points.items():
            blind_ecef = Geometry.lla2ecef(
                blind_lla[0], blind_lla[1], blind_lla[2])
            blind_arr = np.array(blind_ecef)

            nearest_dist = float('inf')
            for hex_key, adsb_lla in adsb_points.items():
                adsb_ecef = Geometry.lla2ecef(
                    adsb_lla[0], adsb_lla[1], adsb_lla[2])
                dist = np.linalg.norm(blind_arr - np.array(adsb_ecef))
                if dist < nearest_dist:
                    nearest_dist = dist

            if nearest_dist > match_distance:
                noncoop.append(track_id)
            else:
                coop.append(track_id)
        return coop, noncoop

    def test_target_near_adsb_is_cooperative(self):
        """Blind target within 100m of ADS-B target → cooperative."""
        adsb = {
            'ABC123': [-34.9286, 138.5999, 1000],
        }
        blind = {
            'T1': [-34.9287, 138.6000, 1000],  # ~20 m away
        }
        coop, noncoop = self._classify_blind(blind, adsb, match_distance=1000)
        self.assertIn('T1', coop)
        self.assertNotIn('T1', noncoop)

    def test_target_far_from_adsb_is_noncooperative(self):
        """Blind target 5 km from nearest ADS-B → non-cooperative with
        match_distance=1000."""
        adsb = {
            'ABC123': [-34.9286, 138.5999, 1000],
        }
        blind = {
            'T1': [-34.88, 138.55, 1000],  # ~7 km away
        }
        coop, noncoop = self._classify_blind(blind, adsb, match_distance=1000)
        self.assertIn('T1', noncoop)
        self.assertNotIn('T1', coop)

    def test_match_distance_tight_classifies_correctly(self):
        """match_distance=1m — even a 20m offset flags non-cooperative."""
        adsb = {
            'ABC123': [-34.9286, 138.5999, 1000],
        }
        blind = {
            'T1': [-34.9287, 138.6000, 1000],  # ~20 m away
        }
        coop, noncoop = self._classify_blind(blind, adsb, match_distance=1)
        self.assertIn('T1', noncoop)
        self.assertNotIn('T1', coop)

    def test_no_adsb_all_blind_are_noncooperative(self):
        """No ADS-B targets → all blind targets are non-cooperative."""
        blind = {
            'T1': [-34.9286, 138.5999, 1000],
            'T2': [-34.90, 138.60, 2000],
        }
        coop, noncoop = self._classify_blind(blind, {}, match_distance=1000)
        self.assertEqual(coop, [])
        self.assertEqual(sorted(noncoop), ['T1', 'T2'])

    def test_nearest_adsb_selected_not_all_compared(self):
        """Blind target near ADS-B A but far from B → cooperative
        (nearest ADS-B target is used)."""
        adsb = {
            'A': [-34.9286, 138.5999, 1000],    # near
            'B': [-34.70, 139.00, 1000],          # far
        }
        blind = {
            'T1': [-34.9287, 138.6000, 1000],   # ~20 m from A
        }
        coop, noncoop = self._classify_blind(blind, adsb, match_distance=1000)
        self.assertIn('T1', coop)
        self.assertNotIn('T1', noncoop)


if __name__ == '__main__':
    unittest.main()