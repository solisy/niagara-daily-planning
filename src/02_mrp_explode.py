
"""
02_mrp_explode.py
Explodes planned production (cases) into material requirements and identifies shortages.
"""
from __future__ import annotations
import os
import pandas as pd

def mrp_explode(plan_df: pd.DataFrame, bom_df: pd.DataFrame) -> pd.DataFrame:
    # plan_df columns: date, sku, planned_cases
    req = plan_df.merge(bom_df, on="sku", how="left")
    req["req_qty"] = req["planned_cases"] * req["usage_per_case"]
    agg = req.groupby(["date","material"], as_index=False)["req_qty"].sum()
    return agg

def material_availability(material_inv: pd.DataFrame, date: str) -> pd.DataFrame:
    # Simple: on_hand + on_order if eta_date <= date
    inv = material_inv.copy()
    inv["eta_date"] = inv["eta_date"].fillna("")
    inv["available_qty"] = inv["on_hand_qty"] + inv.apply(lambda r: r["on_order_qty"] if (r["eta_date"] != "" and r["eta_date"] <= date) else 0.0, axis=1)
    return inv[["material","available_qty","eta_date","on_order_qty","on_hand_qty"]]

def build_mrp_exception(req_df: pd.DataFrame, material_inv: pd.DataFrame) -> pd.DataFrame:
    # For each date, check shortages vs available. This is a simplified daily bucket check.
    out = []
    for d in sorted(req_df["date"].unique()):
        req_day = req_df[req_df["date"] == d].copy()
        avail = material_availability(material_inv, d)
        chk = req_day.merge(avail, on="material", how="left").fillna({"available_qty":0.0})
        chk["short_qty"] = (chk["req_qty"] - chk["available_qty"]).clip(lower=0.0)
        chk = chk[chk["short_qty"] > 0].copy()
        chk["earliest_eta"] = chk["eta_date"]
        chk["suggested_action"] = "Expedite / Re-sequence / Substitute"
        out.append(chk[["date","material","req_qty","available_qty","short_qty","earliest_eta","suggested_action"]])
    if out:
        return pd.concat(out, ignore_index=True)
    return pd.DataFrame(columns=["date","material","req_qty","available_qty","short_qty","earliest_eta","suggested_action"])

def main(data_dir: str, results_dir: str):
    os.makedirs(results_dir, exist_ok=True)
    # Inputs from scheduler's aggregate plan
    plan_path = os.path.join(results_dir, "plan_by_sku_day.csv")
    if not os.path.exists(plan_path):
        raise FileNotFoundError("Missing plan_by_sku_day.csv. Run 03_daily_scheduler.py first.")
    plan = pd.read_csv(plan_path)
    bom = pd.read_csv(os.path.join(data_dir, "bom_materials.csv"))
    mat_inv = pd.read_csv(os.path.join(data_dir, "material_inventory.csv"))

    req = mrp_explode(plan.rename(columns={"planned_qty_cases":"planned_cases"})[["date","sku","planned_cases"]], bom)
    exc = build_mrp_exception(req, mat_inv)

    req.to_csv(os.path.join(results_dir, "mrp_requirements.csv"), index=False)
    exc.to_csv(os.path.join(results_dir, "mrp_exception_report.csv"), index=False)
    print("✅ MRP requirements & exception report written to results/")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--data_dir", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    p.add_argument("--results_dir", default=os.path.join(os.path.dirname(__file__), "..", "results"))
    args = p.parse_args()
    main(os.path.abspath(args.data_dir), os.path.abspath(args.results_dir))
