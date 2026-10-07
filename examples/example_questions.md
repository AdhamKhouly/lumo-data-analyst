# Example questions

Questions my team asked Lumo, grouped by the kind of work they need. The function Lumo
calls is noted after each one.

## Looking things up

- What was revenue in week 7? (`get_metric`)
- How many employees did we have in week 10? (`get_metric`)
- What was our cash balance at the end of week 7? (`get_financial_line_item`)
- How much did we spend on advertising in week 5? (`account_activity`)
- What were customers saying about prices in week 4? (`search_comments`)
- Which weeks are loaded? (`list_weeks`)

## Comparing weeks

- How much did revenue increase from week 3 to week 8? (`compare_metric`)
- How has customer satisfaction changed since week 1? (`compare_metric`, `metric_trend`)
- Which week had the most customers leave without being served? (`find_extreme_week`)
- Which week had our biggest jump in revenue? (`find_extreme_week`)
- Compare week 7 and week 8. (`compare_weeks`)

## Explaining

- What happened in week 6? (`week_summary`)
- Why did revenue increase last week? (`week_summary`, then `search_comments` or `search_news`)
- Was there any news about spring break? (`search_news`)
- Is revenue related to how many employees we have? (`correlations`, `fit_regression`)
- Does wait-time satisfaction drop when we are busier? (`fit_regression` with `demand_to_capacity`)

## Planning

- What seems to be our biggest bottleneck right now? (`plan_next_week`)
- What should we consider changing next week? (`plan_next_week`)
- What happens if we add 4 employees? (`evaluate_scenario`)
- What if demand rises 10% next week? (`evaluate_scenario`)
- Should we hire two more people or raise prices 5%? (`compare_scenarios`)
- How many customers should we expect next week? (`forecast_next_week`)

Follow-ups work too: ask about week 7, then "what about week 8?".
