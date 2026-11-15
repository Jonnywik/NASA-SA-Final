# Validation Record: CAMANAVA 2026 (`camanava_2026`)

This document records the independent 2026 flood evidence search, threshold sensitivity method, published CAMANAVA/Metro Manila subsidence references, and current blocker status for Task T5.

## 1. Current Status & Honesty Guard

- **NISAR Flood Rhythm (T1):** **Blocked (`dataKind: "synthetic"`).** `backend/data/output/camanava_2026/nisar/manifest.json` currently holds a synthetic demo fixture because reading NASA/ASF L2 GCOV HDF5 granules requires `EARTHDATA_TOKEN`, which is not present in this environment.
- **NISAR Ground Motion (T2):** **Blocked (`nisarMotionStatus: "blocked_pending_real_gunw"`).** No real GUNW InSAR displacement product exists yet for `camanava_2026`.
- **Policy:** `backend/scripts/60_validation.py` explicitly refuses to compute raster agreement, barangay hit rates, threshold sensitivity, or subsidence comparisons against synthetic outputs. All blocked validation metrics remain `null` with an explicit `reason`.

---

## 2. Independent 2026 Flood Evidence Search

Searched over study bbox `[120.88, 14.60, 121.04, 14.82]` (W, S, E, N) around the 11 NISAR track 140 A / frame 009 pass dates (`2026-06-23` to `2026-11-02`).

### 2.1 NASA OPERA Dynamic Surface Water Extent from Sentinel-1 (`OPERA_L3_DSWX-S1_V1`)
- **Collection:** `C2949811996-POCLOUD` (NASA/JPL/PO.DAAC), DOI `https://doi.org/10.5067/OPDSWS1-L3V1`
- **Access & Licence:** NASA Earth Science open data policy; protected GeoTIFF downloads (`https://archive.podaac.earthdata.nasa.gov/podaac-ops-cumulus-protected/...`) require Earthdata Login authentication (`EARTHDATA_TOKEN`).
- **CMR Query:** `https://cmr.earthdata.nasa.gov/search/granules.umm_json?short_name=OPERA_L3_DSWX-S1_V1&bounding_box=120.88,14.60,121.04,14.82&temporal=2026-06-21T00:00:00Z,2026-11-04T23:59:59Z&page_size=200`
- **Result (checked 2026-11-15):** **40 granules** total over tile `T51PTS` (30 m Sentinel-1A/C/D). **10 of 11** NISAR pass dates have at least one DSWx-S1 granule within ±2 days:

| NISAR Pass Date | DSWx-S1 Granules (±2 days) | Granule IDs |
|---|---|---|
| 2026-06-23 | 4 | `OPERA_L3_DSWx-S1_T51PTS_20260623T215442Z_20260828T220426Z_S1A_30_v1.0`, `..._20260624T215403Z_20260628T225340Z_S1C_30_v1.0`, `..._20260624T215348Z_20260702T113613Z_S1C_30_v1.0`, `..._20260624T215351Z_20260826T172034Z_S1C_30_v1.0` |
| 2026-07-05 | 2 | `..._20260706T215404Z_20260719T185202Z_S1C_30_v1.0`, `..._20260706T215349Z_20260720T015400Z_S1C_30_v1.0` |
| 2026-07-17 | 1 | `..._20260718T215350Z_20260725T205750Z_S1C_30_v1.0` |
| 2026-08-10 | 1 | `..._20260811T215351Z_20260812T132331Z_S1C_30_v1.0` |
| 2026-08-22 | 1 | `..._20260823T215352Z_20260824T145614Z_S1C_30_v1.0` |
| 2026-09-03 | 2 | `..._20260904T215352Z_20261005T194321Z_S1C_30_v1.0`, `..._20260904T215352Z_20260919T032925Z_S1C_30_v1.0` |
| 2026-09-15 | 1 | `..._20260917T214554Z_20261012T223352Z_S1D_30_v1.0` |
| 2026-09-27 | 0 | — |
| 2026-10-09 | 2 | `..._20261010T215353Z_20261013T071335Z_S1C_30_v1.0`, `..._20261011T214554Z_20261013T061017Z_S1D_30_v1.0` |
| 2026-10-21 | 1 | `..._20261022T215352Z_20261023T115302Z_S1C_30_v1.0` |
| 2026-11-02 | 2 | `..._20261103T215352Z_20261106T094855Z_S1C_30_v1.0`, `..._20261104T214554Z_20261109T201952Z_S1D_30_v1.0` |

- **Status:** Catalogue matched; raster download blocked pending Earthdata token + real T1 NISAR output. Note also that DSWx-S1 is Sentinel-1 **C-band**, whereas NISAR is **L-band** (different vegetation penetration and acquisition times).

### 2.2 Copernicus EMS Rapid Mapping
- **URL:** `https://mapping.emergency.copernicus.eu/`
- **Checked:** 2026-11-15
- **Finding:** No 2026 Philippine flood or typhoon Rapid Mapping activations were found (historical activations include `EMSR636` for Typhoon Noru/Karding in Sept 2022 and `EMSR741` for the Manila Bay oil spill in July 2024).

