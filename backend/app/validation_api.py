"""Read-only validation API serving precomputed validation cache JSONs."""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from processing.nisar_flood.constants import AREA_ID, BACKEND_DIR

PREFIX = "/api/v1"
AREA_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DEFAULT_VALIDATION_DIR = BACKEND_DIR / "data" / "cache" / "validation"

CONTRACT_FIELDS = (
    "area",
    "dataKind",
    "source",
    "generatedAt",
    "nativeResolution",
    "floodValidation",
    "thresholdSensitivity",
    "subsidenceComparison",
    "warnings",
    "limitations",
)


def _error(status: int, code: str, message: str, **extra):
    return HTTPException(status, detail={"code": code, "message": message, **extra})


def make_router(output_root, read_public_events, *, validation_dir=None):
    del output_root  # validation cache lives under validation_dir; kept for router signature parity
    router = APIRouter(prefix=PREFIX)
    vdir = Path(validation_dir) if validation_dir is not None else DEFAULT_VALIDATION_DIR

    def known_area(area: str) -> str:
        if not isinstance(area, str) or not AREA_RE.match(area) or area not in {e["id"] for e in read_public_events()}:
            raise _error(404, "unknown_area", f"Unknown area {area!r}")
        return area

    @router.get("/validation")
    def validation(area: str = Query(AREA_ID)):
        known_area(area)
        path = vdir / f"validation_{area}.json"
        if not path.is_file():
            raise _error(
                404,
                "data_unavailable",
                f"No validation cache found for {area!r}. Run scripts/60_validation.py first.",
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise _error(404, "data_unavailable", "Validation cache file is unreadable or invalid JSON") from None
        if not isinstance(payload, dict) or not all(field in payload for field in CONTRACT_FIELDS):
            raise _error(404, "data_unavailable", "Validation cache file is missing required contract fields")
        return {field: payload[field] for field in CONTRACT_FIELDS}

    return router
