from __future__ import annotations

import csv
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.errors import AppError
from app.core.storage import get_upload_path, read_upload_metadata
from app.schemas import SheetPreview, UploadPreviewResponse
from app.services.schema_profiler import profile_columns


CSV_SHEET_NAME = "CSV"
CSV_SAMPLE_CHARS = 1024 * 1024
CSV_DELIMITERS = [",", "\t", ";", "|"]


def _clean_header(values: list[Any]) -> list[str]:
    headers: list[str] = []
    seen: dict[str, int] = {}
    for index, value in enumerate(values):
        name = str(value).strip() if value is not None and str(value).strip() else f"column_{index + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        headers.append(name)
    return headers


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def _fallback_csv_dialect(delimiter: str):
    return type("FallbackCsvDialect", (csv.excel,), {"delimiter": delimiter})


def _detect_csv_dialect(sample: str):
    """Detect the CSV delimiter, preferring the delimiter used by the header row.

    ``csv.Sniffer`` works well for homogeneous files, but it can be misled by
    files whose later rows switch delimiters (for example comma-separated rows
    followed by semicolon-separated rows).  The header row is the strongest
    single-row signal, so it wins when it contains exactly one candidate
    delimiter.
    """
    if not sample:
        return csv.excel

    first_line = next((line for line in sample.splitlines() if line.strip()), sample)
    candidate_counts = {delimiter: first_line.count(delimiter) for delimiter in CSV_DELIMITERS}
    present = [delimiter for delimiter, count in candidate_counts.items() if count > 0]
    if len(present) == 1:
        return _fallback_csv_dialect(present[0])

    try:
        return csv.Sniffer().sniff(sample, delimiters="".join(CSV_DELIMITERS))
    except csv.Error:
        delimiter = max(CSV_DELIMITERS, key=lambda item: first_line.count(item))
        if first_line.count(delimiter) == 0:
            delimiter = ","
        return _fallback_csv_dialect(delimiter)


def _read_csv_sample(path: Path, encoding: str) -> str:
    with path.open("r", encoding=encoding, newline="") as handle:
        return handle.read(CSV_SAMPLE_CHARS)


def _detect_csv_encoding(path: Path) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            _read_csv_sample(path, encoding)
        except UnicodeDecodeError:
            continue
        return encoding
    raise AppError("Failed to decode the CSV file. Please use UTF-8 or GB18030 encoding.")


def _csv_read_options(path: Path) -> dict[str, str]:
    encoding = _detect_csv_encoding(path)
    sample = _read_csv_sample(path, encoding)
    dialect = _detect_csv_dialect(sample)
    return {"encoding": encoding, "sep": dialect.delimiter}


def _csv_sample_field_counts(sample: str, delimiter: str) -> list[int]:
    reader = csv.reader(StringIO(sample), _fallback_csv_dialect(delimiter))
    counts = [len(record) for record in reader if record]
    # The sample may end in the middle of a record.  Drop that partial record
    # unless the whole file fit into the sample.
    if len(sample) >= CSV_SAMPLE_CHARS and len(counts) > 1:
        counts.pop()
    return counts


def _sample_uses_mixed_delimiters(path: Path, encoding: str) -> bool:
    sample = _read_csv_sample(path, encoding)
    dialect = _detect_csv_dialect(sample)
    preferred_counts = _csv_sample_field_counts(sample, dialect.delimiter)
    if not preferred_counts:
        return False

    expected = preferred_counts[0]
    if expected <= 1:
        return False

    # A single delimiter is still authoritative when it parses the complete
    # sample (including the header) into a consistent field count.
    for delimiter in CSV_DELIMITERS:
        counts = _csv_sample_field_counts(sample, delimiter)
        if counts and len(set(counts)) == 1 and counts[0] == expected:
            return False

    mixed_counts = [len(record) for record in _iter_multi_delimiter_records(StringIO(sample), CSV_DELIMITERS)]
    if len(sample) >= CSV_SAMPLE_CHARS and len(mixed_counts) > 1:
        mixed_counts.pop()
    return len(mixed_counts) >= 2 and len(set(mixed_counts)) == 1 and mixed_counts[0] == expected


class _CharCursor:
    def __init__(self, handle: Any):
        self.handle = handle
        self.chunk = ""
        self.pos = 0

    def peek(self) -> str:
        while self.pos >= len(self.chunk):
            self.chunk = self.handle.read(65536)
            self.pos = 0
            if not self.chunk:
                return ""
        return self.chunk[self.pos]

    def get(self) -> str:
        char = self.peek()
        if char:
            self.pos += 1
        return char


