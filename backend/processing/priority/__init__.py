"""Priority zones: pixels flooded >= half of valid passes AND moving away in LOS > T mm.

Combines NISAR flood rhythm (``rhythm_half.tif``) with P3 cumulative line-of-sight
ground motion (``displacementMm``) on the motion grid's resolution or coarser
(never finer). Nodata (255 in rhythm, NaN in motion) always stays 255.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from pyproj import CRS, Geod, Transformer
from rasterio.features import geometry_mask
from rasterio.warp import Resampling, reproject, transform as transform_coordinates
from shapely.geometry import box, shape
from shapely.ops import transform as shp_transform

from processing.nisar_flood.constants import AREA_ID, BACKEND_DIR, STUDY_BBOX
from processing.nisar_flood.export import sha256_path, write_gtiff
from processing.nisar_flood.geo import Grid
from processing.nisar_flood.synthetic import make_axes
from processing.p3 import catalog, core, series
from processing.places.exposure import exposure_for_mask

PRIORITY_MASK_FILENAME = "priority_mask.tif"
PRIORITY_MANIFEST_FILENAME = "priority_manifest.json"

DEFAULT_LIMITATIONS = [
    "exposure, not damage",
    "cumulative line-of-sight motion away from the satellite is not decomposed into vertical and horizontal components",
    "overlap of flood frequency and line-of-sight motion does not by itself prove causation",
    "nodata in either flood rhythm or ground-motion input remains nodata (255) and is never counted as dry or zero",
]


def _as_grid(grid: Grid | dict[str, Any]) -> Grid:
    return grid if isinstance(grid, Grid) else Grid.from_dict(grid)


def _grid_resolution_metres(grid: Grid) -> tuple[float, float]:
    """Pixel spacing (x_m, y_m) at the grid centre in WGS84 metres."""
    col = grid.width / 2.0
    row = grid.height / 2.0
    pts = [grid.affine @ (col, row), grid.affine @ (col + 1.0, row), grid.affine @ (col, row + 1.0)]
    xs, ys = transform_coordinates(grid.crs, "EPSG:4326", [p[0] for p in pts], [p[1] for p in pts])
    geod = Geod(ellps="WGS84")
    dx = float(geod.inv(xs[0], ys[0], xs[1], ys[1])[2])
    dy = float(geod.inv(xs[0], ys[0], xs[2], ys[2])[2])
    if not (math.isfinite(dx) and math.isfinite(dy) and dx > 0 and dy > 0):
        raise ValueError(f"Unable to measure pixel spacing for grid {grid}")
    return dx, dy


def _load_raster_input(
    source: str | Path | tuple[Any, ...],
    *,
    default_nodata: float | int | None = None,
) -> tuple[np.ndarray, Grid, float | int | None]:
    """Load a 2-D raster from a file path or (array, grid_or_transform[, crs[, nodata]])."""
    if isinstance(source, (str, Path)):
        with rasterio.open(source) as ds:
            if ds.crs is None:
                raise ValueError(f"Raster has no CRS: {source}")
            arr = ds.read(1)
            nodata = ds.nodata if ds.nodata is not None else default_nodata
            grid = Grid(ds.crs.to_string(), tuple(float(v) for v in ds.transform)[:6], ds.width, ds.height)
        return arr, grid, nodata

    if isinstance(source, tuple) and len(source) >= 2:
        arr = np.asarray(source[0])
        second = source[1]
        if isinstance(second, (Grid, dict)):
            grid = _as_grid(second)
            nodata = source[2] if len(source) >= 3 else default_nodata
        else:
            crs = source[2] if len(source) >= 3 and source[2] is not None else "EPSG:4326"
            nodata = source[3] if len(source) >= 4 else default_nodata
            tf = tuple(float(v) for v in tuple(Affine(*tuple(second)[:6]))[:6])
            grid = Grid(CRS.from_user_input(crs).to_string(), tf, arr.shape[1], arr.shape[0])
        if arr.ndim != 2 or arr.shape != (grid.height, grid.width):
            raise ValueError("Raster array shape must match grid dimensions")
        return arr, grid, nodata

    raise ValueError("Raster input must be a file path or (array, grid_or_transform[, ...]) tuple")


def _to_float_with_nan(arr: np.ndarray, nodata: float | int | None) -> np.ndarray:
    out = np.asarray(arr, dtype=np.float64).copy()
    if nodata is not None and not (isinstance(nodata, float) and np.isnan(nodata)):
        out[out == nodata] = np.nan
    out[~np.isfinite(out)] = np.nan
    return out


def align_grids(
    rhythm_arr: np.ndarray,
    rhythm_grid: Grid | dict[str, Any],
    motion_arr: np.ndarray,
    motion_grid: Grid | dict[str, Any],
    *,
    rhythm_nodata: int | float = 255,
    motion_nodata: float | None = None,
    fit_residual: np.ndarray | None = None,
    reference_mask: np.ndarray | None = None,
    reference_mask_grid: Grid | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Align rhythm and motion onto the motion grid's resolution or coarser (never finer)."""
    rg = _as_grid(rhythm_grid)
    mg = _as_grid(motion_grid)

    rx, ry = _grid_resolution_metres(rg)
    mx, my = _grid_resolution_metres(mg)
    rhythm_res_m = math.sqrt(rx * ry)
    motion_res_m = math.sqrt(mx * my)

    r_nodata = 255 if rhythm_nodata is None else int(rhythm_nodata)
    r_u8 = np.where(np.isfinite(rhythm_arr), rhythm_arr, r_nodata).astype(np.uint8) if rhythm_arr.dtype.kind == "f" else np.asarray(rhythm_arr, dtype=np.uint8)
    m_f64 = _to_float_with_nan(motion_arr, motion_nodata)
    res_f64 = None if fit_residual is None else _to_float_with_nan(fit_residual, motion_nodata)

    if rg.same_as(mg):
        target_grid = mg
        aligned_rhythm = r_u8
        aligned_motion = m_f64
        aligned_residual = res_f64
        strategy = "none_identical_grids"
    elif rhythm_res_m <= motion_res_m * (1.0 + 1e-6):
        # Rhythm is finer or equal resolution: keep motion grid, resample rhythm with nearest neighbour.
        target_grid = mg
        aligned_rhythm = np.full((mg.height, mg.width), 255, dtype=np.uint8)
        reproject(
            source=r_u8,
            destination=aligned_rhythm,
            src_transform=rg.affine,
            src_crs=rg.crs,
            src_nodata=r_nodata,
            dst_transform=mg.affine,
            dst_crs=mg.crs,
            dst_nodata=255,
            resampling=Resampling.nearest,
        )
        aligned_motion = m_f64
        aligned_residual = res_f64
        strategy = "rhythm_nearest_to_motion_grid"
    else:
        # Motion is strictly finer than rhythm: downsample motion onto coarser rhythm grid via average.
        target_grid = rg
        aligned_rhythm = r_u8
        dst_motion = np.full((rg.height, rg.width), np.nan, dtype=np.float32)
        reproject(
            source=m_f64.astype(np.float32),
            destination=dst_motion,
            src_transform=mg.affine,
            src_crs=mg.crs,
            src_nodata=np.nan,
            dst_transform=rg.affine,
            dst_crs=rg.crs,
            dst_nodata=np.nan,
            resampling=Resampling.average,
        )
        aligned_motion = dst_motion.astype(np.float64)
        aligned_residual = None
        if res_f64 is not None:
            dst_res = np.full((rg.height, rg.width), np.nan, dtype=np.float32)
            reproject(
                source=res_f64.astype(np.float32),
                destination=dst_res,
                src_transform=mg.affine,
                src_crs=mg.crs,
                src_nodata=np.nan,
                dst_transform=rg.affine,
                dst_crs=rg.crs,
                dst_nodata=np.nan,
                resampling=Resampling.average,
            )
            aligned_residual = dst_res.astype(np.float64)
        strategy = "motion_average_to_coarser_rhythm_grid"

    aligned_ref = None
    if reference_mask is not None:
        ref_bool = np.asarray(reference_mask, dtype=np.uint8)
        src_ref_grid = _as_grid(reference_mask_grid) if reference_mask_grid is not None else mg
        if src_ref_grid.same_as(target_grid):
            aligned_ref = ref_bool > 0
        else:
            dst_ref = np.zeros((target_grid.height, target_grid.width), dtype=np.uint8)
            reproject(
                source=(ref_bool > 0).astype(np.uint8),
                destination=dst_ref,
                src_transform=src_ref_grid.affine,
                src_crs=src_ref_grid.crs,
                src_nodata=255,
                dst_transform=target_grid.affine,
                dst_crs=target_grid.crs,
                dst_nodata=0,
                resampling=Resampling.nearest,
            )
            aligned_ref = dst_ref > 0

    tx, ty = _grid_resolution_metres(target_grid)
    return {
        "rhythm": aligned_rhythm,
        "displacement": aligned_motion,
        "fit_residual": aligned_residual,
        "reference_mask": aligned_ref,
        "grid": target_grid,
        "alignment": {
            "strategy": strategy,
            "rhythmResolutionMetres": {"x": round(rx, 3), "y": round(ry, 3)},
            "motionResolutionMetres": {"x": round(mx, 3), "y": round(my, 3)},
            "targetResolutionMetres": {"x": round(tx, 3), "y": round(ty, 3)},
        },
    }


