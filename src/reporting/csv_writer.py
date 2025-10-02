"""Shared CSV export utilities for reporting outputs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DEFAULT_REPORT_CSV_ENCODING = "utf-8-sig"


def write_report_csv(
    dataframe: pd.DataFrame,
    output_path: Path | str,
    *,
    encoding: str = DEFAULT_REPORT_CSV_ENCODING,
    index: bool = False,
    mkdirs: bool = True,
    logger=None,
    log_message: str | None = "Wrote report to %s",
) -> Path:
    """Persist a report DataFrame to CSV using standard project defaults.

    Parameters
    ----------
    dataframe:
        The pandas DataFrame to persist.
    output_path:
        Destination path for the CSV file.
    encoding:
        Encoding to use when writing the CSV. Defaults to ``utf-8-sig`` to
        retain compatibility with Excel on macOS.
    index:
        Whether to include the DataFrame index in the output.
    mkdirs:
        When ``True``, ensure the destination directory exists before writing.
    logger:
        Optional logger to emit a confirmation message.
    log_message:
        Message format compatible with ``logger.info``. Set to ``None`` to
        suppress logging even when a logger is provided.

    Returns
    -------
    pathlib.Path
        The normalized output path that was written.
    """

    path = Path(output_path)
    if mkdirs:
        path.parent.mkdir(parents=True, exist_ok=True)

    dataframe.to_csv(path, index=index, encoding=encoding)

    if logger is not None and log_message:
        logger.info(log_message, path)

    return path
