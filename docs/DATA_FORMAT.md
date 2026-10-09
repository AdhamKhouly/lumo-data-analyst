# Data format

What Lumo reads, what it looks for in each workbook, and where every value ends up. The
short version is in the [README](../README.md#what-the-excel-files-look-like); this page
is the detail.

## 1. Folder layout and discovery

```text
data/
├── Week 1/
│   ├── results-dashboard.xlsx
│   ├── results-income_statement.xlsx
│   ├── results-balance_sheet.xlsx
│   ├── results-cash_flow.xlsx
│   ├── results-receipts.xlsx
│   ├── results-checkbook.xlsx
│   ├── market-survey.xlsx
│   └── market-labor.xlsx
├── Week 2/ ... Week 14/
└── Week 9/
    └── decisions-review.xlsx      (plus the usual eight)
```

- **Week folders.** `src/ingest.py` treats any folder whose name matches `Week N`
  (case-insensitive, extra spaces allowed) as a week. The number comes from the folder
  name, not from inside the files. Folders are sorted numerically.
- **Report files.** Each `.xlsx` inside a week folder is matched against the file-name
  patterns in `REPORT_TYPES` (`src/parsers.py`). The pattern only needs to appear in the
  stem, so `results-dashboard.xlsx` and `results-dashboard (1).xlsx` both count as a
  dashboard. Files that match nothing are counted as "unsupported" and skipped; Excel lock
  files (`~$...`) are ignored.
- **Provenance key.** A file is identified as `"Week 7/results-dashboard.xlsx"`. Every row
  it produces stores that string as `source_file`, plus the sheet name and cell.
- **Title check.** Most reports have a title line like `Cafe A - Week 7` in the first few
  rows. The parser reads the company name from it and warns if the week there disagrees
  with the folder name. The file is still loaded.
- **Incremental loading.** Each file's SHA-256 hash is stored in the `files` table. On the
  next run, unchanged files are skipped, a changed file replaces all of its previous rows,
  and a file that no longer exists on disk has its rows removed. `--force` re-parses
  everything.

## 2. How the parsers read a sheet

`src/parsers.py` loads each worksheet into a `Grid`: a dictionary of the non-empty cells
with their values and Excel number formats. Parsers then use three operations:

| Operation | What it does | Example |
|---|---|---|
| `find(label)` | first cell whose text equals the label (case-insensitive) | `find("Weekly Totals")` |
| `find_header_row([labels])` | first row that contains all the labels; returns the row and a label-to-column map | `find_header_row(["Measure", "Value"])` |
| `table_rows(start)` | the rows from `start` down to the first fully blank row | the body of a table |

Nothing is addressed by a fixed cell. If a table moves down a few rows, or a column is
added to the right, the parser still finds it. What a parser cannot survive is the label
text changing, the table losing its blank separator row, or the file being renamed to
something `REPORT_TYPES` does not recognize.

## 3. The reports

Each report lists the labels the parser anchors on and the table(s) its rows go to.

### `results-dashboard.xlsx` → `dashboard`

```text
Dashboard
Cafe A - Week 3

Measure                  Value     Change   Rank
Revenue                  $13,048   23.7%    5
...
Industry News
<one line per item>

Company News
<one line per item>
```

- Anchors: header row with `Measure` and `Value` (`Change` and `Rank` optional); the cells
  `Industry News` and `Company News`.
- `metrics` rows: section `Measures`, one per measure, with `rank` and `change_reported`.
- `text_records` rows: sections `Industry News` and `Company News`, one per line.

### `market-survey.xlsx` → `survey`

- Anchors: header rows `Company` + `Satisfaction`, `Survey Category` + `Rating`,
  `Comments/Suggestions` + `Weight`.
- `metrics` rows: section `Company Satisfaction` (one row per company, including
  `Industry Average`), section `Survey Category Ratings` (`Price Rating`, `Ambiance Rating`,
  `Service Rating`, unit `rating`, scale 5).
- `survey_comments` rows: one per comment with its weight.
- The first company row names the reporting cafe; this is where `company` comes from when a
  report has no title line.

### `market-labor.xlsx` → `labor`

- Anchors: header rows `Measure` + `Local Average`, `Company` + `Employees`.
- `metrics` rows: section `Local Labor Market` (`Avg. Server Wages`, `Avg. Manager Wages`,
  `Avg. Turnover Rate`, `Minimum Wage`, with their periods, e.g. "per week"), and section
  `Employees by Company` (one row per cafe, `company` set). Unused team slots in the
  simulation are numbered rather than named and are kept as text.

### `results-receipts.xlsx` → `receipts`

- Anchors: header row with `Date`, `Day`, `Cups Served`, `Receipts` (plus
  `Daily Capacity`, `Avg. Price`, `Satisfied`, `Long Wait`, `Served After Hours`,
  `Left or Outside Hours` when present); the cell `Weekly Totals` for the product table.
- `daily_receipts` rows: one per day plus the `Total` row (`is_total = true`).
  `Left or Outside Hours` is reported as "About 442"; the number is stored with the
  original text alongside.
- `metrics` rows: section `Weekly Traffic Totals` from the Total row (`Cups Served`,
  `Daily Capacity`, `Long Wait`, `Left or Outside Hours`, `Avg. Price`, ...), and section
  `Product Sales` from the weekly product table (`Small Coffee Units`,
  `Small Coffee Unit Price`, `Small Coffee Receipts`, ..., `Total Receipts`).
- Weeks 2 and 3 have no product table. Ingestion prints a warning and loads the rest.

### `results-checkbook.xlsx` → `checkbook`

- Anchors: header row with `Date`, `Description`, `Account`, `Balance` (plus `Payment`,
  `Deposit`).
- `transactions` rows: one per line of the checkbook.
- `metrics` rows: section `Checkbook Balance` (`Beginning Balance`, `Ending Balance`) and
  section `Checkbook Account Totals`, which the parser derives by summing payments and
  deposits per account (`Adv./Promo. Payments`, `Staff Payments`, `COGS Payments`, ...).
  Derived rows have a `cell` of `derived:<account>` rather than a real cell.

### `results-income_statement.xlsx`, `results-balance_sheet.xlsx`, `results-cash_flow.xlsx` → `income_statement`, `balance_sheet`, `cash_flow`

- Only the first sheet is read. The remaining sheets are per-account transaction listings
  that duplicate the checkbook.
- Anchors: a period label in the first rows (`January, Month to Date`, `End of Month`,
  `Year to Date`); for the income statement, a header row containing `% of Rev.`, which
  separates the month-to-date and year-to-date value columns.
- Every row whose first cell is text and whose value cell holds a number becomes a
  `metrics` row. A text row with no amount next to it (`Assets`, `Liabilities`) starts a
  new section. Each row records `period` (`month_to_date` or `year_to_date`) and
  `period_label`.
- These values are **cumulative for the period**, not amounts for the week. The analytics
  functions say so in their results; for a week's actual spending, use the checkbook.

### `decisions-review.xlsx` → `decisions`

- Anchor: a row with `Week N` column headers.
- `decisions` rows: one per label and week column, with label-only rows acting as section
  headers (purchases, staffing, prices, marketing). Present for Week 9 only in this dataset.

## 4. Value cleaning

`src/values.py` turns each cell into a number with a unit, never raising on unreadable
input. The number format of native Excel numbers (`$#,##0`, `0.0%`) supplies the unit.

| In the cell | `value_numeric` | `unit` | extra |
|---|---|---|---|
| `$5,687` | 5687.0 | USD | |
| `($3,832)` | -3832.0 | USD | accounting negative |
| `40.3%` or a cell formatted `0.0%` | 0.403 | percent | stored as a fraction of 1 |
| `1,129` | 1129.0 | count | |
| `3 out of 5` | 3.0 | rating | `scale` 5 |
| `$931.25 / week` | 931.25 | USD | `period` "per week" |
| `About 50` | 50.0 | count | `qualifier` "about" |
| `n/a` | null | | `qualifier` "n/a" |
| anything else | null | | kept in `value_text` |

`format_value()` reverses this for display (`0.403` → `40.3%`), which is what the
`display` fields in function results use.

## 5. The DuckDB tables

Defined in `SCHEMA` in `src/database.py`. The database file is `lumo.duckdb` in the project
folder (`--db` on the command line, or the `LUMO_DB_PATH` environment variable).

| Table | One row per | Key columns |
|---|---|---|
| `files` | ingested workbook | `source_file`, `week`, `report_type`, `company`, `file_hash`, `ingested_at` |
| `metrics` | numeric fact | `week`, `report_type`, `section`, `company`, `metric`, `value_numeric`, `value_text`, `unit`, `scale`, `qualifier`, `rank`, `change_reported`, `period`, `period_label`, `line_order`, `source_file`, `sheet_name`, `cell` |
| `survey_comments` | customer comment | `week`, `comment`, `weight`, `comment_order` |
| `text_records` | news line | `week`, `report_type`, `section`, `text`, `text_order` |
| `transactions` | checkbook line | `week`, `txn_order`, `date_text`, `description`, `account`, `payment`, `deposit`, `balance` |
| `daily_receipts` | day of receipts (plus the total row) | `week`, `date_text`, `day`, `daily_capacity`, `cups_served`, `avg_price`, `receipts`, `satisfied`, `long_wait`, `served_after_hours`, `left_or_outside`, `is_total` |
| `decisions` | decision item and week | `week`, `decision_week`, `section`, `item`, `value_text`, `value_numeric` |

Every table also carries `source_file`, `sheet_name` and `cell`. For the 14 included weeks
this is 113 files, 1,533 metric rows, 210 comments and 212 transactions.

## 6. How names are resolved

Stored metric names are the labels as they appear in the reports (`Revenue`,
`Customer Satisfaction`, `Left or Outside Hours`). Two lookup layers sit on top:

- `KNOWN_METRICS` in `src/analytics.py` maps everyday names to a stored metric, report and
  section: `sales` → dashboard `Revenue`; `lost customers` → receipts
  `Left or Outside Hours`; `csat` → dashboard `Customer Satisfaction`. A name that is not an
  alias still works if it matches a stored metric name exactly; otherwise the function
  returns `not_found` with close suggestions.
- `VARIABLES` in `src/modeling.py` picks the metrics that become columns of the weekly
  table (`revenue`, `cups_served`, `employees`, `advertising_spend`, ...) and `DERIVED`
  adds a few computed ones (`demand`, `demand_to_capacity`, `lost_share`, `payroll`).

## 7. Adapting Lumo to a different set of reports

1. **Name the report type.** Add a `"<file-name pattern>": ("<type>", parse_fn)` entry to
   `REPORT_TYPES` in `src/parsers.py`.
2. **Write the parser.** A function `parse_fn(grids, report)` that finds its header labels
   with `find_header_row` / `find`, walks `table_rows`, and calls `report.add_metric(...)`,
   `report.add_text(...)`, or appends to `report.comments` / `report.transactions`. Add a
   warning to `report.warnings` when an expected table is missing rather than raising.
3. **Add aliases.** Put the names people will use in `KNOWN_METRICS` (`src/analytics.py`).
4. **Expose variables to the models.** Add the metrics that should be analyzable over time
   to `VARIABLES` in `src/modeling.py`. `planning.py` expects some specific ones
   (employees, capacity, demand, revenue, price, margin); if your data does not have them,
   the scenario functions will say which are missing.
5. **Tell the model what it is looking at.** Edit `SYSTEM_PROMPT` in `src/agent.py`.
6. **Test it.** `tests/test_parsers.py` shows how a parser is tested against a real file.

Everything from the database down (storage, queries, comparisons, trends, modeling, chat,
Discord) is unchanged by this. What the project does not do is understand a workbook it has
never seen: there is no automatic table detection and no model-assisted extraction, so a
substantially different format means a new parser.
