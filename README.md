# Niagara-Style Daily Production Planning & MRP (Portfolio)

This portfolio project simulates a **bottled water plant** planning workflow aligned to **Niagara Supply Chain Planning Analyst II**: daily production re-plan, MRP-driven raw material requirements, and inventory policy adherence (Min/Target/Max DOS).

---

## Start here (key outputs)

Open these three files first — they mirror daily outputs for Planning (schedule), Purchasing (MRP exceptions), and Ops/CS (inventory policy adherence).

- **Daily production schedule (daily re-plan):** `results/daily_production_schedule.csv`
- **MRP shortages & ETA exceptions (Purchasing actions):** `results/mrp_exception_report.csv`
- **Inventory policy adherence (Min/Target/Max DOS):** `results/inventory_policy_adherence.csv`

---

## What this repo does

- **Daily production re-plan:** assigns SKUs to eligible lines under capacity and changeover constraints; flags unassigned volume as OTIF risk proxy.
- **MRP explode:** converts planned production to raw material requirements; highlights shortages / late ETAs for Purchasing action.
- **Inventory policy adherence:** evaluates DOS vs Min/Target/Max; recommends production to recover to policy with MOQ + rounding rules.

---

## Repo structure

- `data/` — mock inputs (orders, forecast, inventory, BOM, suppliers, line constraints)
- `src/` — scripts for data generation, daily scheduling, MRP explode, and reporting
- `results/` — output CSVs
- `results/charts/` — charts (line load, OTIF risk proxy)

---

## How to run

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

python src/01_generate_mock_data.py --out_dir data
python src/03_daily_scheduler.py --data_dir data --results_dir results
python src/02_mrp_explode.py --data_dir data --results_dir results
python src/04_reports_and_charts.py --data_dir data --results_dir results
