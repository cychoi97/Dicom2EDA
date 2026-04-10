# DICOM Analysis & Anonymization Tool (DicomAnt)

This repository provides an automated, secure pipeline for both **Exploratory Data Analysis (EDA)** and **Anonymization** of DICOM medical image datasets. The toolkit is specifically mapped out to prepare raw clinical data for Machine Learning model development and external multi-institutional research sharing.

## Overview

- **`dicom2EDA`**: A powerful parser and visualizer that rapidly indexes DICOM directories and outputs a presentation-ready (16:9) multi-section PDF summarizing dataset consistency, completeness, and distributions.
- **`anonymizer`**: A privacy-first DICOM modifier designed to strip Protected Health Information (PHI) from metadata and file paths while preserving the dataset's logical folder structure and image geometries.

> 💡 **Tip:** For more detailed usage instructions, advanced options, and examples, please refer to the individual `README.md` files located inside the [`dicom2EDA/`](./dicom2EDA) and [`anonymizer/`](./anonymizer) directories.

---

## 🔍 dicom2EDA

The EDA module scans datasets, bypassing hefty pixel data loads to quickly extract key structural metadata. 

### Key Features
- **Presentation-Ready Visuals**: Auto-generates a sequence of detailed charts (Sections A–I) spanning dataset overviews, missing-value rates, and series-level histograms. All visuals are optimized for Widescreen PowerPoint slides.
- **Smart Downsampling**: Supports `--one-slice-per-series` for immensely faster processing over millions of files, selecting representations across various strategies (`first`, `middle`, `last`).
- **Comprehensive Metacsv**: Converts DICOM headers into `pandas` DataFrames/CSV formats grouping files logically via `SeriesInstanceUID`.

### Usage
```bash
python dicom2EDA/dicom2EDA.py \
    --dicom-dir /path/to/raw_dicom \
    --out-dir ./eda_output \
    --patient-depth 1
```

---

## 🛡️ dicom_anonymize

The anonymization module replaces sensitive identifiers without destroying the native clinical organization required for downstream engineering.

### Key Features
- **PHI Masking & Truncation**: Strictly scrubs specific institution/physician tags. Dates (StudyDate, PatientBirthDate) are truncated down to `YYYYMM` (6 digits) to keep broad lifecycle integrity while completely eliminating precise dates & times.
- **Sub-folder String Sanitization**: If identifying PHI details (such as Patient Name or ID) are explicitly written out in the folder names, they are dynamically stripped out, collapsing empty name gaps to secure folder layouts.
- **Secure ID Generaton**: Replaces standard identifiable strings with sequential placeholders (e.g., `ANON_001`).
- **Comprehensive Mapping**: Outputs a single authoritative `mapping_log.csv` tracing the lineage from the original paths and patient IDs to the new paths.

### Usage
```bash
python anonymizer/dicom_anonymize.py \
    --input /path/to/raw_dicom \
    --output /path/to/anonymized_dicom \
    --prefix ANON \
    --patient-depth 1 \
    --log ./mapping_log.csv
```

> **⚠️ Security Warning:**
> The `--log` parameter generates a file that contains the explicit map from raw PHI to anonymous placeholders. Store `mapping_log.csv` under strict security policies (e.g., IRB-secure datastores) and **never** distribute it alongside the anonymized dataset.

---

## Requirements
- Python `3.9+`
- `pydicom`
- `pandas`
- `matplotlib`, `seaborn` (for EDA visual reports)
- `tqdm`, `natsort`

---

## Changelog

### dicom2EDA

#### v1.1.0 — 2026-04-10
- **Modality-aware analysis**: Sections B, C, D now split data by `Modality` before plotting.
  - Tags that are entirely absent (all-null) for a given modality are silently excluded from that modality's figure — e.g. `KVP`/`Exposure` will not appear in MR plots.
  - **Section B** redesigned as a 2-panel figure: `B1` Modality × Column missing-rate heatmap + `B2` overall missing-rate bar chart.
  - **Section C** (Categorical): one PDF page / PNG file per Modality (e.g. `C_categorical_CT.png`, `C_categorical_MR.png`).
  - **Section D** (Numeric): one PDF page / PNG file per Modality (e.g. `D_numeric_CT.png`, `D_numeric_MR.png`).
  - Falls back to the original single-combined output when `Modality` is unavailable.
- Added internal helper `_cols_with_data_for_modality()` for reusable per-modality column filtering.

#### v1.0.0 — 2026-04-02
- Initial release.
- Hierarchical DICOM parsing with `--patient-depth` option.
- Header-based series grouping via `SeriesInstanceUID`.
- 9-section EDA report (A–I) saved as PDF + individual PNGs at 300 DPI.
- All figures use fixed 18-inch wide widescreen (16:9) layout optimized for PowerPoint.
- Section I: `SeriesDescription` visual gallery with pixel thumbnails and windowing.
- Privacy-safe by default: SHA-256 hashing for PHI tags, date coarsening to YYYYMM.
- `--keep-phi`, `--one-slice-per-series`, `--rep-policy`, `--no-gallery` CLI options.

---

### anonymizer

#### v1.0.1 — 2026-04-10
- Removed `Manufacturer` (0x0008,0x0070) and `ManufacturerModelName` (0x0008,0x1090) from `TAGS_TO_BLANK` — these are non-PHI device identifiers needed for downstream EDA/model conditioning.
- Added `AcquisitionDate` (0x0008,0x0022), `ContentDate` (0x0008,0x0023), and `AcquisitionDateTime` (0x0008,0x002a) to `TAGS_TO_TRUNCATE_DATE` — dates are coarsened to `YYYYMM` for consistency with `StudyDate`/`SeriesDate`/`PatientBirthDate`.

#### v1.0.0 — 2026-03-26
- Initial release.
- Sequential anonymous IDs (`ANON_001`, `ANON_002`, …) assigned per patient folder.
- DICOM files renamed to zero-padded slice order (`0001.dcm`, `0002.dcm`, …).
- PHI tag blanking (institution, physician, station, device identifiers).
- Date/time coarsening: `StudyDate`, `SeriesDate`, `PatientBirthDate` → `YYYYMM`; `StudyTime`/`SeriesTime` removed.
- `PatientName` replaced with anonymous ID; `PatientID` and `PatientBirthDate` blanked.
- Folder-name sanitization: patient identifiers stripped from directory names.
- `mapping_log.csv` output linking original paths/IDs to anonymized equivalents.
- `--patient-depth`, `--prefix`, `--dry-run`, `--log` CLI options.
