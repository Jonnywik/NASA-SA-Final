"""Script 50: compute priority zones (flood rhythm >= half AND LOS motion > T mm).

Reads ``<output-root>/<area>/nisar/rhythm_half.tif`` and the P3 ``ground-motion``
product for ``<area>``. Writes ``priority_mask.tif`` and ``priority_manifest.json``
next to ``rhythm_half.tif``.

If no reviewed ground-motion product exists, this script exits non-zero without
fabricating data. Pass ``--synthetic-motion-demo`` ONLY when an explicit
``dataKind='synthetic'`` demo run is intentionally desired.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from processing.nisar_flood.constants import AREA_ID  # noqa: E402
from processing.p3.catalog import ProductUnavailable  # noqa: E402
from processing.priority import (  # noqa: E402
    PRIORITY_MANIFEST_FILENAME,
    PRIORITY_MASK_FILENAME,
    build_priority_zones,
    create_synthetic_motion_demo,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--area", default=AREA_ID, help=f"study area / event id (default: {AREA_ID})")
    parser.add_argument("--output-root", help="product output root (default: backend/data/output)")
    parser.add_argument("--places-root", help="places cache root (default: backend/data/cache/places)")
    parser.add_argument("--run-id", help="optional P3 ground-motion runId")
    parser.add_argument("--threshold-mm", type=float, help="explicit LOS displacement threshold in mm (positive away from satellite)")
    parser.add_argument(
        "--reference-bbox",
        type=float,
        nargs=4,
        metavar=("W", "S", "E", "N"),
        help="optional WGS84 reference bbox for 2*std noise threshold derivation",
    )
    parser.add_argument(
        "--synthetic-motion-demo",
        action="store_true",
        help="explicitly build a clearly labelled dataKind='synthetic' P3 ground-motion demo run before computing priority zones",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="with --synthetic-motion-demo, allow replacing a non-synthetic current ground-motion pointer",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.synthetic_motion_demo:
            gm_path = create_synthetic_motion_demo(
                area=args.area,
                output_root=args.output_root,
                force=args.force,
            )
            print(f"Published SYNTHETIC demo ground-motion manifest: {gm_path}")

        manifest = build_priority_zones(
            area=args.area,
            output_root=args.output_root,
            places_root=args.places_root,
            run_id=args.run_id,
            threshold_mm=args.threshold_mm,
            reference_bbox=tuple(args.reference_bbox) if args.reference_bbox else None,
        )
    except ProductUnavailable as exc:
        print(
            f"error: ground-motion product unavailable for {args.area!r} ({exc.code}: {exc}). "
            "Run the T2 GUNW ground-motion chain first (do not fabricate motion data); "
            "or pass --synthetic-motion-demo explicitly for a synthetic demo.",
            file=sys.stderr,
        )
        return 2
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    totals = manifest["exposure"]["totals"]
    print(
        f"Wrote {PRIORITY_MASK_FILENAME} and {PRIORITY_MANIFEST_FILENAME} "
        f"(area={manifest['area']}, dataKind={manifest['dataKind']}, "
        f"T={manifest['thresholdMm']:.3f} mm [{manifest['thresholdMethod']}], "
        f"priorityPixels={manifest['counts']['priorityPixels']}, "
        f"areaKm2={totals['areaKm2']}, population={totals['population']}, buildings={totals['buildings']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
