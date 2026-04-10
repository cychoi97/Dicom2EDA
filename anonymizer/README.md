# DICOM Anonymize

> **DICOM Data Anonymisation & Path Sanitisation Pipeline** (v1.0.1)
> Recursively scan a directory of DICOM files, assign sequential anonymous IDs, safely scrub DICOM header tags, strip patient identifiers from folder names, and reorganize files by series.

---

## Features

| Category | Details |
|----------|---------|
| **Sequential IDs** | Replaces original `PatientID` and `PatientName` with simplified sequential identifiers (e.g., `ANON_001`, `ANON_002`) |
| **Deep Path Sanitisation** | Dynamically scans original nested folder names for PHI strings (Name, ID, Dates) and selectively scrubs them out while retaining original subfolder context |
| **Header Scrubbing** | Overwrites 11+ identifiable metadata tags (e.g. `InstitutionName`, `ReferringPhysicianName`) with empty strings |
| **Date Truncation** | Truncates precise dates (Birth, Study, Series) down to `YYYYMM` (6 chars) to retain cohort research utility while preventing exact identification |
| **Time Removal** | Entirely removes Study and Series time tags |
| **Pixel PHI Warning** | Automatically detects `BurnedInAnnotation=YES` and logs a prominent warning indicating standard pixel PHI might be present |
| **Series-based Layout** | Reformats file trees into a clean `<SeriesNumber>_<SeriesDesc>/<N>.dcm` layout |
| **Traceable Mapping Log** | Exports a secure per-file `mapping_log.csv` tracking original/anonymous IDs, raw file paths, and subfolder sanitisation histories |

---

## Directory Model

**Source (Input):**
```
<input_root>/                          ← --input
  <PATIENT_NAME_STUDY_12345>/          ← level 1 (--patient-depth 1, default)
    CT_Chest_20231215/                 ← Nested sub-folder containing a Date (PHI)
      slice1.dcm
      slice2.dcm
```

**Anonymised Output:**
```
<output_root>/                         ← --output
  ANON_001/                            ← Sequential ID assignment
    CT_Chest/                          ← "20231215" stripped out automatically
      1_Chest_HRCT/                    ← <SeriesNumber>_<SeriesDescription>
        0001.dcm
        0002.dcm
  ANON_002/
    ...
  mapping_log.csv                      ← Original ↔ Anonymised mapping table
```

---

## Installation

```bash
pip install pydicom tqdm natsort
```

---

## Quick Start

```bash
# Basic run (patient folders are direct children of the root)
python dicom_anonymize.py --input /path/to/source --output /path/to/anon_output \
    --log ./mapping_log.csv

# Multi-site layout: root/site/patient/
python dicom_anonymize.py --input /path/to/source --output /path/to/anon_output \
    --patient-depth 2 \
    --log ./mapping_log.csv

# Custom Prefix for ID generation (e.g., SITE_A_001)
python dicom_anonymize.py --input /path/to/source --output /path/to/anon_output \
    --prefix SITE_A \
    --log ./mapping_log.csv

# Dry Run - evaluate mapping, folder structures, and PHI removal without writing anything
python dicom_anonymize.py --input /path/to/source --output /path/to/anon_output \
    --log ./mapping_log_dryrun.csv \
    --dry-run
```

---

## CLI Reference

| Argument | Default | Description |
|----------|---------|-------------|
| `--input`, `-i` | *(required)* | Root directory of source DICOM files. |
| `--output`, `-o`| *(required)* | Root directory for anonymised DICOM output. |
| `--prefix` | `ANON` | Prefix for sequential patient folder names (e.g., `ANON` → `ANON_001`). |
| `--patient-depth`| `1` | Directory levels below `--input` that define one patient folder. |
| `--log` | `None` | Path for the per-file CSV mapping log. **WARNING: Contains original PHI.** |
| `--dry-run` | `False` | Compute anonymisation plan and save log without writing DICOM files. |

---

## Output Structure

```
anon_output/
  ANON_001/                  
  ANON_002/
  ...
  mapping_log.csv       ← MUST be separated from data distributions
```

### `mapping_log.csv` Columns
| Column | Description |
|--------|-------------|
| `anon_patient_id` | Auto-generated ID (`ANON_001`) |
| `original_patient_id` | **Raw PatientID** |
| `original_patient_name` | **Raw PatientName** |
| `original_file_path` | Absolute path of the source file |
| `anon_file_path` | Absolute path of the newly written `.dcm` |
| `original_subfolder_path` | Raw subfolder structure under the patient level |
| `anon_subfolder_path` | Subfolder structure with extracted PHI strings scrubbed out |
| `modality` | Modality tag (`CT`, `MR`, etc.) |
| `series_description` | `SeriesDescription` tag |
| `burned_in_annotation` | `YES` / `NO` / Empty |
| `status` / `error_msg` | Processing health tracking |

---

## Privacy & Handling Strategy

1. **Patient Identifier Relocation**  
`PatientName` and `PatientID` are overwritten by `--prefix` (`ANON_XXX`).

2. **Explicit Tag Blanking**  
The following tags persist in the DICOM but their strings are wiped (`""`):  
`InstitutionName`, `InstitutionAddress`, `ReferringPhysicianName`, `PerformingPhysicianName`, `SoftwareVersions`, `OperatorsName`, `StationName`, `DeviceSerialNumber`, `RequestingPhysician`, `AccessionNumber`.

3. **Date/Time Coarsening**  
- **StudyDate, SeriesDate, PatientBirthDate, AcquisitionDate, ContentDate, AcquisitionDateTime**: Retain the first 6 characters (`YYYYMM`).  
- **StudyTime, SeriesTime**: Tag is completely removed.

4. **Retained Fields**  
`PatientSex` and `PatientAge` (e.g., "055Y") are intentionally retained to protect dataset research value while posing extremely low re-identification risks.

5. **Path PHI Scrubbing**  
All values extracted from the scrubbed DICOM tags (Dates, Times, Names, Accession Numbers) are collected. During folder reconstruction, any instance of these strings discovered within nested sub-folder names is algorithmically stripped out.

> [!CAUTION]
> The exported `mapping_log.csv` contains transparent links back to raw MRNs and Patient Names. **Treat this CSV with extreme caution** and ensure it is stored on secure internal servers, never bundled alongside outward-facing datasets.
