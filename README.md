# Tanaw data package v1 (camanava_2026)

The processed NASA-ISRO NISAR product that the Tanaw app reads (`backend/data/output/camanava_2026/nisar/`, 75 files, byte-for-byte; 392,437,688 bytes zipped). Source code is on the `main` branch; setup steps are in its README ("Run it yourself") and `docs/DATA_PACKAGE.md`.

Download the four parts, join them, check the checksum, and unzip at the repository root:

macOS / Linux:
```
cat tanaw-data-camanava_2026-v1.zip.part00 tanaw-data-camanava_2026-v1.zip.part01 tanaw-data-camanava_2026-v1.zip.part02 tanaw-data-camanava_2026-v1.zip.part03 > tanaw-data-camanava_2026-v1.zip
shasum -a 256 tanaw-data-camanava_2026-v1.zip
```
Windows (Command Prompt):
```
copy /b tanaw-data-camanava_2026-v1.zip.part00+tanaw-data-camanava_2026-v1.zip.part01+tanaw-data-camanava_2026-v1.zip.part02+tanaw-data-camanava_2026-v1.zip.part03 tanaw-data-camanava_2026-v1.zip
certutil -hashfile tanaw-data-camanava_2026-v1.zip SHA256
```
Expected SHA-256: `3290a66b2fc115bd666c1f199c17c7e5d0c6f978132264eb28335219110a2cfa`

Attribution and caveats: see `DATA_README.txt` (NASA-ISRO NISAR via ASF, provisional and V1 products; derived product CC BY 4.0). Open water outside the usual water is not a flood map; NISAR ground motion is not available.
