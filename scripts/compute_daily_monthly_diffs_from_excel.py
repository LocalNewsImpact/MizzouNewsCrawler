#!/usr/bin/env python3
import argparse
import pandas as pd
from datetime import date, timedelta

START_DATE = date(2025, 12, 1)
END_DATE = date(2026, 2, 1)  # exclusive

SCENARIO_KEYWORDS = {
    'baseline': ['baseline', 'base'],
    'error': ['error', 'errors', 'with_errors', 'wire_error'],
    'latest_fix': ['latest', 'fix', 'fixed', 'after_fix']
}


def detect_date_column(df: pd.DataFrame):
    best_col = None
    best_count = -1
    for col in df.columns:
        try:
            dt = pd.to_datetime(df[col], errors='coerce')
            count = dt.notna().sum()
            if count > best_count:
                best_col = col
                best_count = count
        except Exception:
            continue
    return best_col


def normalize_sheet(df: pd.DataFrame):
    date_col = detect_date_column(df)
    if not date_col:
        return None, {}
    df = df.copy()
    df['__day__'] = pd.to_datetime(df[date_col], errors='coerce').dt.date
    df = df.dropna(subset=['__day__'])
    df = df[(df['__day__'] >= START_DATE) & (df['__day__'] < END_DATE)]

    num_cols = [c for c in df.columns if c != '__day__' and pd.api.types.is_numeric_dtype(df[c])]
    if not num_cols:
        for c in df.columns:
            if c != '__day__' and c != date_col:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        num_cols = [c for c in df.columns if c != '__day__' and pd.api.types.is_numeric_dtype(df[c])]
    if not num_cols:
        return None, {}

    agg = df.groupby('__day__')[num_cols].sum().reset_index()

    scenario_map = {}
    for col in num_cols:
        lower = str(col).lower()
        for scenario, keys in SCENARIO_KEYWORDS.items():
            if any(k in lower for k in keys) and scenario not in scenario_map:
                scenario_map[scenario] = col
                break

    return agg, scenario_map


def build_daily(xls: pd.ExcelFile):
    daily = pd.DataFrame({'__day__': pd.date_range(START_DATE, END_DATE - timedelta(days=1))})
    daily['__day__'] = daily['__day__'].dt.date

    collected = {}

    for sheet in xls.sheet_names:
        df = xls.parse(sheet)
        agg, scenario_map = normalize_sheet(df)
        if agg is None:
            continue
        # Merge all numeric columns; we'll pick scenarios by name below
        daily = daily.merge(agg, on='__day__', how='left')
        for scenario, col in scenario_map.items():
            if col in daily.columns and scenario not in collected:
                collected[scenario] = col

    # Fallbacks: pick first numeric columns if scenarios missing
    if 'baseline' not in collected:
        num_cols = [c for c in daily.columns if c != '__day__' and pd.api.types.is_numeric_dtype(daily[c])]
        if num_cols:
            collected['baseline'] = num_cols[0]
    if 'error' not in collected:
        num_cols = [c for c in daily.columns if c != '__day__' and pd.api.types.is_numeric_dtype(daily[c])]
        if len(num_cols) > 1:
            collected['error'] = num_cols[1]
    if 'latest_fix' not in collected:
        num_cols = [c for c in daily.columns if c != '__day__' and pd.api.types.is_numeric_dtype(daily[c])]
        if len(num_cols) > 2:
            collected['latest_fix'] = num_cols[2]

    # Construct the final daily frame
    out = pd.DataFrame({'day': daily['__day__']})
    for key in ['baseline', 'error', 'latest_fix']:
        col = collected.get(key)
        out[key] = daily[col].fillna(0).astype(int) if col else 0

    out['error_minus_baseline'] = out['error'] - out['baseline']
    out['latest_minus_baseline'] = out['latest_fix'] - out['baseline']

    return out


def month_range(month_start: date, month_end_exclusive: date):
    return (month_start, month_end_exclusive)


def summarize_month(daily: pd.DataFrame, start: date, end: date):
    mask = (daily['day'] >= start) & (daily['day'] < end)
    sub = daily.loc[mask]
    sums = sub[['baseline', 'error', 'latest_fix', 'error_minus_baseline', 'latest_minus_baseline']].sum()
    return {
        'month': start.strftime('%Y-%m'),
        'baseline_total': int(sums['baseline']),
        'error_total': int(sums['error']),
        'latest_fix_total': int(sums['latest_fix']),
        'error_minus_baseline': int(sums['error_minus_baseline']),
        'latest_minus_baseline': int(sums['latest_minus_baseline']),
    }


def main():
    parser = argparse.ArgumentParser(description='Compute daily and monthly diffs from Excel')
    parser.add_argument('--file', required=True, help='Path to wire_errors.xlsx')
    parser.add_argument('--out-daily', default='data/export_daily_diffs_dec_jan.csv', help='Path to save daily CSV')
    parser.add_argument('--out-monthly', default='data/export_monthly_diffs_dec_jan.csv', help='Path to save monthly CSV')
    args = parser.parse_args()

    xls = pd.ExcelFile(args.file)
    daily = build_daily(xls)

    # Save daily
    daily.to_csv(args.out_daily, index=False)

    # Summaries for Dec and Jan
    dec_summary = summarize_month(daily, date(2025, 12, 1), date(2026, 1, 1))
    jan_summary = summarize_month(daily, date(2026, 1, 1), date(2026, 2, 1))

    monthly = pd.DataFrame([dec_summary, jan_summary])
    monthly.to_csv(args.out_monthly, index=False)

    # Print concise summary
    for row in [dec_summary, jan_summary]:
        print(f"{row['month']}: baseline={row['baseline_total']}, error={row['error_total']} (Δ={row['error_minus_baseline']}), latest_fix={row['latest_fix_total']} (Δ={row['latest_minus_baseline']})")


if __name__ == '__main__':
    main()
