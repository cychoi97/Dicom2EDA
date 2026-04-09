#!/usr/bin/env python3
"""
dicom_anonymize.py  (v1.0)

DICOM anonymisation pipeline.

Integrates with dicom2EDA.py workflow:
  - Same directory scanning logic (patient-depth, series grouping)
  - Same PHI tag awareness as dicom2EDA.py PHI_LIKE_TAGS
  - Extends reference code (07.LDCT2NDCT/dicom_anonymizer.py) TAGS_TO_BLANK list

PHI handling strategy (confirmed):
  - PatientName / PatientID       : replaced with ANON_XXX sequential ID
  - TAGS_TO_BLANK                 : overwritten with empty string (tag kept)
  - Dates (StudyDate, SeriesDate, PatientBirthDate) : truncated to YYYYMM (6 chars)
  - Times (StudyTime, SeriesTime) : removed entirely
  - PatientSex / PatientAge       : kept as-is (low PHI risk)
  - BurnedInAnnotation = YES      : warning logged, file still copied

Output directory layout:
  <output>/
    ANON_001/
      sub_001/                          <- anonymised sub-folder (original name hidden)
        <SeriesNumber>_<SeriesDesc>/    <- series-level subfolder
          0001.dcm
          0002.dcm
          ...
    ANON_002/
      ...
    mapping_log.csv                     <- full original <-> anon mapping (per file)

Usage:
  python dicom_anonymize.py \\
      --input  /path/to/source_dicom \\
      --output /path/to/anon_output  \\
      --prefix ANON                  \\
      --patient-depth 1              \\
      --log    ./mapping_log.csv     \\
      [--dry-run]

Dependencies:
  pip install pydicom tqdm natsort
"""

import os
import re
import csv
import logging
import argparse
from pathlib import Path
from collections import defaultdict

import pydicom
from tqdm import tqdm
from natsort import natsorted

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PHI tag definitions
# ---------------------------------------------------------------------------

# Tags to overwrite with an empty string (tag is kept in the file, value blanked).
# Source: 07.LDCT2NDCT/jupyter_lab/dicom_anonymizer.py  +  AccessionNumber added.
TAGS_TO_BLANK: list[tuple[int, int]] = [
    (0x0008, 0x0070),  # Manufacturer
    (0x0008, 0x0080),  # InstitutionName
    (0x0008, 0x0081),  # InstitutionAddress
    (0x0008, 0x0090),  # ReferringPhysicianName
    (0x0008, 0x1050),  # PerformingPhysicianName
    (0x0008, 0x1090),  # ManufacturerModelName
    # PatientName (0x0010,0x0010) is replaced with anon_id, not just blanked
    (0x0018, 0x1020),  # SoftwareVersions
    (0x0008, 0x1070),  # OperatorsName
    (0x0008, 0x1010),  # StationName
    (0x0018, 0x1000),  # DeviceSerialNumber
    (0x0032, 0x1032),  # RequestingPhysician
    (0x0008, 0x0050),  # AccessionNumber  <- added vs. reference code
]

# Date tags: truncated to first 6 characters (YYYYMM) to retain research utility
# while preventing identification by exact birth/study date.
TAGS_TO_TRUNCATE_DATE: list[tuple[int, int]] = [
    (0x0008, 0x0020),  # StudyDate
    (0x0008, 0x0021),  # SeriesDate
    (0x0010, 0x0030),  # PatientBirthDate
]

# Time tags: removed entirely (time-of-day is higher-risk than just date).
TAGS_TO_REMOVE_TIME: list[tuple[int, int]] = [
    (0x0008, 0x0030),  # StudyTime
    (0x0008, 0x0031),  # SeriesTime
]

# ---------------------------------------------------------------------------
# PatientMapper: manages original PatientID -> sequential ANON_XXX mapping
# ---------------------------------------------------------------------------

