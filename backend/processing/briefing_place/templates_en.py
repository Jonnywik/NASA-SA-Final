"""Deterministic English templates for place-level spot-check briefings."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

FIELD_ORDER: tuple[str, ...] = (
    "longitude",
    "latitude",
    "barangay_name",
    "city_name",
    "nisar_flood_count",
    "nisar_valid_passes",
    "nisar_permanent_water",
    "nisar_flooded_vegetation_passes",
    "latest_pass_date",
    "latest_pass_same_day_rainfall_mm",
    "latest_pass_prior_3_day_rainfall_mm",
    "latest_pass_prior_7_day_rainfall_mm",
    "ground_motion_cumulative_los_mm",
    "ground_motion_rate_mm_per_year",
    "ground_motion_valid_epochs",
    "in_priority_zone",
    "priority_threshold_mm",
)

_LABELS: dict[str, str] = {
    "longitude": "Location longitude",
    "latitude": "Location latitude",
    "barangay_name": "Barangay",
    "city_name": "City or municipality",
    "nisar_flood_count": "NISAR passes classified as open water at this cell",
    "nisar_valid_passes": "Valid NISAR passes observed at this cell",
    "nisar_permanent_water": "Permanent water classification at this cell",
    "nisar_flooded_vegetation_passes": "NISAR passes flagged as possible flooded vegetation",
    "latest_pass_date": "Latest NISAR pass date evaluated for rainfall",
    "latest_pass_same_day_rainfall_mm": "Same-day NASA POWER rainfall on the latest pass date",
    "latest_pass_prior_3_day_rainfall_mm": "Prior three-day NASA POWER rainfall before the latest pass date",
    "latest_pass_prior_7_day_rainfall_mm": "Prior seven-day NASA POWER rainfall before the latest pass date",
    "ground_motion_cumulative_los_mm": "Cumulative line-of-sight motion (positive away from satellite)",
    "ground_motion_rate_mm_per_year": "Extrapolated line-of-sight motion rate (not a multi-year trend)",
    "ground_motion_valid_epochs": "Valid line-of-sight motion epochs at this cell",
    "in_priority_zone": "Within priority exposure zone (frequent water and line-of-sight motion above threshold)",
    "priority_threshold_mm": "Priority zone line-of-sight motion threshold",
}

_UNIT_SUFFIX: dict[str, str] = {
    "longitude": " degrees east",
    "latitude": " degrees north",
    "nisar_flood_count": " passes",
    "nisar_valid_passes": " passes",
    "nisar_flooded_vegetation_passes": " passes",
    "latest_pass_same_day_rainfall_mm": " mm",
    "latest_pass_prior_3_day_rainfall_mm": " mm",
    "latest_pass_prior_7_day_rainfall_mm": " mm",
    "ground_motion_cumulative_los_mm": " mm",
    "ground_motion_rate_mm_per_year": " mm/year",
    "ground_motion_valid_epochs": " epochs",
    "priority_threshold_mm": " mm",
}

SYNTHETIC_WARNING = (
    "**SYNTHETIC DATA WARNING: One or more datasets in this briefing are synthetic demo data "
    "and must not be presented as real observations.**"
)

HYPOTHESIS_NOTE = (
    "Note: Any proposed causes linking rainfall, groundwater use, drainage, and radar observations "
    "are hypotheses requiring independent verification; spatial overlap reflects exposure, not confirmed impact."
)


def _format_value(field: str, value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return f"{value}{_UNIT_SUFFIX.get(field, '')}"


def render_fact_en(fact: Mapping[str, Any]) -> str:
    """Render one fact deterministically in English without ever substituting 0 for None."""
    field = str(fact["field"])
    label = _LABELS[field]
    value = fact.get("value")
    if value is None:
        reason = str(fact.get("reason") or "no reason was provided").strip().rstrip(".")
        return f"{label}: not available because {reason}."
    return f"{label}: {_format_value(field, value)}."


def render_briefing_en(
    facts: Sequence[Mapping[str, Any]],
    *,
    data_kind: str,
    warnings: Sequence[str] = (),
    limitations: Sequence[str] = (),
) -> dict[str, Any]:
    """Render a deterministic English briefing from spot-check facts."""
    by_field = {str(f["field"]): f for f in facts}
    lines = [render_fact_en(by_field[field]) for field in FIELD_ORDER]

    paragraphs: list[str] = []
    if data_kind == "synthetic":
        paragraphs.append(SYNTHETIC_WARNING)
    paragraphs.extend(lines)
    paragraphs.append(HYPOTHESIS_NOTE)

    return {
        "title": "Tanaw Place Briefing (English)",
        "text": "\n".join(paragraphs),
        "lines": lines,
        "syntheticWarningText": SYNTHETIC_WARNING if data_kind == "synthetic" else None,
        "hypothesisNote": HYPOTHESIS_NOTE,
        "warnings": list(warnings),
        "limitations": list(limitations),
    }
