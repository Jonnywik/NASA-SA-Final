"""Validation metrics for NISAR flood masks, barangay hits, and threshold sensitivity."""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np
from affine import Affine
from pyproj import CRS, Transformer
from rasterio.warp import Resampling, reproject

from processing.nisar_flood import water


def _to_affine(transform) -> Affine:
    if isinstance(transform, Affine):
        return transform
    return Affine(*tuple(float(v) for v in transform[:6]))


def _pixel_area_m2(shape: tuple[int, int], transform: Affine, crs_str: str) -> float:
    """Approximate pixel area in m^2 at grid centre for choosing the coarser grid."""
    crs = CRS.from_user_input(crs_str)
    dx, dy = abs(float(transform.a)), abs(float(transform.e))
    if crs.is_projected:
        fx = crs.axis_info[0].unit_conversion_factor if crs.axis_info else 1.0
        fy = crs.axis_info[1].unit_conversion_factor if len(crs.axis_info) > 1 else fx
        return (dx * fx) * (dy * fy)
    h, w = shape
    cx, cy = transform @ (w / 2.0, h / 2.0)
    _, lat_deg = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(cx, cy)
    cos_lat = max(math.cos(math.radians(float(lat_deg))), 1e-6)
    return (dx * 111320.0 * cos_lat) * (dy * 111320.0)


def _to_float_with_nan(mask: np.ndarray, nodata) -> np.ndarray:
    arr = np.asarray(mask, dtype="float32").copy()
    arr[~np.isfinite(arr)] = np.nan
    if nodata is not None and not (isinstance(nodata, float) and math.isnan(nodata)):
        arr[arr == float(nodata)] = np.nan
    return arr


def _same_grid(s1: tuple[int, int], t1: Affine, c1: str, s2: tuple[int, int], t2: Affine, c2: str) -> bool:
    if s1 != s2 or CRS.from_user_input(c1) != CRS.from_user_input(c2):
        return False
    return np.allclose(tuple(t1)[:6], tuple(t2)[:6], rtol=0, atol=1e-6)


def _reproject_nearest(src: np.ndarray, src_transform: Affine, src_crs: str,
                       dst_shape: tuple[int, int], dst_transform: Affine, dst_crs: str) -> np.ndarray:
    out = np.full(dst_shape, np.nan, dtype="float32")
    reproject(
        source=np.ascontiguousarray(src, dtype="float32"),
        destination=out,
        src_transform=src_transform,
        src_crs=src_crs,
        src_nodata=np.nan,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        dst_nodata=np.nan,
        resampling=Resampling.nearest,
    )
    return out


def raster_agreement(
    pred_mask: np.ndarray,
    pred_transform,
    pred_crs: str,
    ref_mask: np.ndarray,
    ref_transform,
    ref_crs: str,
    pred_nodata=255,
    ref_nodata=255,
) -> dict:
    """Compare two binary flood masks on the coarser common grid (nearest neighbour).

    Pixels that are nodata or non-finite in either source are excluded from all counts.
    """
    pred_arr = _to_float_with_nan(pred_mask, pred_nodata)
    ref_arr = _to_float_with_nan(ref_mask, ref_nodata)
    t_pred = _to_affine(pred_transform)
    t_ref = _to_affine(ref_transform)

    if _same_grid(pred_arr.shape, t_pred, pred_crs, ref_arr.shape, t_ref, ref_crs):
        p_grid, r_grid = pred_arr, ref_arr
        target = "identical"
    else:
        pred_m2 = _pixel_area_m2(pred_arr.shape, t_pred, pred_crs)
        ref_m2 = _pixel_area_m2(ref_arr.shape, t_ref, ref_crs)
        if ref_m2 > pred_m2:
            p_grid = _reproject_nearest(pred_arr, t_pred, pred_crs, ref_arr.shape, t_ref, ref_crs)
            r_grid = ref_arr
            target = "reference_coarser"
        else:
            p_grid = pred_arr
            r_grid = _reproject_nearest(ref_arr, t_ref, ref_crs, pred_arr.shape, t_pred, pred_crs)
            target = "prediction_coarser"

    valid = np.isfinite(p_grid) & np.isfinite(r_grid)
    valid_pixels = int(valid.sum())
    if valid_pixels == 0:
        return {
            "overallAgreement": None,
            "f1": None,
            "iou": None,
            "confusionMatrix": {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "validPixels": 0},
            "targetGrid": target,
            "reason": "no overlapping valid pixels between prediction and reference masks",
        }

    p_pos = p_grid[valid] > 0
    r_pos = r_grid[valid] > 0
    tp = int(np.sum(p_pos & r_pos))
    fp = int(np.sum(p_pos & ~r_pos))
    fn = int(np.sum(~p_pos & r_pos))
    tn = int(np.sum(~p_pos & ~r_pos))

    overall = round((tp + tn) / valid_pixels, 6)
    f1_denom = 2 * tp + fp + fn
    iou_denom = tp + fp + fn
    f1 = round((2 * tp) / f1_denom, 6) if f1_denom > 0 else None
    iou = round(tp / iou_denom, 6) if iou_denom > 0 else None
    reason = None if iou_denom > 0 else "no positive pixels in either prediction or reference"
    return {
        "overallAgreement": overall,
        "f1": f1,
        "iou": iou,
        "confusionMatrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "validPixels": valid_pixels},
        "targetGrid": target,
        "reason": reason,
    }


