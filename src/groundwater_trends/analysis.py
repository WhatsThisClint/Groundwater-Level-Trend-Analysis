"""Reusable groundwater-level trend analysis workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd
from scipy.stats import linregress

LOGGER = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"date", "site", "level"}
QUARTER_MONTHS: Mapping[str, tuple[int, int, int]] = {
    "Q1": (1, 2, 3),
    "Q2": (4, 5, 6),
    "Q3": (7, 8, 9),
    "Q4": (10, 11, 12),
}


@dataclass(frozen=True)
class AnalysisConfig:
    """Configuration for one groundwater trend-analysis run."""

    input_csv: Path | str
    output_dir: Path | str | None = None
    end_date: str = "2020-12-31"
    years: int = 20
    state: str | None = None
    resample_period: str = "3MS"
    missing_threshold_percent: float | None = 10.0
    slope_threshold_m: float = 2.0
    alpha: float = 0.05
    save_graphs: bool = False
    write_quarter_files: bool = True
    write_excel: bool = True
    write_summary: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_csv", Path(self.input_csv))
        if self.output_dir is None:
            object.__setattr__(self, "output_dir", default_output_dir(self))
        else:
            object.__setattr__(self, "output_dir", Path(self.output_dir))

        if self.years <= 0:
            raise ValueError("years must be greater than zero")
        if self.missing_threshold_percent is not None and not (
            0 <= self.missing_threshold_percent <= 100
        ):
            raise ValueError("missing_threshold_percent must be between 0 and 100")
        if not 0 < self.alpha < 1:
            raise ValueError("alpha must be between 0 and 1")

    @property
    def slope_scale(self) -> int:
        """Scale one-observation slopes to meters over the analysis window."""

        return self.years * 4


@dataclass(frozen=True)
class AnalysisOutputs:
    """Paths written by an analysis run."""

    output_dir: Path
    quarter_files: dict[str, Path] = field(default_factory=dict)
    filtered_quarter_files: dict[str, Path] = field(default_factory=dict)
    aggregate_files: dict[str, Path] = field(default_factory=dict)
    pre_aggregation_files: dict[str, Path] = field(default_factory=dict)
    post_aggregation_mk: Path | None = None
    post_aggregation_lr: Path | None = None
    summary: Path | None = None


def default_output_dir(config: AnalysisConfig) -> Path:
    threshold = (
        f"{config.missing_threshold_percent:g}%"
        if config.missing_threshold_percent is not None
        else "NoMissingFilter"
    )
    state = config.state if config.state else "NAState"
    filter_label = (
        "Filtered" if config.missing_threshold_percent is not None else "Unfiltered"
    )
    return Path(f"{threshold}_{config.resample_period}_{state}_{filter_label}")


def load_groundwater_data(csv_path: Path | str) -> pd.DataFrame:
    """Load and validate a groundwater observations CSV."""

    path = Path(csv_path)
    data = pd.read_csv(path)
    missing = REQUIRED_COLUMNS.difference(data.columns)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"{path} is missing required columns: {missing_list}")

    data = data.copy()
    data["date"] = pd.to_datetime(
        data["date"], errors="coerce", dayfirst=True, format="mixed"
    )
    data["site"] = data["site"].astype(str)
    data["level"] = pd.to_numeric(data["level"], errors="coerce")
    return data


def select_timeframe(
    data: pd.DataFrame, end_date: str | pd.Timestamp, years: int
) -> pd.DataFrame:
    """Return observations in the inclusive analysis window."""

    end = pd.to_datetime(end_date)
    start = end - pd.DateOffset(years=years)
    mask = data["date"].notna() & data["date"].between(start, end, inclusive="both")
    return data.loc[mask].copy()


def filter_by_state(data: pd.DataFrame, state: str | None) -> pd.DataFrame:
    """Filter rows by state name when requested."""

    if not state:
        return data.copy()
    if "state" not in data.columns:
        raise ValueError("state filtering was requested, but no state column exists")
    mask = data["state"].astype(str).str.casefold() == state.casefold()
    return data.loc[mask].copy()


def split_by_quarter_window(data: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split observations into calendar-quarter month groups."""

    return {
        label: data.loc[data["date"].dt.month.isin(months)].copy()
        for label, months in QUARTER_MONTHS.items()
    }