class PatientMapper:
    """Maps original DICOM PatientID values to sequential anonymised IDs."""

    def __init__(self, prefix: str = "ANON") -> None:
        self._prefix = prefix
        self._map: dict[str, str] = {}        # original_pid -> anon_id
        self._counter: int = 0

    def get_or_create(self, original_pid: str) -> str:
        """Return existing or newly assigned anon_id for *original_pid*."""
        original_pid = str(original_pid).strip() or "UNKNOWN"
        if original_pid not in self._map:
            self._counter += 1
            # Zero-pad to at least 3 digits; expand automatically beyond 999
            width = max(3, len(str(self._counter)))
            anon_id = f"{self._prefix}_{self._counter:0{width}d}"
            self._map[original_pid] = anon_id
            logger.debug("Patient '%s' → '%s'", original_pid, anon_id)
        return self._map[original_pid]

    @property
    def mapping(self) -> dict[str, str]:
        return dict(self._map)


# ---------------------------------------------------------------------------
# Core anonymisation logic
# ---------------------------------------------------------------------------

def anonymise_dataset(
    ds: pydicom.Dataset,
    anon_patient_id: str,
) -> pydicom.Dataset:
    """
    Modify *ds* in-place to anonymise PHI tags.

    Actions performed (in order):
      1. PatientName / PatientID  → replaced with anon_patient_id
      2. TAGS_TO_BLANK            → value set to empty string
      3. TAGS_TO_TRUNCATE_DATE    → value truncated to first 6 chars (YYYYMM)
      4. TAGS_TO_REMOVE_TIME      → tag deleted from dataset
      5. BurnedInAnnotation=YES   → logged as warning (pixel not modified)

    Tags NOT modified:
      - PatientSex, PatientAge (low PHI risk, kept for research utility)
      - All acquisition / geometry / series tags (Modality, Rows, Columns, ...)
    """
    # 1. Replace PatientName and PatientID with anonymised ID
    if (0x0010, 0x0010) in ds:
        ds.PatientName = anon_patient_id
    if (0x0010, 0x0020) in ds:
        ds.PatientID = anon_patient_id

    # 2. Blank the target tags (preserve tag existence with empty value)
    for tag in TAGS_TO_BLANK:
        if tag in ds:
            try:
                ds[tag].value = ""
            except Exception:
                pass  # skip read-only or sequence tags silently

    # 3. Truncate date tags to YYYYMM (first 6 characters)
    for tag in TAGS_TO_TRUNCATE_DATE:
        if tag in ds:
            try:
                raw = str(ds[tag].value).strip()
                if len(raw) >= 6:
                    ds[tag].value = raw[:6]
                elif raw:
                    # Short value: keep as-is to avoid breaking DICOM validity
                    pass
                else:
                    ds[tag].value = ""
            except Exception:
                pass

    # 4. Remove time tags entirely
    for tag in TAGS_TO_REMOVE_TIME:
        if tag in ds:
            try:
                del ds[tag]
            except Exception:
                pass

    # 5. Warn if burned-in annotation is present (pixel data not modified)
    bia = getattr(ds, "BurnedInAnnotation", None)
    if bia is not None and str(bia).strip().upper() == "YES":
        logger.warning(
            "BurnedInAnnotation=YES detected — pixel PHI may be present: %s",
            getattr(ds, "filename", "<unknown>"),
        )

    return ds


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

def collect_dicom_files(root: Path) -> list[Path]:
    """
    Recursively collect all DICOM files under *root*.
    Accepted if the file ends in .dcm / .DCM, or contains the DICOM magic
    bytes 'DICM' at offset 128.
    """
    candidates: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        # Accept by extension
        if p.suffix.lower() in (".dcm", ".dicom"):
            candidates.append(p)
            continue
        # Accept by DICOM magic bytes (DICM at bytes 128-132)
        try:
            with open(p, "rb") as fh:
                header = fh.read(132)
            if header[128:132] == b"DICM":
                candidates.append(p)
        except Exception:
            pass
    return sorted(candidates)


# ---------------------------------------------------------------------------
# Output path construction
# ---------------------------------------------------------------------------

# Characters that are unsafe in folder/file names on Windows & Linux
_UNSAFE_CHARS_RE = re.compile(r'[\\/:*?"<>|]')


def _safe_name(s: str, max_len: int = 60) -> str:
    """Sanitise a string for use as part of a filesystem path component."""
    s = _UNSAFE_CHARS_RE.sub("_", str(s).strip())
    s = re.sub(r"[\s_]+", "_", s)       # collapse whitespace and multiple underscores → single underscore
    s = s.strip("._")                   # trim leading/trailing dots and underscores
    return s[:max_len] if s else "unknown"


