"""Tests for Task T3: priority zones (flood rhythm >= half AND LOS motion > T)."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

BACKEND_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for p in (str(BACKEND_DIR), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.places_api import make_router as make_places_router  # noqa: E402
from processing.nisar_flood.constants import AREA_ID  # noqa: E402
from processing.nisar_flood.export import write_gtiff  # noqa: E402
from processing.nisar_flood.geo import Grid  # noqa: E402
from processing.p3 import core, series  # noqa: E402
from processing.priority import (  # noqa: E402
    align_grids,
    build_priority_zones,
    compute_priority_mask,
    create_synthetic_motion_demo,
    derive_threshold,
)
from test_places_support import MID_LAT, MID_LON, N, STEP, W, make_places_root, write_raster  # noqa: E402

# Import script 50 via importlib because filename starts with digits.
import importlib.util  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("script_50_priority_zones", BACKEND_DIR / "scripts" / "50_priority_zones.py")
script_50 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(script_50)


def _publish_motion_pair_and_series(
    output_root: Path,
    area: str,
    disp_arr: np.ndarray,
    grid: Grid,
    *,
    data_kind: str = "derived",
    ref_polygon: dict | None = None,
    with_current: bool = True,
) -> dict:
    """Helper to publish a minimal valid P3 ground-motion run via los-pair + series.build_series."""
    pair_meta_base = {
        "dataKind": data_kind,
        "syntheticLineage": data_kind == "synthetic",
        "displacementConvention": "positive_away_from_satellite",
        "displacementUnits": "mm",
        "units": {"displacement": "mm"},
        "spatialReferenceId": "test-ref",
        "spatialReferenceHash": "test-ref-hash",
        "correctionState": {"sourceApplied": [], "subtractedByThisRun": []},
        "correctionsApplied": [],
        "sourceBasis": {"orbit": "ascending", "frame": "009", "maturity": data_kind},
    }
    if ref_polygon is not None:
        pair_meta_base["referenceRegion"] = {"type": "polygonWgs84", "hash": "test-ref-hash", "geometry": ref_polygon}

    # 4 epochs (0->1, 1->2, 2->3, 0->3) so fitResidualMm is populated (counts >= 3).
    epochs = ["2026-06-23T00:00:00Z", "2026-07-17T00:00:00Z", "2026-08-22T00:00:00Z", "2026-10-21T00:00:00Z"]
    pairs = [(0, 1, 0.25), (1, 2, 0.35), (2, 3, 0.40), (0, 3, 1.0)]
    pair_manifests = []
    for idx, (i0, i1, frac) in enumerate(pairs):
        arr = (disp_arr * frac).astype(np.float32)
        if idx == 3:
            # Slight residual so fitResidualMm is nonzero when testing fallback.
            arr = np.where(np.isfinite(arr), arr + 0.5, np.nan).astype(np.float32)
        meta = dict(pair_meta_base)
        meta["acquisitionDates"] = [epochs[i0], epochs[i1]]

        def _writer(stage: Path, a: np.ndarray = arr) -> dict[str, str]:
            core.write_raster(stage / "displacement_mm.tif", a, grid.to_dict())
            return {"displacementMm": "displacement_mm.tif"}

        pair_manifests.append(core.publish(area, "los-pair", meta, _writer, output_root=output_root, review=(data_kind == "synthetic")))

    gm_manifest_path = series.build_series(area, pair_manifests, output_root=output_root)
    if with_current and data_kind == "synthetic":
        gm_base = output_root / area / "p3" / "ground-motion"
        (gm_base / "current.json").write_text(json.dumps({"runId": gm_manifest_path.parent.name}), encoding="utf-8")
    return core.load_manifest(gm_manifest_path)


class PriorityZonesUnitTests(unittest.TestCase):
    def test_and_logic_and_nodata_propagation(self):
        rhythm = np.array(
            [
                [1, 1, 1, 0],
                [0, 255, 1, 255],
                [1, 0, 255, 0],
            ],
            dtype=np.uint8,
        )
        disp = np.array(
            [
                [15.0, 10.0, 5.0, 20.0],
                [2.0, 25.0, np.nan, np.nan],
                [10.001, np.nan, 0.0, 12.0],
            ],
            dtype=np.float64,
        )
        mask, counts = compute_priority_mask(rhythm, disp, threshold_mm=10.0)
        expected = np.array(
            [
                [1, 0, 0, 0],
                [0, 255, 255, 255],
                [1, 255, 255, 0],
            ],
            dtype=np.uint8,
        )
        self.assertEqual(mask.dtype, np.uint8)
        np.testing.assert_array_equal(mask, expected)
        self.assertEqual(counts["priorityPixels"], 2)
        self.assertEqual(counts["validBothPixels"], 7)
        self.assertEqual(counts["nodataPixels"], 5)

    def test_threshold_derivation_2x_std_and_fallback(self):
        disp = np.array(
            [
                [0.0, 2.0, 4.0, 20.0],
                [0.0, 2.0, np.nan, 30.0],
            ],
            dtype=np.float64,
        )
        ref_mask = np.array(
            [
                [True, True, True, False],
                [True, True, True, False],
            ]
        )
        # Valid ref values are [0, 2, 4, 0, 2] -> mean=1.6, std=sqrt(mean((x-1.6)^2))
        expected_std = float(np.std(np.array([0.0, 2.0, 4.0, 0.0, 2.0])))
        t_mm, method, details = derive_threshold(disp, reference_mask=ref_mask)
        self.assertEqual(method, "2x_std_reference_pixels")
        self.assertAlmostEqual(t_mm, 2.0 * expected_std, places=6)
        self.assertEqual(details["referencePixelCount"], 5)

        # Fallback to 2 * nanmedian(fitResidualMm) when no reference mask exists
        fit_res = np.array([[1.0, 2.5, np.nan, 10.0], [1.5, np.nan, np.nan, 3.5]], dtype=np.float64)
        # finite values: [1.0, 1.5, 2.5, 3.5, 10.0] -> median = 2.5 -> T = 5.0
        t_fb, method_fb, details_fb = derive_threshold(disp, fit_residual_mm=fit_res)
        self.assertEqual(method_fb, "2x_nanmedian_fit_residual_mm")
        self.assertAlmostEqual(t_fb, 5.0, places=6)
        self.assertAlmostEqual(details_fb["medianFitResidualMm"], 2.5, places=6)

        # Explicit threshold override
        t_exp, method_exp, _ = derive_threshold(disp, threshold_mm=12.5, reference_mask=ref_mask, fit_residual_mm=fit_res)
        self.assertEqual(method_exp, "explicit")
        self.assertEqual(t_exp, 12.5)

        # Missing everything raises ValueError
        with self.assertRaises(ValueError):
            derive_threshold(disp)

    def test_resampling_finer_rhythm_onto_coarser_motion_grid(self):
        # Rhythm: 20 m (8x8), Motion: 40 m (4x4) -> target MUST be 40 m motion grid (never finer)
        r_grid = Grid("EPSG:32651", (20.0, 0.0, 500000.0, 0.0, -20.0, 1600000.0), 8, 8)
        m_grid = Grid("EPSG:32651", (40.0, 0.0, 500000.0, 0.0, -40.0, 1600000.0), 4, 4)

        rhythm = np.zeros((8, 8), dtype=np.uint8)
        rhythm[0:2, 0:2] = 1
        rhythm[2:4, 2:4] = 255  # nodata block aligning with motion cell (1, 1)
        motion = np.full((4, 4), 25.0, dtype=np.float64)

        aligned = align_grids(rhythm, r_grid, motion, m_grid)
        self.assertTrue(aligned["grid"].same_as(m_grid))
        self.assertEqual(aligned["alignment"]["strategy"], "rhythm_nearest_to_motion_grid")
        self.assertEqual(aligned["rhythm"].shape, (4, 4))
        self.assertEqual(int(aligned["rhythm"][0, 0]), 1)
        self.assertEqual(int(aligned["rhythm"][1, 1]), 255)
        self.assertEqual(int(aligned["rhythm"][3, 3]), 0)

    def test_resampling_finer_motion_onto_coarser_rhythm_grid(self):
        # Motion: 20 m (8x8), Rhythm: 40 m (4x4) -> target MUST be coarser 40 m rhythm grid (never finer than motion)
        m_grid = Grid("EPSG:32651", (20.0, 0.0, 500000.0, 0.0, -20.0, 1600000.0), 8, 8)
        r_grid = Grid("EPSG:32651", (40.0, 0.0, 500000.0, 0.0, -40.0, 1600000.0), 4, 4)

        rhythm = np.ones((4, 4), dtype=np.uint8)
        motion = np.full((8, 8), 10.0, dtype=np.float64)
        motion[0:2, 0:2] = np.array([[10.0, 30.0], [10.0, np.nan]])  # valid avg = 50/3 = 16.6667
        motion[2:4, 2:4] = np.nan  # all NaN -> stays NaN

        aligned = align_grids(rhythm, r_grid, motion, m_grid)
        self.assertTrue(aligned["grid"].same_as(r_grid))
        self.assertEqual(aligned["alignment"]["strategy"], "motion_average_to_coarser_rhythm_grid")
        self.assertEqual(aligned["displacement"].shape, (4, 4))
        self.assertAlmostEqual(float(aligned["displacement"][0, 0]), 50.0 / 3.0, places=4)
        self.assertTrue(np.isnan(aligned["displacement"][1, 1]))


class PriorityZonesIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.places = make_places_root(self.base / "places")
        self.out = self.base / "output"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_rhythm(self, arr: np.ndarray, *, data_kind: str = "synthetic", grid: Grid | None = None) -> tuple[Path, Grid]:
        nisar_dir = self.out / AREA_ID / "nisar"
        nisar_dir.mkdir(parents=True, exist_ok=True)
        if grid is None:
            grid = Grid("EPSG:4326", (STEP, 0.0, W, 0.0, -STEP, N), arr.shape[1], arr.shape[0])
        write_gtiff(nisar_dir / "rhythm_half.tif", arr.astype(np.uint8), grid, nodata=255, dtype="uint8")
        (nisar_dir / "manifest.json").write_text(json.dumps({"area": AREA_ID, "passCount": 6, "dataKind": data_kind}), encoding="utf-8")
        return nisar_dir / "rhythm_half.tif", grid

    def test_sensitivity_datakind_and_wording(self):
        # 4x4 grid matching test_places_support (W, N, STEP)
        rhythm = np.array(
            [
                [1, 1, 1, 0],
                [1, 1, 1, 0],
                [0, 0, 255, 0],
                [0, 0, 0, 1],
            ],
            dtype=np.uint8,
        )
        _, grid = self._write_rhythm(rhythm, data_kind="observed")

        # Reference pixels in bottom-left T1-2 (rows 2..3, cols 0..1) -> values [0, 2, 0, 2], std = 1.0 -> T = 2.0 mm
        # Exposed priority candidates:
        # (0,0)=1.5 -> exposed at 0.5*T (1.0), NOT at T (2.0)
        # (0,1)=3.0 -> exposed at 0.5*T & T (2.0), NOT at 2*T (4.0)
        # (0,2)=6.0 -> exposed at 0.5*T, T, AND 2*T (4.0)
        # (1,0)=2.0 -> == T, so exposed ONLY at 0.5*T (1.0), NOT at T (strict > T)
        # (1,1)=np.nan -> nodata 255 always
        # (3,3)=5.0 -> exposed at 0.5*T, T, 2*T
        disp = np.array(
            [
                [1.5, 3.0, 6.0, 10.0],
                [2.0, np.nan, 0.5, 10.0],
                [0.0, 2.0, 5.0, 0.0],
                [0.0, 2.0, 0.0, 5.0],
            ],
            dtype=np.float64,
        )
        ref_mask = np.zeros((4, 4), dtype=bool)
        ref_mask[2:4, 0:2] = True

        # Case 1: observed rhythm + derived motion -> derived
        gm_manifest = _publish_motion_pair_and_series(self.out, AREA_ID, disp, grid, data_kind="derived")
        gm_manifest["dataStatus"] = "validated"
        manifest = build_priority_zones(
            AREA_ID,
            output_root=self.out,
            places_root=self.places,
            motion_manifest=gm_manifest,
            motion_input=(disp, grid),
            reference_mask=ref_mask,
        )
        self.assertEqual(manifest["dataKind"], "derived")
        self.assertAlmostEqual(manifest["thresholdMm"], 2.0, places=6)
        self.assertEqual(manifest["thresholdMethod"], "2x_std_reference_pixels")
        # At T=2.0: (0,1), (0,2), (3,3) -> 3 pixels
        self.assertEqual(manifest["counts"]["priorityPixels"], 3)

        # Sensitivity math: 0.5*T=1.0 -> 5 px ((0,0),(0,1),(0,2),(1,0),(3,3)), 1.0*T=2.0 -> 3 px, 2.0*T=4.0 -> 2 px ((0,2),(3,3))
        sens = {s["label"]: s for s in manifest["sensitivity"]}
        self.assertAlmostEqual(sens["0.5xT"]["thresholdMm"], 1.0, places=6)
        self.assertAlmostEqual(sens["1.0xT"]["thresholdMm"], 2.0, places=6)
        self.assertAlmostEqual(sens["2.0xT"]["thresholdMm"], 4.0, places=6)
        self.assertEqual(sens["0.5xT"]["priorityPixels"], 5)
        self.assertEqual(sens["1.0xT"]["priorityPixels"], 3)
        self.assertEqual(sens["2.0xT"]["priorityPixels"], 2)
        self.assertGreaterEqual(sens["0.5xT"]["totals"]["population"], sens["1.0xT"]["totals"]["population"])
        self.assertGreaterEqual(sens["1.0xT"]["totals"]["population"], sens["2.0xT"]["totals"]["population"])

        # Verify priority_mask.tif on disk was NOT overwritten by sensitivity variants (still has 3 priority pixels).
        mask_path = self.out / AREA_ID / "nisar" / "priority_mask.tif"
        with rasterio.open(mask_path) as ds:
            on_disk = ds.read(1)
            self.assertEqual(ds.nodata, 255)
        self.assertEqual(int(np.count_nonzero(on_disk == 1)), 3)
        self.assertEqual(int(on_disk[1, 1]), 255)
        self.assertEqual(int(on_disk[2, 2]), 255)

        # Wording check: no "sinking", and "damage" only in "exposure, not damage"
        raw_manifest = (self.out / AREA_ID / "nisar" / "priority_manifest.json").read_text(encoding="utf-8").lower()
        self.assertNotIn("sinking", raw_manifest)
        self.assertNotIn("damage", raw_manifest.replace("exposure, not damage", ""))

        # Case 2: observed rhythm + synthetic motion -> synthetic
        gm_syn = _publish_motion_pair_and_series(self.out, AREA_ID, disp, grid, data_kind="synthetic")
        m2 = build_priority_zones(
            AREA_ID,
            output_root=self.out,
            places_root=self.places,
            motion_manifest=gm_syn,
            motion_input=(disp, grid),
            reference_mask=ref_mask,
        )
        self.assertEqual(m2["dataKind"], "synthetic")

        # Case 3: synthetic rhythm + derived motion -> synthetic
        self._write_rhythm(rhythm, data_kind="synthetic")
        m3 = build_priority_zones(
            AREA_ID,
            output_root=self.out,
            places_root=self.places,
            motion_manifest=gm_manifest,
            motion_input=(disp, grid),
            reference_mask=ref_mask,
        )
        self.assertEqual(m3["dataKind"], "synthetic")

    def test_end_to_end_fit_residual_fallback(self):
        rhythm = np.array(
            [
                [1, 1, 0, 0],
                [1, 0, 0, 0],
                [0, 0, 0, 0],
                [0, 0, 0, 0],
            ],
            dtype=np.uint8,
        )
        _, grid = self._write_rhythm(rhythm, data_kind="synthetic")
        disp = np.full((4, 4), 10.0, dtype=np.float64)
        disp[0, 0] = 0.0  # below fallback threshold
        # No referenceRegion in los-pair -> build_priority_zones falls back to 2 * nanmedian(fitResidualMm)
        gm_manifest = _publish_motion_pair_and_series(self.out, AREA_ID, disp, grid, data_kind="synthetic", ref_polygon=None)
        manifest = build_priority_zones(
            AREA_ID,
            output_root=self.out,
            places_root=self.places,
            run_id=gm_manifest["runId"],
        )
        self.assertEqual(manifest["thresholdMethod"], "2x_nanmedian_fit_residual_mm")
        self.assertGreater(manifest["thresholdMm"], 0.0)
        # (0,1) and (1,0) have rhythm==1 and disp==10 > T; (0,0) has disp==0 <= T
        self.assertEqual(manifest["counts"]["priorityPixels"], 2)

    def test_cli_exits_nonzero_when_ground_motion_missing(self):
        rhythm = np.ones((4, 4), dtype=np.uint8)
        self._write_rhythm(rhythm, data_kind="synthetic")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rc = script_50.main(["--output-root", str(self.out), "--places-root", str(self.places)])

        self.assertNotEqual(rc, 0)
        self.assertIn("ground-motion", stderr.getvalue().lower())
        # Must NOT fabricate motion or write priority_mask.tif
        self.assertFalse((self.out / AREA_ID / "nisar" / "priority_mask.tif").exists())
        self.assertFalse((self.out / AREA_ID / "p3" / "ground-motion").exists())

    def test_end_to_end_synthetic_demo_and_places_exposure_endpoint(self):
        # Create a 30 m rhythm_half.tif over STUDY_BBOX, then run script 50 with --synthetic-motion-demo
        # and verify GET /api/v1/places/exposure?area=camanava_2026&mask=priority returns 200 with dataKind='synthetic'.
        # Use test places root with polygons covering STUDY_BBOX or real places cache if available.
        from processing.nisar_flood.synthetic import make_axes

        x, y = make_axes(spacing=30.0, pad_m=500.0)
        r_grid = Grid("EPSG:32651", (30.0, 0.0, float(x[0] - 15.0), 0.0, -30.0, float(y[0] + 15.0)), x.size, y.size)
        rhythm = np.zeros((y.size, x.size), dtype=np.uint8)
        # Mark coastal/central area inside test_places_support box (W..E, S..N) as flooded >= half
        from pyproj import Transformer

        xx, yy = np.meshgrid(x, y)
        lon, lat = Transformer.from_crs("EPSG:32651", "EPSG:4326", always_xy=True).transform(xx, yy)
        in_test_box = (lon >= W) & (lon <= W + 4 * STEP) & (lat >= N - 4 * STEP) & (lat <= N)
        rhythm[in_test_box] = 1
        self._write_rhythm(rhythm, data_kind="synthetic", grid=r_grid)

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = script_50.main([
                "--synthetic-motion-demo",
                "--output-root", str(self.out),
                "--places-root", str(self.places),
            ])
        self.assertEqual(rc, 0, stdout.getvalue())

        manifest_path = self.out / AREA_ID / "nisar" / "priority_manifest.json"
        mask_path = self.out / AREA_ID / "nisar" / "priority_mask.tif"
        self.assertTrue(manifest_path.is_file())
        self.assertTrue(mask_path.is_file())

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["dataKind"], "synthetic")
        self.assertEqual(manifest["thresholdMethod"], "2x_std_reference_pixels")
        self.assertEqual(manifest["gridAlignment"]["strategy"], "rhythm_nearest_to_motion_grid")
        self.assertGreater(manifest["counts"]["priorityPixels"], 0)
        self.assertEqual(len(manifest["sensitivity"]), 3)

        app = FastAPI()
        app.include_router(make_places_router(self.out, lambda: [], places_root=self.places))
        client = TestClient(app)

        resp = client.get("/api/v1/places/exposure", params={"area": AREA_ID, "mask": "priority"})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["dataKind"], "synthetic")
        self.assertEqual(body["mask"], "priority")
        self.assertEqual(body["totals"], manifest["exposure"]["totals"])
        self.assertGreater(body["totals"]["areaKm2"], 0.0)
        self.assertGreater(body["totals"]["population"], 0)


if __name__ == "__main__":
    unittest.main()
