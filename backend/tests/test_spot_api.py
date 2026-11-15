"""Tests for spot-check and bilingual place briefing API (Task T4)."""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from app.spot_api import make_router
from climate_fixtures import constant_daily, power_payload
from nisar_fixtures import build_product
from processing.briefing_place import templates_en, templates_fil
from processing.climate.store import write_cache
from processing.p3 import catalog as p3_catalog
from processing.p3 import core as p3_core
from test_places_support import make_places_root

NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _err_code(response) -> str:
    return response.json()["detail"]["code"]


def _write_priority_mask(nisar_dir: Path, value: int, *, data_kind: str = "derived", threshold_mm: float = 12.5):
    nisar_dir.mkdir(parents=True, exist_ok=True)
    # 2x2 grid covering CAMANAVA bbox [120.88, 14.60, 121.04, 14.82]
    transform = from_origin(120.85, 14.85, 0.12, 0.14)
    arr = np.full((2, 2), value, dtype="uint8")
    mask_path = nisar_dir / "priority_mask.tif"
    with rasterio.open(
        mask_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=transform,
        nodata=255,
    ) as ds:
        ds.write(arr, 1)
    (nisar_dir / "priority_manifest.json").write_text(
        json.dumps({
            "dataKind": data_kind,
            "thresholdMm": threshold_mm,
            "thresholdMethod": "2x reference std",
            "version": "1.0",
        }),
        encoding="utf-8",
    )


def _publish_ground_motion(output_root: Path, event: str, *, data_kind: str = "synthetic", displacement_val: float = 18.4, rate_val: float = 24.2):
    grid = {
        "crs": "EPSG:4326",
        "transform": [0.25, 0.0, 120.85, 0.0, -0.25, 14.85],
        "width": 2,
        "height": 2,
    }
    epochs = ["2026-06-23T00:00:00Z", "2026-08-22T00:00:00Z", "2026-10-21T00:00:00Z"]
    series_arr = np.zeros((3, 2, 2), dtype="float32")
    series_arr[1, :, :] = displacement_val / 2.0
    series_arr[2, :, :] = displacement_val
    disp_arr = np.full((2, 2), displacement_val, dtype="float32")
    rate_arr = np.full((2, 2), rate_val, dtype="float32")
    span_arr = np.full((2, 2), 120.0, dtype="float32")
    res_arr = np.full((2, 2), 1.2, dtype="float32")

    metadata = {
        "dataKind": data_kind,
        "syntheticLineage": data_kind == "synthetic",
        "sourceRunIds": ["pair-1"],
        "sensor": "NISAR L-band InSAR",
        "processingVersion": "test-1.0",
        "nativeResolutionMetres": 90.0,
        "displacementConvention": "positive_away_from_satellite",
        "referenceEpoch": epochs[0],
        "latestEpoch": epochs[-1],
        "epochs": epochs,
        "grid": grid,
    }

    def writer(stage: Path):
        np.savez_compressed(stage / "series.npz", epochs=np.asarray(epochs), displacementMm=series_arr)
        p3_core.write_raster(stage / "displacementMm.tif", disp_arr, grid)
        p3_core.write_raster(stage / "rateMmPerYear.tif", rate_arr, grid)
        p3_core.write_raster(stage / "spanDays.tif", span_arr, grid)
        p3_core.write_raster(stage / "fitResidualMm.tif", res_arr, grid)
        return {
            "series": "series.npz",
            "displacementMm": "displacementMm.tif",
            "rateMmPerYear": "rateMmPerYear.tif",
            "spanDays": "spanDays.tif",
            "fitResidualMm": "fitResidualMm.tif",
        }

    manifest_path = p3_core.publish(
        event,
        "ground-motion",
        metadata,
        writer,
        output_root=output_root,
        review=(data_kind == "synthetic"),
    )
    if data_kind != "synthetic":
        manifest = p3_core.load_manifest(manifest_path)
        receipt_path = manifest_path.parent / "review.json"
        receipt_path.write_text(
            json.dumps({
                "status": "validated",
                "reviewer": "test-reviewer",
                "reviewedAt": "2026-11-14T12:00:00Z",
                "evidence": ["test validation receipt"],
                "manifestSha256": p3_core.digest(manifest_path),
                "sourceRunIds": manifest.get("sourceRunIds", []),
            }),
            encoding="utf-8",
        )
        p3_catalog.promote(manifest_path, receipt_path)


class SpotApiUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.output_root = self.base / "output"
        self.places_root = make_places_root(self.base / "places")
        self.climate_dir = self.base / "climate"
        daily = constant_daily(date(2026, 6, 15), date(2026, 7, 15), value=3.5)
        write_cache("power_daily", power_payload(daily), {"test": True}, cache_dir=self.climate_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def _client(self, *, output_root=None, places_root=None, climate_dir=None, events=None):
        app = FastAPI()
        ev = events if events is not None else [{"id": "camanava_2026"}]
        app.include_router(
            make_router(
                output_root or self.output_root,
                lambda: ev,
                places_root=places_root or self.places_root,
                climate_cache_dir=climate_dir or self.climate_dir,
            )
        )
        return TestClient(app)

    def _assert_numbers_in_facts(self, text: str, facts: list[dict]):
        fact_numbers = set()
        for f in facts:
            if f["value"] is not None:
                fact_numbers.update(NUM_RE.findall(str(f["value"])))
            if f.get("reason"):
                fact_numbers.update(NUM_RE.findall(str(f["reason"])))
        text_numbers = set(NUM_RE.findall(text))
        self.assertTrue(
            text_numbers.issubset(fact_numbers),
            f"Numbers in briefing text not traced to facts: {text_numbers - fact_numbers}",
        )

    def test_error_codes(self):
        client = self._client()
        # Unknown area
        for path in ("/api/v1/spot-check?area=mars&lon=120.95&lat=14.67", "/api/v1/briefing/place?area=mars&lon=120.95&lat=14.67"):
            r = client.get(path)
            self.assertEqual((r.status_code, _err_code(r)), (404, "unknown_area"), path)

        # Invalid lon/lat
        for q in ("", "?lon=120.95", "?lat=14.67", "?lon=abc&lat=14.67", "?lon=nan&lat=14.67", "?lon=181&lat=14.67", "?lon=120.95&lat=-95"):
            r = client.get(f"/api/v1/spot-check{q}")
            self.assertEqual((r.status_code, _err_code(r)), (422, "invalid_request"), q)

        # Outside coverage bbox
        r = client.get("/api/v1/spot-check?lon=120.50&lat=14.70")
        self.assertEqual((r.status_code, _err_code(r)), (404, "outside_coverage"))
        r = client.get("/api/v1/briefing/place?lon=120.50&lat=14.70")
        self.assertEqual((r.status_code, _err_code(r)), (404, "outside_coverage"))

        # Invalid lang / format
        r = client.get("/api/v1/briefing/place?lon=120.95&lat=14.67&lang=es")
        self.assertEqual((r.status_code, _err_code(r)), (422, "invalid_request"))
        r = client.get("/api/v1/briefing/place?lon=120.95&lat=14.67&format=pdf")
        self.assertEqual((r.status_code, _err_code(r)), (422, "invalid_request"))

    def test_missing_components_emit_explicit_reasons_never_zero(self):
        empty_places = self.base / "empty_places"
        empty_places.mkdir()
        empty_climate = self.base / "empty_climate"
        empty_climate.mkdir()
        empty_out = self.base / "empty_out"
        empty_out.mkdir()
        client = self._client(output_root=empty_out, places_root=empty_places, climate_dir=empty_climate)

        sc = client.get("/api/v1/spot-check?lon=120.957&lat=14.665")
        self.assertEqual(sc.status_code, 200)
        body = sc.json()
        for key in ("place", "nisar", "rainfall", "groundMotion", "priorityZone"):
            self.assertFalse(body[key]["available"], key)
            self.assertTrue(body[key]["reason"], key)
        self.assertIsNone(body["nisar"]["floodCount"])
        self.assertIsNone(body["groundMotion"]["cumulativeDisplacementMm"])
        self.assertIsNone(body["priorityZone"]["inPriorityZone"])

        for lang, phrase in (("en", "not available because"), ("fil", "hindi available dahil")):
            br = client.get(f"/api/v1/briefing/place?lon=120.957&lat=14.665&lang={lang}")
            self.assertEqual(br.status_code, 200)
            b = br.json()
            self.assertIn(phrase, b["text"])
            self._assert_numbers_in_facts(b["text"], b["facts"])
            for fact in b["facts"]:
                if fact["field"] not in ("longitude", "latitude"):
                    self.assertIsNone(fact["value"], fact["field"])
                    self.assertTrue(fact["reason"], fact["field"])

        # CSV must leave missing values empty, never "0"
        csv_resp = client.get("/api/v1/briefing/place?lon=120.957&lat=14.665&format=csv")
        self.assertEqual(csv_resp.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(csv_resp.text)))
        for row in rows:
            if row["field"] not in ("longitude", "latitude"):
                self.assertEqual(row["value"], "", row)
                self.assertTrue(row["reason"], row)

    def test_synthetic_flag_propagates_from_any_upstream_component(self):
        # 1) Derived NISAR + derived motion + derived priority -> top-level derived
        out_dir = self.base / "derived_case"
        out_root, _, _ = build_product(out_dir, data_kind="observed")
        _publish_ground_motion(out_root, "camanava_2026", data_kind="derived", displacement_val=15.0, rate_val=20.0)
        _write_priority_mask(out_root / "camanava_2026" / "nisar", 1, data_kind="derived", threshold_mm=10.0)
        client = self._client(output_root=out_root)
        sc = client.get("/api/v1/spot-check?lon=120.945&lat=14.70").json()
        self.assertEqual(sc["dataKind"], "derived")
        self.assertTrue(sc["groundMotion"]["available"])
        self.assertEqual(sc["groundMotion"]["cumulativeDisplacementMm"], 15.0)
        self.assertTrue(sc["priorityZone"]["inPriorityZone"])

        br = client.get("/api/v1/briefing/place?lon=120.945&lat=14.70&lang=en").json()
        self.assertEqual(br["dataKind"], "derived")
        self.assertNotIn("SYNTHETIC DATA WARNING", br["text"])

        # 2) Only groundMotion is synthetic -> propagates to top-level synthetic
        out_gm_syn = self.base / "gm_syn_case"
        out_root2, _, _ = build_product(out_gm_syn, data_kind="observed")
        _publish_ground_motion(out_root2, "camanava_2026", data_kind="synthetic", displacement_val=19.5, rate_val=25.0)
        _write_priority_mask(out_root2 / "camanava_2026" / "nisar", 0, data_kind="derived", threshold_mm=10.0)
        c2 = self._client(output_root=out_root2)
        self.assertEqual(c2.get("/api/v1/spot-check?lon=120.945&lat=14.70").json()["dataKind"], "synthetic")
        br2 = c2.get("/api/v1/briefing/place?lon=120.945&lat=14.70&lang=en").json()
        self.assertEqual(br2["dataKind"], "synthetic")
        self.assertTrue(br2["text"].startswith("**SYNTHETIC DATA WARNING:"))

        # 3) Only priorityZone is synthetic -> propagates to top-level synthetic
        out_pr_syn = self.base / "pr_syn_case"
        out_root3, _, _ = build_product(out_pr_syn, data_kind="observed")
        _write_priority_mask(out_root3 / "camanava_2026" / "nisar", 1, data_kind="synthetic", threshold_mm=10.0)
        c3 = self._client(output_root=out_root3)
        self.assertEqual(c3.get("/api/v1/spot-check?lon=120.945&lat=14.70").json()["dataKind"], "synthetic")

    def test_en_fil_consistency_wording_csv_and_html_formats(self):
        out_root, _, _ = build_product(self.base / "full", data_kind="synthetic")
        _publish_ground_motion(out_root, "camanava_2026", data_kind="synthetic", displacement_val=22.5, rate_val=30.0)
        _write_priority_mask(out_root / "camanava_2026" / "nisar", 1, data_kind="synthetic", threshold_mm=8.5)
        client = self._client(output_root=out_root)

        self.assertEqual(templates_en.FIELD_ORDER, templates_fil.FIELD_ORDER)
        en = client.get("/api/v1/briefing/place?lon=120.945&lat=14.70&lang=en").json()
        fil = client.get("/api/v1/briefing/place?lon=120.945&lat=14.70&lang=fil").json()

        self.assertEqual(en["translationStatus"], "en_source")
        self.assertEqual(fil["translationStatus"], "pending native-speaker review")
        self.assertEqual([f["field"] for f in en["facts"]], list(templates_en.FIELD_ORDER))
        self.assertEqual(len(en["lines"]), len(fil["lines"]))
        self.assertEqual(len(en["lines"]), len(en["facts"]))

        self._assert_numbers_in_facts(en["text"], en["facts"])
        self._assert_numbers_in_facts(fil["text"], fil["facts"])

        # Wording rules
        for txt in (en["text"], fil["text"]):
            lower = txt.lower()
            self.assertNotIn("damage", lower)
            self.assertNotIn("sinking", lower)
            self.assertIn("line-of-sight", lower)
        self.assertIn("exposure", en["text"].lower())
        self.assertIn("hypothes", en["text"].lower())
        self.assertIn("exposure", fil["text"].lower())
        self.assertIn("haypotesis", fil["text"].lower())
        self.assertTrue(fil["text"].startswith("**BABALA"))

        # CSV format
        csv_resp = client.get("/api/v1/briefing/place?lon=120.945&lat=14.70&lang=en&format=csv")
        self.assertEqual(csv_resp.status_code, 200)
        self.assertTrue(csv_resp.headers["content-type"].startswith("text/csv"))
        reader = csv.DictReader(io.StringIO(csv_resp.text))
        self.assertEqual(reader.fieldnames, ["field", "value", "units", "source", "dataKind", "reason"])
        rows = list(reader)
        self.assertEqual(len(rows), len(en["facts"]))

        # HTML format
        html_resp = client.get("/api/v1/briefing/place?lon=120.945&lat=14.70&lang=fil&format=html")
        self.assertEqual(html_resp.status_code, 200)
        self.assertTrue(html_resp.headers["content-type"].startswith("text/html"))
        self.assertIn("<!DOCTYPE html>", html_resp.text)
        self.assertIn("<strong>", html_resp.text)
        self.assertIn("pending native-speaker review", html_resp.text)
        self.assertIn("Sources", html_resp.text)
        self.assertIn("Limitations", html_resp.text)
        self.assertNotIn("damage", html_resp.text.lower())
        self.assertNotIn("sinking", html_resp.text.lower())

    def test_unreviewed_ground_motion_is_unavailable(self):
        out_root, _, _ = build_product(self.base / "unreviewed", data_kind="observed")
        # Publish ground-motion WITHOUT promoting it via review receipt
        grid = {"crs": "EPSG:4326", "transform": [0.25, 0.0, 120.85, 0.0, -0.25, 14.85], "width": 2, "height": 2}
        epochs = ["2026-06-23T00:00:00Z", "2026-08-22T00:00:00Z"]
        p3_core.publish(
            "camanava_2026",
            "ground-motion",
            {"dataKind": "derived", "epochs": epochs, "grid": grid, "nativeResolutionMetres": 90.0},
            lambda s: (p3_core.write_raster(s / "displacementMm.tif", np.ones((2, 2), dtype="float32"), grid), {"displacementMm": "displacementMm.tif"})[1],
            output_root=out_root,
        )
        client = self._client(output_root=out_root)
        sc = client.get("/api/v1/spot-check?lon=120.945&lat=14.70").json()
        self.assertFalse(sc["groundMotion"]["available"])
        self.assertIn("review", sc["groundMotion"]["reason"].lower())

    def test_priority_nodata_and_open_water_point_emit_null_with_reason(self):
        out_root, _, _ = build_product(self.base / "nodata_case", data_kind="observed")
        _write_priority_mask(out_root / "camanava_2026" / "nisar", 255, data_kind="derived", threshold_mm=11.0)
        client = self._client(output_root=out_root)
        # Open-water point inside bbox (120.9, 14.62) has no barangay in test_places_support
        sc = client.get("/api/v1/spot-check?lon=120.9&lat=14.62").json()
        self.assertIsNone(sc["place"]["barangay"])
        self.assertTrue(sc["place"]["reason"])
        self.assertIsNone(sc["priorityZone"]["inPriorityZone"])
        self.assertIn("nodata", sc["priorityZone"]["reason"])
        br = client.get("/api/v1/briefing/place?lon=120.9&lat=14.62&lang=en").json()
        self.assertIn("not available because", br["text"])
        self._assert_numbers_in_facts(br["text"], br["facts"])


