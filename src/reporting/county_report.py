"""Utilities for generating recurring county-level article reports."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import pandas as pd
from sqlalchemy import text

from src.models.database import DatabaseManager

from .csv_writer import write_report_csv

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDED_STATUSES: tuple[str, ...] = (
    "opinion",
    "opinions",
    "obituary",
    "obits",
    "wire",
)


@dataclass(frozen=True)
class CountyReportConfig:
    """Configuration options for a county-level article report."""

    counties: Sequence[str]
    start_date: datetime
    end_date: Optional[datetime] = None
    database_url: str = "sqlite:///data/mizzou.db"
    include_entities: bool = True
    entity_separator: str = "; "
    label_version: Optional[str] = None


def _clean_counties(raw_counties: Iterable[str]) -> List[str]:
    cleaned: List[str] = []
    for county in raw_counties:
        if not county:
            continue
        county_str = str(county).strip()
        if county_str:
            cleaned.append(county_str)
    if not cleaned:
        raise ValueError(
            "At least one county must be provided for report generation."
        )
    return cleaned


def _format_datetime_for_sql(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def generate_county_report(
    config: CountyReportConfig,
    output_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Generate a county-focused article report and optionally persist to CSV.

    Parameters
    ----------
    config:
        Configuration parameters controlling the report scope and output.
    output_path:
        Optional path for the output CSV. When omitted, the caller can
        handle persistence using the returned DataFrame.

    Returns
    -------
    pandas.DataFrame
        DataFrame containing the requested report rows.
    """

    counties = _clean_counties(config.counties)
    county_bindings = {
        f"county_{idx}": county
        for idx, county in enumerate(counties)
    }
    county_placeholders = ", ".join(f":{name}" for name in county_bindings)

    start_date_sql = _format_datetime_for_sql(config.start_date)
    params: dict[str, str] = {
        "start_date": start_date_sql,
        "entity_separator": config.entity_separator,
        **county_bindings,
    }

    status_bindings = {
        f"status_{idx}": status.lower()
        for idx, status in enumerate(DEFAULT_EXCLUDED_STATUSES)
    }
    params.update(status_bindings)
    status_placeholders = ", ".join(
        f":{name}"
        for name in status_bindings
    )
    status_filter = (
        "  AND LOWER(COALESCE(a.status, '')) NOT IN (\n"
        f"      {status_placeholders}\n"
        "  )\n"
    )
    wire_filter = (
        "  AND (\n"
        "        COALESCE(\n"
        "            json_extract(a.metadata, '$.byline.is_wire_content'),\n"
        "            0\n"
        "        ) = 0\n"
        "        AND COALESCE(\n"
        "            CASE\n"
        "                WHEN a.wire IS NULL THEN ''\n"
        "                WHEN json_valid(a.wire) = 0 THEN '__wire__'\n"
        "                ELSE json_extract(a.wire, '$.provider')\n"
        "            END,\n"
        "            ''\n"
        "        ) = ''\n"
        "      )\n"
    )

    label_filter_subquery = ""
    label_filter_clause = ""
    if config.label_version:
        label_filter_subquery = (
            "        WHERE label_version = :label_version\n"
        )
        label_filter_clause = "    WHERE al.label_version = :label_version\n"
        params["label_version"] = config.label_version

    cte_parts: list[str] = [
        (
            "latest_labels AS (\n"
            "    SELECT al.article_id,\n"
            "           al.primary_label,\n"
            "           al.alternate_label,\n"
            "           al.label_version,\n"
            "           al.applied_at\n"
            "    FROM article_labels al\n"
            "    JOIN (\n"
            "        SELECT article_id,\n"
            "               MAX(applied_at) AS max_applied_at\n"
            "        FROM article_labels\n"
            f"{label_filter_subquery}"
            "        GROUP BY article_id\n"
            "    ) latest\n"
            "      ON latest.article_id = al.article_id\n"
            "     AND latest.max_applied_at = al.applied_at\n"
            f"{label_filter_clause}"
            ")\n"
        )
    ]

    entity_join = ""
    entities_column = "    '' AS entities\n"
    if config.include_entities:
        cte_parts.append(
            (
                "entity_agg AS (\n"
                "    SELECT grouped.article_id,\n"
                "           GROUP_CONCAT(\n"
                "               grouped.entity_value,\n"
                "               :entity_separator\n"
                "           ) AS entities\n"
                "    FROM (\n"
                "        SELECT DISTINCT ae.article_id,\n"
                "                CASE\n"
                "                    WHEN ae.entity_label IS NOT NULL\n"
                "                         AND ae.entity_label != '' THEN\n"
                "                        ae.entity_text || ' [' ||\n"
                "                        ae.entity_label || ']'\n"
                "                    ELSE ae.entity_text\n"
                "                END AS entity_value\n"
                "        FROM article_entities ae\n"
                "    ) AS grouped\n"
                "    GROUP BY grouped.article_id\n"
                ")\n"
            )
        )
        entity_join = "LEFT JOIN entity_agg ON entity_agg.article_id = a.id\n"
        entities_column = (
            "    COALESCE(entity_agg.entities, '') AS entities\n"
        )
    else:
        params.pop("entity_separator", None)

    cte_clause = "WITH " + ",\n".join(part.rstrip() for part in cte_parts)
    cte_clause += "\n"

    time_filters = "  AND a.publish_date > :start_date\n"
    if config.end_date:
        params["end_date"] = _format_datetime_for_sql(config.end_date)
        time_filters += "  AND a.publish_date <= :end_date\n"

    county_filter = (
        "  AND COALESCE(s.county, cl.source_county) IN ("
        + county_placeholders
        + ")\n"
    )

    query_sql = (
        f"{cte_clause}"
        "SELECT\n"
        "    a.id AS article_id,\n"
        "    COALESCE(s.host, cl.source) AS host,\n"
        "    a.publish_date,\n"
        "    COALESCE(a.author, '') AS author,\n"
        "    a.url,\n"
        "    a.title,\n"
        "    COALESCE(\n"
        "        latest_labels.primary_label,\n"
        "        a.primary_label\n"
        "    ) AS primary_label,\n"
        "    COALESCE(\n"
        "        latest_labels.alternate_label,\n"
        "        a.alternate_label\n"
        "    ) AS secondary_label,\n"
        f"{entities_column}"
        "FROM articles a\n"
        "JOIN candidate_links cl ON a.candidate_link_id = cl.id\n"
        "LEFT JOIN sources s ON cl.source_id = s.id\n"
        "LEFT JOIN latest_labels ON latest_labels.article_id = a.id\n"
        f"{entity_join}"
        "WHERE a.publish_date IS NOT NULL\n"
        f"{status_filter}"
        f"{wire_filter}"
        f"{time_filters}"
        f"{county_filter}"
        "ORDER BY a.publish_date DESC\n"
    )

    query = text(query_sql)

    db = DatabaseManager(database_url=config.database_url)
    try:
        with db.engine.connect() as conn:
            df = pd.read_sql_query(query, conn, params=params)
    finally:
        db.close()

    if df.empty:
        df = pd.DataFrame(
            columns=[
                "article_id",
                "host",
                "publish_date",
                "author",
                "url",
                "title",
                "primary_label",
                "secondary_label",
                "entities",
            ]
        )
    else:
        df["article_id"] = df["article_id"].astype(str)
        df["host"] = df["host"].astype(str)
        parsed_dates = pd.to_datetime(
            df["publish_date"],
            errors="coerce",
            utc=True,
        )
        parsed_dates = parsed_dates.dt.tz_localize(None)
        df["publish_date"] = parsed_dates.dt.strftime(
            "%Y-%m-%d %H:%M:%S"
        ).fillna("")
        df["author"] = df["author"].fillna("").astype(str)
        df["url"] = df["url"].astype(str)
        df["title"] = df["title"].fillna("")
        df["primary_label"] = df["primary_label"].fillna("")
        df["secondary_label"] = df["secondary_label"].fillna("")
        if "entities" in df.columns:
            df["entities"] = df["entities"].fillna("")

    if output_path:
        write_report_csv(
            df,
            output_path,
            logger=logger,
            log_message="Wrote county report to %s",
        )

    return df
