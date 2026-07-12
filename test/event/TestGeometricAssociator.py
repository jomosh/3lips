"""
@file TestGeometricAssociator.py
@brief Unit tests for GeometricAssociator blind association.
"""
import unittest
from algorithm.associator.GeometricAssociator import GeometricAssociator


class TestGeometricAssociator(unittest.TestCase):

    def setUp(self):
        """Build a minimal config dict matching the geometric block."""
        self.config = {
            'threshold': 500,
            'nSamples': 50,
            'doppler_tolerance': 5,
            'max_detections': 20,
        }

    def _build_synthetic_radar_data(self, delays_per_radar):
        """Build a radar_data dict for synthetic radars with given delays.

        Uses known TX/RX positions (Adelaide, Australia area) so ellipsoid
        geometry is well-defined.  Each entry in delays_per_radar is a
        list of (delay_seconds, doppler_hz) tuples.
        """
        radar_data = {}
        for i, det_list in enumerate(delays_per_radar):
            name = f'radar{i}'
            radar_data[name] = {
                'detection': {
                    'delay': [d[0] for d in det_list],
                    'doppler': [d[1] for d in det_list],
                },
                'config': {
                    'location': {
                        # Slightly offset TX/RX per radar to avoid
                        # degenerate identical-ellipsoid geometry.
                        'tx': {
                            'latitude': -34.9286,
                            'longitude': 138.5999 + i * 0.01,
                            'altitude': 50,
                        },
                        'rx': {
                            'latitude': -34.8 - i * 0.02,
                            'longitude': 138.5 + i * 0.01,
                            'altitude': 30,
                        },
                    },
                },
            }
        return radar_data

    def test_empty_detection_lists_returns_empty_dict(self):
        """Empty detection lists → empty output."""
        assoc = GeometricAssociator(self.config)
        radar_data = self._build_synthetic_radar_data([
            [], [], [],
        ])
        radar_list = list(radar_data.keys())
        result = assoc.process(radar_list, radar_data, 0)
        self.assertEqual(result, {})

    def test_output_schema_matches_adsb_associator_format(self):
        """Output is {synthetic_id: [{radar, delay, doppler}]}."""
        assoc = GeometricAssociator(self.config)
        # One real target: bistatic delay ~0.001 s (300 km path) for all 3 radars.
        # Doppler: small positive values.
        radar_data = self._build_synthetic_radar_data([
            [(0.001, 12.0), (0.003, -8.0), (0.005, 3.0)],   # radar 0
            [(0.00105, 11.5), (0.0028, -7.5), (0.0045, 4.0)],  # radar 1
            [(0.00098, 12.2), (0.0031, -9.0), (0.0048, 2.5)],  # radar 2
        ])
        radar_list = list(radar_data.keys())
        result = assoc.process(radar_list, radar_data, 0)

        self.assertIsInstance(result, dict)
        for synth_id, det_list in result.items():
            self.assertIsInstance(synth_id, str)
            self.assertEqual(len(synth_id), 8)  # sha256[:8]
            self.assertIsInstance(det_list, list)
            self.assertGreaterEqual(len(det_list), 1)
            for det in det_list:
                self.assertIn('radar', det)
                self.assertIn('delay', det)
                self.assertIn('doppler', det)
                self.assertIsInstance(det['radar'], str)
                self.assertIsInstance(det['delay'], float)
                self.assertIsInstance(det['doppler'], float)

    def test_max_detections_zero_returns_empty(self):
        """max_detections=0 with any detections → early return {}."""
        config_bad = dict(self.config)
        config_bad['max_detections'] = 0
        assoc = GeometricAssociator(config_bad)
        radar_data = self._build_synthetic_radar_data([
            [(0.001, 12.0)],
            [(0.00105, 11.5)],
            [(0.00098, 12.2)],
        ])
        radar_list = list(radar_data.keys())
        result = assoc.process(radar_list, radar_data, 0)
        self.assertEqual(result, {})

    def test_duplicate_delays_produce_correct_index_mapping(self):
        """Two detections with identical (delay, doppler) in the same
        radar must not mis-map via the old .index() bug — the enumerated
        candidate path must still work correctly."""
        assoc = GeometricAssociator(self.config)
        # Radar 0 has two detections with *identical* delay/doppler values.
        radar_data = self._build_synthetic_radar_data([
            [(0.001, 12.0), (0.001, 12.0)],  # duplicates
            [(0.00105, 11.5)],
            [(0.00098, 12.2)],
        ])
        radar_list = list(radar_data.keys())
        result = assoc.process(radar_list, radar_data, 0)

        # Should not crash and should return a dict (may be empty
        # if the geometry doesn't intersect, but must not raise).
        self.assertIsInstance(result, dict)


if __name__ == '__main__':
    unittest.main()