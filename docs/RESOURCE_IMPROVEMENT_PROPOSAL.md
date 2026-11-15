## Proposal for Claude / coordinator

The owner asked us to consider using more of the challenge's listed NASA and partner resources to improve Tanaw's data interpretation and user experience. This is a proposal for prioritization, not an instruction to change the release or rerun data processing.

**Current baseline:** reviewed `main` at `5df5d74`, including the v6.1 second-track and robustness work. The rain relationship seen on the morning track was not reproduced on the evening track; the storm coherence result is interval-confounded. Preserve these qualifications and the published NISAR product and validation hashes.

### Recommended near-term improvements

1. **NISAR quality and provenance:** Present acquisition time in Manila and UTC, sensor/product, processing version and provisional/validated status, pixel spacing, valid coverage, and a link to the applicable [ASF NISAR product guide](https://nisar-docs.asf.alaska.edu/products-overview/). Reuse facts already present in the manifest or API; show unavailable fields as unavailable. Review the [GCOV mask and number-of-looks documentation](https://nisar-docs.asf.alaska.edu/gcov/) and exact product specification before interpreting mask values or changing exclusions. The current optional reader assumes `mask > 0` is valid; do not enable or modify the mask without verifying its encoding on the actual product. Any new processing must be isolated and independently validated before release.

2. **Better SAR explanations:** Extend the existing explainer with short, cited explanations based on [NASA ARSET](https://forum.earthdata.nasa.gov/viewtopic.php?t=6022) and NISAR's [phase and coherence guide](https://nisar-docs.asf.alaska.edu/phase/): backscatter and polarization, why dark-water detection can miss urban flooding, and why a coherence drop can have multiple causes. Preserve v6.1's interval caveat and the non-reproduced evening-track rainfall finding. Cite the actual training or guide used.

3. **Discovery and coverage:** Assess a small observation-availability view using the existing CMR search and manifests: acquisition dates, track, product type, maturity and coverage, with links to [Earthdata Search](https://nisar-docs.asf.alaska.edu/earthdata-search/) or ASF. Distinguish catalogue availability from actual processed observations. Avoid new paid services or runtime accounts.

### Future investigation, outside the immediate submission

4. **Ground-motion research:** Use the [GUNW guide](https://nisar-docs.asf.alaska.edu/gunw/) to audit ionosphere and external correction state, sign convention, coherence and reference area. Included correction layers are not automatically applied. Keep motion and priority zones unavailable until the pipeline and results are independently reviewed and validated; a longer record may be needed.

5. **Historical radar:** Check the [open RADARSAT-1 archive](https://www.asc-csa.gc.ca/eng/satellites/radarsat1/data-access.asp) for accessible acquisitions over the study area between 2000 and 2013. Coverage, API/access details, processing effort and useful dates remain unverified. If viable, present it as a separate C-band sensor with its own provenance; never label it NISAR or imply that a continuous comparable time series exists. Do not add a new data dependency to the submission without checking coverage, terms and laptop feasibility.

RCM access may require registration and some products have restricted availability; SAOCOM access and costs/coverage also need verification. Neither is proposed as an immediate dependency.

**Requested coordinator review:** Which near-term items, if any, fit the current freeze and submission priorities? Please record any decision or follow-up in the repository. No claims above establish new scientific accuracy; no code or data has been changed by this proposal.
