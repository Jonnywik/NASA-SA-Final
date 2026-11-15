"""
Script 60: build the validation summary JSON for CAMANAVA 2026.

Honesty rule (AGENTS.md / CODEX_TASKS.md T5):
- Never compute agreement or threshold sensitivity on a synthetic NISAR product
  and present it as validation. When manifest.json has dataKind == "synthetic"
  (or is missing), mark floodValidation and thresholdSensitivity as
  "blocked_pending_real_nisar" with metrics=None.
- When a real ("observed") NISAR flood product exists, compute threshold
  sensitivity (+/-1 dB) in memory from its db_*.tif rasters without modifying
  published assets.
- Record verified independent 2026 flood searches (NASA CMR OPERA_L3_DSWX-S1_V1,
  Copernicus EMS, UNOSAT, NDRRMC/MMDA) and verified published CAMANAVA / Metro
  Manila / Bulacan subsidence studies.

Run from backend/:
    ../.venv/Scripts/python.exe scripts/60_validation.py
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processing.nisar_flood.constants import AREA_ID, BACKEND_DIR, STUDY_BBOX  # noqa: E402
from processing.nisar_flood.geo import Grid, pixel_area_km2, study_mask  # noqa: E402
from processing.p3 import catalog as p3_catalog  # noqa: E402
from processing.validation import threshold_sensitivity  # noqa: E402

DEFAULT_CACHE_DIR = BACKEND_DIR / "data" / "cache" / "validation"
DEFAULT_OUTPUT_ROOT = BACKEND_DIR / "data" / "output"

OPERA_CMR_URL = (
    "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
    "?short_name=OPERA_L3_DSWX-S1_V1"
    "&bounding_box=120.88,14.60,121.04,14.82"
    "&temporal=2026-06-21T00:00:00Z,2026-11-04T23:59:59Z&page_size=200"
)

# Verified live against NASA CMR on 2026-11-15 (UTC 2026-11-14T17:25Z):
# 40 granules in collection C2949811996-POCLOUD (DOI 10.5067/OPDSWS1-L3V1).
OPERA_PASS_MATCHES = [
    {"nisarDate": "2026-06-23", "granuleCount": 4, "granules": [
        "OPERA_L3_DSWx-S1_T51PTS_20260623T215442Z_20260828T220426Z_S1A_30_v1.0",
        "OPERA_L3_DSWx-S1_T51PTS_20260624T215403Z_20260628T225340Z_S1C_30_v1.0",
        "OPERA_L3_DSWx-S1_T51PTS_20260624T215348Z_20260702T113613Z_S1C_30_v1.0",
        "OPERA_L3_DSWx-S1_T51PTS_20260624T215351Z_20260826T172034Z_S1C_30_v1.0",
    ]},
    {"nisarDate": "2026-07-05", "granuleCount": 2, "granules": [
        "OPERA_L3_DSWx-S1_T51PTS_20260706T215404Z_20260719T185202Z_S1C_30_v1.0",
        "OPERA_L3_DSWx-S1_T51PTS_20260706T215349Z_20260720T015400Z_S1C_30_v1.0",
    ]},
    {"nisarDate": "2026-07-17", "granuleCount": 1, "granules": [
        "OPERA_L3_DSWx-S1_T51PTS_20260718T215350Z_20260725T205750Z_S1C_30_v1.0",
    ]},
    {"nisarDate": "2026-08-10", "granuleCount": 1, "granules": [
        "OPERA_L3_DSWx-S1_T51PTS_20260811T215351Z_20260812T132331Z_S1C_30_v1.0",
    ]},
    {"nisarDate": "2026-08-22", "granuleCount": 1, "granules": [
        "OPERA_L3_DSWx-S1_T51PTS_20260823T215352Z_20260824T145614Z_S1C_30_v1.0",
    ]},
    {"nisarDate": "2026-09-03", "granuleCount": 2, "granules": [
        "OPERA_L3_DSWx-S1_T51PTS_20260904T215352Z_20261005T194321Z_S1C_30_v1.0",
        "OPERA_L3_DSWx-S1_T51PTS_20260904T215352Z_20260919T032925Z_S1C_30_v1.0",
    ]},
    {"nisarDate": "2026-09-15", "granuleCount": 1, "granules": [
        "OPERA_L3_DSWx-S1_T51PTS_20260917T214554Z_20261012T223352Z_S1D_30_v1.0",
    ]},
    {"nisarDate": "2026-09-27", "granuleCount": 0, "granules": []},
    {"nisarDate": "2026-10-09", "granuleCount": 2, "granules": [
        "OPERA_L3_DSWx-S1_T51PTS_20261010T215353Z_20261013T071335Z_S1C_30_v1.0",
        "OPERA_L3_DSWx-S1_T51PTS_20261011T214554Z_20261013T061017Z_S1D_30_v1.0",
    ]},
    {"nisarDate": "2026-10-21", "granuleCount": 1, "granules": [
        "OPERA_L3_DSWx-S1_T51PTS_20261022T215352Z_20261023T115302Z_S1C_30_v1.0",
    ]},
    {"nisarDate": "2026-11-02", "granuleCount": 2, "granules": [
        "OPERA_L3_DSWx-S1_T51PTS_20261103T215352Z_20261106T094855Z_S1C_30_v1.0",
        "OPERA_L3_DSWx-S1_T51PTS_20261104T214554Z_20261109T201952Z_S1D_30_v1.0",
    ]},
]

INDEPENDENT_FLOOD_SOURCES = [
    {
        "id": "opera_dswx_s1",
        "name": "NASA OPERA Dynamic Surface Water Extent from Sentinel-1 (OPERA_L3_DSWX-S1_V1)",
        "collectionConceptId": "C2949811996-POCLOUD",
        "doi": "10.5067/OPDSWS1-L3V1",
        "url": OPERA_CMR_URL,
        "dateChecked": "2026-11-15",
        "license": "NASA Earth Science open data policy (Earthdata Login registration required for archive.podaac.earthdata.nasa.gov downloads)",
        "status": "catalogue_matched_download_blocked",
        "totalGranulesInWindow": 40,
        "matchedNisarPasses": 10,
        "totalNisarPasses": 11,
        "passMatchesPlusMinus2Days": OPERA_PASS_MATCHES,
        "notes": "40 Sentinel-1A/C/D 30 m tile T51PTS granules exist in CMR for Jun-Nov 2026; 10 of 11 NISAR passes have >=1 granule within +/-2 days (2026-09-27 has 0). GeoTIFF download requires EARTHDATA_TOKEN.",
    },
    {
        "id": "copernicus_ems",
        "name": "Copernicus Emergency Management Service (EMS) Rapid Mapping",
        "url": "https://mapping.emergency.copernicus.eu/",
        "dateChecked": "2026-11-15",
        "license": "Copernicus EMS / European Union open access (subject to Copernicus terms)",
        "status": "no_2026_philippines_flood_activation",
        "notes": "Web search over rapidmapping.copernicus.eu found no 2026 Philippine flood/typhoon Rapid Mapping activations (prior activations include EMSR636 Noru 2022 and EMSR741 Manila Bay oil spill 2024).",
    },
    {
        "id": "unosat",
        "name": "UNITAR / UNOSAT Emergency Mapping",
        "url": "https://www.unitar.org/maps",
        "dateChecked": "2026-11-15",
        "license": "UNOSAT open humanitarian mapping",
        "status": "no_2026_philippines_flood_activation",
        "notes": "Web search over unitar.org / unosat.org found no 2026 Philippine flood impact assessment activations (prior examples include Typhoon Trami/Kristine in Oct 2024).",
    },
    {
        "id": "ndrrmc_mmda_pagasa",
        "name": "NDRRMC / MMDA / DOST-PAGASA 2026 Flood Advisories",
        "url": "https://www.pagasa.dost.gov.ph/",
        "dateChecked": "2026-11-15",
        "license": "Philippine government public advisories",
        "status": "no_machine_readable_pass_list",
        "notes": "November 2026 search found no active CAMANAVA emergency flood advisories and no machine-readable barangay-level flooded list aligned to the 11 Jun-Nov 2026 NISAR pass dates.",
    },
]

PUBLISHED_SUBSIDENCE_STUDIES = [
    {
        "id": "rodolfo_siringan_2006",
        "citation": (
            "Rodolfo, K.S. & Siringan, F.P. (2006). Global sea-level rise is recognised, but flooding from "
            "anthropogenic land subsidence is ignored around northern Manila Bay, Philippines. Disasters, 30(1), 118-139."
        ),
        "url": "https://doi.org/10.1111/j.1467-9523.2006.00310.x",
        "doi": "10.1111/j.1467-9523.2006.00310.x",
        "method": "Coastal geology, groundwater withdrawal analysis, and northern Manila Bay elevation/flooding synthesis",
        "studyPeriod": "Pre-2006 multi-decade record",
        "publishedRate": "several centimetres to more than a decimetre per year (vs 1 to 3 mm/yr global sea-level rise)",
        "verbatimQuote": (
            "excessive groundwater extraction is lowering the land surface by several centimetres to more than "
            "a decimetre per year."
        ),
        "verifiedVia": "Crossref API (api.crossref.org/works/10.1111/j.1467-9523.2006.00310.x) and OpenAlex abstract",
    },
    {
        "id": "sulapas_2024",
        "citation": (
            "Sulapas, J.J.S., Ybañez, A.A.B., Marasigan, K.M.M., Grageda, J.M.B.M., & Lagmay, A.M.F.A. (2024). "
            "Ground subsidence in major Philippine metropolitan cities from 2014 to 2020. International Journal of "
            "Applied Earth Observation and Geoinformation, 133, 104107."
        ),
        "url": "https://doi.org/10.1016/j.jag.2024.104107",
        "doi": "10.1016/j.jag.2024.104107",
        "method": "Sentinel-1 InSAR time-series analysis (UK COMET LiCSAR products and LiCSBAS; vertical ground motion rates)",
        "studyPeriod": "2014-2020",
        "publishedRate": "up to 109 mm/yr maximum subsidence rate in Bulacan Province in Greater Manila",
        "verbatimQuote": "The results revealed a maximum subsidence rate of 109 mm/yr in Bulacan Province in Greater Manila.",
        "verifiedVia": "Crossref API (api.crossref.org/works/10.1016/j.jag.2024.104107) and OpenAlex abstract",
    },
    {
        "id": "eco_2020",
        "citation": (
            "Eco, R.C., Rodolfo, K.S., Sulapas, J.J., Morales Rivera, A.M., Lagmay, A.M.F., & Amelung, F. (2020). "
            "Disaster in Slow Motion: Widespread Land Subsidence in and Around Metro Manila, Philippines. "
            "JSM Environmental Science & Ecology, 8(1), 1068."
        ),
        "url": "https://www.jscimedcentral.com/public/assets/articles/environmentalscience-8-1068.pdf",
        "doi": None,
        "method": "InSAR time-series analysis over Metro Manila and surrounding coastal provinces",
        "studyPeriod": "Multi-year SAR archive prior to 2020",
        "publishedRate": "Orders of magnitude more rapid than global warming sea-level rise (exact numeric tables in full-text PDF not extracted as plain text here)",
        "verbatimQuote": (
            "Extensive land subsidence in and around Metro Manila, largely from overuse of groundwater, is orders of "
            "magnitude more rapid than sea-level rise from global warming."
        ),
        "verifiedVia": "Direct HTTP 200 PDF retrieval from jscimedcentral.com (12 September 2020)",
    },
]

COMPARISON_LIMITS = [
    "Viewing geometry: NISAR GUNW measures 1-D line-of-sight (LOS) displacement along the radar look vector, not pure vertical subsidence; vertical motion equals LOS only if horizontal motion is zero.",
    "Time baseline mismatch: the 2026 NISAR GUNW stack spans ~4 months (June-October 2026), whereas published InSAR and geological rates reflect multi-year trends (2014-2020 or multi-decade averages) and cannot be compared 1:1 without noting seasonal moisture, ionosphere, and short-baseline noise.",
    "Blocker status: T2 (real NISAR GUNW chain) has not been executed yet because reading ASF GUNW HDF5 files requires EARTHDATA_TOKEN and manual verification of phase sign and stable reference area.",
]


def _run_real_threshold_sensitivity(nisar_dir: Path, manifest: dict) -> dict:
    grid = Grid.from_dict(manifest["grid"])
    bbox = tuple(manifest.get("studyBbox", STUDY_BBOX))
    in_area = study_mask(grid, bbox)
    area_km2 = pixel_area_km2(grid)
    perm_entry = manifest["assets"]["permanent_water"]
    with rasterio.open(nisar_dir / perm_entry["path"]) as ds:
        perm_mask = ds.read(1) == 1

    hh_list, hv_list, valid_list = [], [], []
    for p in manifest["passes"]:
        db_entry = manifest["assets"][p["assets"]["db"]]
        with rasterio.open(nisar_dir / db_entry["path"]) as ds:
            hh = ds.read(1).astype("float32")
            hv = ds.read(2).astype("float32")
        hh_list.append(hh)
        hv_list.append(hv)
        valid_list.append(np.isfinite(hh) & np.isfinite(hv))

    min_valid = int(manifest.get("rhythm", {}).get("minValidPasses", 3))
    return threshold_sensitivity(
        hh_list, hv_list, valid_list, in_area, area_km2,
        manifest["rule"], perm_mask, min_valid_passes=min_valid, deltas=(-1.0, 0.0, 1.0),
    )


def _check_ground_motion(area: str, output_root: Path) -> dict:
    try:
        gm_manifest = p3_catalog.select(area, "ground-motion", None, root=output_root)
    except p3_catalog.ProductUnavailable:
        gm_manifest = None

    if gm_manifest is None or gm_manifest.get("dataKind") == "synthetic":
        status = "blocked_pending_real_gunw"
        reason = (
            "No real NISAR GUNW ground-motion product exists yet for this area "
            "(T2 requires Earthdata token and phase-sign / reference-area verification)."
        )
        if gm_manifest and gm_manifest.get("dataKind") == "synthetic":
            reason = "Existing ground-motion product is synthetic; published subsidence rates are not compared against synthetic displacement."
        return {
            "nisarMotionStatus": status,
            "nisarCumulativeLosMm": None,
            "reason": reason,
            "publishedStudies": PUBLISHED_SUBSIDENCE_STUDIES,
            "comparisonLimits": COMPARISON_LIMITS,
        }

    return {
        "nisarMotionStatus": "observed_product_present",
        "nisarDataKind": gm_manifest.get("dataKind"),
        "nisarRunId": gm_manifest.get("runId"),
        "nisarCumulativeLosMm": None,
        "reason": "Real ground-motion product found; qualitative comparison with published rates awaits spatial summary.",
        "publishedStudies": PUBLISHED_SUBSIDENCE_STUDIES,
        "comparisonLimits": COMPARISON_LIMITS,
    }


def build_validation_payload(area: str = AREA_ID, output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict:
    output_root = Path(output_root)
    nisar_dir = output_root / area / "nisar"
    manifest_path = nisar_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else None
    nisar_kind = manifest.get("dataKind") if manifest else "missing"

    warnings: list[str] = []
    if nisar_kind == "observed":
        ts_metrics = _run_real_threshold_sensitivity(nisar_dir, manifest)
        threshold_block = {
            "status": "computed",
            "nisarDataKind": "observed",
            "metrics": ts_metrics,
            "reason": None,
        }
        flood_block = {
            "status": "blocked_pending_independent_reference_download",
            "nisarDataKind": "observed",
            "metrics": None,
            "reason": (
                "Observed NISAR flood product is present, but OPERA DSWx-S1 GeoTIFFs require Earthdata Login "
                "download and no local 2026 flood reference raster or barangay list is cached."
            ),
            "independentSources": INDEPENDENT_FLOOD_SOURCES,
        }
        warnings.append("Independent 2026 flood raster agreement awaits Earthdata download of OPERA DSWx-S1 GeoTIFFs.")
    else:
        reason = (
            "NISAR flood product is synthetic (T1 requires Earthdata token); independent agreement metrics are not computed on synthetic data."
            if nisar_kind == "synthetic"
            else "No NISAR flood product manifest found for this area; validation metrics cannot be computed."
        )
        ts_reason = (
            "NISAR flood product is synthetic (T1 requires Earthdata token); threshold sensitivity is not computed on synthetic data."
            if nisar_kind == "synthetic"
            else "No NISAR flood product manifest found for this area; threshold sensitivity cannot be computed."
        )
        flood_block = {
            "status": "blocked_pending_real_nisar",
            "nisarDataKind": nisar_kind,
            "metrics": None,
            "reason": reason,
            "independentSources": INDEPENDENT_FLOOD_SOURCES,
        }
        threshold_block = {
            "status": "blocked_pending_real_nisar",
            "nisarDataKind": nisar_kind,
            "metrics": None,
            "reason": ts_reason,
        }
        warnings.append(reason)

    subsidence_block = _check_ground_motion(area, output_root)
    if subsidence_block["nisarMotionStatus"] == "blocked_pending_real_gunw":
        warnings.append(subsidence_block["reason"])

    native_res = manifest.get("nativeResolution") if manifest else {"x": 30.0, "y": 30.0, "units": "m"}
    return {
        "schemaVersion": "1.0",
        "area": area,
        "dataKind": "derived",
        "source": {
            "name": "Tanaw validation summary (NASA CMR OPERA DSWx-S1 catalogue + peer-reviewed subsidence literature)",
            "url": OPERA_CMR_URL,
            "version": "1.0",
        },
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "nativeResolution": native_res,
        "floodValidation": flood_block,
        "thresholdSensitivity": threshold_block,
        "subsidenceComparison": subsidence_block,
        "warnings": warnings,
        "limitations": [
            "No agreement scores or threshold sensitivities are computed on synthetic NISAR outputs.",
            "OPERA L3 DSWx-S1 (Sentinel-1 C-band) and NISAR (L-band) differ in radar wavelength, overpass timing (+/-1 to 2 days), and vegetation/urban penetration.",
            "Copernicus EMS and UNOSAT had no 2026 Philippine flood Rapid Mapping activations; NDRRMC/MMDA had no machine-readable barangay polygon/list dataset aligned to the 11 pass dates.",
            *COMPARISON_LIMITS,
        ],
    }


def write_validation_cache(
    area: str = AREA_ID,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> Path:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = build_validation_payload(area=area, output_root=output_root)
    out_path = cache_dir / f"validation_{area}.json"
    out_path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build validation cache JSON for Tanaw.")
    parser.add_argument("--area", default=AREA_ID)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    args = parser.parse_args(argv)
    out_path = write_validation_cache(area=args.area, output_root=args.output_root, cache_dir=args.cache_dir)
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    print(f"wrote {out_path}")
    print(f"  floodValidation.status = {payload['floodValidation']['status']}")
    print(f"  thresholdSensitivity.status = {payload['thresholdSensitivity']['status']}")
    print(f"  subsidenceComparison.nisarMotionStatus = {payload['subsidenceComparison']['nisarMotionStatus']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
