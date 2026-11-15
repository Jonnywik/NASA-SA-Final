import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.validation_api import CONTRACT_FIELDS, make_router
from nisar_fixtures import build_product
from processing.nisar_flood.water import WaterRule
from processing.validation import barangay_hit_rate, raster_agreement, threshold_sensitivity

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _load_script_60():
    spec = importlib.util.spec_from_file_location("script_60_validation", BACKEND_DIR / "scripts" / "60_validation.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["script_60_validation"] = mod
    spec.loader.exec_module(mod)
    return mod


class RasterAgreementTests(unittest.TestCase):
    def test_identical_grid_confusion_matrix_and_metrics(self):
        t = (30.0, 0.0, 270000.0, 0.0, -30.0, 1640000.0)
        pred = np.array([[1, 1, 0], [0, 255, 1]], dtype="uint8")
        ref = np.array([[1, 0, 0], [1, 1, 255]], dtype="uint8")
        res = raster_agreement(pred, t, "EPSG:32651", ref, t, "EPSG:32651", pred_nodata=255, ref_nodata=255)
        self.assertEqual(res["targetGrid"], "identical")
        self.assertEqual(res["confusionMatrix"], {"tp": 1, "fp": 1, "fn": 1, "tn": 1, "validPixels": 4})
        self.assertAlmostEqual(res["overallAgreement"], 0.5)
        self.assertAlmostEqual(res["f1"], 0.5)
        self.assertAlmostEqual(res["iou"], 1 / 3, places=6)
        self.assertIsNone(res["reason"])

    def test_coarser_reference_grid_alignment_and_nan_exclusion(self):
        t_fine = (30.0, 0.0, 270000.0, 0.0, -30.0, 1640000.0)
        t_coarse = (60.0, 0.0, 270000.0, 0.0, -60.0, 1640000.0)
        pred_fine = np.array([
            [1, 1, 0, 0],
            [1, 1, 0, 0],
            [0, 0, 1, 1],
            [0, 0, 1, 1],
        ], dtype="uint8")
        ref_coarse = np.array([
            [1.0, 0.0],
            [np.nan, 1.0],
        ], dtype="float32")
        res = raster_agreement(pred_fine, t_fine, "EPSG:32651", ref_coarse, t_coarse, "EPSG:32651", pred_nodata=255, ref_nodata=255)
        self.assertEqual(res["targetGrid"], "reference_coarser")
        self.assertEqual(res["confusionMatrix"], {"tp": 2, "fp": 0, "fn": 0, "tn": 1, "validPixels": 3})
        self.assertAlmostEqual(res["overallAgreement"], 1.0)
        self.assertAlmostEqual(res["f1"], 1.0)
        self.assertAlmostEqual(res["iou"], 1.0)

    def test_coarser_prediction_grid_alignment(self):
        t_coarse = (60.0, 0.0, 270000.0, 0.0, -60.0, 1640000.0)
        t_fine = (30.0, 0.0, 270000.0, 0.0, -30.0, 1640000.0)
        pred_coarse = np.array([[1, 0], [0, 255]], dtype="uint8")
        ref_fine = np.array([
            [1, 1, 1, 1],
            [1, 1, 1, 1],
            [0, 0, 1, 1],
            [0, 0, 1, 1],
        ], dtype="uint8")
        res = raster_agreement(pred_coarse, t_coarse, "EPSG:32651", ref_fine, t_fine, "EPSG:32651")
        self.assertEqual(res["targetGrid"], "prediction_coarser")
        self.assertEqual(res["confusionMatrix"], {"tp": 1, "fp": 0, "fn": 1, "tn": 1, "validPixels": 3})
        self.assertAlmostEqual(res["overallAgreement"], 2 / 3, places=6)
        self.assertAlmostEqual(res["f1"], 2 / 3, places=6)
        self.assertAlmostEqual(res["iou"], 0.5)

    def test_zero_overlapping_valid_pixels_returns_none_with_reason(self):
        t1 = (30.0, 0.0, 270000.0, 0.0, -30.0, 1640000.0)
        t2 = (30.0, 0.0, 290000.0, 0.0, -30.0, 1640000.0)
        pred = np.ones((2, 2), dtype="uint8")
        ref = np.ones((2, 2), dtype="uint8")
        res = raster_agreement(pred, t1, "EPSG:32651", ref, t2, "EPSG:32651")
        self.assertIsNone(res["overallAgreement"])
        self.assertIsNone(res["f1"])
        self.assertIsNone(res["iou"])
        self.assertEqual(res["confusionMatrix"]["validPixels"], 0)
        self.assertTrue(res["reason"])


class BarangayHitRateTests(unittest.TestCase):
    def test_hit_rate_matched_missed_extra(self):
        res = barangay_hit_rate(["Tanza", "San Roque", "Hulong Duhat"], ["tanza", "Concepcion"])
        self.assertAlmostEqual(res["hitRate"], 0.5)
        self.assertEqual(res["matched"], ["tanza"])
        self.assertEqual(res["missed"], ["Concepcion"])
        self.assertEqual(res["extra"], ["Hulong Duhat", "San Roque"])
        self.assertEqual(res["referenceCount"], 2)
        self.assertEqual(res["predictedCount"], 3)
        self.assertIsNone(res["reason"])

    def test_empty_reference_returns_none_hit_rate(self):
        res = barangay_hit_rate(["Tanza"], [])
        self.assertIsNone(res["hitRate"])
        self.assertEqual(res["referenceCount"], 0)
        self.assertEqual(res["predictedCount"], 1)
        self.assertTrue(res["reason"])


class ThresholdSensitivityTests(unittest.TestCase):
    def test_threshold_sensitivity_monotonic_and_deltas(self):
        shape = (4, 4)
        in_area = np.ones(shape, dtype=bool)
        area_km2 = np.full(shape, 0.25, dtype="float64")
        permanent = np.zeros(shape, dtype=bool)
        permanent[0, 0] = True
        valid = np.ones(shape, dtype=bool)

        # Row 1: very dark water (-22 / -30 dB) -> flooded at -1, 0, +1 dB
        # Row 2: borderline (-18.5 / -26.5 dB) -> dry at -1 dB (-19/-27), flooded at 0 and +1 dB
        # Row 3: slightly brighter (-17.5 / -25.5 dB) -> flooded only at +1 dB (-17/-25)
        hh = np.full(shape, -10.0, dtype="float32")
        hv = np.full(shape, -18.0, dtype="float32")
        hh[1, :], hv[1, :] = -22.0, -30.0
        hh[2, :], hv[2, :] = -18.5, -26.5
        hh[3, :], hv[3, :] = -17.5, -25.5

        res = threshold_sensitivity(
            [hh, hh, hh, hh],
            [hv, hv, hv, hv],
            [valid, valid, valid, valid],
            in_area,
            area_km2,
            WaterRule(hh_db=-18.0, hv_db=-26.0),
            permanent,
            min_valid_passes=3,
            deltas=(-1.0, 0.0, 1.0),
        )
        by_delta = {v["deltaDb"]: v for v in res["variants"]}
        self.assertAlmostEqual(by_delta[-1.0]["halfOrMoreKm2"], 1.0)
        self.assertAlmostEqual(by_delta[0.0]["halfOrMoreKm2"], 2.0)
        self.assertAlmostEqual(by_delta[1.0]["halfOrMoreKm2"], 3.0)
        self.assertAlmostEqual(by_delta[-1.0]["deltaHalfOrMoreKm2"], -1.0)
        self.assertAlmostEqual(by_delta[0.0]["deltaHalfOrMoreKm2"], 0.0)
        self.assertAlmostEqual(by_delta[1.0]["deltaHalfOrMoreKm2"], 1.0)
        self.assertAlmostEqual(by_delta[1.0]["floodedAtLeastOnceKm2"], 3.0)


class Script60AndApiTests(unittest.TestCase):
    def test_script_60_refuses_synthetic_product(self):
        s60 = _load_script_60()
        with tempfile.TemporaryDirectory() as tmp:
            root, _, _ = build_product(tmp, data_kind="synthetic")
            cache_dir = Path(tmp) / "cache"
            out_path = s60.write_validation_cache(area="camanava_2026", output_root=root, cache_dir=cache_dir)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["floodValidation"]["status"], "blocked_pending_real_nisar")
            self.assertIsNone(payload["floodValidation"]["metrics"])
            self.assertIn("synthetic", payload["floodValidation"]["reason"].lower())
            self.assertEqual(payload["thresholdSensitivity"]["status"], "blocked_pending_real_nisar")
            self.assertIsNone(payload["thresholdSensitivity"]["metrics"])
            self.assertEqual(payload["subsidenceComparison"]["nisarMotionStatus"], "blocked_pending_real_gunw")

    def test_script_60_computes_threshold_sensitivity_for_observed_product(self):
        s60 = _load_script_60()
        with tempfile.TemporaryDirectory() as tmp:
            root, _, _ = build_product(tmp, data_kind="observed")
            cache_dir = Path(tmp) / "cache"
            out_path = s60.write_validation_cache(area="camanava_2026", output_root=root, cache_dir=cache_dir)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["thresholdSensitivity"]["status"], "computed")
            variants = payload["thresholdSensitivity"]["metrics"]["variants"]
            self.assertEqual([v["deltaDb"] for v in variants], [-1.0, 0.0, 1.0])
            self.assertEqual(variants[1]["deltaHalfOrMoreKm2"], 0.0)
            self.assertEqual(payload["floodValidation"]["status"], "blocked_pending_independent_reference_download")

    def test_validation_api_200_and_404s(self):
        s60 = _load_script_60()
        with tempfile.TemporaryDirectory() as tmp:
            root, _, _ = build_product(tmp, data_kind="synthetic")
            cache_dir = Path(tmp) / "cache"
            s60.write_validation_cache(area="camanava_2026", output_root=root, cache_dir=cache_dir)

            app = FastAPI()
            app.include_router(make_router(root, lambda: [{"id": "camanava_2026"}, {"id": "karding_2022"}], validation_dir=cache_dir))
            client = TestClient(app)

            r200 = client.get("/api/v1/validation?area=camanava_2026")
            self.assertEqual(r200.status_code, 200)
            body = r200.json()
            for field in CONTRACT_FIELDS:
                self.assertIn(field, body)
            self.assertEqual(body["area"], "camanava_2026")
            self.assertEqual(body["floodValidation"]["status"], "blocked_pending_real_nisar")

            r_unknown = client.get("/api/v1/validation?area=nowhere")
            self.assertEqual(r_unknown.status_code, 404)
            self.assertEqual(r_unknown.json()["detail"]["code"], "unknown_area")

            r_missing = client.get("/api/v1/validation?area=karding_2022")
            self.assertEqual(r_missing.status_code, 404)
            self.assertEqual(r_missing.json()["detail"]["code"], "data_unavailable")


if __name__ == "__main__":
    unittest.main()