def _iter_multi_delimiter_records(handle: Any, delimiters: list[str]):
    """Parse CSV records while treating every candidate delimiter as a separator.

    Quoting rules are honored, so a semicolon inside a quoted field is kept
    literal.  This parser is used only for files that have no single consistent
    delimiter (for example a comma header followed by semicolon data rows).
    """
    delimiter_set = set(delimiters)
    cursor = _CharCursor(handle)
    field: list[str] = []
    record: list[str] = []
    in_quotes = False

    while True:
        char = cursor.get()
        if not char:
            if field or record:
                record.append("".join(field))
                field = []
                if record:
                    yield record
            break

        if in_quotes:
            if char == '"':
                next_char = cursor.peek()
                if next_char == '"':
                    field.append('"')
                    cursor.get()
                else:
                    in_quotes = False
            else:
                field.append(char)
            continue

        if char == '"' and not field:
            in_quotes = True
        elif char in delimiter_set:
            record.append("".join(field))
            field = []
        elif char in "\r\n":
            value = "".join(field)
            field = []
            if record or value:
                record.append(value)
                yield record
                record = []
            if char == "\r" and cursor.peek() == "\n":
                cursor.get()
        else:
            field.append(char)


def _read_mixed_delimiter_csv_dataframe(path: Path, encoding: str) -> pd.DataFrame:
    with path.open("r", encoding=encoding, newline="") as handle:
        records = _iter_multi_delimiter_records(handle, CSV_DELIMITERS)
        try:
            header_record = next(records)
        except StopIteration as exc:
            raise AppError("The CSV file is empty.") from exc
        headers = _clean_header(header_record)
        data = list(records)
    return pd.DataFrame(data, columns=headers)


