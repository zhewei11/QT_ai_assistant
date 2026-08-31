import importlib.util
import json
import math
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "integration" / "ecg_session.py"
SPEC = importlib.util.spec_from_file_location("ecg_session", MODULE_PATH)
ecg_session = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ecg_session)


class ECGSessionTest(unittest.TestCase):
    @staticmethod
    def synthetic_ecg(rr_ms, sample_rate=375.0):
        peak_times = [1.0]
        for interval in rr_ms:
            peak_times.append(peak_times[-1] + interval / 1000.0)
        duration = max(60.0, peak_times[-1] + 1.0)
        time_axis = np.arange(int(duration * sample_rate)) / sample_rate
        samples = 0.01 * np.sin(2 * np.pi * 1.2 * time_axis)
        peaks = []
        for peak_time in peak_times:
            center = int(round(peak_time * sample_rate))
            peaks.append(center)
            for offset in range(-5, 6):
                index = center + offset
                if 0 <= index < samples.size:
                    samples[index] += math.exp(-((offset / 2.2) ** 2))
        return samples, np.asarray(peaks)

    def test_metrics_for_regular_60_bpm_peaks(self):
        peaks = np.arange(0, 61 * 375, 375)
        metrics = ecg_session.calculate_metrics(peaks, 375.0)
        self.assertIsNotNone(metrics)
        self.assertAlmostEqual(metrics["bpm"], 60.0, places=1)
        self.assertAlmostEqual(metrics["arrhythmia_indicator_percent"], 0.0, places=1)

    def test_detects_synthetic_r_peaks(self):
        sample_rate = 375.0
        duration = 12
        samples = np.zeros(int(sample_rate * duration), dtype=np.float64)
        for second in range(1, duration):
            center = int(second * sample_rate)
            for offset in range(-4, 5):
                samples[center + offset] += math.exp(-((offset / 2.0) ** 2))

        peaks = ecg_session.detect_r_peaks(samples, sample_rate)
        metrics = ecg_session.calculate_metrics(peaks, sample_rate)
        self.assertGreaterEqual(len(peaks), 9)
        self.assertIsNotNone(metrics)
        self.assertAlmostEqual(metrics["bpm"], 60.0, delta=2.0)

    def test_valid_heartbeat_gate_requires_plausible_r_peaks(self):
        regular_samples, _ = self.synthetic_ecg([1000.0] * 8)
        flat_samples = np.zeros(int(10 * 375), dtype=np.float64)
        self.assertTrue(ecg_session.has_valid_heartbeat(regular_samples[:3750], 375.0))
        self.assertFalse(ecg_session.has_valid_heartbeat(flat_samples, 375.0))
        self.assertFalse(ecg_session.has_valid_heartbeat(regular_samples[:500], 375.0))

    def test_heartbeat_gate_rejects_noise_even_with_peak_candidates(self):
        rng = np.random.default_rng(0)
        noisy_samples = rng.normal(0, 0.05, int(10 * 375))
        details = ecg_session.heartbeat_gate_details(noisy_samples, 375.0)
        self.assertFalse(details["valid"])
        self.assertNotEqual(details["reason"], "ok")

    def test_ybc_model_can_be_disabled(self):
        previous = os.environ.get("ECG_YBC_MODEL_ENABLED")
        os.environ["ECG_YBC_MODEL_ENABLED"] = "false"
        try:
            samples, peaks = self.synthetic_ecg([1000.0] * 8)
            result = ecg_session.analyze_ybc_arrhythmia(samples, peaks, 375.0)
            self.assertEqual(result["status"], "disabled")
            self.assertFalse(result["enabled"])
        finally:
            if previous is None:
                os.environ.pop("ECG_YBC_MODEL_ENABLED", None)
            else:
                os.environ["ECG_YBC_MODEL_ENABLED"] = previous

    def test_stream_packet_identity(self):
        batch, packet_id = ecg_session._extract_stream_packet({
            "data": {"batch": [0.1, 0.2], "session_id": "abc", "sequence": 7}
        })
        self.assertEqual(batch, [0.1, 0.2])
        self.assertEqual(packet_id, "abc:7")

    def test_current_person_identity_and_ecg_update(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_path = Path(tmpdir) / "face_memory.json"
            memory_path.write_text(json.dumps({
                "current_person_id": "person_1",
                "people": [{
                    "person_id": "person_1",
                    "face_tracking_id": 11,
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                }],
            }), encoding="utf-8")

            identity = ecg_session.current_person_identity(memory_path, current_ttl_seconds=30)
            self.assertEqual(identity["person_id"], "person_1")

            snapshot = {
                "measurement_id": "m1",
                "person_id": "person_1",
                "status": "complete",
                "measured_at": datetime.now(timezone.utc).isoformat(),
                "metrics": {"bpm": 72},
            }
            self.assertTrue(ecg_session.update_person_ecg_measurement(memory_path, snapshot))
            updated = json.loads(memory_path.read_text(encoding="utf-8"))
            person = updated["people"][0]
            self.assertEqual(person["latest_ecg_measurement_id"], "m1")
            self.assertEqual(person["latest_ecg_measurement"]["metrics"]["bpm"], 72)

    def test_regular_rhythm_screen(self):
        samples, peaks = self.synthetic_ecg([1000.0] * 58)
        result = ecg_session.analyze_arrhythmia(samples, peaks, 375.0)
        self.assertEqual(result["status"], "complete")
        self.assertIn("regular_rhythm_pattern", result["rhythm_labels"])
        self.assertLess(result["screening_scores"]["irregular_rhythm"], 0.25)

    def test_irregular_af_like_screen(self):
        rr = [620, 1180, 760, 1040, 540, 1320, 850, 690, 1210, 730] * 6
        samples, peaks = self.synthetic_ecg(rr)
        result = ecg_session.analyze_arrhythmia(samples, peaks, 375.0)
        self.assertIn("possible_af_pattern", result["rhythm_labels"])
        self.assertGreaterEqual(result["screening_scores"]["possible_af_pattern"], 0.6)

    def test_compensated_premature_pattern_is_not_called_af(self):
        samples, peaks = self.synthetic_ecg([600.0, 1400.0] * 29)
        result = ecg_session.analyze_arrhythmia(samples, peaks, 375.0)
        self.assertIn("frequent_premature_pattern", result["rhythm_labels"])
        self.assertNotIn("possible_af_pattern", result["rhythm_labels"])

    def test_rate_patterns(self):
        fast_samples, fast_peaks = self.synthetic_ecg([500.0] * 100)
        slow_samples, slow_peaks = self.synthetic_ecg([1500.0] * 38)
        fast = ecg_session.analyze_arrhythmia(fast_samples, fast_peaks, 375.0)
        slow = ecg_session.analyze_arrhythmia(slow_samples, slow_peaks, 375.0)
        self.assertIn("tachycardia_pattern", fast["rhythm_labels"])
        self.assertIn("bradycardia_pattern", slow["rhythm_labels"])


if __name__ == "__main__":
    unittest.main()