def barangay_hit_rate(predicted_barangays: Iterable[str], reference_barangays: Iterable[str]) -> dict:
    """Compare predicted flooded barangay names/codes against a reference list."""
    pred_map = {str(b).strip().lower(): str(b).strip() for b in predicted_barangays if str(b).strip()}
    ref_map = {str(b).strip().lower(): str(b).strip() for b in reference_barangays if str(b).strip()}

    matched_keys = sorted(pred_map.keys() & ref_map.keys())
    missed_keys = sorted(ref_map.keys() - pred_map.keys())
    extra_keys = sorted(pred_map.keys() - ref_map.keys())

    ref_count = len(ref_map)
    hit_rate = round(len(matched_keys) / ref_count, 6) if ref_count > 0 else None
    return {
        "hitRate": hit_rate,
        "matched": [ref_map[k] for k in matched_keys],
        "referenceCount": ref_count,
        "predictedCount": len(pred_map),
        "missed": [ref_map[k] for k in missed_keys],
        "extra": [pred_map[k] for k in extra_keys],
        "reason": None if ref_count > 0 else "no reference barangays provided",
    }


def _coerce_rule(base_rule) -> water.WaterRule:
    if isinstance(base_rule, water.WaterRule):
        return base_rule
    if isinstance(base_rule, dict):
        return water.WaterRule(
            hh_db=float(base_rule["hhThresholdDb"]),
            hv_db=float(base_rule["hvThresholdDb"]),
            calibration=base_rule.get("calibration") or {},
        )
    raise TypeError("base_rule must be a WaterRule or a dict with hhThresholdDb/hvThresholdDb")


def _rhythm_for_delta(
    hh_list: list[np.ndarray],
    hv_list: list[np.ndarray],
    valid_list: list[np.ndarray],
    in_area: np.ndarray,
    area_km2: np.ndarray,
    rule: water.WaterRule,
    permanent_mask: np.ndarray,
    min_valid_passes: int,
) -> dict:
    water_masks, valids = [], []
    for hh, hv, v_in in zip(hh_list, hv_list, valid_list):
        w, v_arr = water.classify(hh, hv, rule)
        v = v_arr & np.asarray(v_in, dtype=bool) & in_area
        water_masks.append(w & v)
        valids.append(v)
    flooded = [water.flooded_from(w, v, permanent_mask) for w, v in zip(water_masks, valids)]
    rhythm = water.compute_rhythm(flooded, valids, permanent_mask, in_area, min_valid_passes=min_valid_passes)
    return water.rhythm_stats(rhythm, area_km2)


def threshold_sensitivity(
    hh_list: list[np.ndarray],
    hv_list: list[np.ndarray],
    valid_list: list[np.ndarray],
    in_area: np.ndarray,
    area_km2: np.ndarray,
    base_rule,
    permanent_mask: np.ndarray,
    min_valid_passes: int = 3,
    deltas: tuple[float, ...] = (-1.0, 0.0, 1.0),
) -> dict:
    """Re-run flood classification and rhythm stats in memory at shifted HH/HV thresholds."""
    if not (len(hh_list) == len(hv_list) == len(valid_list) and hh_list):
        raise ValueError("hh_list, hv_list, and valid_list must be non-empty lists of equal length")
    rule = _coerce_rule(base_rule)
    in_area_b = np.asarray(in_area, dtype=bool)
    perm_b = np.asarray(permanent_mask, dtype=bool) & in_area_b

    cache: dict[float, dict] = {}

    def stats_for(delta: float) -> dict:
        d = float(delta)
        if d not in cache:
            shifted = water.WaterRule(hh_db=rule.hh_db + d, hv_db=rule.hv_db + d, calibration=rule.calibration)
            cache[d] = _rhythm_for_delta(hh_list, hv_list, valid_list, in_area_b, area_km2, shifted, perm_b, min_valid_passes)
        return cache[d]

    base_half = stats_for(0.0)["halfOrMoreKm2"]
    variants = []
    for delta in deltas:
        d = float(delta)
        st = stats_for(d)
        variants.append({
            "deltaDb": d,
            "hhThresholdDb": round(rule.hh_db + d, 3),
            "hvThresholdDb": round(rule.hv_db + d, 3),
            "halfOrMoreKm2": st["halfOrMoreKm2"],
            "floodedAtLeastOnceKm2": st["floodedAtLeastOnceKm2"],
            "countableKm2": st["countableKm2"],
            "deltaHalfOrMoreKm2": round(st["halfOrMoreKm2"] - base_half, 4),
        })
    return {
        "baseRule": {"hhThresholdDb": rule.hh_db, "hvThresholdDb": rule.hv_db},
        "minValidPasses": int(min_valid_passes),
        "variants": variants,
    }
