
"""
04_reports_and_charts.py
Builds Niagara-style policy adherence report, OTIF risk list, and simple charts.
"""
from __future__ import annotations
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def build_policy_adherence(fg_inv: pd.DataFrame, forecast: pd.DataFrame, policy: pd.DataFrame, today: str) -> pd.DataFrame:
    fc7 = forecast[(forecast["date"] >= today) & (forecast["date"] < (pd.to_datetime(today)+pd.Timedelta(days=7)).date().isoformat())]
    mu = fc7.groupby("sku", as_index=False)["forecast_cases"].mean().rename(columns={"forecast_cases":"avg_daily_fcst_7d"})
    df = fg_inv.merge(mu, on="sku", how="left").merge(policy, on="sku", how="left")
    df["avg_daily_fcst_7d"] = df["avg_daily_fcst_7d"].fillna(1.0)
    df["dos"] = df["on_hand_cases"] / df["avg_daily_fcst_7d"]
    df["status"] = np.where(df["dos"] < df["min_dos"], "RED", np.where(df["dos"] > df["max_dos"], "YELLOW", "GREEN"))
    df["recommended_prod_cases"] = (df["target_dos"] * df["avg_daily_fcst_7d"] - df["on_hand_cases"]).clip(lower=0).round().astype(int)
    # apply MOQ and rounding
    df["recommended_prod_cases"] = np.maximum(df["recommended_prod_cases"], df["moq_cases"]).astype(int)
    df["recommended_prod_cases"] = (np.ceil(df["recommended_prod_cases"] / df["pack_rounding"]) * df["pack_rounding"]).astype(int)
    return df[["sku","abc","on_hand_cases","on_order_cases","eta_date","avg_daily_fcst_7d","dos","min_dos","target_dos","max_dos","status","recommended_prod_cases"]]

def chart_line_load(schedule: pd.DataFrame, out_path: str):
    load = schedule.groupby("line_id", as_index=False)["planned_qty_cases"].sum().sort_values("planned_qty_cases", ascending=False)
    plt.figure()
    plt.bar(load["line_id"], load["planned_qty_cases"])
    plt.title("Planned Cases by Line (Daily Re-plan)")
    plt.xlabel("Line")
    plt.ylabel("Planned Cases")
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close()

def chart_otif_risk(orders: pd.DataFrame, schedule: pd.DataFrame, out_path: str):
    # Risk proxy: unmet qty by SKU (if any) weighted by due date proximity
    unmet = schedule.groupby("sku", as_index=False)["unmet_qty_cases"].sum()
    unmet = unmet[unmet["unmet_qty_cases"] > 0].copy()
    if unmet.empty:
        unmet = pd.DataFrame({"sku":["(none)"],"unmet_qty_cases":[0]})
    plt.figure()
    plt.bar(unmet["sku"].astype(str).str.slice(0,14), unmet["unmet_qty_cases"])
    plt.title("OTIF Risk Proxy: Unmet Cases by SKU")
    plt.xlabel("SKU")
    plt.ylabel("Unmet Cases")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close()

def main(data_dir: str, results_dir: str):
    os.makedirs(os.path.join(results_dir, "charts"), exist_ok=True)

    orders = pd.read_csv(os.path.join(data_dir, "orders.csv"))
    forecast = pd.read_csv(os.path.join(data_dir, "forecast.csv"))
    fg_inv = pd.read_csv(os.path.join(data_dir, "fg_inventory.csv"))
    policy = pd.read_csv(os.path.join(data_dir, "policy.csv"))
    sched = pd.read_csv(os.path.join(results_dir, "daily_production_schedule.csv"))

    today = str(orders["order_date"].min())
    policy_report = build_policy_adherence(fg_inv, forecast, policy, today)
    policy_report.to_csv(os.path.join(results_dir, "inventory_policy_adherence.csv"), index=False)

    chart_line_load(sched[sched["line_id"]!="UNASSIGNED"], os.path.join(results_dir, "charts", "line_load.png"))
    chart_otif_risk(orders[orders["order_date"]==today], sched, os.path.join(results_dir, "charts", "otif_risk.png"))

    print("✅ inventory_policy_adherence.csv created")
    print("✅ charts saved to results/charts/")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--data_dir", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    p.add_argument("--results_dir", default=os.path.join(os.path.dirname(__file__), "..", "results"))
    args = p.parse_args()
    main(os.path.abspath(args.data_dir), os.path.abspath(args.results_dir))
