"""Human-readable exports for immutable market data versions."""

from __future__ import annotations

from io import StringIO

import pandas as pd


# Keep the columns that a researcher reads most often first.  Any future
# standardized fields are retained after these instead of being silently lost.
PREFERRED_COLUMNS = (
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "universe_member",
    "universe_rank",
)


def version_frame_to_csv(frame: pd.DataFrame) -> bytes:
    """Return an Excel-friendly UTF-8 CSV containing every version row.

    The UTF-8 BOM lets common local spreadsheet applications open Chinese
    symbols and headings correctly.  CSV is intentionally used instead of an
    application-specific workbook so researchers can inspect it in Excel,
    WPS, Numbers, R or Python without another dependency.
    """

    ordered = [column for column in PREFERRED_COLUMNS if column in frame.columns]
    ordered.extend(column for column in frame.columns if column not in ordered)
    export = frame.loc[:, ordered].copy()
    if "date" in export.columns:
        export["date"] = pd.to_datetime(export["date"]).dt.strftime("%Y-%m-%d")
    sort_columns = [column for column in ("date", "symbol") if column in export.columns]
    if sort_columns:
        export = export.sort_values(sort_columns, kind="stable")
    output = StringIO()
    export.to_csv(output, index=False, lineterminator="\n")
    return output.getvalue().encode("utf-8-sig")
