"""In-memory CSV and ZIP exports for a persisted generated dataset."""

from __future__ import annotations

import csv
from io import BytesIO, StringIO
from zipfile import ZIP_DEFLATED, ZipFile

from dataset_repository import StoredDataset


def export_table_csv(dataset: StoredDataset, table_name: str) -> bytes:
    """Return one persisted table as a UTF-8 CSV with DDL-ordered columns."""

    try:
        table = dataset.schema.table(table_name)
    except KeyError as error:
        raise ValueError(f"Unknown table selected for export: {table_name}") from error

    column_names = [column.name for column in table.columns]
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(column_names)
    for row in dataset.rows_for(table.name):
        writer.writerow([row.get(column_name) for column_name in column_names])
    return output.getvalue().encode("utf-8")


def export_dataset_zip(dataset: StoredDataset) -> bytes:
    """Return every persisted table as a CSV entry in a compressed ZIP archive."""

    output = BytesIO()
    with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
        for table in dataset.schema.tables:
            archive.writestr(f"{table.name}.csv", export_table_csv(dataset, table.name))
    return output.getvalue()
