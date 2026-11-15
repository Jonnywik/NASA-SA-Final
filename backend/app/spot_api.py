"""Read-only spot-check and bilingual place briefing API (T4)."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from rasterio.warp import transform as transform_coordinates

from processing.briefing_place import build_place_briefing, render_csv, render_html
from processing.climate import stats as climate_stats
from processing.climate.constants import CACHE_DIR as CLIMATE_CACHE_DIR
from processing.climate.power import NATIVE_RESOLUTION as POWER_RESOLUTION, POWER_URL, daily_series
from processing.climate.store import read_cache as read_climate_cache
from processing.nisar_flood.geo import Grid
from processing.p3 import catalog as p3_catalog
from processing.p3.series import sample_point as sample_motion_point
from processing.places import BBOX as STUDY_BBOX, PLACES_DIR, gazetteer, path_for as places_path_for

PREFIX = "/api/v1"
AREA_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
STATE_TEXT = {0: "dry", 1: "water", 2: "water", 3: "dry"}


def _error(status: int, code: str, message: str, **extra):
    return HTTPException(status, detail={"code": code, "message": message, **extra})


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _float_or_none(value):
    val = float(value)
    return val if math.isfinite(val) else None


def make_router(output_root, read_public_events, *, places_root=None, climate_cache_dir=None):
    router = APIRouter(prefix=PREFIX)
    root = Path(output_root)
    p_root = Path(places_root) if places_root else PLACES_DIR
    c_root = Path(climate_cache_dir) if climate_cache_dir else CLIMATE_CACHE_DIR

    def _validate_area(area: str) -> str:
        known = {e["id"] for e in read_public_events()}
        if not isinstance(area, str) or not AREA_RE.match(area) or area not in known:
            raise _error(404, "unknown_area", f"Unknown area {area!r}")
        return area

    def _validate_point(lon: str | None, lat: str | None) -> tuple[float, float]:
        try:
            lon_v, lat_v = float(lon), float(lat)
        except (TypeError, ValueError):
            raise _error(422, "invalid_request", "lon and lat are required numbers (WGS84 degrees)") from None
        if not (math.isfinite(lon_v) and math.isfinite(lat_v) and -180 <= lon_v <= 180 and -90 <= lat_v <= 90):
            raise _error(422, "invalid_request", "lon must be within [-180, 180] and lat within [-90, 90]")
        west, south, east, north = STUDY_BBOX
        if not (west <= lon_v <= east and south <= lat_v <= north):
            raise _error(404, "outside_coverage", f"Point is outside the study area bbox {list(STUDY_BBOX)}")
        return lon_v, lat_v

    def _read_place(lon_v: float, lat_v: float, warnings: list[str]) -> dict:
        if not (places_path_for("barangay", p_root).exists() and places_path_for("city", p_root).exists()):
            return {
                "available": False,
                "reason": "place boundary cache is unavailable",
                "source": None,
                "dataKind": None,
                "nativeResolution": None,
                "barangay": None,
                "city": None,
            }
        manifest_path = places_path_for("manifest", p_root)
        manifest = {}
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                manifest = {}
        b_meta = (manifest.get("inputs") or {}).get("boundaries") or {}
        boundary_source = {
            "name": b_meta.get("name", "Philippines COD-AB admin boundaries"),
            "url": b_meta.get("landingPage", "https://data.humdata.org/dataset/cod-ab-phl"),
            "version": b_meta.get("datasetDate", "v03, valid 2025-02-13"),
        }
        loc = gazetteer.locate(lon_v, lat_v, root=p_root)
        reason = None
        if loc["barangay"] is None:
            reason = "point is inside the study bbox but outside any barangay polygon (e.g., open water)"
            warnings.append(reason)
        return {
            "available": True,
            "reason": reason,
            "source": boundary_source,
            "dataKind": "observed",
            "nativeResolution": "administrative boundary (barangay)",
            "barangay": loc["barangay"],
            "city": loc["city"],
        }

    def _read_nisar(area: str, lon_v: float, lat_v: float) -> tuple[dict, dict | None]:
        nisar_dir = root / area / "nisar"
        manifest_path = nisar_dir / "manifest.json"
        unavailable = {
            "available": False,
            "reason": "NISAR flood-rhythm product is unavailable for this area",
            "source": None,
            "dataKind": None,
            "nativeResolution": None,
            "cellCenter": None,
            "floodCount": None,
            "validCount": None,
            "floodCountReason": None,
            "permanentWater": None,
            "possibleFloodedVegetationPasses": None,
            "passCount": None,
            "minValidPasses": None,
            "perPass": [],
        }
        if not manifest_path.is_file():
            return unavailable, None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            unavailable["reason"] = "NISAR product manifest is unreadable"
            return unavailable, None
        if manifest.get("kind") != "nisar-flood-rhythm" or manifest.get("area") != area or "passes" not in manifest:
            unavailable["reason"] = "NISAR product manifest is not a flood-rhythm product for this area"
            return unavailable, None

        data_kind = "synthetic" if manifest.get("dataKind") == "synthetic" else "derived"
        west, south, east, north = manifest["studyBbox"]
        grid = Grid.from_dict(manifest["grid"])
        row_f, col_f = grid.lonlat_to_rowcol(lon_v, lat_v)
        row, col = int(np.floor(row_f)), int(np.floor(col_f))
        if not (west <= lon_v <= east and south <= lat_v <= north) or not (0 <= row < grid.height and 0 <= col < grid.width):
            unavailable["reason"] = "point is outside the NISAR grid coverage"
            return unavailable, manifest

        window = rasterio.windows.Window(col, row, 1, 1)
        base = nisar_dir.resolve()

        def read_pixel(key: str):
            entry = manifest["assets"].get(key)
            if entry is None:
                raise FileNotFoundError(f"missing NISAR asset {key!r}")
            asset_path = (base / entry["path"]).resolve()
            if not asset_path.is_relative_to(base) or not asset_path.is_file():
                raise FileNotFoundError(f"NISAR asset {key!r} is missing on disk")
            with rasterio.open(asset_path) as ds:
                return ds.read(window=window)[:, 0, 0]

        try:
            permanent = bool(read_pixel("permanent_water")[0] == 1)
            counts = read_pixel("rhythm_counts")
            countable = int(counts[1]) > 0
            per_pass = []
            valid = flooded = veg = 0
            for p in manifest["passes"]:
                state = int(read_pixel(p["assets"]["state"])[0])
                db = read_pixel(p["assets"]["db"])
                nodata = state == 255
                if not nodata:
                    valid += 1
                    flooded += state == 1
                    veg += state == 3
                per_pass.append({
                    "date": p["date"],
                    "state": "nodata" if nodata else STATE_TEXT[state],
                    "hhDb": None if nodata else _float_or_none(db[0]),
                    "hvDb": None if nodata else _float_or_none(db[1]),
                    "possibleFloodedVegetation": state == 3,
                    "reason": "no valid HH/HV at this pixel on this pass (outside swath or invalid)" if nodata else None,
                })
        except (OSError, KeyError, ValueError, FileNotFoundError) as exc:
            unavailable["reason"] = f"NISAR raster asset unreadable: {exc}"
            return unavailable, manifest

        lon_c, lat_c = grid.rowcol_to_lonlat(row, col)
        min_valid = manifest["rhythm"]["minValidPasses"]
        if permanent:
            flood_count, count_reason = None, "permanent water is excluded from the flood rhythm"
        elif not countable:
            flood_count, count_reason = None, f"fewer than {min_valid} valid passes at this pixel"
        else:
            flood_count, count_reason = int(counts[0]), None

        return {
            "available": True,
            "reason": count_reason,
            "source": manifest.get("source"),
            "dataKind": data_kind,
            "nativeResolution": manifest.get("nativeResolution"),
            "cellCenter": {"lon": float(lon_c), "lat": float(lat_c)},
            "floodCount": flood_count,
            "validCount": valid,
            "floodCountReason": count_reason,
            "permanentWater": permanent,
            "possibleFloodedVegetationPasses": int(veg),
            "passCount": manifest.get("passCount"),
            "minValidPasses": min_valid,
            "units": {"backscatter": "dB"},
            "perPass": per_pass,
        }, manifest

    def _read_rainfall(nisar_manifest: dict | None, nisar_data_kind: str | None, warnings: list[str]) -> dict:
        unavailable = {
            "available": False,
            "reason": "NASA POWER rainfall cache is missing or failed integrity check",
            "source": None,
            "dataKind": None,
            "nativeResolution": None,
            "units": "mm",
            "passes": [],
        }
        payload, entry = read_climate_cache("power_daily", cache_dir=c_root)
        if payload is None or entry is None:
            return unavailable
        if not nisar_manifest or not isinstance(nisar_manifest.get("passes"), list):
            unavailable["reason"] = "NISAR pass list is unavailable so pass-aligned rainfall cannot be computed"
            return unavailable
        pass_dates = sorted({p["date"] for p in nisar_manifest["passes"] if p.get("date")})
        if not pass_dates:
            unavailable["reason"] = "NISAR pass list is empty"
            return unavailable

        daily = daily_series(payload)
        rows = climate_stats.pass_rainfall(daily, pass_dates)
        first, last = min(daily), max(daily)
        for r in rows:
            if r["date"] > last or r["date"] < first:
                r["reasons"]["all"] = f"outside the cached series ({first} to {last})"

        kind = "synthetic" if nisar_data_kind == "synthetic" else "derived"
        if kind == "synthetic":
            warnings.append("pass dates for rainfall alignment come from a synthetic NISAR product")
        other = [c for c in payload.get("chunks", []) if c.get("sources") and set(c["sources"]) != {"MERRA2"}]
        if other:
            warnings.append(
                f"from {other[0]['start']} NASA POWER serves {'/'.join(other[0]['sources'])} "
                "(near-real-time) instead of MERRA-2 for the latest months"
            )
        if entry.get("lastRefreshError"):
            e = entry["lastRefreshError"]
            warnings.append(f"the last climate refresh failed at {e['at']}; serving cached data from {entry['retrievedAt']}")

        return {
            "available": True,
            "reason": None,
            "source": {
                "name": "NASA POWER Daily API, PRECTOTCORR (MERRA-2 based)",
                "url": POWER_URL,
                "version": payload.get("apiVersion"),
            },
            "dataKind": kind,
            "nativeResolution": POWER_RESOLUTION,
            "retrievedAt": entry.get("retrievedAt"),
            "point": payload.get("point"),
            "units": "mm",
            "windowDefinition": (
                "sameDayMm = pass calendar day; prior3DayMm = 3 days before pass; "
                "prior7DayMm = 7 days before pass (pass day excluded). Null if any day is missing."
            ),
            "passes": rows,
        }

    def _read_ground_motion(area: str, lon_v: float, lat_v: float) -> dict:
        unavailable = {
            "available": False,
            "reason": "No ground-motion product is available for this area",
            "source": None,
            "dataKind": None,
            "nativeResolution": None,
            "runId": None,
            "dataStatus": None,
            "displacementConvention": "positive_away_from_satellite",
            "epochs": [],
            "displacementMm": [],
            "cumulativeDisplacementMm": None,
            "validEpochCount": None,
            "spanDays": None,
            "rateMmPerYear": None,
            "fitResidualMm": None,
            "units": "mm",
        }
        try:
            manifest = p3_catalog.select(area, "ground-motion", root=root)
        except p3_catalog.ProductUnavailable as exc:
            unavailable["reason"] = f"{exc} ({exc.code})"
            return unavailable
        except (ValueError, KeyError, OSError) as exc:
            unavailable["reason"] = f"Ground-motion product is unreadable ({exc})"
            return unavailable

        data_kind = manifest.get("dataKind", "derived")
        source = {
            "name": manifest.get("sensor") or "NISAR L-band InSAR ground motion",
            "url": "https://nisar.jpl.nasa.gov/",
            "version": manifest.get("processingVersion") or manifest.get("algorithmVersion") or manifest.get("runId"),
        }
        res_m = manifest.get("nativeResolutionMetres")
        native_res = {"value": res_m, "units": "m"} if res_m is not None else manifest.get("nativeResolution")

        try:
            pt = sample_motion_point(manifest, lon_v, lat_v)
        except (ValueError, KeyError, OSError) as exc:
            unavailable["reason"] = f"Ground-motion raster could not be sampled ({exc})"
            unavailable["source"] = source
            unavailable["dataKind"] = data_kind
            unavailable["nativeResolution"] = native_res
            return unavailable

        if pt.get("status") != "ok":
            unavailable["reason"] = f"No valid ground-motion estimate at this point ({pt.get('reason') or 'nodata'})"
            unavailable["source"] = source
            unavailable["dataKind"] = data_kind
            unavailable["nativeResolution"] = native_res
            unavailable["runId"] = manifest.get("runId")
            unavailable["dataStatus"] = manifest.get("dataStatus")
            unavailable["epochs"] = pt.get("epochs", [])
            unavailable["displacementMm"] = pt.get("displacementMm", [])
            return unavailable

        valid_vals = [v for v in pt["displacementMm"] if v is not None]
        cumulative = float(valid_vals[-1]) if valid_vals else None
        return {
            "available": True,
            "reason": None,
            "source": source,
            "dataKind": data_kind,
            "nativeResolution": native_res,
            "runId": manifest.get("runId"),
            "dataStatus": manifest.get("dataStatus"),
            "displacementConvention": manifest.get("displacementConvention", "positive_away_from_satellite"),
            "referenceEpoch": manifest.get("referenceEpoch"),
            "latestEpoch": manifest.get("latestEpoch"),
            "cellCenter": pt.get("cellCenter"),
            "epochs": pt["epochs"],
            "displacementMm": pt["displacementMm"],
            "cumulativeDisplacementMm": cumulative,
            "validEpochCount": pt["validEpochCount"],
            "spanDays": pt.get("spanDays"),
            "rateMmPerYear": pt.get("rateMmPerYear"),
            "fitResidualMm": pt.get("fitResidualMm"),
            "units": "mm",
        }

    def _read_priority(area: str, lon_v: float, lat_v: float, nisar_manifest: dict | None) -> dict:
        nisar_dir = root / area / "nisar"
        mask_path = nisar_dir / "priority_mask.tif"
        manifest_path = nisar_dir / "priority_manifest.json"
        unavailable = {
            "available": False,
            "inPriorityZone": None,
            "thresholdMm": None,
            "thresholdMethod": None,
            "thresholdReason": None,
            "reason": "priority_mask.tif is not available yet",
            "source": None,
            "dataKind": None,
            "nativeResolution": None,
        }
        if not mask_path.is_file():
            return unavailable

        pm = {}
        if manifest_path.is_file():
            try:
                pm = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pm = {}

        threshold_mm = pm.get("thresholdMm")
        threshold_method = pm.get("thresholdMethod")
        threshold_reason = None if threshold_mm is not None else "priority_manifest.json is missing or has no thresholdMm"
        data_kind = pm.get("dataKind") or (nisar_manifest or {}).get("dataKind") or "derived"
        source = pm.get("source") or {
            "name": "Tanaw priority exposure zone (NISAR flood rhythm >= half AND line-of-sight motion > threshold)",
            "url": None,
            "version": pm.get("version") or "1.0",
        }

        try:
            with rasterio.open(mask_path) as ds:
                if ds.crs is None:
                    unavailable["reason"] = "priority_mask.tif has no CRS"
                    return unavailable
                native_res = pm.get("nativeResolution") or {
                    "x": float(abs(ds.transform.a)),
                    "y": float(abs(ds.transform.e)),
                    "units": "m" if ds.crs.is_projected else "degree",
                }
                x, y = transform_coordinates("EPSG:4326", ds.crs, [lon_v], [lat_v])
                row, col = ds.index(x[0], y[0])
                if row < 0 or row >= ds.height or col < 0 or col >= ds.width:
                    return {
                        "available": False,
                        "inPriorityZone": None,
                        "thresholdMm": threshold_mm,
                        "thresholdMethod": threshold_method,
                        "thresholdReason": threshold_reason,
                        "reason": "point is outside the priority_mask.tif grid",
                        "source": source,
                        "dataKind": data_kind,
                        "nativeResolution": native_res,
                    }
                window = rasterio.windows.Window(col, row, 1, 1)
                raw = ds.read(1, window=window)[0, 0]
                is_nodata = (ds.nodata is not None and raw == ds.nodata) or (
                    isinstance(raw, (float, np.floating)) and not math.isfinite(float(raw))
                )
        except (OSError, ValueError) as exc:
            unavailable["reason"] = f"priority_mask.tif is unreadable ({exc})"
            return unavailable

        if is_nodata:
            return {
                "available": True,
                "inPriorityZone": None,
                "thresholdMm": threshold_mm,
                "thresholdMethod": threshold_method,
                "thresholdReason": threshold_reason,
                "reason": "priority mask is nodata at this location (flood rhythm or ground motion missing)",
                "source": source,
                "dataKind": data_kind,
                "nativeResolution": native_res,
            }

        return {
            "available": True,
            "inPriorityZone": bool(int(raw) == 1),
            "thresholdMm": threshold_mm,
            "thresholdMethod": threshold_method,
            "thresholdReason": threshold_reason,
            "reason": None,
            "source": source,
            "dataKind": data_kind,
            "nativeResolution": native_res,
        }

    def _compute_spot_check(area: str, lon: str | None, lat: str | None) -> dict:
        area_id = _validate_area(area)
        lon_v, lat_v = _validate_point(lon, lat)
        warnings: list[str] = []

        place = _read_place(lon_v, lat_v, warnings)
        nisar, nisar_manifest = _read_nisar(area_id, lon_v, lat_v)
        rainfall = _read_rainfall(nisar_manifest, nisar.get("dataKind"), warnings)
        ground_motion = _read_ground_motion(area_id, lon_v, lat_v)
        priority_zone = _read_priority(area_id, lon_v, lat_v, nisar_manifest)

        components = (place, nisar, rainfall, ground_motion, priority_zone)
        is_synthetic = any(comp.get("dataKind") == "synthetic" for comp in components)
        top_kind = "synthetic" if is_synthetic else "derived"
        if is_synthetic:
            warnings.insert(0, "SYNTHETIC DEMO DATA: one or more components are synthetic and must not be presented as real observations.")

        limitations = [
            "Point values reflect the containing cell or administrative polygon; points near borders can fall on either side.",
            "NASA POWER rainfall represents one MERRA-2 0.5° x 0.625° grid cell, not a local rain gauge.",
            "NISAR open-water classification under-detects water in dense urban blocks due to radar double-bounce.",
            "Ground motion is measured along the radar line of sight (LOS), not vertical subsidence unless separately derived.",
            "Missing values are reported as null with a reason and are never treated as zero.",
            "Priority zone membership indicates spatial overlap and exposure context, not confirmed impact or causation.",
        ]

        return {
            "area": area_id,
            "lon": lon_v,
            "lat": lat_v,
            "dataKind": top_kind,
            "generatedAt": _now_utc(),
            "source": {
                "name": "Tanaw spot-check aggregator (places, NISAR flood rhythm, NASA POWER rainfall, P3 ground motion, priority zone)",
                "url": None,
                "version": "1.0",
            },
            "nativeResolution": "multi-source (barangay polygon, NISAR grid, 0.5° x 0.625° MERRA-2 cell, ground-motion grid)",
            "place": place,
            "nisar": nisar,
            "rainfall": rainfall,
            "groundMotion": ground_motion,
            "priorityZone": priority_zone,
            "warnings": warnings,
            "limitations": limitations,
        }

    @router.get("/spot-check")
    def spot_check(
        area: str = Query("camanava_2026"),
        lon: str | None = Query(None),
        lat: str | None = Query(None),
    ):
        return _compute_spot_check(area, lon, lat)

    @router.get("/briefing/place")
    def briefing_place(
        area: str = Query("camanava_2026"),
        lon: str | None = Query(None),
        lat: str | None = Query(None),
        lang: str = Query("en"),
        fmt: str = Query("json", alias="format"),
    ):
        if lang not in ("en", "fil"):
            raise _error(422, "invalid_request", "lang must be 'en' or 'fil'")
        if fmt not in ("json", "csv", "html"):
            raise _error(422, "invalid_request", "format must be 'json', 'csv', or 'html'")

        spot = _compute_spot_check(area, lon, lat)
        briefing = build_place_briefing(spot, lang=lang)

        if fmt == "csv":
            csv_text = render_csv(briefing["facts"])
            return Response(
                content=csv_text,
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="tanaw_briefing_{area}_{lang}.csv"',
                    "X-Tanaw-Data-Kind": briefing["dataKind"],
                },
            )
        if fmt == "html":
            html_text = render_html(briefing)
            return HTMLResponse(
                content=html_text,
                headers={"X-Tanaw-Data-Kind": briefing["dataKind"]},
            )
        return briefing

    return router