### 2.3 UNITAR / UNOSAT
- **URL:** `https://www.unitar.org/maps`
- **Checked:** 2026-11-15
- **Finding:** No 2026 Philippine flood emergency mapping activations were found (historical examples include Typhoon Trami/Kristine in Oct 2024).

### 2.4 NDRRMC / MMDA / DOST-PAGASA
- **URL:** `https://www.pagasa.dost.gov.ph/`
- **Checked:** 2026-11-15
- **Finding:** No active CAMANAVA flood advisories in November 2026 and no machine-readable barangay-level flood list aligned to the 11 June–November 2026 NISAR overpass dates were retrieved.

---

## 3. Agreement & Sensitivity Methods Implemented

Implemented in `backend/processing/validation/__init__.py`:

1. **`raster_agreement(...)`:** Reprojects the finer mask onto the **coarser** of the prediction and reference grids via nearest-neighbour resampling (`Resampling.nearest`), excludes pixels that are nodata or non-finite in either source, and reports `overallAgreement`, `f1`, `iou`, and `confusionMatrix` (`tp`, `fp`, `fn`, `tn`, `validPixels`), returning `null` metrics with `reason` when `validPixels == 0`.
2. **`barangay_hit_rate(...)`:** Computes `hitRate`, `matched`, `referenceCount`, `predictedCount`, `missed`, and `extra` against reference flooded barangay lists.
3. **`threshold_sensitivity(...)`:** Re-runs `processing.nisar_flood.water` (`classify`, `flooded_from`, `compute_rhythm`, `rhythm_stats`) in memory with HH and HV thresholds shifted by `-1.0`, `0.0`, and `+1.0` dB relative to the manifest's `rule`, reporting `halfOrMoreKm2`, `floodedAtLeastOnceKm2`, and `deltaHalfOrMoreKm2` without overwriting published rasters. When `manifest.json` has `dataKind == "observed"`, `scripts/60_validation.py` runs this directly on `tif/db_*.tif`.

---

## 4. Published Subsidence Literature (Qualitative Reference Only)

1. **Rodolfo, K.S. & Siringan, F.P. (2006).** *Global sea-level rise is recognised, but flooding from anthropogenic land subsidence is ignored around northern Manila Bay, Philippines.* **Disasters**, 30(1), 118–139.
   - **URL/DOI:** `https://doi.org/10.1111/j.1467-9523.2006.00310.x` (verified via Crossref & OpenAlex)
   - **Method / Period:** Coastal geology, groundwater withdrawal, and northern Manila Bay flooding/elevation synthesis (pre-2006 multi-decade record).
   - **Published Rate (verbatim from abstract):** *"excessive groundwater extraction is lowering the land surface by several centimetres to more than a decimetre per year"* (contrasted with global sea-level rise of *"one to three millimetres per year"*).

2. **Sulapas, J.J.S., Ybañez, A.A.B., Marasigan, K.M.M., Grageda, J.M.B.M., & Lagmay, A.M.F.A. (2024).** *Ground subsidence in major Philippine metropolitan cities from 2014 to 2020.* **International Journal of Applied Earth Observation and Geoinformation**, 133, 104107.
   - **URL/DOI:** `https://doi.org/10.1016/j.jag.2024.104107` (verified via Crossref & OpenAlex)
   - **Method / Period:** Sentinel-1 InSAR time-series analysis from 2014 to 2020 using UK COMET LiCSAR products and LiCSBAS (vertical ground motion rates).
   - **Published Rate (verbatim from abstract):** *"a maximum subsidence rate of 109 mm/yr in Bulacan Province in Greater Manila."*

3. **Eco, R.C., Rodolfo, K.S., Sulapas, J.J., Morales Rivera, A.M., Lagmay, A.M.F., & Amelung, F. (2020).** *Disaster in Slow Motion: Widespread Land Subsidence in and Around Metro Manila, Philippines.* **JSM Environmental Science & Ecology**, 8(1), 1068.
   - **URL:** `https://www.jscimedcentral.com/public/assets/articles/environmentalscience-8-1068.pdf` (verified HTTP 200 PDF)
   - **Finding (verbatim from PDF abstract opening):** *"Extensive land subsidence in and around Metro Manila, largely from overuse of groundwater, is orders of magnitude more rapid than sea-level rise from global warming."*

### Qualitative Comparison Limits
- **LOS vs vertical:** NISAR GUNW measures 1-D line-of-sight (LOS) motion along the radar look vector, not pure vertical subsidence.
- **Window length:** The 2026 NISAR stack covers ~4 months (June–October 2026), whereas published InSAR/geological rates span 6+ years or decades; short-window LOS displacement is sensitive to atmospheric moisture, ionospheric delay, and unwrapping noise.
- **T2 pending:** Real GUNW processing (T2) has not been run yet, so no qualitative agreement/disagreement against 2026 NISAR displacement is claimed.