def rasterize_reference_geometry(geometry_or_bbox: dict[str, Any] | list[float] | tuple[float, ...], grid: Grid | dict[str, Any]) -> np.ndarray:
    """Rasterize a WGS84 GeoJSON Polygon/MultiPolygon or (W, S, E, N) bbox onto ``grid``."""
    g = _as_grid(grid)
    if isinstance(geometry_or_bbox, dict):
        geom_obj = geometry_or_bbox.get("geometry") if geometry_or_bbox.get("type") == "Feature" else geometry_or_bbox
        geom = shape(geom_obj)
    elif isinstance(geometry_or_bbox, (list, tuple)) and len(geometry_or_bbox) == 4:
        w, s, e, n = (float(v) for v in geometry_or_bbox)
        if not (w < e and s < n):
            raise ValueError("reference_bbox must have west < east and south < north")
        geom = box(w, s, e, n)
    else:
        raise ValueError("Reference geometry must be a GeoJSON geometry/Feature or 4-element (W, S, E, N) bbox")

    if CRS.from_user_input(g.crs) != CRS.from_epsg(4326):
        tf = Transformer.from_crs("EPSG:4326", g.crs, always_xy=True).transform
        geom = shp_transform(tf, geom)
    return geometry_mask([geom], out_shape=(g.height, g.width), transform=g.affine, invert=True)


