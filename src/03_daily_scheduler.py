
"""
03_daily_scheduler.py
Heuristic daily re-plan scheduler for a Niagara-style plant with 6+ lines.

Outputs:
- daily_production_schedule.csv (line-level plan)
- plan_by_sku_day.csv (sku/day aggregate for MRP explode)
- forecast_override_log.csv (sample overrides)
"""
from __future__ import annotations
import os
from dataclasses import dataclass
import pandas as pd
import numpy as np

RNG = np.random.default_rng(7)

@dataclass
class Weights:
    overdue: float = 100.0
    due_0_1: float = 60.0
    due_2_3: float = 35.0
    key_customer: float = 20.0
    high_priority: float = 18.0
    med_priority: float = 8.0
    low_priority: float = 0.0
    policy_red: float = 25.0
    policy_yellow: float = 10.0
    changeover_penalty: float = 0.06  # per minute (subtract)

def _priority_score(order_row, today: str, policy_status: str, w: Weights) -> float:
    due = order_row["due_date"]
    # days to due
    dtd = (pd.to_datetime(due) - pd.to_datetime(today)).days
    score = 0.0
    if dtd < 0:
        score += w.overdue
    elif dtd <= 1:
        score += w.due_0_1
    elif dtd <= 3:
        score += w.due_2_3

    if order_row["customer"] in ["CUST01","CUST02"]:
        score += w.key_customer

    pc = order_row["priority_class"]
    score += w.high_priority if pc == "HIGH" else (w.med_priority if pc == "MED" else w.low_priority)

    if policy_status == "RED":
        score += w.policy_red
    elif policy_status == "YELLOW":
        score += w.policy_yellow
    return score

def build_policy_status(fg_inv: pd.DataFrame, forecast: pd.DataFrame, policy: pd.DataFrame, today: str) -> pd.DataFrame:
    # DOS approx: on_hand / avg_daily_forecast(next 7 days)
    fc7 = forecast[(forecast["date"] >= today) & (forecast["date"] < (pd.to_datetime(today)+pd.Timedelta(days=7)).date().isoformat())]
    mu = fc7.groupby("sku", as_index=False)["forecast_cases"].mean().rename(columns={"forecast_cases":"avg_daily_fcst_7d"})
    df = fg_inv.merge(mu, on="sku", how="left").merge(policy[["sku","min_dos","target_dos","max_dos"]], on="sku", how="left")
    df["avg_daily_fcst_7d"] = df["avg_daily_fcst_7d"].fillna(1.0)
    df["dos"] = df["on_hand_cases"] / df["avg_daily_fcst_7d"]
    def stat(r):
        if r["dos"] < r["min_dos"]:
            return "RED"
        if r["dos"] > r["max_dos"]:
            return "YELLOW"
        return "GREEN"
    df["policy_status"] = df.apply(stat, axis=1)
    return df[["sku","dos","min_dos","target_dos","max_dos","policy_status"]]

def build_forecast_override_log(forecast: pd.DataFrame) -> pd.DataFrame:
    # Create a small synthetic override log (promo/customer add) for realism
    df = forecast.copy()
    sample = df.sample(n=min(18, len(df)), random_state=3).copy()
    sample["baseline_fcst"] = sample["forecast_cases"]
    # override by +/- 10-35%
    mult = RNG.uniform(0.85, 1.35, size=len(sample))
    sample["override_fcst"] = (sample["baseline_fcst"] * mult).round().astype(int)
    sample["reason"] = RNG.choice(["Customer add-on","Promo lift","Trend break","Ops constraint"], size=len(sample))
    sample["owner"] = RNG.choice(["CS","Sales","Planning"], size=len(sample))
    return sample[["sku","date","baseline_fcst","override_fcst","reason","owner"]]

def schedule_day(orders: pd.DataFrame, lines: pd.DataFrame, changeover: pd.DataFrame, policy_status: pd.DataFrame, day: str) -> pd.DataFrame:
    w = Weights()
    # For scheduling, we allocate orders to lines and sequence SKUs to reduce changeovers.
    # 1) compute order scores
    pol = policy_status.set_index("sku")["policy_status"].to_dict()
    orders = orders.copy()
    orders["policy_status"] = orders["sku"].map(pol).fillna("GREEN")
    orders["priority_score"] = orders.apply(lambda r: _priority_score(r, day, r["policy_status"], w), axis=1)

    # group by sku (cases needed for near-term)
    sku_need = orders.groupby(["sku"], as_index=False).agg(
        total_qty_cases=("qty_cases","sum"),
        max_priority=("priority_score","max")
    ).sort_values(["max_priority","total_qty_cases"], ascending=[False,False])

    # line capacity (cases/day)
    ldf = lines.copy()
    ldf["capacity_cases"] = (ldf["rate_cph"] * ldf["shift_hours"]) - (ldf["rate_cph"] * (ldf["downtime_min"]/60.0))
    ldf["remaining_cases"] = ldf["capacity_cases"].clip(lower=0).astype(int)
    ldf["last_sku"] = ""

    # helper to get changeover
    ch = changeover.set_index(["from_sku","to_sku"])["changeover_min"].to_dict()
    def chg(a,b):
        if a=="" or a is None:
            return 0
        return int(ch.get((a,b), 60))

    sched_rows = []

    # For each SKU need, assign to best eligible line with remaining capacity,
    # choose line minimizing changeover and with most remaining capacity.
    for _, s in sku_need.iterrows():
        sku = s["sku"]
        qty = int(s["total_qty_cases"])
        # find eligible lines
        elig = []
        for _, lr in ldf.iterrows():
            eligible = str(lr["eligible_skus"]).split("|")
            if sku in eligible and lr["remaining_cases"] > 0:
                co = chg(lr["last_sku"], sku)
                # score: remaining capacity minus changeover penalty
                score = lr["remaining_cases"] - (co * ldf["rate_cph"].median()/60.0) - (co * 10)
                elig.append((score, lr["line_id"], co))
        if not elig:
            # cannot schedule (no capacity/eligibility)
            sched_rows.append((day, "UNASSIGNED", sku, 0, qty, "", 0, "CAPACITY_OR_ELIGIBILITY"))
            continue
        elig.sort(reverse=True, key=lambda x: x[0])
        _, line_id, co_min = elig[0]
        idx = ldf.index[ldf["line_id"] == line_id][0]
        can = int(ldf.loc[idx,"remaining_cases"])
        make = min(qty, can)
        ldf.loc[idx,"remaining_cases"] = can - make
        ldf.loc[idx,"last_sku"] = sku

        flag = ""
        sched_rows.append((day, line_id, sku, make, qty-make, "AUTO", int(co_min), flag))

    out = pd.DataFrame(sched_rows, columns=["date","line_id","sku","planned_qty_cases","unmet_qty_cases","plan_source","changeover_min","flags"])
    return out

