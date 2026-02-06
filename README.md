
# Niagara-Style Daily Production Planning & MRP Control Tower (6+ Lines)

**Goal (JD-aligned):** Create and execute daily production plans, maintain planning parameters, monitor/adjust forecasts, ensure MRP drives accurate material needs, and enforce inventory policy adherence — while coordinating across Manufacturing, Purchasing, Sales/CS, and Transportation.

## What this repo produces (deliverables)
- `results/daily_production_schedule.csv` — **daily re-plan** schedule (line × SKU) with capacity/eligibility flags
- `results/plan_by_sku_day.csv` — short-horizon production plan by SKU/day (input to MRP explode)
- `results/mrp_requirements.csv` — materials requirements by date (MRP explode output)
- `results/mrp_exception_report.csv` — material shortages + ETA + suggested actions (for Purchasing/Ops)
- `results/inventory_policy_adherence.csv` — DOS / Min-Target-Max / recommended production quantities (policy adherence)
- `results/forecast_override_log.csv` — example override log (audit trail)
- `results/charts/line_load.png`, `results/charts/otif_risk.png`

## How to run
From repo root:
```bash
python -m pip install -r requirements.txt
python src/01_generate_mock_data.py --out_dir data
python src/03_daily_scheduler.py --data_dir data --results_dir results
python src/02_mrp_explode.py --data_dir data --results_dir results
python src/04_reports_and_charts.py --data_dir data --results_dir results
```

## Niagara-style operating cadence (how you talk about it in interview)
**Daily re-plan loop**
1. **Customer Service / Sales**: order adds/changes + priority updates
2. **Planning**: run daily re-plan → publish schedule + exception list
3. **Purchasing**: act on `mrp_exception_report.csv` (expedite/substitute)
4. **Manufacturing/Ops**: execute schedule; escalate constraints; update downtime/rates
5. **Transportation**: verify ship windows / load capacity; align on cutoffs

## Notes
This is a heuristic scheduler intended for a portfolio project. In a production system, you would add:
- frozen window rules, WIP, labor/crew constraints
- multi-day sequencing, maintenance windows, and richer changeover families
- transportation load building (palletization, full truck vs LTL)
