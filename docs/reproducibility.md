# Reproducibility Notes

## Environment

Install the package from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

The Python dependencies are declared in `pyproject.toml`.

## Tests

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
```

## Example Runs

Filtered state-level run:

```powershell
groundwater-trends --input Results\Texas_sites.csv --state Texas --output outputs\texas-filtered
```

Unfiltered state-level run:

```powershell
groundwater-trends --input Results\Texas_sites.csv --state Texas --no-missing-filter --output outputs\texas-unfiltered
```

Basin-wide filtered run:

```powershell
groundwater-trends --input Results\Offset_Final_resampled_data_quarterly_by_site.csv --output outputs\all-filtered
```

## Output Files

Each run writes:

- `Q1.csv`, `Q2.csv`, `Q3.csv`, `Q4.csv`
- `Filtered_Q1.csv` through `Filtered_Q4.csv` when missing-data filtering is enabled
- `Post_Agre_MK.xlsx`
- `Post_Agri_LR.xlsx`
- `3_aggregated_data.csv`
- `3_Aggregated_data_Q1.csv` through `3_Aggregated_data_Q4.csv`
- `Pre_Agre_results.xlsx`
- `Pre_Agre_results_Q1.xlsx` through `Pre_Agre_results_Q4.xlsx`
- `analysis_summary.txt`

Use `--save-graphs` to also write hydrograph PNGs. Graph creation imports `matplotlib` only when requested.
