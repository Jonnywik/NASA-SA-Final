# Hypotheses and checked sources

These are hypotheses for investigation, not findings established by Tanaw. Spatial overlap does not prove cause. Filipino wording awaits native-speaker review.

1. Eco et al. (2020), *Disaster in Slow Motion*, JSM Environmental Science & Ecology 8(1):1068. [Paper](https://www.jscimedcentral.com/journal-article-info/JSM-Environmental-Science-and-Ecology/Disaster-in-Slow-Motion:-Widespread-Land-Subsidence-in-and-Around-Metro-Manila,-Philippines-Quantified-By-Insar-Time-Series-Analysis-5350). The authors attribute subsidence in and around CAMANAVA principally to groundwater over-extraction and discuss increased exposure to floods and tides. Their historical regional analysis does not establish the cause at each Tanaw pixel.
2. Maynilad Water Services, *Valenzuela Sewerage System Environmental Assessment*, section on tidal control gates, [World Bank document E2677 V8](https://documents.worldbank.org/curated/en/169381468295521077/pdf/E26770V80P113800Box385202B00PUBLIC0.pdf), p. 49. It describes gates closing at high tide to prevent entry and opening at low tide for drainage. This supports a plausible tidal mechanism, not proof of flood duration in a particular event.
3. US Environmental Protection Agency, [Urbanization – Hydrology](https://www.epa.gov/caddis/urbanization-hydrology). It describes reduced infiltration and increased runoff associated with impervious surfaces. This general mechanism is not a measurement of local runoff.

Fishpond conversion and coastal land-use effects on flood persistence were dropped: the sources reviewed did not establish this particular causal relationship for the study area. A broad claim that subsidence increases both flood frequency and duration was narrowed to increased flood exposure: the checked paper supports the latter but does not quantify those two outcomes.

```json
[
  {
    "id": "groundwater-subsidence",
    "title": "Hypothesis: groundwater extraction and ground motion",
    "titleFil": "Haypotesis: pagkuha ng tubig sa ilalim ng lupa at paggalaw ng lupa",
    "statement": "Groundwater over-extraction may contribute to land subsidence in CAMANAVA and the Bulacan coast.",
    "statementFil": "Maaaring mag-ambag sa paglubog ng lupa sa CAMANAVA at baybayin ng Bulacan ang labis na pagkuha ng tubig sa ilalim ng lupa.",
    "evidenceInApp": "Ground motion (N3)",
    "references": [{"citation": "Eco et al. (2020), Disaster in Slow Motion, JSM Environmental Science & Ecology 8(1):1068", "url": "https://www.jscimedcentral.com/journal-article-info/JSM-Environmental-Science-and-Ecology/Disaster-in-Slow-Motion:-Widespread-Land-Subsidence-in-and-Around-Metro-Manila,-Philippines-Quantified-By-Insar-Time-Series-Analysis-5350", "quote": "due mainly to over-extraction of groundwater"}]
  },
  {
    "id": "subsidence-flood-exposure",
    "title": "Hypothesis: subsidence and flood exposure",
    "titleFil": "Haypotesis: paglubog ng lupa at pagkakalantad sa baha",
    "statement": "Land subsidence may increase exposure to flooding and tidal incursions in coastal Metro Manila.",
    "statementFil": "Maaaring tumaas ang pagkakalantad sa baha at pagpasok ng tubig-dagat dahil sa paglubog ng lupa sa baybayin ng Metro Manila.",
    "evidenceInApp": "Ground motion (N3) and flood rhythm (N1)",
    "references": [{"citation": "Eco et al. (2020), Disaster in Slow Motion, JSM Environmental Science & Ecology 8(1):1068", "url": "https://www.jscimedcentral.com/journal-article-info/JSM-Environmental-Science-and-Ecology/Disaster-in-Slow-Motion:-Widespread-Land-Subsidence-in-and-Around-Metro-Manila,-Philippines-Quantified-By-Insar-Time-Series-Analysis-5350", "quote": "worsening floods and tidal incursions"}]
  },
  {
    "id": "tidal-drainage",
    "title": "Hypothesis: tides and drainage",
    "titleFil": "Haypotesis: pagtaas ng tubig-dagat at daluyan ng tubig",
    "statement": "High tides and river backflow may delay drainage in Malabon and Navotas.",
    "statementFil": "Maaaring maantala ang pagdaloy ng tubig sa Malabon at Navotas dahil sa pagtaas ng tubig-dagat at pagbalik ng tubig sa ilog.",
    "evidenceInApp": "Flood rhythm (N1)",
    "references": [{"citation": "Maynilad Water Services, Valenzuela Sewerage System Environmental Assessment, p. 49, World Bank E2677 V8", "url": "https://documents.worldbank.org/curated/en/169381468295521077/pdf/E26770V80P113800Box385202B00PUBLIC0.pdf", "quote": "During high tide, the gates are closed"}]
  },
  {
    "id": "impervious-runoff",
    "title": "Hypothesis: urban surfaces and runoff",
    "titleFil": "Haypotesis: mga ibabaw sa lungsod at pag-agos ng tubig-ulan",
    "statement": "Urban expansion and impervious surfaces may increase runoff.",
    "statementFil": "Maaaring dumami ang tubig-ulang umaagos sa ibabaw dahil sa paglawak ng lungsod at mga ibabaw na hindi nasisipsipan ng tubig.",
    "evidenceInApp": "Flood rhythm (N1) and rainfall history",
    "references": [{"citation": "US Environmental Protection Agency, Urbanization – Hydrology", "url": "https://www.epa.gov/caddis/urbanization-hydrology", "quote": "Decreased infiltration and increased surface runoff"}]
  }
]
```
