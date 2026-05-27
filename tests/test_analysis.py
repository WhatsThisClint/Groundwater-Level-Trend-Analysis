from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from groundwater_trends.analysis import (
    AnalysisConfig,
    aggregate_normalised,
    build_analysis_data,
    classify_slope,
    drop_sparse_sites,
    filter_by_state,
    linear_regression_by_site,
    run_analysis,
    select_timeframe,
    split_by_quarter_window,
)


class AnalysisHelperTests(unittest.TestCase):
    def sample_data(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": pd.to_datetime(
                    [
                        "2020-01-15",
                        "2020-02-15",
                        "2020-04-15",
                        "2020-07-15",
                        "2020-10-15",
                    ]
                ),
                "site": ["A", "A", "A", "A", "A"],
                "level": [1.0, 2.0, 3.0, 4.0, 5.0],
                "state": ["Texas"] * 5,
            }
        )

    def test_select_timeframe_and_state(self) -> None:
        data = self.sample_data()
        selected = select_timeframe(data, "2020-12-31", 1)
        filtered = filter_by_state(selected, "texas")
        self.assertEqual(len(filtered), 5)

    def test_split_by_quarter_window(self) -> None:
        quarters = split_by_quarter_window(self.sample_data())
        self.assertEqual(len(quarters["Q1"]), 2)
        self.assertEqual(len(quarters["Q2"]), 1)
        self.assertEqual(len(quarters["Q3"]), 1)
        self.assertEqual(len(quarters["Q4"]), 1)

    def test_drop_sparse_sites_per_quarter(self) -> None:
        quarters = {
            "Q1": pd.DataFrame(
                {
                    "date": pd.to_datetime(["2020-01-01", "2020-02-01"]),
                    "site": ["A", "A"],
                    "level": [1.0, None],
                }
            ),
            "Q2": pd.DataFrame(
                {
                    "date": pd.to_datetime(["2020-04-01"]),
                    "site": ["A"],
                    "level": [3.0],
                }
            ),
        }
        filtered, dropped = drop_sparse_sites(quarters, threshold_percent=10)
        self.assertEqual(dropped["Q1"], ["A"])
        self.assertTrue(filtered["Q1"].empty)
        self.assertEqual(len(filtered["Q2"]), 1)

    def test_linear_regression_classifies_scaled_slope(self) -> None:
        data = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    ["2020-01-01", "2020-04-01", "2020-07-01", "2020-10-01"]
                ),
                "site": ["A"] * 4,
                "level": [1.0, 2.0, 3.0, 4.0],
            }
        )
        results, skipped, summary = linear_regression_by_site(
            data, slope_scale=4, slope_threshold_m=2, alpha=0.05
        )
        self.assertTrue(skipped.empty)
        self.assertEqual(results.loc[0, "trend"], "Increasing")
        self.assertEqual(summary.loc[0, "Number of Increasing Trends"], 1)
        self.assertEqual(classify_slope(-3, 2), "Decreasing")

    def test_aggregate_normalised(self) -> None:
        data = pd.DataFrame(
            {
                "date": pd.to_datetime(["2020-01-01", "2021-01-01"] * 2),
                "site": ["A", "A", "B", "B"],
                "level": [1.0, 3.0, 10.0, 12.0],
            }
        )
        aggregate = aggregate_normalised(data, "YS")
        self.assertEqual(list(aggregate["normalised_level"]), [-1.0, 1.0])


class EndToEndSmokeTest(unittest.TestCase):
    def test_run_analysis_explains_empty_missing_filter_result(self) -> None:
        data = pd.DataFrame(
            {
                "date": ["2020-01-01", "2020-02-01"],
                "site": ["A", "A"],
                "level": [None, None],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_csv = root / "input.csv"
            data.to_csv(input_csv, index=False)
            config = AnalysisConfig(
                input_csv=input_csv,
                output_dir=root / "out",
                years=1,
                write_quarter_files=False,
                write_excel=False,
                write_summary=False,
            )
            with self.assertRaisesRegex(ValueError, "--no-missing-filter"):
                run_analysis(config)

    def test_run_analysis_reports_missing_optional_dependency_cleanly(self) -> None:
        data = pd.DataFrame(
            {
                "date": ["2020-01-01", "2020-04-01"],
                "site": ["A", "A"],
                "level": [1.0, 2.0],
                "state": ["Texas", "Texas"],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_csv = root / "input.csv"
            data.to_csv(input_csv, index=False)
            config = AnalysisConfig(
                input_csv=input_csv,
                output_dir=root / "out",
                state="Texas",
                years=1,
                write_quarter_files=False,
                write_excel=False,
                write_summary=False,
            )
            try:
                run_analysis(config)
            except RuntimeError as exc:
                self.assertIn("pymannkendall is required", str(exc))


if __name__ == "__main__":
    unittest.main()
