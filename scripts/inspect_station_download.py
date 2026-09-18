"""Inspect one official station ZIP without extracting or changing raw files.

Input: the downloaded ZIP containing CSV, JSON, XML and RDF exports.
The CSV has three string fields: 测站编码, 测站名称, 站类.
Output: console statistics and, optionally, a JSON inspection report in outputs/.
This is an inspection tool, not a station normalizer. It creates no stations.csv.
"""

import argparse
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["测站编码", "测站名称", "站类"]
SOURCE_FIELDS = ["STCD", "STNM", "STTP"]


def inspect_download(archive_path):
    """Read ZIP bytes and return a report dict; all source field values stay strings.

    No DataFrame, coordinate conversion, unit conversion, filtering or file repair
    is performed. checked_at is inspection time (+08:00), not observation time.
    """
    original = archive_path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(original)) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise ValueError(f"ZIP integrity failed: {bad_member}")
        files = {name: archive.read(name) for name in archive.namelist()
                 if not name.endswith("/")}

    def member(extension):
        matches = [name for name in files if name.lower().endswith(extension)]
        if len(matches) != 1:
            raise ValueError(f"Expected one {extension} member, found {len(matches)}")
        return files[matches[0]]

    reader = csv.DictReader(io.StringIO(member(".csv").decode("utf-8-sig")))
    if reader.fieldnames != FIELDS:
        raise ValueError(f"Source schema changed: {reader.fieldnames}")
    rows = list(reader)
    if not rows or any(None in row or None in row.values() for row in rows):
        raise ValueError("CSV is empty or has malformed rows; inspect the source.")
    ids = Counter(row["测站编码"] for row in rows)
    names = Counter(row["测站名称"] for row in rows)
    types = Counter(row["站类"] for row in rows)
    expected = [dict(zip(SOURCE_FIELDS, (row[field] for field in FIELDS)))
                for row in rows]

    # Diagnose the source export error explicitly. Never save a repaired JSON.
    json_text = member(".json").decode("utf-8-sig").strip()
    json_check = {"strict_valid": True, "error": None}
    try:
        json_check["matches_csv"] = json.loads(json_text) == expected
    except json.JSONDecodeError as error:
        json_check.update(strict_valid=False, error=str(error))
        if json_text.startswith("{[") and json_text.endswith("]}"):
            try:
                diagnostic_rows = json.loads(json_text[1:-1])
                json_check["diagnostic_only_extra_outer_braces"] = True
                json_check["diagnostic_inner_array_matches_csv"] = diagnostic_rows == expected
            except json.JSONDecodeError as inner_error:
                json_check["diagnostic_error"] = str(inner_error)

    xml_root = ET.fromstring(member(".xml"))
    xml_rows = [{child.tag: child.text for child in record}
                for record in xml_root.findall("LIST")]
    rdf_root = ET.fromstring(member(".rdf"))
    rdf_rows, metadata = [], {}
    for description in rdf_root:
        values = {child.tag.rsplit("}", 1)[-1]: child.text for child in description}
        if all(field in values for field in SOURCE_FIELDS):
            rdf_rows.append({field: values[field] for field in SOURCE_FIELDS})
        else:
            metadata.update(values)
    row_signature = lambda records: Counter(tuple(row.get(k) for k in SOURCE_FIELDS)
                                             for row in records)
    duplicate_names = {name: count for name, count in names.items() if count > 1}
    report = {
        "checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "raw_path": str(archive_path.resolve()),
        "sha256": hashlib.sha256(original).hexdigest(),
        "member_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        "csv_fields": FIELDS,
        "record_count": len(rows),
        "unique_station_ids": len(ids),
        "duplicate_id_extra_rows": len(rows) - len(ids),
        "exact_duplicate_extra_rows": len(rows) - len({tuple(row[k] for k in FIELDS) for row in rows}),
        "missing_by_field": {field: sum(not row[field].strip() for row in rows) for field in FIELDS},
        "station_type_counts": dict(types),
        "duplicate_names": duplicate_names,
        "duplicate_name_affected_rows": sum(duplicate_names.values()),
        "coordinate_fields_present": False,
        "records_without_coordinates": len(rows),
        "coordinate_crs": "coordinate_crs_unknown",
        "outside_shenzhen_count": None,
        "spatial_check_note": "No coordinate fields; geographic validity and Shenzhen coverage cannot be checked.",
        "observation_timestamp_present": False,
        "source_metadata": metadata,
        "json_check": json_check,
        "xml_matches_csv_in_order": xml_rows == expected,
        "rdf_matches_csv_by_values": row_signature(rdf_rows) == row_signature(expected),
        "standard_station_interface_status": "blocked",
        "blocker": "coordinates_missing; coordinate_crs_unknown",
    }
    if archive_path.read_bytes() != original:
        raise RuntimeError("Raw archive changed during inspection; report not saved.")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Original downloaded ZIP")
    parser.add_argument("--output", type=Path, help="New JSON report path inside outputs/")
    args = parser.parse_args()
    report = inspect_download(args.archive)
    if args.output:
        if not args.output.resolve().is_relative_to(PROJECT_ROOT / "outputs"):
            parser.error("The report must be saved inside the project's outputs/ directory.")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    print("Records:", report["record_count"])
    print("Unique station IDs:", report["unique_station_ids"])
    print("Duplicate ID extra rows:", report["duplicate_id_extra_rows"])
    print("Missing values:", report["missing_by_field"])
    print("Station types:", report["station_type_counts"])
    print("Source JSON strict valid:", report["json_check"]["strict_valid"])
    print("XML / RDF agree with CSV:", report["xml_matches_csv_in_order"], report["rdf_matches_csv_by_values"])
    print("Records without coordinates:", report["records_without_coordinates"])
    print("Outside Shenzhen: NOT CHECKABLE (no coordinates)")
    print("Inspection complete. Standard station interface: BLOCKED.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
