"""Deterministic bilingual place-level briefing builder (facts -> EN/FIL/CSV/HTML)."""
from __future__ import annotations

import csv
import html
import io
import math
from typing import Any, Mapping, Sequence

from .templates_en import FIELD_ORDER as EN_ORDER, render_briefing_en
from .templates_fil import FIELD_ORDER as FIL_ORDER, TRANSLATION_STATUS, render_briefing_fil

if EN_ORDER != FIL_ORDER:  # pragma: no cover - module-level invariant check
    raise RuntimeError("templates_en.FIELD_ORDER and templates_fil.FIELD_ORDER must match identically")

CSV_COLUMNS = ("field", "value", "units", "source", "dataKind", "reason")


def _clean_number(value: Any, decimals: int = 3) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        rounded = round(value, decimals)
        return int(rounded) if rounded.is_integer() and decimals == 0 else rounded
    return None


def _source_name(component: Mapping[str, Any] | None) -> str | None:
    if not isinstance(component, Mapping):
        return None
    src = component.get("source")
    if isinstance(src, Mapping):
        name = src.get("name")
        return str(name) if name is not None else None
    if isinstance(src, str):
        return src
    return None


def _fact(
    field: str,
    value: Any,
    units: str | None,
    source: str | None,
    data_kind: str | None,
    reason: str | None = None,
) -> dict[str, Any]:
    if value is None and not reason:
        reason = "value is unavailable"
    if value is not None:
        reason = None
    return {
        "field": field,
        "value": value,
        "units": units,
        "source": source,
        "dataKind": data_kind,
        "reason": reason,
    }


