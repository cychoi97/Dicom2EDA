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
- `Python 3.9+`
- `pydicom`
- `pandas`
- `matplotlib`, `seaborn` (for EDA visual reports)
- `tqdm`, `natsort`
