TANAW DATA PACKAGE  -  tanaw-data-camanava_2026-v1
=================================================

What this is
------------
The derived NASA-ISRO NISAR L-band product that the Tanaw app (FastAPI + Next.js)
reads at run time for the CAMANAVA study area, Metro Manila. It is excluded from
the Git repository by .gitignore because of its size (about 376 MB unpacked).

It matches repository commit ce42105 (main) of
https://github.com/Jonnywik/NASA-SA-Final

Unzip this archive at the ROOT of your repository clone. It creates exactly one
folder:

    backend/data/output/camanava_2026/nisar/      (75 files)
    backend/data/output/camanava_2026/DATA_README.txt   (this file)

Contents of nisar/:
  manifest.json            product manifest; lists every asset with its SHA-256
  water_rule.json          calibrated HH/HV open-water thresholds used
  pass_YYYYMMDD.png        open water outside usual water, per pass (map overlay)
  hh_YYYYMMDD.png          HH backscatter, per pass (map overlay)
  pol_YYYYMMDD.png         HH/HV polarization composite, per pass (map overlay)
  veg_YYYYMMDD.png         possible flooded vegetation, per pass (map overlay)
  rhythm.png, rhythm_legend.png   open-water rhythm overlay and legend
  rhythm.tif, rhythm_half.tif     rhythm count and "half or more passes" GeoTIFFs
  tif/db_YYYYMMDD.tif      HH/HV backscatter in dB, per pass (spot check reads)
  tif/state_YYYYMMDD.tif   per-pass water state (spot check reads)
  tif/rhythm_counts.tif, tif/permanent_water.tif, tif/hh_dry_reference.tif

11 passes, track 140 ascending, frame 9, 23 June to 2 November 2026.

The files are copied byte-for-byte from the product the submission was run on;
nothing was regenerated. The validation, robustness, cross-track and timelapse
results committed in backend/data/cache/ are bound to this exact manifest
(backend/app/product_binding.py). Do not edit or regenerate these files, or
those results will be reported as unavailable.

No Earthdata login is needed to run the app with this package.

Important caveats
-----------------
* "Open water outside usual water" is NOT a flood map. Water between buildings
  brightens the radar return (double bounce), so flooded city streets are
  under-detected or missed; a missing signal does not mean an area did not flood.
  Results depend on the fixed HH/HV threshold rule and the 2021 WorldCover
  usual-water mask.
* "Possible flooded vegetation" is a possibility, not a confirmed flood.
* Ground motion is NOT available. No line-of-sight or vertical motion result is
  included or claimed; priority zones, which require motion, are also unavailable.
* Most GCOV inputs are provisional products and may change.
* Passes are about 12 days apart at about 05:30 Manila time; floods between
  passes are not seen.

Sources and attribution
-----------------------
* NASA-ISRO NISAR L2 GCOV (NISAR_L2_GCOV_PROVISIONAL_V1 and NISAR_L2_GCOV_V1),
  distributed by the Alaska Satellite Facility DAAC (ASF),
  https://asf.alaska.edu/data-sets/sar-data-sets/nisar/ . Granule IDs are listed
  in nisar/manifest.json.
* NASA GPM IMERG precipitation via NASA GES DISC (rainfall context in the app;
  cached in the repository, not in this package).
* ESA WorldCover 2021 v200, (c) ESA WorldCover project, CC BY 4.0 (usual-water
  mask and land cover used to derive this product).
* WorldPop Philippines 2020 constrained, CC BY 4.0 (exposure, in the repository).
* OpenStreetMap buildings, (c) OpenStreetMap contributors, ODbL 1.0 (in the
  repository).
* HDX COD-AB Philippines administrative boundaries, CC BY-IGO (in the repository).

Licence of this derived product
-------------------------------
The derived files in this package are released under Creative Commons
Attribution 4.0 International (CC BY 4.0) by the Tanaw contributors, subject to
the source terms above. Please credit: "Tanaw contributors; contains modified
NASA-ISRO NISAR data (ASF DAAC) and ESA WorldCover data".
The application source code is MIT licensed (see LICENSE in the repository).

Note: manifest.json records the processing machine's local working paths in its
"provenance" block. They are inert metadata, are not used at run time, and are
kept unchanged because the manifest hash binds the validation results.
