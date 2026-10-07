# The data

These are the weekly reports from a cafe business simulation, fourteen weeks of them. Each
`Week N` folder holds the Excel workbooks the simulation produced for our cafe at the end of
that week.

The files are anonymized copies. The team names were replaced consistently (our cafe is
**Cafe A**; the other teams are Cafe B to Cafe I; two unused team slots are numbered), and
the workbook metadata was cleared. Nothing numeric was changed. The script that produced
them is `scripts/anonymize_workbooks.py`.

## Report types

| File | What it contains |
|---|---|
| `results-dashboard.xlsx` | the week's headline measures (revenue, cup sales, customer satisfaction, capacity utilization, wait-time satisfaction, ...) with the change from the previous week and our rank among the cafes; industry news and company news |
| `market-survey.xlsx` | our customer satisfaction next to the industry average; price, ambiance and service ratings out of 5; customer comments with a weight for how much each one counted |
| `market-labor.xlsx` | local average wages, turnover and minimum wage; employees per cafe |
| `results-receipts.xlsx` | one row per day: capacity, cups served, average price, receipts, customers served promptly, after a long wait, after hours, and roughly how many left; a weekly product-sales table (missing in Weeks 2 and 3) |
| `results-checkbook.xlsx` | every transaction of the week with its account and the running balance |
| `results-income_statement.xlsx` | income statement, month to date and year to date, plus per-account detail sheets |
| `results-balance_sheet.xlsx` | balance sheet at the end of the week, plus per-account detail sheets |
| `results-cash_flow.xlsx` | cash flow statement for the month to date, plus detail sheets |
| `decisions-review.xlsx` | (Week 9 only) a summary of the decisions entered for Weeks 9 and 10: purchases, staffing and pay, hours, prices, marketing |

## Things worth knowing

- The dashboard, survey, labor, receipts and checkbook figures are for that week alone.
  The three financial statements are cumulative for the month (or year) to date, so a
  week-to-week comparison of, say, "Net Income" from the income statement compares
  cumulative totals. For a week's actual spending, the checkbook is the right source.
- Percent values in the reports are stored as fractions after parsing (0.403 = 40.3%).
- The "Left or Outside Hours" column in the receipts is reported approximately ("About 50")
  and is kept with that qualifier.
- The pipeline only reads the first sheet of each financial workbook (the statement
  itself). The per-account detail sheets repeat the checkbook.
