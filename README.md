# Tanaw

[![CI](https://github.com/Jonnywik/NASA-Space-Apps/actions/workflows/ci.yml/badge.svg)](https://github.com/Jonnywik/NASA-Space-Apps/actions/workflows/ci.yml)


**Tanaw** is an entry to NASA Space Apps "Dancing with the SARs". We grew up wading through the floods of CAMANAVA (Caloocan, Malabon, Navotas, Valenzuela) and the Bulacan coast north of it, one of the most flood-prone and subsiding urban coasts in the Philippines. NASA-ISRO's NISAR satellite revisits the area about every 12 days. Tanaw is an interactive map that uses those L-band radar passes to show how often each place flooded during the 2026 wet season and how the ground moved, then turns that into plain-language briefings for the people who live there.

Backend context caches (places, boundaries, NASA POWER, Open-Meteo ERA5/SEAS5) and analysis APIs are implemented and tested; real NISAR GCOV/GUNW HDF5 reads (T1, T2) remain **blocked pending `EARTHDATA_TOKEN`**, so the current `camanava_2026` NISAR raster product on disk is an explicitly labelled **`dataKind: "synthetic"`** fixture using the 11 real pass slot dates.

## Limitations first

- **Synthetic NISAR placeholder until Earthdata auth.** Without `EARTHDATA_TOKEN`, T1 (GCOV flood rhythm) and T2 (GUNW ground-motion chain) cannot read ASF HDF5 granules. Every endpoint and briefing built on the synthetic demo carries `dataKind: "synthetic"` and a visible warning; missing ground-motion and validation metrics are returned as `null` with a `reason` (never `0`).
- **Real data only policy.** No silent sample data, no Sentinel-1 relabelled as NISAR, and no number without a source.
- **NISAR catalogue verified, HDF5 files not yet read.** NASA CMR lists 11 GCOV passes (9 Provisional `2026-06-23`..`2026-10-09`, 2 V1 `2026-10-21`..`2026-11-02`) and 9 GUNW pairs on track 140 A, frame 9, mode 4005 (`gunwMode: 4000`), recorded in [docs/DATA_MANIFEST.md](docs/DATA_MANIFEST.md).
- **Provisional data.** Most 2026 NISAR products in the season are labelled Provisional by the provider.
- **Short record.** The NISAR season is ~4 months and 11 passes on one track. Flood counts are not a long-term flood frequency.
- **Line-of-sight motion.** Ground motion from InSAR is along the satellite's line of sight (`positive_away_from_satellite`), not true vertical, unless ascending and descending tracks are combined. Published multi-year coastal subsidence citations (Rodolfo & Siringan 2006; Eco et al. 2020; Sulapas et al. 2024, up to 109 mm/yr in Bulacan 2014–2020) are contextual references only and cannot be compared 1:1 with a 4-month 1-D LOS stack.
- **Exposure, not damage.** Priority zones (`rhythm_half` AND reviewed cumulative LOS motion `> T mm`) report people (WorldPop 2020), buildings (OSM snapshot `2026-10-12`), and area by COD-AB barangay/city. They are exposure counts, not damage or risk estimates.
- **Independent validation pending real NISAR.** NASA CMR matched 40 `OPERA_L3_DSWX-S1_V1` granules (`2026-06-21`..`2026-11-04`) to 10 of 11 NISAR passes (0 matches for `2026-09-27`); pixel-level accuracy is `null` (`blocked_pending_real_nisar`), and no machine-readable 2026 Copernicus EMS, UNOSAT, or NDRRMC/MMDA flood pass list exists for the area.
- **Rain-to-flood and scenarios are exploratory.** With ~11 passes no model is fitted, and scenarios are conditional rather than forecasts.
- **Different sensors are never merged.** Sentinel-1 (`karding_2022`, `carina_2024`, `habagat_2025`) and Landsat (`landsat-c2-l2`) are context only and are never combined numerically with NISAR L-band.
- **Hypotheses only.** Driver explanations (`h1`–`h5`) in [docs/HYPOTHESES_SOURCES.md](docs/HYPOTHESES_SOURCES.md) are labelled hypotheses with checked citations, not causal proof. Filipino translations carry `pending native-speaker review`.

## Challenge mapping

Feature codes refer to [docs/SUBMISSION_SCOPE.md](docs/SUBMISSION_SCOPE.md).

| Challenge asks for | Tanaw | Status |
|---|---|---|
| Interactive app using **NISAR** to track and visualize surface change | N1 Flood rhythm, N2 animation, N3 ground motion: all NISAR | partial (synthetic GCOV pipeline + API ready; T1/T2 real HDF5 blocked on `EARTHDATA_TOKEN`) |
| Floodplains extending and retracting | N1 and N2: flood extent on every pass, June–November 2026 | done with synthetic data (`dataKind: "synthetic"` on real pass slots) |
| Coastal subsidence and land deformation | N3: GUNW InSAR over the Manila Bay coast | blocked (T2 requires `EARTHDATA_TOKEN`, phase sign & reference bbox; chain script ready) |
| Agricultural lands and crop changes | N4: L-band flooded vegetation in the Bulacan fields and fishponds | done with synthetic data (WorldCover + HH brightening rule implemented) |
| Change maps, time-series animations, dashboards | N2 animation, U1 swipe, U2 spot check, U3 story mode | partial (backend `/nisar/*`, `/spot-check`, `/validation` & SpotCheck/panel UI wired; real T1/T2 HDF5 pending token) |
| Accessible to a broad audience | U3 story mode, U5 "How radar sees", U6 briefings in English and Filipino, U4 barangay search | partial (UI EN/FIL, barangay search & `/briefing/place` CSV/HTML export wired; `fil` pending native-speaker review) |
| Open-source and actionable | MIT licence, public demo, priority zones, briefing export, downloads | partial (MIT `LICENSE`, priority zones script 50 & SpotCheck briefing export wired; `ground-motion` blocker noted) |
| Study area such as a hometown or flooded neighbourhood | The team's own CAMANAVA, with P2 personal stories | partial (COD-AB CAMANAVA + Bulacan coast 7 cities / 300 barangays cached) |
| Free NISAR data | ASF NISAR GCOV and GUNW (Provisional/V1), recorded in a manifest | catalogue verified (`nisar_manifest_t140_A_f009_m4005.json`); HDF5 blocked on token |
| Supplemental optical and GIS layers | WorldCover, WorldPop, OSM buildings, municipal boundaries, NASA POWER rainfall, Sentinel-1 history | done (real observed caches verified with SHA-256 hashes in [docs/DATA_MANIFEST.md](docs/DATA_MANIFEST.md)) |
| Hypothesize physical drivers | N6: labelled hypotheses, each with a checked reference | done (`h1`–`h5` populated in `frontend/public/hypotheses.json`; `fil` pending native-speaker review) |
| Which polarizations show the change | N5: HH vs HV vs ratio, explained | done with synthetic data (`/api/v1/nisar/polarization`) |
| Other frequencies from other sensors | C2: Sentinel-1 C-band context | done (`karding_2022`, `carina_2024`, `habagat_2025` kept separate) |
| Time series plus ancillary population and vegetation data | N1–N3 with WorldPop and WorldCover | partial (exposure & climate timelines done with real context + synthetic N1) |
| Human drivers | N6 (groundwater pumping, reclamation, fishponds), C1 exposure | partial (`frontend/public/hypotheses.json` & `50_priority_zones.py` done; waiting on T2 motion product) |
| Personal context and stories | P2 and U7 "Our stories" pins | in progress |
| Interactive summary | U1 swipe, U3 story mode, the public web map | in progress |
| Future NISAR applications | P3 | in progress |

## Features (planned for the submission)

- **Flood rhythm (N1, N2):** how many of the season's NISAR passes saw water at each place, with a pass-by-pass animation and a chart against NASA POWER rainfall.
- **Ground motion (N3):** cumulative line-of-sight displacement from chained 12-day GUNW pairs, with a time series per point.
- **Flooded vegetation, polarizations, hypotheses (N4–N6):** HH/HV/ratio views and labelled hypotheses for why this is happening.
- **Priority zones and context (C1–C5):** places that flood often and are sinking, with population, buildings and barangay; Sentinel-1 then-and-now; rain-to-flood response; validation against independent sources.
- **History and future conditions (F1–F5):** timeline from 2000, rainfall history, optical then-and-now, seasonal outlook and conditional scenarios.
- **Experience (U1–U10):** swipe and spot check, guided Story Mode, find-my-barangay search, "How radar sees" cards, briefings in English and Filipino, "Our stories" pins, a public static demo and downloads.

## Data sources

Provenance, licences and retrieval dates are tracked in [docs/DATA_MANIFEST.md](docs/DATA_MANIFEST.md).

- NISAR L2 GCOV and GUNW via the [Alaska Satellite Facility (ASF) DAAC](https://asf.alaska.edu/) (collections found through [NASA CMR](https://cmr.earthdata.nasa.gov/))
- [NASA POWER](https://power.larc.nasa.gov/) daily rainfall
- [Open-Meteo](https://open-meteo.com/) seasonal forecast and historical APIs
- [WorldPop](https://www.worldpop.org/) population
- [OpenStreetMap](https://www.openstreetmap.org/) buildings and places
- [ESA WorldCover](https://esa-worldcover.org/) land cover
- [Sentinel-1](https://sentinels.copernicus.eu/web/sentinel/missions/sentinel-1) for regional context only

## Quick start

Backend (Python 3.12), from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd backend
uvicorn app.main:app --reload
```

Frontend (Node 20), in a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). API documentation is served at `/docs` on the backend.

Downloading NISAR files needs a free NASA Earthdata login. Set the token as an environment variable and never commit it:

```bash
export EARTHDATA_TOKEN=...
```

## Reproduce

From `backend/` using the virtual environment Python:

```bash
# 1. Context caches (real observed data; no login required)
python scripts/30_fetch_climate.py
python scripts/40_fetch_places.py

# 2. NASA CMR NISAR catalogue manifest (no login required)
python scripts/19_nisar_search.py --track 140 --direction A --frame 9 --mode 4005

# 3a. Synthetic NISAR flood-rhythm fixture (when EARTHDATA_TOKEN is unset; tagged dataKind="synthetic")
python scripts/22_nisar_synthetic_demo.py

# 3b. Real NISAR GCOV + GUNW path (requires EARTHDATA_TOKEN; see docs/NISAR_RUNBOOK.md)
# export EARTHDATA_TOKEN=...
# python scripts/20_nisar_flood_rhythm.py --manifest data/cache/nisar/nisar_manifest_t140_A_f009_m4005.json --calibrate
# python scripts/21_nisar_gunw_chain.py --manifest data/cache/nisar/nisar_manifest_t140_A_f009_m4005.json --download

# 4. Priority zones (requires reviewed ground-motion from 3b, or explicit --synthetic-motion-demo)
python scripts/50_priority_zones.py --area camanava_2026

# 5. Validation cache (OPERA DSWx-S1 CMR check + published subsidence comparison)
python scripts/60_validation.py --area camanava_2026
```

## Tests

```bash
cd backend
python -m unittest discover -s tests
cd ../frontend
npm run lint
npm run build
```

The same checks run in GitHub Actions (`.github/workflows/ci.yml`).

## Repository layout

| Path | Contents |
|---|---|
| `backend/app/` | FastAPI application |
| `backend/scripts/` | Numbered offline processing scripts |
| `backend/processing/` | Processing modules |
| `backend/tests/` | Backend unit tests |
| `backend/data/` | Local data and outputs (large raw products are not committed) |
| `frontend/` | Next.js web app |
| `docs/` | Scope, API contract and data manifest |

## Pipeline documentation

- [backend/COHERENCE_PIPELINE.md](backend/COHERENCE_PIPELINE.md): paired HyP3 coherence extraction, change mapping, input manifests and verification commands.
- [backend/DREI_P2_PIPELINE.md](backend/DREI_P2_PIPELINE.md)
- [backend/P3_PIPELINE.md](backend/P3_PIPELINE.md): NISAR ground-motion, vegetation, scenario and briefing modules.
- [docs/API_CONTRACT.md](docs/API_CONTRACT.md) and [docs/SUBMISSION_SCOPE.md](docs/SUBMISSION_SCOPE.md)

## Future of NISAR

Future work, not part of the current build: near-real-time flood alerts for local government units, nationwide subsidence monitoring, and crop-loss warning. Flood watch and evacuation planning are the first roadmap items.

## AI assistance

AI coding assistants were used in development; see the submission page for the full disclosure.

## Licence

[MIT](LICENSE). Copyright 2026 Tanaw contributors.