def _extract_phi_strings(ds: pydicom.Dataset, pid: str, pname: str) -> list[str]:
    """Collect string representations of all PHI tags to strip from folder names."""
    phi_strings = set()
    
    if pid and pid != "UNKNOWN":
        phi_strings.add(pid)
        
    if pname and pname != "UNKNOWN":
        phi_strings.add(pname)
        for token in re.split(r'[\^ \-,_]', pname):
            token = token.strip()
            # Require at least 3 characters to avoid false positives with common short words
            if len(token) > 2:
                phi_strings.add(token)

    for group, elem in TAGS_TO_BLANK + TAGS_TO_TRUNCATE_DATE + TAGS_TO_REMOVE_TIME:
        if (group, elem) in ds:
            try:
                val = ds[group, elem].value
                if hasattr(val, "__iter__") and not isinstance(val, (str, bytes)):
                    for v in val:
                        sv = str(v).strip()
                        if len(sv) > 2:
                            phi_strings.add(sv)
                else:
                    sv = str(val).strip()
                    if len(sv) > 2:
                        phi_strings.add(sv)
            except Exception:
                pass
                
    return sorted(list(phi_strings), key=len, reverse=True)


def _get_series_folder_name(ds: pydicom.Dataset) -> str:
    """
    Construct a human-readable series subfolder name from DICOM header.
    Format: <SeriesNumber>_<SeriesDescription>
    Falls back gracefully when tags are missing.
    """
    series_num = getattr(ds, "SeriesNumber", None)
    series_desc = getattr(ds, "SeriesDescription", None)

    parts: list[str] = []
    if series_num is not None:
        try:
            parts.append(str(int(series_num)))
        except Exception:
            parts.append(str(series_num))
    if series_desc is not None:
        desc_clean = _safe_name(str(series_desc))
        if desc_clean:
            parts.append(desc_clean)

    return "_".join(parts) if parts else "unknown_series"


def build_anon_path(
    src: Path,
    input_dir: Path,
    output_dir: Path,
    anon_id: str,
    original_pid: str,
    original_pname: str,
    ds: pydicom.Dataset,
    patient_depth: int,
    slice_counters: dict[tuple, int],
) -> tuple[Path, str, str]:
    """
    Compute the anonymised output path for one DICOM file.

    Sub-folder components below the patient level have known PHI strings
    stripped out (Patient ID/Name, Date, Time, etc.). Safe folder names 
    are kept.

    Output layout:
        <output_dir>/<anon_id>/[sub_anon]/.../<SeriesNum>_<SeriesDesc>/<N>.dcm

    Args:
        src                 : original file path
        input_dir           : root input directory
        output_dir          : root output directory
        anon_id             : e.g. 'ANON_001'
        original_pid        : original PatientID
        original_pname      : original PatientName
        ds                  : pydicom Dataset (header already read)
        patient_depth       : number of path levels below input_dir defining one patient
        slice_counters      : mutable dict tracking sequential slice numbers per
                              (anon_id, anon_sub_path, series_folder); updated in-place

    Returns:
        Destination Path, Original Sub, Anon Sub
    """
    rel_parts = list(src.relative_to(input_dir).parts)
    # rel_parts = [patient_part0, ..., patient_partN-1, sub0, sub1, ..., filename]

    # Parts below the patient level (exclude the filename itself)
    below_patient = rel_parts[patient_depth:-1]  # may be empty

    # -- Anonymise each sub-folder component below the patient level ----------
    phi_strings = _extract_phi_strings(ds, original_pid, original_pname)
    
    anon_sub_parts: list[str] = []
    for part in below_patient:
        res = part
        for phis in phi_strings:
            res = re.sub(re.escape(phis), "", res, flags=re.IGNORECASE)
            
        res = _safe_name(res)
        if not res or res == "unknown":
            res = "anon_folder"
            
        anon_sub_parts.append(res)
    # -------------------------------------------------------------------------

    # Series subfolder from DICOM header (contains no PHI by design)
    series_folder = _get_series_folder_name(ds)

    # Build the key for slice counter: unique per (anon_id, anon sub-path, series)
    counter_key = (anon_id, "/".join(anon_sub_parts), series_folder)
    slice_counters[counter_key] = slice_counters.get(counter_key, 0) + 1
    seq_num = slice_counters[counter_key]
    filename = f"{seq_num:04d}.dcm"

    # Assemble destination path
    # Structure: output / anon_id / [anon_sub_parts] / series_folder / filename
    dst = output_dir / anon_id
    for part in anon_sub_parts:
        dst = dst / part
    dst = dst / series_folder / filename

    return dst, "/".join(below_patient), "/".join(anon_sub_parts)