def recover_reference_mask(
    grid: Grid,
    *,
    reference_mask: Any = None,
    reference_bbox: tuple[float, float, float, float] | list[float] | None = None,
    motion_manifest: dict[str, Any] | None = None,
    output_root: Path | None = None,
    area: str = AREA_ID,
) -> tuple[np.ndarray | None, str | None]:
    """Recover a boolean reference mask on ``grid`` from explicit args or P3 pair metadata."""
    if reference_mask is not None:
        arr, mask_grid, nodata = _load_raster_input(reference_mask) if not isinstance(reference_mask, np.ndarray) else (reference_mask, grid, None)
        valid = np.isfinite(arr) if arr.dtype.kind == "f" else np.ones(arr.shape, dtype=bool)
        if nodata is not None and not (isinstance(nodata, float) and np.isnan(nodata)):
            valid &= arr != nodata
        bool_mask = (valid & (arr > 0)).astype(np.uint8)
        if not mask_grid.same_as(grid):
            dst = np.zeros((grid.height, grid.width), dtype=np.uint8)
            reproject(
                source=bool_mask,
                destination=dst,
                src_transform=mask_grid.affine,
                src_crs=mask_grid.crs,
                src_nodata=255,
                dst_transform=grid.affine,
                dst_crs=grid.crs,
                dst_nodata=0,
                resampling=Resampling.nearest,
            )
            return dst > 0, "explicit_reference_mask"
        return bool_mask > 0, "explicit_reference_mask"

    if reference_bbox is not None:
        return rasterize_reference_geometry(reference_bbox, grid), "explicit_reference_bbox"

    if motion_manifest:
        reg = motion_manifest.get("referenceRegion")
        if isinstance(reg, dict) and isinstance(reg.get("geometry"), dict):
            return rasterize_reference_geometry(reg["geometry"], grid), "motion_manifest_reference_region"
        if motion_manifest.get("referenceBbox") is not None:
            return rasterize_reference_geometry(motion_manifest["referenceBbox"], grid), "motion_manifest_reference_bbox"

        root = Path(output_root or core.OUTPUT_ROOT)
        pair_ids = motion_manifest.get("sourceRunIds") or motion_manifest.get("upstreamRunIds") or []
        for pair_id in pair_ids:
            pair_manifest_path = root / area / "p3" / "los-pair" / str(pair_id) / "manifest.json"
            if not pair_manifest_path.is_file():
                continue
            try:
                pair_manifest = json.loads(pair_manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            pair_reg = pair_manifest.get("referenceRegion")
            if isinstance(pair_reg, dict) and isinstance(pair_reg.get("geometry"), dict):
                return rasterize_reference_geometry(pair_reg["geometry"], grid), f"los_pair_reference_region:{pair_id}"

    return None, None


def derive_threshold(
    displacement_mm: np.ndarray,
    *,
    threshold_mm: float | None = None,
    reference_mask: np.ndarray | None = None,
    reference_source: str | None = None,
    fit_residual_mm: np.ndarray | None = None,
) -> tuple[float, str, dict[str, Any]]:
    """Derive noise threshold T (mm) from explicit value, 2*std(reference), or 2*nanmedian(fitResidualMm)."""
    if threshold_mm is not None:
        if isinstance(threshold_mm, bool) or not isinstance(threshold_mm, (int, float, np.number)):
            raise ValueError("threshold_mm must be a finite non-negative number")
        t_val = float(threshold_mm)
        if not math.isfinite(t_val) or t_val < 0:
            raise ValueError("threshold_mm must be a finite non-negative number")
        return t_val, "explicit", {"explicitThresholdMm": t_val}

    fallback_reason = None
    if reference_mask is not None:
        ref = np.asarray(reference_mask, dtype=bool)
        if ref.shape != displacement_mm.shape:
            raise ValueError("reference_mask shape must match displacement grid")
        ref_vals = displacement_mm[ref & np.isfinite(displacement_mm)]
        if ref_vals.size >= 2:
            std_mm = float(np.std(ref_vals))
            return 2.0 * std_mm, "2x_std_reference_pixels", {
                "referenceSource": reference_source or "reference_mask",
                "referencePixelCount": int(ref_vals.size),
                "referenceStdMm": std_mm,
                "referenceMeanMm": float(np.mean(ref_vals)),
            }
        fallback_reason = f"reference mask had {int(ref_vals.size)} valid pixels (need >= 2)"
    else:
        fallback_reason = "no reference mask or reference geometry available"

    if fit_residual_mm is not None:
        valid_res = fit_residual_mm[np.isfinite(fit_residual_mm)]
        if valid_res.size >= 1:
            med_res = float(np.nanmedian(valid_res))
            return 2.0 * med_res, "2x_nanmedian_fit_residual_mm", {
                "medianFitResidualMm": med_res,
                "fitResidualPixelCount": int(valid_res.size),
                "referenceFallbackReason": fallback_reason,
            }

    raise ValueError(
        "Cannot derive priority threshold: provide --threshold-mm, a reference mask/bbox/geometry with >= 2 valid pixels, "
        "or a ground-motion fitResidualMm asset"
    )


def compute_priority_mask(
    rhythm_half: np.ndarray,
    displacement_mm: np.ndarray,
    threshold_mm: float,
    *,
    rhythm_nodata: int | float = 255,
    motion_nodata: float | None = None,
) -> tuple[np.ndarray, dict[str, int]]:
    """Compute uint8 priority mask (1 = flooded >= half AND displacement > T, 0 = valid other, 255 = nodata)."""
    if rhythm_half.shape != displacement_mm.shape:
        raise ValueError("rhythm_half and displacement_mm must have identical shape")
    r_arr = np.asarray(rhythm_half)
    r_valid = np.isfinite(r_arr) if r_arr.dtype.kind == "f" else np.ones(r_arr.shape, dtype=bool)
    if rhythm_nodata is not None and not (isinstance(rhythm_nodata, float) and np.isnan(rhythm_nodata)):
        r_valid &= r_arr != rhythm_nodata

    m_arr = _to_float_with_nan(displacement_mm, motion_nodata)
    m_valid = np.isfinite(m_arr)
    both_valid = r_valid & m_valid

    r_flood = r_valid & (r_arr == 1)
    m_over = m_valid & (m_arr > float(threshold_mm))
    priority = both_valid & r_flood & m_over

    out = np.full(r_arr.shape, 255, dtype=np.uint8)
    out[both_valid] = 0
    out[priority] = 1

    counts = {
        "priorityPixels": int(np.count_nonzero(priority)),
        "validBothPixels": int(np.count_nonzero(both_valid)),
        "nodataPixels": int(np.count_nonzero(~both_valid)),
        "rhythmHalfExposedPixels": int(np.count_nonzero(both_valid & r_flood)),
        "motionExceedsThresholdPixels": int(np.count_nonzero(both_valid & m_over)),
    }
    return out, counts


def compute_sensitivity(
    rhythm_half: np.ndarray,
    displacement_mm: np.ndarray,
    grid: Grid,
    threshold_mm: float,
    *,
    primary_totals: dict[str, Any] | None = None,
    primary_pixels: int | None = None,
    places_root: Path | None = None,
    rhythm_nodata: int | float = 255,
    motion_nodata: float | None = None,
) -> list[dict[str, Any]]:
    """Compute exposure totals at 0.5*T, 1.0*T, and 2.0*T without modifying priority_mask.tif."""
    results: list[dict[str, Any]] = []
    for mult, label in ((0.5, "0.5xT"), (1.0, "1.0xT"), (2.0, "2.0xT")):
        t_var = float(threshold_mm) * mult
        if mult == 1.0 and primary_totals is not None and primary_pixels is not None:
            results.append({
                "multiplier": mult,
                "label": label,
                "thresholdMm": t_var,
                "priorityPixels": int(primary_pixels),
                "totals": primary_totals,
            })
            continue
        mask_var, counts_var = compute_priority_mask(
            rhythm_half, displacement_mm, t_var, rhythm_nodata=rhythm_nodata, motion_nodata=motion_nodata
        )
        exp = exposure_for_mask((mask_var, grid.affine, grid.crs), level="barangay", nodata=255, root=places_root)
        results.append({
            "multiplier": mult,
            "label": label,
            "thresholdMm": t_var,
            "priorityPixels": counts_var["priorityPixels"],
            "totals": exp["totals"],
        })
    return results


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        tmp.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _atomic_write_gtiff(path: Path, array: np.ndarray, grid: Grid, *, nodata: int, dtype: str, descriptions: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{uuid.uuid4().hex[:8]}.tif"
    try:
        write_gtiff(tmp, array, grid, nodata=nodata, dtype=dtype, descriptions=descriptions)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def build_priority_zones(
    area: str = AREA_ID,
    *,
    output_root: str | Path | None = None,
    places_root: str | Path | None = None,
    run_id: str | None = None,
    threshold_mm: float | None = None,
    reference_mask: Any = None,
    reference_bbox: tuple[float, float, float, float] | list[float] | None = None,
    rhythm_input: str | Path | tuple[Any, ...] | None = None,
    rhythm_manifest: dict[str, Any] | None = None,
    motion_input: str | Path | tuple[Any, ...] | None = None,
    motion_manifest: dict[str, Any] | None = None,
    fit_residual_input: str | Path | tuple[Any, ...] | None = None,
    out_dir: str | Path | None = None,
    write_outputs: bool = True,
) -> dict[str, Any]:
    """Compute priority zones (flood rhythm >= half AND LOS motion > T), exposure, and sensitivity."""
    root = Path(output_root or core.OUTPUT_ROOT)
    nisar_dir = root / area / "nisar"
    dest_dir = Path(out_dir) if out_dir is not None else nisar_dir
    places_dir = Path(places_root) if places_root is not None else None

    if rhythm_input is None:
        rhythm_path = nisar_dir / "rhythm_half.tif"
        if not rhythm_path.is_file():
            raise FileNotFoundError(f"Flood rhythm raster not found: {rhythm_path}")
        rhythm_input = rhythm_path
        if rhythm_manifest is None and (nisar_dir / "manifest.json").is_file():
            rhythm_manifest = json.loads((nisar_dir / "manifest.json").read_text(encoding="utf-8"))
    rhythm_arr, rhythm_grid, rhythm_nodata = _load_raster_input(rhythm_input, default_nodata=255)
    rhythm_meta = rhythm_manifest or {}

    if motion_input is None:
        if motion_manifest is None:
            motion_manifest = catalog.select(area, "ground-motion", run_id, root=root)
        motion_arr, motion_grid_dict = core.read_raster(motion_manifest, "displacementMm")
        motion_grid = _as_grid(motion_grid_dict)
        motion_nodata = np.nan
        if fit_residual_input is None and "fitResidualMm" in motion_manifest.get("assets", {}):
            fit_res_arr, _ = core.read_raster(motion_manifest, "fitResidualMm")
        elif fit_residual_input is not None:
            fit_res_arr, _, _ = _load_raster_input(fit_residual_input, default_nodata=np.nan)
        else:
            fit_res_arr = None
    else:
        motion_arr, motion_grid, motion_nodata = _load_raster_input(motion_input, default_nodata=np.nan)
        if fit_residual_input is not None:
            fit_res_arr, _, _ = _load_raster_input(fit_residual_input, default_nodata=np.nan)
        else:
            fit_res_arr = None
    motion_meta = motion_manifest or {}

    # Recover reference mask on motion grid first (if supplied on motion grid or via P3 metadata)
    # or rasterize reference geometry directly onto target grid after alignment.
    explicit_ref_arr = None
    explicit_ref_grid = None
    explicit_ref_source = None
    if reference_mask is not None:
        if isinstance(reference_mask, np.ndarray):
            explicit_ref_arr = reference_mask
            explicit_ref_grid = motion_grid
        else:
            explicit_ref_arr, explicit_ref_grid, _ = _load_raster_input(reference_mask)
        explicit_ref_source = "explicit_reference_mask"

    aligned = align_grids(
        rhythm_arr,
        rhythm_grid,
        motion_arr,
        motion_grid,
        rhythm_nodata=255 if rhythm_nodata is None else rhythm_nodata,
        motion_nodata=motion_nodata,
        fit_residual=fit_res_arr,
        reference_mask=explicit_ref_arr,
        reference_mask_grid=explicit_ref_grid,
    )
    target_grid: Grid = aligned["grid"]

    if aligned["reference_mask"] is not None:
        ref_mask_target = aligned["reference_mask"]
        ref_source = explicit_ref_source
    else:
        ref_mask_target, ref_source = recover_reference_mask(
            target_grid,
            reference_bbox=reference_bbox,
            motion_manifest=motion_meta,
            output_root=root,
            area=area,
        )

    t_mm, t_method, t_details = derive_threshold(
        aligned["displacement"],
        threshold_mm=threshold_mm,
        reference_mask=ref_mask_target,
        reference_source=ref_source,
        fit_residual_mm=aligned["fit_residual"],
    )

    priority_mask, counts = compute_priority_mask(
        aligned["rhythm"], aligned["displacement"], t_mm, rhythm_nodata=255
    )

    warnings: list[str] = []
    if not rhythm_meta:
        warnings.append("NISAR flood-rhythm manifest not found; rhythm dataKind could not be verified.")
    rhythm_kind = rhythm_meta.get("dataKind", "unknown")
    motion_kind = motion_meta.get("dataKind", "unknown")
    is_synthetic = (
        rhythm_kind == "synthetic"
        or motion_kind == "synthetic"
        or bool(motion_meta.get("syntheticLineage"))
    )
    data_kind = "synthetic" if is_synthetic else "derived"
    if data_kind == "synthetic":
        warnings.insert(0, "SYNTHETIC INPUTS PRESENT: priority zones carry dataKind='synthetic' and must not be published as real observations.")
    if t_mm == 0.0:
        warnings.append("Derived noise threshold T is 0.0 mm.")

    mask_path = dest_dir / PRIORITY_MASK_FILENAME
    manifest_path = dest_dir / PRIORITY_MANIFEST_FILENAME

    if write_outputs:
        _atomic_write_gtiff(
            mask_path,
            priority_mask,
            target_grid,
            nodata=255,
            dtype="uint8",
            descriptions=[
                f"1 = flooded >= half valid passes and cumulative LOS displacement > {t_mm:.4f} mm (away from satellite), 0 = valid not priority, 255 = nodata"
            ],
        )
        exposure = exposure_for_mask(str(mask_path), level="barangay", root=places_dir)
    else:
        exposure = exposure_for_mask((priority_mask, target_grid.affine, target_grid.crs), level="barangay", nodata=255, root=places_dir)

    sensitivity = compute_sensitivity(
        aligned["rhythm"],
        aligned["displacement"],
        target_grid,
        t_mm,
        primary_totals=exposure["totals"],
        primary_pixels=counts["priorityPixels"],
        places_root=places_dir,
        rhythm_nodata=255,
    )

    warnings.extend(exposure.get("warnings", []))
    limitations = list(dict.fromkeys(DEFAULT_LIMITATIONS + list(exposure.get("limitations", []))))

    rhythm_sha = sha256_path(Path(rhythm_input)) if isinstance(rhythm_input, (str, Path)) else None
    motion_asset_sha = (motion_meta.get("assets") or {}).get("displacementMm", {}).get("sha256")
    manifest: dict[str, Any] = {
        "schemaVersion": "1.0",
        "kind": "nisar-priority-zones",
        "area": area,
        "dataKind": data_kind,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "thresholdMm": t_mm,
        "thresholdMethod": t_method,
        "thresholdDetails": t_details,
        "grid": target_grid.to_dict(),
        "nativeResolutionMetres": aligned["alignment"]["targetResolutionMetres"],
        "gridAlignment": aligned["alignment"],
        "maskDefinition": (
            "1 where rhythm_half == 1 and cumulative line-of-sight displacement > thresholdMm "
            "(away from satellite); 0 where valid in both otherwise; 255 where either input is nodata"
        ),
        "counts": counts,
        "inputs": {
            "rhythm": {
                "path": str(rhythm_input) if isinstance(rhythm_input, (str, Path)) else None,
                "dataKind": rhythm_kind,
                "passCount": rhythm_meta.get("passCount"),
                "sha256": rhythm_sha,
            },
            "groundMotion": {
                "runId": motion_meta.get("runId"),
                "dataKind": motion_kind,
                "dataStatus": motion_meta.get("dataStatus"),
                "referenceEpoch": motion_meta.get("referenceEpoch"),
                "latestEpoch": motion_meta.get("latestEpoch"),
                "displacementConvention": motion_meta.get("displacementConvention", "positive_away_from_satellite"),
                "displacementMmSha256": motion_asset_sha,
            },
        },
        "sensitivity": sensitivity,
        "exposure": {
            "level": "barangay",
            "zones": exposure["zones"],
            "totals": exposure["totals"],
            "populationUnavailableReason": exposure["populationUnavailableReason"],
            "buildingsUnavailableReason": exposure["buildingsUnavailableReason"],
        },
        "source": {
            "name": "Tanaw priority zones (NISAR flood rhythm AND cumulative line-of-sight motion)",
            "url": "https://nisar.jpl.nasa.gov/",
        },
        "assets": (
            {
                "priority_mask": {
                    "path": PRIORITY_MASK_FILENAME,
                    "sha256": sha256_path(mask_path),
                    "bytes": mask_path.stat().st_size,
                    "kind": "geotiff",
                }
            }
            if write_outputs
            else {}
        ),
        "warnings": warnings,
        "limitations": limitations,
    }

    if write_outputs:
        _atomic_write_json(manifest_path, manifest)
    return manifest


def create_synthetic_motion_demo(
    area: str = AREA_ID,
    *,
    output_root: str | Path | None = None,
    spacing_m: float = 60.0,
    reference_bbox: tuple[float, float, float, float] = (121.00, 14.74, 121.03, 14.78),
    force: bool = False,
) -> Path:
    """Explicitly build and publish a synthetic P3 ground-motion run for demo/testing ONLY.

    Refuses to overwrite a non-synthetic current ground-motion pointer unless ``force=True``.
    """
    root = Path(output_root or core.OUTPUT_ROOT)
    gm_base = root / area / "p3" / "ground-motion"
    current_ptr = gm_base / "current.json"
    if current_ptr.is_file() and not force:
        try:
            existing = catalog.select(area, "ground-motion", root=root)
            if existing.get("dataKind") != "synthetic":
                raise ValueError(
                    f"Existing ground-motion product for {area!r} has dataKind={existing.get('dataKind')!r}; "
                    "pass --force to replace it with synthetic demo data."
                )
        except catalog.ProductUnavailable:
            pass

    x, y = make_axes(STUDY_BBOX, spacing=float(spacing_m), pad_m=1500.0, epsg=32651)
    xx, yy = np.meshgrid(x, y)
    lon, lat = Transformer.from_crs("EPSG:32651", "EPSG:4326", always_xy=True).transform(xx, yy)
    grid = {
        "crs": "EPSG:32651",
        "transform": [float(spacing_m), 0.0, float(x[0] - spacing_m / 2.0), 0.0, -float(spacing_m), float(y[0] + spacing_m / 2.0)],
        "width": int(x.size),
        "height": int(y.size),
    }

    # Deterministic synthetic cumulative LOS displacement field (mm, positive away from satellite):
    # - Inland east reference area has small zero-mean noise (~1.5 mm std)
    # - Low-lying coastal CAMANAVA strip has synthetic positive-away LOS displacement (+18 to +32 mm)
    # - Small NaN nodata block in south-east to exercise nodata propagation
    rng = np.random.default_rng(20261115)
    coast = 120.935 + 0.012 * np.sin((lat - 14.6) * 40.0)
    coastal_belt = np.exp(-((lon - (coast + 0.025)) / 0.025) ** 2) * np.exp(-((lat - 14.69) / 0.08) ** 2)
    cumulative_mm = 28.0 * coastal_belt
    rw, rs, re, rn = reference_bbox
    in_ref = (lon >= rw) & (lon <= re) & (lat >= rs) & (lat <= rn)
    cumulative_mm[in_ref] = 0.0
    nodata_patch = (lon >= 121.01) & (lon <= 121.035) & (lat >= 14.605) & (lat <= 14.625)

    epochs = ["2026-06-23T21:30:35Z", "2026-07-17T21:30:34Z", "2026-08-22T21:30:32Z", "2026-10-21T21:30:32Z"]
    fractions = [0.0, 0.3, 0.65, 1.0]
    epoch_fields = [cumulative_mm * f + rng.normal(0.0, 1.2, size=cumulative_mm.shape) for f in fractions]
    epoch_fields[0] = np.zeros_like(cumulative_mm)

    ref_poly = {
        "type": "Polygon",
        "coordinates": [[[rw, rs], [re, rs], [re, rn], [rw, rn], [rw, rs]]],
    }
    ref_hash = hashlib.sha256(json.dumps(ref_poly, sort_keys=True).encode("utf-8")).hexdigest()

    source_basis = {
        "orbit": "ascending-synthetic",
        "frame": "009",
        "maturity": "synthetic",
        "sensor": "SYNTHETIC GUNW-like fixture (not NISAR)",
        "frequency": "L",
        "polarization": "HH",
        "track": 140,
    }
    pair_defs = [(0, 1), (1, 2), (2, 3), (0, 3)]
    pair_manifests: list[Path] = []
    for idx, (i0, i1) in enumerate(pair_defs):
        diff = (epoch_fields[i1] - epoch_fields[i0]).astype(np.float32)
        diff[nodata_patch] = np.nan
        pair_meta = {
            "dataKind": "synthetic",
            "syntheticLineage": True,
            "displacementConvention": "positive_away_from_satellite",
            "displacementUnits": "mm",
            "units": {"displacement": "mm"},
            "acquisitionDates": [epochs[i0], epochs[i1]],
            "spatialReferenceId": "synthetic-east-inland",
            "spatialReferenceHash": ref_hash,
            "referenceRegion": {"type": "polygonWgs84", "hash": ref_hash, "geometry": ref_poly},
            "correctionState": {"sourceApplied": [], "subtractedByThisRun": [], "note": "synthetic demo"},
            "correctionsApplied": [],
            "sourceBasis": source_basis,
            "nativeResolutionMetres": {"x": float(spacing_m), "y": float(spacing_m)},
            "warnings": ["SYNTHETIC DEMO DATA: generated for priority-zone end-to-end verification; not NISAR GUNW data."],
        }
        def _write_pair(stage: Path, arr: np.ndarray = diff) -> dict[str, str]:
            core.write_raster(stage / "displacement_mm.tif", arr, grid)
            return {"displacementMm": "displacement_mm.tif"}
        pair_manifests.append(core.publish(area, "los-pair", pair_meta, _write_pair, output_root=root, review=True))

    gm_manifest_path = series.build_series(area, pair_manifests, output_root=root)
    gm_run_id = gm_manifest_path.parent.name
    pointer = gm_base / f".current-{gm_run_id}.json"
    pointer.write_text(json.dumps({"runId": gm_run_id}), encoding="utf-8")
    os.replace(pointer, current_ptr)
    return gm_manifest_path
