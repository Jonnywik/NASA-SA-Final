# Translation status: pending native-speaker review
"""Deterministic Filipino (Tagalog) templates for place-level spot-check briefings."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

TRANSLATION_STATUS = "pending native-speaker review"

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
    "longitude": "Longhitud ng lokasyon",
    "latitude": "Latitud ng lokasyon",
    "barangay_name": "Barangay",
    "city_name": "Lungsod o munisipalidad",
    "nisar_flood_count": "Bilang ng mga pass ng NISAR na may natukoy na bukas na tubig o baha sa seldang ito",
    "nisar_valid_passes": "Bilang ng mga valid na pass ng NISAR na nasuri sa seldang ito",
    "nisar_permanent_water": "Pag-uuri bilang permanenteng tubig sa seldang ito",
    "nisar_flooded_vegetation_passes": "Bilang ng mga pass ng NISAR na may posibleng binahang halaman",
    "latest_pass_date": "Pinakahuling petsa ng pass ng NISAR na sinuri para sa ulan",
    "latest_pass_same_day_rainfall_mm": "Ulan sa mismong araw ng pinakahuling pass (NASA POWER)",
    "latest_pass_prior_3_day_rainfall_mm": "Kabuuang ulan sa naunang tatlong araw bago ang pinakahuling pass",
    "latest_pass_prior_7_day_rainfall_mm": "Kabuuang ulan sa naunang pitong araw bago ang pinakahuling pass",
    "ground_motion_cumulative_los_mm": "Pinagsamang paggalaw ng lupa sa line-of-sight (positibo palayo sa satelayt)",
    "ground_motion_rate_mm_per_year": "Tinatayang taunang bilis ng paggalaw sa line-of-sight (extrapolated, hindi pangmatagalang trend)",
    "ground_motion_valid_epochs": "Bilang ng mga valid na epoch ng sukat sa paggalaw sa line-of-sight",
    "in_priority_zone": "Nasa sona ng prayoridad para sa pagtataya ng pagkalantad (exposure)",
    "priority_threshold_mm": "Threshold ng paggalaw sa line-of-sight para sa sona ng prayoridad",
}

_UNIT_SUFFIX: dict[str, str] = {
    "longitude": " digri silangan",
    "latitude": " digri hilaga",
    "nisar_flood_count": " na pass",
    "nisar_valid_passes": " na pass",
    "nisar_flooded_vegetation_passes": " na pass",
    "latest_pass_same_day_rainfall_mm": " mm",
    "latest_pass_prior_3_day_rainfall_mm": " mm",
    "latest_pass_prior_7_day_rainfall_mm": " mm",
    "ground_motion_cumulative_los_mm": " mm",
    "ground_motion_rate_mm_per_year": " mm/taon",
    "ground_motion_valid_epochs": " na epoch",
    "priority_threshold_mm": " mm",
}

SYNTHETIC_WARNING = (
    "**BABALA TUNGKOL SA SINTETIKONG DATOS (SYNTHETIC DATA WARNING): Isa o higit pang datos sa ulat na ito "
    "ay sintetikong demo lamang at hindi dapat ituring na totoong obserbasyon.**"
)

HYPOTHESIS_NOTE = (
    "Paalala: Ang anumang mungkahing ugnayan ng ulan, pagkuha ng tubig sa ilalim ng lupa, daluyan ng tubig, "
    "at mga obserbasyon ng radar ay mga haypotesis (hypotheses) na nangangailangan ng hiwalay na beripikasyon; "
    "ang pagkakapatong sa mapa ay nagpapakita ng pagkalantad (exposure) lamang."
)


def _format_value(field: str, value: Any) -> str:
    if isinstance(value, bool):
        return "oo" if value else "hindi"
    return f"{value}{_UNIT_SUFFIX.get(field, '')}"


def render_fact_fil(fact: Mapping[str, Any]) -> str:
    """Render one fact deterministically in Tagalog without ever substituting 0 for None."""
    field = str(fact["field"])
    label = _LABELS[field]
    value = fact.get("value")
    if value is None:
        reason = str(fact.get("reason") or "walang naibigay na dahilan").strip().rstrip(".")
        return f"{label}: hindi available dahil {reason}."
    return f"{label}: {_format_value(field, value)}."


def render_briefing_fil(
    facts: Sequence[Mapping[str, Any]],
    *,
    data_kind: str,
    warnings: Sequence[str] = (),
    limitations: Sequence[str] = (),
) -> dict[str, Any]:
    """Render a deterministic Filipino briefing from spot-check facts."""
    by_field = {str(f["field"]): f for f in facts}
    lines = [render_fact_fil(by_field[field]) for field in FIELD_ORDER]

    paragraphs: list[str] = []
    if data_kind == "synthetic":
        paragraphs.append(SYNTHETIC_WARNING)
    paragraphs.extend(lines)
    paragraphs.append(HYPOTHESIS_NOTE)

    return {
        "title": "Ulat ng Lokasyon sa Tanaw (Filipino)",
        "text": "\n".join(paragraphs),
        "lines": lines,
        "syntheticWarningText": SYNTHETIC_WARNING if data_kind == "synthetic" else None,
        "hypothesisNote": HYPOTHESIS_NOTE,
        "warnings": list(warnings),
        "limitations": list(limitations),
    }