def build_facts(spot_check: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract ordered, provenance-tagged facts from a spot-check payload."""
    place = spot_check.get("place") or {}
    nisar = spot_check.get("nisar") or {}
    rainfall = spot_check.get("rainfall") or {}
    motion = spot_check.get("groundMotion") or {}
    priority = spot_check.get("priorityZone") or {}

    place_src = _source_name(place)
    place_kind = place.get("dataKind")
    barangay = place.get("barangay") if isinstance(place.get("barangay"), Mapping) else None
    city = place.get("city") if isinstance(place.get("city"), Mapping) else None
    place_reason = place.get("reason") or "place lookup is unavailable"

    nisar_src = _source_name(nisar)
    nisar_kind = nisar.get("dataKind")
    nisar_avail = bool(nisar.get("available"))
    nisar_reason = nisar.get("reason") or "NISAR flood rhythm product is unavailable"

    rain_src = _source_name(rainfall)
    rain_kind = rainfall.get("dataKind")
    rain_avail = bool(rainfall.get("available"))
    rain_passes = rainfall.get("passes") if isinstance(rainfall.get("passes"), list) else []
    latest_rain = rain_passes[-1] if rain_passes else None
    rain_reason = rainfall.get("reason") or "pass-aligned NASA POWER rainfall is unavailable"

    if latest_rain is not None:
        latest_date = latest_rain.get("date")
        latest_date_reason = None
        same_day = _clean_number(latest_rain.get("sameDayMm"), 3)
        p3 = _clean_number(latest_rain.get("prior3DayMm"), 3)
        p7 = _clean_number(latest_rain.get("prior7DayMm"), 3)
        r_reasons = latest_rain.get("reasons") or {}
        same_reason = r_reasons.get("sameDayMm") or r_reasons.get("all") or "same-day rainfall is missing"
        p3_reason = r_reasons.get("prior3DayMm") or r_reasons.get("all") or "prior three-day rainfall has missing days"
        p7_reason = r_reasons.get("prior7DayMm") or r_reasons.get("all") or "prior seven-day rainfall has missing days"
    else:
        latest_date = None
        latest_date_reason = rain_reason
        same_day = p3 = p7 = None
        same_reason = p3_reason = p7_reason = rain_reason

    motion_src = _source_name(motion)
    motion_kind = motion.get("dataKind")
    motion_avail = bool(motion.get("available"))
    motion_reason = motion.get("reason") or "ground-motion product is unavailable"
    cum_los = _clean_number(motion.get("cumulativeDisplacementMm"), 3) if motion_avail else None
    rate_los = _clean_number(motion.get("rateMmPerYear"), 3) if motion_avail else None
    valid_epochs = motion.get("validEpochCount") if motion_avail else None
    rate_reason = (
        "annual rate requires at least minimum epochs and temporal span; cumulative line-of-sight displacement is reported instead"
        if motion_avail and rate_los is None
        else motion_reason
    )

    prio_src = _source_name(priority)
    prio_kind = priority.get("dataKind")
    prio_reason = priority.get("reason") or "priority zone mask is unavailable"
    in_prio = priority.get("inPriorityZone")
    thresh_mm = _clean_number(priority.get("thresholdMm"), 3)
    thresh_reason = priority.get("thresholdReason") or prio_reason

    return [
        _fact("longitude", _clean_number(spot_check.get("lon"), 6), "degrees_east", "WGS84 query coordinate", "observed"),
        _fact("latitude", _clean_number(spot_check.get("lat"), 6), "degrees_north", "WGS84 query coordinate", "observed"),
        _fact("barangay_name", barangay.get("name") if barangay else None, None, place_src, place_kind, place_reason),
        _fact("city_name", city.get("name") if city else None, None, place_src, place_kind, place_reason),
        _fact(
            "nisar_flood_count",
            nisar.get("floodCount") if nisar_avail else None,
            "passes",
            nisar_src,
            nisar_kind,
            nisar.get("floodCountReason") or nisar_reason,
        ),
        _fact(
            "nisar_valid_passes",
            nisar.get("validCount") if nisar_avail else None,
            "passes",
            nisar_src,
            nisar_kind,
            nisar_reason,
        ),
        _fact(
            "nisar_permanent_water",
            nisar.get("permanentWater") if nisar_avail else None,
            "boolean",
            nisar_src,
            nisar_kind,
            nisar_reason,
        ),
        _fact(
            "nisar_flooded_vegetation_passes",
            nisar.get("possibleFloodedVegetationPasses") if nisar_avail else None,
            "passes",
            nisar_src,
            nisar_kind,
            nisar_reason,
        ),
        _fact(
            "latest_pass_date",
            latest_date if rain_avail else None,
            "ISO date",
            rain_src or nisar_src,
            rain_kind or nisar_kind,
            latest_date_reason,
        ),
        _fact("latest_pass_same_day_rainfall_mm", same_day if rain_avail else None, "mm", rain_src, rain_kind, same_reason),
        _fact("latest_pass_prior_3_day_rainfall_mm", p3 if rain_avail else None, "mm", rain_src, rain_kind, p3_reason),
        _fact("latest_pass_prior_7_day_rainfall_mm", p7 if rain_avail else None, "mm", rain_src, rain_kind, p7_reason),
        _fact("ground_motion_cumulative_los_mm", cum_los, "mm", motion_src, motion_kind, motion_reason),
        _fact("ground_motion_rate_mm_per_year", rate_los, "mm/year", motion_src, motion_kind, rate_reason),
        _fact("ground_motion_valid_epochs", valid_epochs, "epochs", motion_src, motion_kind, motion_reason),
        _fact("in_priority_zone", in_prio, "boolean", prio_src, prio_kind, prio_reason),
        _fact("priority_threshold_mm", thresh_mm, "mm", prio_src, prio_kind, thresh_reason),
    ]


def _collect_sources(spot_check: Mapping[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for key in ("place", "nisar", "rainfall", "groundMotion", "priorityZone"):
        comp = spot_check.get(key)
        if not isinstance(comp, Mapping):
            continue
        src = comp.get("source")
        if isinstance(src, Mapping) and src.get("name"):
            sig = (str(src.get("name")), src.get("url"), src.get("version"))
            if sig not in seen:
                seen.add(sig)
                sources.append({
                    "component": key,
                    "name": src.get("name"),
                    "url": src.get("url"),
                    "version": src.get("version"),
                    "dataKind": comp.get("dataKind"),
                })
    return sources


def build_place_briefing(spot_check: Mapping[str, Any], *, lang: str = "en") -> dict[str, Any]:
    """Build a deterministic bilingual place briefing payload from a spot-check result."""
    if lang not in ("en", "fil"):
        raise ValueError(f"Unsupported lang {lang!r}; expected 'en' or 'fil'")

    facts = build_facts(spot_check)
    data_kind = str(spot_check.get("dataKind") or "derived")
    warnings = list(spot_check.get("warnings") or [])
    limitations = list(spot_check.get("limitations") or [])

    if lang == "fil":
        rendered = render_briefing_fil(facts, data_kind=data_kind, warnings=warnings, limitations=limitations)
        translation_status = TRANSLATION_STATUS
    else:
        rendered = render_briefing_en(facts, data_kind=data_kind, warnings=warnings, limitations=limitations)
        translation_status = "en_source"

    return {
        "area": spot_check.get("area"),
        "lon": spot_check.get("lon"),
        "lat": spot_check.get("lat"),
        "lang": lang,
        "dataKind": data_kind,
        "translationStatus": translation_status,
        "generatedAt": spot_check.get("generatedAt"),
        "source": spot_check.get("source"),
        "nativeResolution": spot_check.get("nativeResolution"),
        "title": rendered["title"],
        "text": rendered["text"],
        "lines": rendered["lines"],
        "syntheticWarningText": rendered["syntheticWarningText"],
        "hypothesisNote": rendered["hypothesisNote"],
        "facts": facts,
        "sources": _collect_sources(spot_check),
        "warnings": warnings,
        "limitations": limitations,
    }


def render_csv(facts: Sequence[Mapping[str, Any]]) -> str:
    """Serialize facts as CSV with columns field,value,units,source,dataKind,reason."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for fact in facts:
        val = fact.get("value")
        writer.writerow({
            "field": fact.get("field") or "",
            "value": "" if val is None else str(val),
            "units": fact.get("units") or "",
            "source": fact.get("source") or "",
            "dataKind": fact.get("dataKind") or "",
            "reason": fact.get("reason") or "",
        })
    return buf.getvalue()


def render_html(briefing: Mapping[str, Any]) -> str:
    """Render a self-contained printable HTML briefing page."""
    esc = lambda v: html.escape("" if v is None else str(v), quote=True)
    data_kind = str(briefing.get("dataKind") or "derived")
    lang = str(briefing.get("lang") or "en")

    banner_html = ""
    if data_kind == "synthetic":
        warn_text = str(briefing.get("syntheticWarningText") or "SYNTHETIC DATA WARNING").strip("*")
        banner_html = f'<div class="synthetic-banner"><strong>{esc(warn_text)}</strong></div>'

    translation_html = ""
    if lang == "fil":
        translation_html = (
            f'<p class="meta"><strong>Translation status:</strong> '
            f'{esc(briefing.get("translationStatus"))}</p>'
        )

    lines_html = "\n".join(f"<li>{esc(line)}</li>" for line in (briefing.get("lines") or []))

    rows_html = []
    for fact in briefing.get("facts") or []:
        val = fact.get("value")
        val_text = "not available" if val is None else esc(val)
        rows_html.append(
            "<tr>"
            f"<td><code>{esc(fact.get('field'))}</code></td>"
            f"<td>{val_text}</td>"
            f"<td>{esc(fact.get('units') or '—')}</td>"
            f"<td>{esc(fact.get('source') or '—')}</td>"
            f"<td>{esc(fact.get('dataKind') or '—')}</td>"
            f"<td>{esc(fact.get('reason') or '—')}</td>"
            "</tr>"
        )
    table_body = "\n".join(rows_html)

    sources_items = []
    for src in briefing.get("sources") or []:
        url = src.get("url")
        url_part = f' (<a href="{esc(url)}">{esc(url)}</a>)' if url else ""
        ver_part = f" — version {esc(src.get('version'))}" if src.get("version") else ""
        sources_items.append(
            f"<li><strong>{esc(src.get('component'))}:</strong> {esc(src.get('name'))}{ver_part}{url_part} "
            f"[{esc(src.get('dataKind'))}]</li>"
        )
    sources_html = "\n".join(sources_items) or "<li>No component sources available.</li>"

    warnings_items = "\n".join(f"<li>{esc(w)}</li>" for w in (briefing.get("warnings") or []))
    warnings_section = f"<section><h2>Warnings</h2><ul>{warnings_items}</ul></section>" if warnings_items else ""

    limits_items = "\n".join(f"<li>{esc(lim)}</li>" for lim in (briefing.get("limitations") or []))
    limits_html = limits_items or "<li>None recorded.</li>"

    return f"""<!DOCTYPE html>
<html lang="{esc(lang)}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(briefing.get("title") or "Tanaw Place Briefing")}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; color: #0f172a; margin: 2rem auto; max-width: 960px; padding: 0 1rem; line-height: 1.5; }}
    h1 {{ margin-bottom: 0.25rem; }}
    h2 {{ margin-top: 1.75rem; border-bottom: 1px solid #cbd5e1; padding-bottom: 0.25rem; font-size: 1.1rem; }}
    .meta {{ color: #475569; font-size: 0.9rem; margin: 0.25rem 0; }}
    .synthetic-banner {{ background: #fef3c7; border: 2px solid #d97706; color: #78350f; padding: 0.85rem 1rem; border-radius: 6px; margin: 1rem 0; }}
    .note {{ background: #f8fafc; border-left: 4px solid #64748b; padding: 0.75rem 1rem; margin: 1rem 0; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 0.75rem; font-size: 0.88rem; }}
    th, td {{ border: 1px solid #cbd5e1; padding: 0.45rem 0.6rem; text-align: left; vertical-align: top; }}
    th {{ background: #f1f5f9; }}
    code {{ font-size: 0.85em; }}
    @media print {{ body {{ margin: 0.5in; }} }}
  </style>
</head>
<body>
  {banner_html}
  <h1>{esc(briefing.get("title"))}</h1>
  <p class="meta">Area: <strong>{esc(briefing.get("area"))}</strong> | Coordinates: {esc(briefing.get("lon"))}, {esc(briefing.get("lat"))} | Data kind: <strong>{esc(data_kind)}</strong> | Generated: {esc(briefing.get("generatedAt"))}</p>
  {translation_html}
  <section>
    <h2>Summary</h2>
    <ul>{lines_html}</ul>
    <p class="note">{esc(briefing.get("hypothesisNote"))}</p>
  </section>
  {warnings_section}
  <section>
    <h2>Structured Facts</h2>
    <table>
      <thead>
        <tr><th>Field</th><th>Value</th><th>Units</th><th>Source</th><th>Data Kind</th><th>Reason if Missing</th></tr>
      </thead>
      <tbody>
        {table_body}
      </tbody>
    </table>
  </section>
  <section>
    <h2>Sources</h2>
    <ul>{sources_html}</ul>
  </section>
  <section>
    <h2>Limitations</h2>
    <ul>{limits_html}</ul>
  </section>
</body>
</html>
"""
