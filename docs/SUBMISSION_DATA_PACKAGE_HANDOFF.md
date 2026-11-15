# Submission data package: request for Claude

The owner wants judges to receive the complete Tanaw system through the Space Apps submission, and asks Claude to address the data packaging gap.

## Problem

The final-project field can link to the public GitHub repository, but `.gitignore` excludes `backend/data/output/camanava_2026/`. The checked-in source and small caches alone do not include the derived NISAR imagery and rasters used by the running app. A fresh clone therefore does not automatically reproduce the laptop demo. The official project page also needs a separate, public demo link. Do not claim the app is ready for independent use until the package and a clean setup have been checked.

## Suggested work

1. Inventory the files needed to reproduce the exact intended submission on a second computer. The canonical ascending product is `backend/data/output/camanava_2026/nisar/`; determine whether the descending-track product, other ignored outputs, and any place-data assets are needed for every claimed feature. On this laptop, the descending product was not present at initial inspection; treat that as a potential blocker to investigate, not a reason to fabricate or silently substitute data. Do not package the `.pre-r2-preserved-*` directory, raw satellite files, unreviewed motion outputs, credentials, tokens, signed URLs, or private files.
2. Preserve the existing observed product and its provenance; do not regenerate or overwrite the canonical output merely to package it. Make a small, documented archive with the required relative paths, source attribution and applicable data-use terms. The current binding logic in `backend/app/product_binding.py` accepts the original manifest hash or a matching product-content fingerprint for validation and timelapse; preserve all needed files and verify the actual endpoints rather than assuming a renamed or regenerated product will match.
3. Publish the package where judges can download it without signing in or requesting permission. If the chosen external host requires an account, interactive login, or cannot be accessed by the agent, prepare the package and exact upload instructions for the owner; never disclose credentials. Put the final public link, package version, checksum, size, attribution and exact Windows extraction/startup steps in the README and the Space Apps project details. Do not claim publication until anonymous access is verified. Keep raw NISAR and large generated artifacts out of Git.
4. Verify on an isolated clean checkout, with no access to this laptop's ignored outputs, and no Earthdata token for the normal run: install dependencies; install the package exactly as documented; start backend and frontend; check the main map and pass overlays, validation and timelapse, and other features claimed in the submission. Record exact results and clearly disclose any features requiring additional data, network access or authentication. Do not represent the app as fully offline: remote basemap tiles and dependencies may require network access.
5. Test the final repository, data-package and demo links in a signed-out/private browser. The demo must remain a separate link in the project submission page. Record the submission commit and preserve a versioned package that matches it; document any missing functionality honestly.

## Constraints

Zero-cost workflow, no app sign-in, no paid hosting, no new scientific claims or synthetic substitutes. Keep NISAR open-water limitations and unavailable ground-motion status explicit. Coordinate around the owner's submission deadline and current repository freeze; this handoff does not authorize publishing credentials or silently modifying observed products.

**Done when:** the owner has a public, anonymously verified repository and matching usable data package, clear instructions and evidence from a clean-checkout run, or an explicit list of remaining blockers with a concrete owner handoff.
