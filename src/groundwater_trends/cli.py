"""Command-line interface for groundwater trend analysis."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

from .analysis import AnalysisConfig, run_analysis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the groundwater-level trend-analysis workflow."
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Input CSV with date, site, and level columns.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Directory for generated analysis outputs.",
    )
    parser.add_argument(
        "--state",
        help="Optional state name to filter before analysis.",
    )
    parser.add_argument(
        "--end-date",
        default="2020-12-31",
        help="Inclusive analysis end date. Defaults to 2020-12-31.",
    )
    parser.add_argument(
        "--years",
        default=20,
        type=int,
        help="Number of years before end date to include. Defaults to 20.",
    )
    parser.add_argument(
        "--resample-period",
        default="3MS",
        help="Pandas resampling frequency for composite hydrographs.",
    )
    parser.add_argument(
        "--missing-threshold",
        default=10.0,
        type=float,
        help="Drop sites with more than this percent missing data per quarter.",
    )
    parser.add_argument(
        "--no-missing-filter",
        action="store_true",
        help="Disable missing-data filtering.",
    )
    parser.add_argument(
        "--save-graphs",
        action="store_true",
        help="Write site and composite hydrograph PNG files.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce progress logging.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    config = AnalysisConfig(
        input_csv=args.input,
        output_dir=args.output,
        end_date=args.end_date,
        years=args.years,
        state=args.state,
        resample_period=args.resample_period,
        missing_threshold_percent=None
        if args.no_missing_filter
        else args.missing_threshold,
        save_graphs=args.save_graphs,
    )
    outputs = run_analysis(config)
    print(f"Analysis written to {outputs.output_dir}")
    return 0