def _rows_from_records(records: list[list[Any]], headers: list[str], limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records[:limit]:
        row = {}
        for index, header in enumerate(headers):
            row[header] = _json_value(record[index]) if index < len(record) else None
        rows.append(row)
    return rows


def _build_csv_sheet_preview(headers: list[str], preview_records: list[list[Any]], row_count: int, limit: int) -> SheetPreview:
    rows = _rows_from_records(preview_records, headers, limit)
    if not headers:
        raise AppError("No header row was found in the CSV file.")
    return SheetPreview(
        sheetName=CSV_SHEET_NAME,
        rowCountApprox=row_count,
        columns=profile_columns(rows, headers),
        previewRows=rows,
    )


def _preview_single_delimiter_csv(path: Path, encoding: str, limit: int) -> SheetPreview:
    with path.open("r", encoding=encoding, newline="") as handle:
        sample = handle.read(CSV_SAMPLE_CHARS)
        handle.seek(0)
        reader = csv.reader(handle, _detect_csv_dialect(sample))
        try:
            headers = _clean_header(next(reader))
        except StopIteration as exc:
            raise AppError("The CSV file is empty.") from exc
        preview_records: list[list[Any]] = []
        row_count = 0
        for record in reader:
            row_count += 1
            if len(preview_records) < limit:
                preview_records.append(record)

    return _build_csv_sheet_preview(headers, preview_records, row_count, limit)


def _preview_mixed_delimiter_csv(path: Path, encoding: str, limit: int) -> SheetPreview:
    with path.open("r", encoding=encoding, newline="") as handle:
        records = _iter_multi_delimiter_records(handle, CSV_DELIMITERS)
        try:
            headers = _clean_header(next(records))
        except StopIteration as exc:
            raise AppError("The CSV file is empty.") from exc
        preview_records: list[list[Any]] = []
        row_count = 0
        for record in records:
            row_count += 1
            if len(preview_records) < limit:
                preview_records.append(record)

    return _build_csv_sheet_preview(headers, preview_records, row_count, limit)


def _preview_csv(path: Path, limit: int) -> SheetPreview:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            _read_csv_sample(path, encoding)
            if _sample_uses_mixed_delimiters(path, encoding):
                return _preview_mixed_delimiter_csv(path, encoding, limit)
            return _preview_single_delimiter_csv(path, encoding, limit)
        except UnicodeDecodeError:
            continue
    raise AppError("Failed to decode the CSV file. Please use UTF-8 or GB18030 encoding.")


def _preview_xlsx_sheet(path: Path, sheet_name: str, limit: int) -> SheetPreview:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise AppError("openpyxl is required to read xlsx files.") from exc

    workbook = load_workbook(filename=path, read_only=True, data_only=True)
    if sheet_name not in workbook.sheetnames:
        workbook.close()
        raise AppError(f"Sheet '{sheet_name}' was not found.", 404)
    sheet = workbook[sheet_name]
    iterator = sheet.iter_rows(values_only=True)
    try:
        headers = _clean_header(list(next(iterator)))
    except StopIteration as exc:
        workbook.close()
        raise AppError(f"Sheet '{sheet_name}' is empty.") from exc

    records: list[list[Any]] = []
    row_count = 0
    for row in iterator:
        row_count += 1
        if len(records) < limit:
            records.append(list(row))
    rows = _rows_from_records(records, headers, limit)
    preview = SheetPreview(
        sheetName=sheet_name,
        rowCountApprox=row_count,
        columns=profile_columns(rows, headers),
        previewRows=rows,
    )
    workbook.close()
    return preview


def _preview_xls_sheet(path: Path, sheet_name: str, limit: int) -> SheetPreview:
    try:
        import xlrd
    except ImportError as exc:
        raise AppError("xlrd is required to read xls files.") from exc

    workbook = xlrd.open_workbook(path)
    if sheet_name not in workbook.sheet_names():
        raise AppError(f"Sheet '{sheet_name}' was not found.", 404)
    sheet = workbook.sheet_by_name(sheet_name)
    if sheet.nrows == 0:
        raise AppError(f"Sheet '{sheet_name}' is empty.")
    headers = _clean_header(sheet.row_values(0))
    records = [sheet.row_values(row_index) for row_index in range(1, min(sheet.nrows, limit + 1))]
    rows = _rows_from_records(records, headers, limit)
    return SheetPreview(
        sheetName=sheet_name,
        rowCountApprox=max(0, sheet.nrows - 1),
        columns=profile_columns(rows, headers),
        previewRows=rows,
    )


def preview_upload(upload_id: str, limit: int = 100) -> UploadPreviewResponse:
    metadata = read_upload_metadata(upload_id)
    path = get_upload_path(upload_id)
    ext = path.suffix.lower()

    if ext == ".csv":
        sheets = [_preview_csv(path, limit)]
    elif ext == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(filename=path, read_only=True, data_only=True)
        sheet_names = workbook.sheetnames
        workbook.close()
        sheets = [_preview_xlsx_sheet(path, sheet_name, limit) for sheet_name in sheet_names]
    elif ext == ".xls":
        import xlrd

        workbook = xlrd.open_workbook(path, on_demand=True)
        sheet_names = workbook.sheet_names()
        workbook.release_resources()
        sheets = [_preview_xls_sheet(path, sheet_name, limit) for sheet_name in sheet_names]
    else:
        raise AppError("Unsupported file format. Please upload a csv, xlsx, or xls file.")

    return UploadPreviewResponse(
        uploadId=upload_id,
        fileName=metadata["fileName"],
        fileSize=metadata["fileSize"],
        fileSha256=metadata["fileSha256"],
        sheets=sheets,
    )


def preview_sheet(upload_id: str, sheet_name: str, limit: int = 100) -> SheetPreview:
    path = get_upload_path(upload_id)
    ext = path.suffix.lower()
    if ext == ".csv":
        return _preview_csv(path, limit)
    if ext == ".xlsx":
        return _preview_xlsx_sheet(path, sheet_name, limit)
    if ext == ".xls":
        return _preview_xls_sheet(path, sheet_name, limit)
    raise AppError("Unsupported file format. Please upload a csv, xlsx, or xls file.")


def read_sheet_dataframe(upload_id: str, sheet_name: str) -> pd.DataFrame:
    path = get_upload_path(upload_id)
    ext = path.suffix.lower()
    try:
        if ext == ".csv":
            options = _csv_read_options(path)
            if _sample_uses_mixed_delimiters(path, options["encoding"]):
                return _read_mixed_delimiter_csv_dataframe(path, options["encoding"])
            return pd.read_csv(path, **options)
        if ext == ".xlsx":
            return pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
        if ext == ".xls":
            return pd.read_excel(path, sheet_name=sheet_name, engine="xlrd")
    except Exception as exc:
        raise AppError(f"Failed to read the selected sheet: {exc}") from exc
    raise AppError("Unsupported file format. Please upload a csv, xlsx, or xls file.")