def main(data_dir: str, results_dir: str):
    os.makedirs(results_dir, exist_ok=True)
    orders = pd.read_csv(os.path.join(data_dir, "orders.csv"))
    forecast = pd.read_csv(os.path.join(data_dir, "forecast.csv"))
    fg_inv = pd.read_csv(os.path.join(data_dir, "fg_inventory.csv"))
    policy = pd.read_csv(os.path.join(data_dir, "policy.csv"))
    lines = pd.read_csv(os.path.join(data_dir, "lines.csv"))
    change = pd.read_csv(os.path.join(data_dir, "changeover_matrix.csv"))
    ship = pd.read_csv(os.path.join(data_dir, "shipping_calendar.csv"))

    # pick "today" as first order_date in file (simulation start)
    today = str(orders["order_date"].min())
    pol_stat = build_policy_status(fg_inv, forecast, policy, today)

    # schedule only "today" (daily re-plan) + produce a 14-day aggregate plan by sku/day from forecast & policy
    day_orders = orders[orders["order_date"] == today].copy()
    sched = schedule_day(day_orders, lines, change, pol_stat, today)

    # shipping feasibility flag: simple check total pallets vs load capacity
    # pallets approx = planned_qty / pallet_units from catalog (join later in reports)
    # Here we just flag if UNASSIGNED exists
    if (sched["line_id"] == "UNASSIGNED").any():
        sched.loc[sched["line_id"] == "UNASSIGNED", "flags"] = sched.loc[sched["line_id"] == "UNASSIGNED", "flags"].replace("", "CAPACITY_OR_ELIGIBILITY")

    sched.to_csv(os.path.join(results_dir, "daily_production_schedule.csv"), index=False)

    # Build plan_by_sku_day for next 7 days using policy gaps (target DOS) as a simplistic production signal
    # This supports the MRP explode demo.
    fc7 = forecast[(forecast["date"] >= today) & (forecast["date"] < (pd.to_datetime(today)+pd.Timedelta(days=7)).date().isoformat())]
    mu = fc7.groupby("sku", as_index=False)["forecast_cases"].mean().rename(columns={"forecast_cases":"avg_daily_fcst_7d"})
    inv = fg_inv.merge(mu, on="sku", how="left").merge(policy[["sku","target_dos","min_dos","max_dos","moq_cases","pack_rounding"]], on="sku", how="left")
    inv["avg_daily_fcst_7d"] = inv["avg_daily_fcst_7d"].fillna(1.0)
    inv["target_qty"] = (inv["target_dos"] * inv["avg_daily_fcst_7d"]).round().astype(int)
    inv["gap_cases"] = (inv["target_qty"] - inv["on_hand_cases"]).clip(lower=0).astype(int)
    # split gap across 3 days to keep it realistic
    plan_rows = []
    for _, r in inv.iterrows():
        gap = int(r["gap_cases"])
        if gap <= 0:
            continue
        # apply MOQ and rounding
        gap = max(gap, int(r["moq_cases"]))
        rnd = max(1, int(r["pack_rounding"]))
        gap = int(np.ceil(gap / rnd) * rnd)
        # allocate across days 0-2
        splits = [0.45, 0.35, 0.20]
        for i, frac in enumerate(splits):
            d = (pd.to_datetime(today) + pd.Timedelta(days=i)).date().isoformat()
            q = int(round(gap * frac))
            if q>0:
                plan_rows.append((d, r["sku"], q))
    plan = pd.DataFrame(plan_rows, columns=["date","sku","planned_qty_cases"])
    plan.to_csv(os.path.join(results_dir, "plan_by_sku_day.csv"), index=False)

    # Forecast override log (for JD alignment)
    ov = build_forecast_override_log(forecast)
    ov.to_csv(os.path.join(results_dir, "forecast_override_log.csv"), index=False)

    # Save policy status table (inventory policy adherence snapshot)
    pol_stat.to_csv(os.path.join(results_dir, "inventory_policy_snapshot.csv"), index=False)

    print("✅ Daily schedule written to results/daily_production_schedule.csv")
    print("✅ plan_by_sku_day.csv written for MRP explode step")
    print("✅ forecast_override_log.csv and inventory_policy_snapshot.csv written")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--data_dir", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    p.add_argument("--results_dir", default=os.path.join(os.path.dirname(__file__), "..", "results"))
    args = p.parse_args()
    main(os.path.abspath(args.data_dir), os.path.abspath(args.results_dir))
