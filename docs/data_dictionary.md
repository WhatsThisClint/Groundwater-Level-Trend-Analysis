# Data Dictionary

The main analysis expects a CSV with the following required columns.

| Column | Type | Description |
| --- | --- | --- |
| `date` | date-like string | Observation date. Mixed formats are accepted and parsed with day-first preference. |
| `site` | string | Monitoring-well identifier. |
| `level` | numeric | Groundwater level measurement in meters. Negative values indicate depth or decline according to the thesis convention. |

Optional columns are preserved when present.

| Column | Description |
| --- | --- |
| `lat` | Well latitude. |
| `long` | Well longitude. |
| `elevation` | Well or ground elevation metadata. |
| `aquifer` | Aquifer name. |
| `state` | State name used by `--state` filtering. |
| `county` | County name. |

## Bundled Input Files

The root `Results/` directory includes ready-to-run thesis inputs:

- `1HPFormatted.csv`
- `Offset_Final_resampled_data_quarterly_by_site.csv`
- `Texas_sites.csv`
- `Colorado_sites.csv`
- `Kansas_sites.csv`
- `Nebraska_sites.csv`
- `New_Mexico_sites.csv`
- `Oklahoma_sites.csv`
- `South_Dakota_sites.csv`