def drop_sparse_sites(
    quarter_data: Mapping[str, pd.DataFrame], threshold_percent: float
) -> tuple[dict[str, pd.DataFrame], dict[str, list[str]]]:
    """Drop sites that exceed the missing-level threshold within each quarter."""

    filtered: dict[str, pd.DataFrame] = {}
    dropped: dict[str, list[str]] = {}

    for label, data in quarter_data.items():
        if data.empty:
            filtered[label] = data.copy()
            dropped[label] = []
            continue

        missing_percent = data.groupby("site")["level"].apply(
            lambda values: values.isna().mean() * 100
        )
        sites_to_drop = (
            missing_percent.loc[missing_percent > threshold_percent]
            .index.astype(str)
            .tolist()
        )
        dropped[label] = sites_to_drop
        filtered[label] = data.loc[~data["site"].isin(sites_to_drop)].copy()

    return filtered, dropped


def build_analysis_data(quarter_data: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Merge quarter data into the site-level analysis dataset."""

    if not quarter_data:
        raise ValueError("No quarter data was supplied")
    analysis_data = pd.concat(quarter_data.values(), ignore_index=True)
    analysis_data = analysis_data.dropna(subset=["date", "site", "level"]).copy()
    analysis_data = analysis_data.sort_values(["site", "date"]).reset_index(drop=True)
    if analysis_data.empty:
        raise ValueError("No usable observations remain after filtering")
    return analysis_data


def mann_kendall_by_site(
    analysis_data: pd.DataFrame, alpha: float, slope_scale: float
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the Mann-Kendall test for each site."""

    mk = _import_mannkendall()
    rows: list[dict[str, object]] = []
    skipped_sites: list[str] = []

    for site, site_data in analysis_data.groupby("site", sort=True):
        values = site_data["level"].dropna()
        if len(values) < 2 or values.nunique() <= 1:
            skipped_sites.append(site)
            continue

        result = mk.original_test(values.to_numpy(), alpha=alpha)
        rows.append(
            {
                "site": site,
                "data_type": "level",
                "trend": result.trend,
                "h": result.h,
                "p": result.p,
                "z": result.z,
                "Tau": result.Tau,
                "s": result.s,
                "var_s": result.var_s,
                "slope": result.slope,
                "intercept": result.intercept,
                "slope m/20y": result.slope * slope_scale,
            }
        )

    result_df = pd.DataFrame(
        rows,
        columns=[
            "site",
            "data_type",
            "trend",
            "h",
            "p",
            "z",
            "Tau",
            "s",
            "var_s",
            "slope",
            "intercept",
            "slope m/20y",
        ],
    )
    skipped_df = pd.DataFrame({"Skipped Sites": skipped_sites})
    summary_df = trend_summary(
        result_df["trend"] if not result_df.empty else pd.Series(dtype=str),
        increasing_label="increasing",
        decreasing_label="decreasing",
        no_trend_label="no trend",
    )
    return result_df, skipped_df, summary_df


def linear_regression_by_site(
    analysis_data: pd.DataFrame,
    slope_scale: float,
    slope_threshold_m: float,
    alpha: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run linear regression for each site."""

    rows: list[dict[str, object]] = []
    skipped_sites: list[str] = []

    for site, site_data in analysis_data.groupby("site", sort=True):
        site_data = site_data.sort_values("date")
        values = site_data["level"].dropna()
        if len(values) < 2 or values.nunique() <= 1:
            skipped_sites.append(site)
            continue

        x = np.arange(len(values), dtype=float)
        slope, intercept, _r_value, p_value, _std_err = linregress(x, values)
        slope_window = slope * slope_scale
        rows.append(
            {
                "site": site,
                "data_type": "level",
                "slope": slope,
                "intercept": intercept,
                "trend": classify_slope(slope_window, slope_threshold_m),
                "slope m/20y": slope_window,
                "p-value": p_value,
                "significance": "Significant" if p_value < alpha else "Insignificant",
            }
        )

    result_df = pd.DataFrame(
        rows,
        columns=[
            "site",
            "data_type",
            "slope",
            "intercept",
            "trend",
            "slope m/20y",
            "p-value",
            "significance",
        ],
    )
    skipped_df = pd.DataFrame({"Skipped Sites": skipped_sites})
    summary_df = trend_summary(
        result_df["trend"] if not result_df.empty else pd.Series(dtype=str),
        increasing_label="Increasing",
        decreasing_label="Decreasing",
        no_trend_label="No trend",
    )
    return result_df, skipped_df, summary_df


def classify_slope(slope_m: float, threshold_m: float) -> str:
    """Classify a window-scaled slope using the thesis threshold."""

    if slope_m > threshold_m:
        return "Increasing"
    if slope_m < -threshold_m:
        return "Decreasing"
    return "No trend"


def trend_summary(
    trends: pd.Series,
    increasing_label: str,
    decreasing_label: str,
    no_trend_label: str,
) -> pd.DataFrame:
    """Summarize trend counts and percentages."""

    total = int(len(trends))
    num_increasing = int((trends == increasing_label).sum())
    num_decreasing = int((trends == decreasing_label).sum())
    num_no_trend = int((trends == no_trend_label).sum())

    def pct(count: int) -> float:
        return (count / total) * 100 if total else 0.0

    return pd.DataFrame(
        {
            "Number of Increasing Trends": [num_increasing],
            "Number of Decreasing Trends": [num_decreasing],
            "Number of No Trends": [num_no_trend],
            "Percentage of Increasing Trends": [pct(num_increasing)],
            "Percentage of Decreasing Trends": [pct(num_decreasing)],
            "Percentage of No Trends": [pct(num_no_trend)],
        }
    )


def aggregate_normalised(data: pd.DataFrame, resample_period: str) -> pd.DataFrame:
    """Normalize levels by site mean and resample a composite hydrograph."""

    work = data.dropna(subset=["date", "site", "level"]).copy()
    if work.empty:
        return pd.DataFrame(columns=["date", "normalised_level"])

    work["date"] = pd.to_datetime(work["date"])
    work = work.set_index("date").sort_index()
    work["normalised_level"] = work["level"] - work.groupby("site")[
        "level"
    ].transform("mean")
    return work["normalised_level"].resample(resample_period).mean().reset_index()


def pre_aggregation_trend(
    aggregated_data: pd.DataFrame, alpha: float, slope_scale: float
) -> pd.DataFrame:
    """Run trend tests on the normalized composite hydrograph."""

    mk = _import_mannkendall()
    clean = aggregated_data.dropna(subset=["date", "normalised_level"]).copy()
    if len(clean) < 2 or clean["normalised_level"].nunique() <= 1:
        return pd.DataFrame(
            [
                {
                    "trend": "insufficient data",
                    "h": False,
                    "p": np.nan,
                    "z": np.nan,
                    "Tau": np.nan,
                    "s": np.nan,
                    "var_s": np.nan,
                    "sens_slope": np.nan,
                    "sens_intercept": np.nan,
                    "slope LR m/20y": np.nan,
                    "slope MK m/20y": np.nan,
                    "p-value LR": np.nan,
                    "Trend Significance": "Not Significant",
                }
            ]
        )

    y = clean["normalised_level"].to_numpy(dtype=float)
    x = np.linspace(0, 1, len(y))
    finite = np.isfinite(x) & np.isfinite(y)
    slope, _intercept, _r_value, p_value, _std_err = linregress(x[finite], y[finite])
    mk_result = mk.original_test(y[finite], alpha=alpha)

    return pd.DataFrame(
        [
            {
                "trend": mk_result.trend,
                "h": mk_result.h,
                "p": mk_result.p,
                "z": mk_result.z,
                "Tau": mk_result.Tau,
                "s": mk_result.s,
                "var_s": mk_result.var_s,
                "sens_slope": mk_result.slope,
                "sens_intercept": mk_result.intercept,
                "slope LR m/20y": slope,
                "slope MK m/20y": mk_result.slope * slope_scale,
                "p-value LR": p_value,
                "Trend Significance": "Significant"
                if p_value < alpha
                else "Not Significant",
            }
        ]
    )


def run_analysis(config: AnalysisConfig) -> AnalysisOutputs:
    """Run one complete groundwater trend analysis."""

    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    LOGGER.info("Loading %s", config.input_csv)
    raw_data = load_groundwater_data(config.input_csv)
    selected_data = select_timeframe(raw_data, config.end_date, config.years)
    selected_data = filter_by_state(selected_data, config.state)
    if selected_data.empty:
        raise ValueError("No observations match the requested time/state filters")

    quarters = split_by_quarter_window(selected_data)
    quarter_files = _write_quarter_csvs(output_dir, quarters) if config.write_quarter_files else {}

    filtered_quarter_files: dict[str, Path] = {}
    dropped_sites: dict[str, list[str]] = {}
    if config.missing_threshold_percent is not None:
        analysis_quarters, dropped_sites = drop_sparse_sites(
            quarters, config.missing_threshold_percent
        )
        filtered_quarter_files = (
            _write_quarter_csvs(output_dir, analysis_quarters, prefix="Filtered_")
            if config.write_quarter_files
            else {}
        )
    else:
        analysis_quarters = quarters

    try:
        analysis_data = build_analysis_data(analysis_quarters)
    except ValueError as exc:
        if config.missing_threshold_percent is not None:
            raise ValueError(
                "No usable observations remain after missing-data filtering. "
                "Try --no-missing-filter or increase --missing-threshold."
            ) from exc
        raise

    mk_df, mk_skipped_df, mk_summary_df = mann_kendall_by_site(
        analysis_data, config.alpha, config.slope_scale
    )
    lr_df, lr_skipped_df, lr_summary_df = linear_regression_by_site(
        analysis_data,
        config.slope_scale,
        config.slope_threshold_m,
        config.alpha,
    )

    post_mk_path = output_dir / "Post_Agre_MK.xlsx"
    post_lr_path = output_dir / "Post_Agri_LR.xlsx"
    if config.write_excel:
        _write_excel(
            post_mk_path,
            {
                "Mann-Kendall Results": mk_df,
                "Skipped Sites": mk_skipped_df,
                "Trend Percentages": mk_summary_df,
            },
        )
        _write_excel(
            post_lr_path,
            {
                "Linear Regression Results": lr_df,
                "Skipped Sites": lr_skipped_df,
                "Trend Percentages": lr_summary_df,
            },
        )

    aggregate_files: dict[str, Path] = {}
    pre_aggregation_files: dict[str, Path] = {}
    aggregate_sources: dict[str, pd.DataFrame] = {"All_Q": analysis_data}
    aggregate_sources.update(analysis_quarters)

    for label, source in aggregate_sources.items():
        aggregate = aggregate_normalised(source, config.resample_period)
        aggregate_path = output_dir / _aggregate_filename(label)
        aggregate.to_csv(aggregate_path, index=False)
        aggregate_files[label] = aggregate_path

        trend = pre_aggregation_trend(aggregate, config.alpha, config.slope_scale)
        trend_path = output_dir / _pre_aggregation_filename(label)
        if config.write_excel:
            trend.to_excel(trend_path, index=False)
            pre_aggregation_files[label] = trend_path

        if config.save_graphs:
            _plot_aggregate(output_dir, label, aggregate, trend)

    if config.save_graphs:
        _plot_site_hydrographs(output_dir, analysis_data, lr_df)

    summary_path = output_dir / "analysis_summary.txt"
    if config.write_summary:
        summary_path.write_text(
            _build_summary(config, raw_data, selected_data, analysis_data, dropped_sites),
            encoding="utf-8",
        )

    return AnalysisOutputs(
        output_dir=output_dir,
        quarter_files=quarter_files,
        filtered_quarter_files=filtered_quarter_files,
        aggregate_files=aggregate_files,
        pre_aggregation_files=pre_aggregation_files,
        post_aggregation_mk=post_mk_path if config.write_excel else None,
        post_aggregation_lr=post_lr_path if config.write_excel else None,
        summary=summary_path if config.write_summary else None,
    )


def _write_quarter_csvs(
    output_dir: Path, quarters: Mapping[str, pd.DataFrame], prefix: str = ""
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for label, data in quarters.items():
        path = output_dir / f"{prefix}{label}.csv"
        data.to_csv(path, index=False)
        paths[label] = path
    return paths


def _write_excel(path: Path, sheets: Mapping[str, pd.DataFrame]) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, data in sheets.items():
            data.to_excel(writer, sheet_name=sheet_name[:31], index=False)


def _aggregate_filename(label: str) -> str:
    if label == "All_Q":
        return "3_aggregated_data.csv"
    return f"3_Aggregated_data_{label}.csv"


def _pre_aggregation_filename(label: str) -> str:
    if label == "All_Q":
        return "Pre_Agre_results.xlsx"
    return f"Pre_Agre_results_{label}.xlsx"


def _build_summary(
    config: AnalysisConfig,
    raw_data: pd.DataFrame,
    selected_data: pd.DataFrame,
    analysis_data: pd.DataFrame,
    dropped_sites: Mapping[str, list[str]],
) -> str:
    end = pd.to_datetime(config.end_date)
    start = end - pd.DateOffset(years=config.years)
    dropped_counts = {
        quarter: len(sites) for quarter, sites in dropped_sites.items() if sites
    }
    lines = [
        f"Analysis Date and Time: {datetime.now().isoformat(timespec='seconds')}",
        f"Input CSV: {config.input_csv}",
        f"Start Date: {start.date()}",
        f"End Date: {end.date()}",
        f"Number of years: {config.years}",
        f"Resampling Period: {config.resample_period}",
        f"Filter by State: {config.state if config.state else 'Not Applied'}",
        "Data Filtering: "
        + (
            f"Sites having > {config.missing_threshold_percent:g}% missing data removed"
            if config.missing_threshold_percent is not None
            else "Not Applied"
        ),
        f"Input rows: {len(raw_data)}",
        f"Rows after time/state filters: {len(selected_data)}",
        f"Rows analyzed: {len(analysis_data)}",
        f"Sites analyzed: {analysis_data['site'].nunique()}",
        f"Sites dropped by quarter: {dropped_counts if dropped_counts else 'None'}",
    ]
    return "\n".join(lines) + "\n"


def _plot_aggregate(
    output_dir: Path, label: str, aggregate: pd.DataFrame, trend: pd.DataFrame
) -> None:
    plt, mdates = _import_plotting()
    clean = aggregate.dropna(subset=["date", "normalised_level"])
    if clean.empty:
        return

    fig, ax = plt.subplots(figsize=(16, 7))
    ax.plot(
        clean["date"],
        clean["normalised_level"],
        color="black",
        marker="o",
        markersize=4,
        label="Composite Hydrograph",
    )
    if not trend.empty and pd.notna(trend.loc[0, "slope LR m/20y"]):
        x = np.linspace(0, 1, len(clean))
        y = clean["normalised_level"].to_numpy(dtype=float)
        slope, intercept, *_ = linregress(x, y)
        ax.plot(
            clean["date"],
            x * slope + intercept,
            color="black",
            linestyle="dashed",
            label=f"Linear trend ({trend.loc[0, 'Trend Significance']})",
        )

    ax.set_xlabel("Date")
    ax.set_ylabel("Normalized groundwater level [m]")
    ax.set_title(f"Composite Hydrograph - {label}")
    ax.grid(True, alpha=0.35)
    ax.legend()
    ax.xaxis.set_major_locator(mdates.YearLocator())
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_dir / f"Pre_aggre_{label}.png", bbox_inches="tight")
    plt.close(fig)


def _plot_site_hydrographs(
    output_dir: Path, analysis_data: pd.DataFrame, regression_results: pd.DataFrame
) -> None:
    plt, mdates = _import_plotting()
    graphs_dir = output_dir / "graphs"
    graphs_dir.mkdir(exist_ok=True)

    for site, site_data in analysis_data.groupby("site", sort=True):
        site_data = site_data.sort_values("date")
        if len(site_data) < 2:
            continue

        trend_row = regression_results.loc[regression_results["site"] == site]
        if trend_row.empty:
            continue

        x_dates = site_data["date"]
        y = site_data["level"]
        x = mdates.date2num(x_dates)
        slope, intercept, *_ = linregress(x, y)

        fig, ax = plt.subplots(figsize=(16, 7))
        ax.plot(x_dates, y, color="black", marker="o", markersize=4, label="Hydrograph")
        ax.plot(
            x_dates,
            slope * x + intercept,
            color="black",
            linestyle="dashed",
            label=(
                "Regression Line "
                f"({trend_row.iloc[0]['slope m/20y']:.2f} m/20y, "
                f"{trend_row.iloc[0]['significance']})"
            ),
        )
        ax.set_xlabel("Date")
        ax.set_ylabel("Groundwater Level [m]")
        ax.set_title(f"Composite Hydrograph for {site}")
        ax.grid(True, alpha=0.35)
        ax.legend()
        ax.xaxis.set_major_locator(mdates.YearLocator())
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(graphs_dir / f"Site_{site}.png", bbox_inches="tight")
        plt.close(fig)


def _import_mannkendall():
    try:
        import pymannkendall as mk
    except ImportError as exc:
        raise RuntimeError(
            "pymannkendall is required for Mann-Kendall trend tests. "
            "Install dependencies with `python -m pip install -e .`."
        ) from exc
    return mk


def _import_plotting():
    try:
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            "matplotlib is required when save_graphs=True. "
            "Install dependencies with `python -m pip install -e .`."
        ) from exc
    return plt, mdates