class SpotApiRealWorkspaceDataTests(unittest.TestCase):
    """Test Malabon point (120.957, 14.665) against real places/climate caches + synthetic NISAR output."""

    @classmethod
    def setUpClass(cls):
        events_file = BACKEND_DIR / "events.json"
        events = json.loads(events_file.read_text(encoding="utf-8"))
        public_events = [e for e in events if e.get("public", True)]
        app = FastAPI()
        app.include_router(make_router(BACKEND_DIR / "data" / "output", lambda: public_events))
        cls.client = TestClient(app)

    def test_malabon_point_end_to_end(self):
        r = self.client.get("/api/v1/spot-check?area=camanava_2026&lon=120.957&lat=14.665")
        self.assertEqual(r.status_code, 200)
        sc = r.json()
        self.assertEqual(sc["area"], "camanava_2026")
        self.assertEqual(sc["dataKind"], "synthetic")
        self.assertTrue(sc["place"]["available"])
        self.assertEqual(sc["place"]["barangay"]["name"], "Niugan")
        self.assertEqual(sc["place"]["city"]["name"], "City of Malabon")
        self.assertTrue(sc["nisar"]["available"])
        self.assertEqual(sc["nisar"]["dataKind"], "synthetic")
        self.assertTrue(sc["rainfall"]["available"])
        self.assertGreater(len(sc["rainfall"]["passes"]), 0)

        for lang in ("en", "fil"):
            br = self.client.get(f"/api/v1/briefing/place?area=camanava_2026&lon=120.957&lat=14.665&lang={lang}")
            self.assertEqual(br.status_code, 200)
            body = br.json()
            self.assertEqual(body["dataKind"], "synthetic")
            self.assertIn("Niugan", body["text"])
            self.assertIn("City of Malabon", body["text"])
            fact_nums = set()
            for f in body["facts"]:
                if f["value"] is not None:
                    fact_nums.update(NUM_RE.findall(str(f["value"])))
                if f.get("reason"):
                    fact_nums.update(NUM_RE.findall(str(f["reason"])))
            text_nums = set(NUM_RE.findall(body["text"]))
            self.assertTrue(text_nums.issubset(fact_nums), f"Untraced numbers in {lang}: {text_nums - fact_nums}")

        csv_r = self.client.get("/api/v1/briefing/place?area=camanava_2026&lon=120.957&lat=14.665&format=csv")
        self.assertEqual(csv_r.status_code, 200)
        self.assertIn("barangay_name,Niugan", csv_r.text)

        html_r = self.client.get("/api/v1/briefing/place?area=camanava_2026&lon=120.957&lat=14.665&lang=fil&format=html")
        self.assertEqual(html_r.status_code, 200)
        self.assertIn("<strong>", html_r.text)
        self.assertIn("Niugan", html_r.text)


if __name__ == "__main__":
    unittest.main()
