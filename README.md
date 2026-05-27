# Groundwater Level Trend Analysis

This repository contains the code, data, and generated outputs from a master's thesis on groundwater-level trends in the High Plains Aquifer region.

The original notebooks are preserved in `Codes/` for traceability. A reproducible Python package and command-line workflow now live in `src/groundwater_trends/` so the analysis can be rerun without copying and editing long notebook cells.

## What Is Included

- `Codes/`: original exploratory notebooks and archived data-preparation notebooks.
- `Results/`: thesis input datasets and generated result folders.
- `src/groundwater_trends/`: reusable analysis code and CLI.
- `tests/`: regression tests for the refactored analysis helpers.
- `docs/`: data schema and reproducibility notes.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

Run a filtered Texas analysis:

```powershell
groundwater-trends --input Results\Texas_sites.csv --state Texas --output outputs\texas-filtered
```

Run the basin-wide analysis without missing-data filtering:

```powershell
groundwater-trends --input Results\Offset_Final_resampled_data_quarterly_by_site.csv --no-missing-filter --output outputs\all-unfiltered
```

## Method Summary

The refactored workflow follows the thesis notebook logic:

1. Load groundwater observations with `date`, `site`, and `level` columns.
2. Select the configured analysis period ending at `2020-12-31` by default.
3. Optionally filter observations to one state.
4. Split observations into quarterly month groups.
5. Optionally remove sites that exceed the missing-data threshold within each quarter.
6. Run post-aggregation Mann-Kendall and linear-regression trend tests by site.
7. Normalize each site's level series by its site mean, resample the composite hydrograph, and run pre-aggregation trend tests.
8. Write CSV, Excel, and summary outputs to the requested output directory.

## Testing

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
```

The tests use small synthetic datasets so they run quickly and do not depend on the large thesis data files.

## Notes

- The checked-in `Results/` folders are retained as thesis artifacts.
- New generated runs should go to `outputs/`, which is ignored by Git.
- Notebook checkpoint folders and execution outputs are excluded so future diffs stay reviewable.