# ---------------------------------------------------------------------------
# Main anonymisation pipeline
# ---------------------------------------------------------------------------

def run_anonymisation(
    input_dir: Path,
    output_dir: Path,
    prefix: str = "ANON",
    patient_depth: int = 1,
    log_path: Path | None = None,
    dry_run: bool = False,
) -> None:
    """
    Anonymise all DICOM files under *input_dir* and write results to
    *output_dir*.

    Args:
        input_dir     : root directory of source DICOM files
        output_dir    : root directory for anonymised output
        prefix        : anonymous ID prefix (default: 'ANON')
        patient_depth : directory levels below input_dir that define one patient
        log_path      : optional CSV file path for the mapping log
        dry_run       : if True, compute plan and log without writing any files
    """
    logger.info("Source         : %s", input_dir)
    logger.info("Destination    : %s", output_dir)
    logger.info("Patient depth  : %d", patient_depth)
    logger.info("Dry run        : %s", dry_run)

    # Step 1: collect all DICOM files
    files = collect_dicom_files(input_dir)
    if not files:
        logger.error("No DICOM files found in %s", input_dir)
        return
    logger.info("Found %d DICOM file(s) — starting anonymisation …", len(files))

    # Step 2: initialise tracking structures
    patient_mapper = PatientMapper(prefix=prefix)
    slice_counters: dict[tuple, int] = {}        # (anon_id, anon_sub, series) -> count
    log_rows: list[dict] = []                    # per-file mapping log entries

    total_count = 0
    success_count = 0
    warn_burned_in = 0

    # Step 3: process each file
    for src in tqdm(natsorted(files, key=str), desc="Anonymising", unit="file"):
        total_count += 1
        status = "success"
        error_msg = ""
        burned_in = ""
        anon_file_path = ""
        anon_id = ""
        original_pid = ""
        original_pname = ""
        modality = ""
        series_desc = ""

        # Read DICOM header (full read needed to also write pixels later)
        try:
            ds = pydicom.dcmread(str(src), force=True)
        except Exception as exc:
            logger.warning("Cannot read %s: %s", src, exc)
            status = "failed"
            error_msg = str(exc)
            log_rows.append(_make_log_row(
                anon_id="",
                original_pid="",
                original_pname="",
                original_file=src,
                anon_file=Path(""),
                modality="",
                series_desc="",
                burned_in="",
                status=status,
                error_msg=error_msg,
            ))
            continue

        # Extract original patient identifiers for mapping
        original_pid   = str(getattr(ds, "PatientID",   "UNKNOWN")).strip() or "UNKNOWN"
        original_pname = str(getattr(ds, "PatientName", "")).strip()
        modality       = str(getattr(ds, "Modality",    "")).strip()
        series_desc    = str(getattr(ds, "SeriesDescription", "")).strip()

        # Note BurnedInAnnotation status BEFORE anonymisation modifies ds
        bia_val = getattr(ds, "BurnedInAnnotation", None)
        burned_in = str(bia_val).strip().upper() if bia_val is not None else ""
        if burned_in == "YES":
            warn_burned_in += 1

        # Assign (or look up) the anonymised patient ID
        anon_id = patient_mapper.get_or_create(original_pid)

        # Compute destination path
        orig_sub = ""
        anon_sub = ""
        try:
            dst, orig_sub, anon_sub = build_anon_path(
                src=src,
                input_dir=input_dir,
                output_dir=output_dir,
                anon_id=anon_id,
                original_pid=original_pid,
                original_pname=original_pname,
                ds=ds,
                patient_depth=patient_depth,
                slice_counters=slice_counters,
            )
        except Exception as exc:
            logger.warning("Path construction failed for %s: %s", src, exc)
            status = "failed"
            error_msg = str(exc)
            log_rows.append(_make_log_row(
                anon_id=anon_id,
                original_pid=original_pid,
                original_pname=original_pname,
                original_file=src,
                anon_file=Path(""),
                orig_sub="",
                anon_sub="",
                modality=modality,
                series_desc=series_desc,
                burned_in=burned_in,
                status=status,
                error_msg=error_msg,
            ))
            continue

        anon_file_path = dst

        if dry_run:
            # Dry run: just print plan without saving anything
            logger.info("[DRY-RUN] %s → %s", src, dst)
            success_count += 1
        else:
            # Anonymise in-place and save
            try:
                anonymise_dataset(ds, anon_id)
                dst.parent.mkdir(parents=True, exist_ok=True)
                ds.save_as(str(dst))
                success_count += 1
            except Exception as exc:
                logger.warning("Failed to save %s → %s: %s", src, dst, exc)
                status = "failed"
                error_msg = str(exc)

        log_rows.append(_make_log_row(
            anon_id=anon_id,
            original_pid=original_pid,
            original_pname=original_pname,
            original_file=src,
            anon_file=anon_file_path,
            orig_sub=orig_sub,
            anon_sub=anon_sub,
            modality=modality,
            series_desc=series_desc,
            burned_in=burned_in,
            status=status,
            error_msg=error_msg,
        ))

    # Step 4: write mapping log
    if log_path is not None:
        _write_mapping_log(log_rows, log_path)
        logger.info("Mapping log saved → %s  (%d rows)", log_path, len(log_rows))

    # Step 5: summary
    n_patients = len(patient_mapper.mapping)
    logger.info("─" * 60)
    logger.info(
        "Done.  %d / %d file(s) anonymised successfully.",
        success_count, total_count,
    )
    logger.info("Unique patients : %d", n_patients)
    if warn_burned_in:
        logger.warning(
            "BurnedInAnnotation=YES detected in %d file(s) — "
            "review mapping_log.csv 'burned_in_annotation' column.",
            warn_burned_in,
        )


# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------

_LOG_FIELDS = [
    "anon_patient_id",
    "original_patient_id",
    "original_patient_name",
    "original_file_path",
    "anon_file_path",
    "original_subfolder_path",   # e.g. "HongStudy/CT_Chest"
    "anon_subfolder_path",       # e.g. "sub_001/sub_002"
    "modality",
    "series_description",
    "burned_in_annotation",
    "status",
    "error_msg",
]


def _make_log_row(
    anon_id: str,
    original_pid: str,
    original_pname: str,
    original_file: Path,
    anon_file: Path,
    orig_sub: str,
    anon_sub: str,
    modality: str,
    series_desc: str,
    burned_in: str,
    status: str,
    error_msg: str,
) -> dict:
    """Construct a single mapping log row dictionary."""
    return {
        "anon_patient_id":        anon_id,
        "original_patient_id":    original_pid,
        "original_patient_name":  original_pname,
        "original_file_path":     str(original_file),
        "anon_file_path":         str(anon_file),
        "original_subfolder_path": orig_sub,
        "anon_subfolder_path":    anon_sub,
        "modality":               modality,
        "series_description":     series_desc,
        "burned_in_annotation":   burned_in,
        "status":                 status,
        "error_msg":              error_msg,
    }


def _write_mapping_log(rows: list[dict], log_path: Path) -> None:
    """Write per-file mapping log to CSV."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=_LOG_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Anonymise DICOM files and save to a new directory.\n"
            "Output layout: <output>/<ANON_XXX>/<sub_folder>/<SeriesNum_SeriesDesc>/<N>.dcm"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        required=True,
        help="Root directory containing source DICOM files.",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        required=True,
        help="Root directory for anonymised DICOM output.",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="ANON",
        help="Prefix for sequential patient folder names (default: ANON → ANON_001, …).",
    )
    parser.add_argument(
        "--patient-depth",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Number of directory levels below --input that define one patient. "
            "E.g. 1 = <input>/<patient>/ (default), "
            "2 = <input>/<site>/<patient>/."
        ),
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Path for the per-file CSV mapping log (original ↔ anonymised). "
             "WARNING: this file contains original PHI — store securely.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Compute anonymisation plan and print mappings without writing "
            "any DICOM files. The mapping log is still written if --log is set."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_anonymisation(
        input_dir=args.input,
        output_dir=args.output,
        prefix=args.prefix,
        patient_depth=args.patient_depth,
        log_path=args.log,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
