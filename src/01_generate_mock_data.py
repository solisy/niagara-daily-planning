
"""
01_generate_mock_data.py
Creates Niagara-style mock datasets for a single plant with 8 production lines.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from datetime import date, timedelta
import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)

@dataclass
class Config:
    plant: str = "CORP-MAIN"
    start_date: str = "2026-02-09"   # Monday
    horizon_days: int = 14
    lines: int = 8
    customers: int = 8
    orders_per_day: int = 25
    skus: int = 12

def _sku_catalog(n: int) -> pd.DataFrame:
    # Niagara-like bottled-water SKUs (examples + auto-fill)
    base = [
        ("WTR-169OZ-24PK", "16.9oz", "24pk", "PET", 0.55),
        ("WTR-500ML-24PK", "500ml", "24pk", "PET", 0.60),
        ("WTR-1L-12PK",    "1L",    "12pk", "PET", 0.75),
        ("WTR-1GAL-6PK",   "1gal",  "6pk",  "HDPE",1.30),
        ("WTR-35PK",       "16.9oz","35pk", "PET", 0.78),
        ("WTR-8OZ-48PK",   "8oz",   "48pk", "PET", 0.62),
    ]
    # expand
    while len(base) < n:
        oz = RNG.choice(["16.9oz","20oz","700ml","1L","1.5L"])
        pack = RNG.choice(["12pk","24pk","35pk","48pk","6pk"])
        resin = "PET" if pack != "6pk" else RNG.choice(["HDPE","PET"])
        code = f"WTR-{oz.replace('.','').replace('oz','OZ').replace('ml','ML').replace('L','L')}-{pack.upper()}"
        # unit cost roughly tied to size
        size_factor = {"8oz":0.45,"16.9oz":0.55,"20oz":0.58,"500ml":0.60,"700ml":0.68,"1L":0.75,"1.5L":0.95,"1gal":1.30}.get(oz,0.70)
        base.append((code, oz, pack, resin, float(size_factor)))
    df = pd.DataFrame(base[:n], columns=["sku","bottle_size","pack","resin","unit_cost"])
    # demand class / family for changeovers
    df["family"] = df["bottle_size"].astype(str) + "|" + df["pack"].astype(str) + "|" + df["resin"].astype(str)
    df["pallet_units"] = RNG.integers(40, 120, size=len(df))  # cases per pallet
    return df

def _lines(n: int, sku_df: pd.DataFrame) -> pd.DataFrame:
    # Each line eligible for a subset of SKUs; rates vary.
    lines = []
    for i in range(1, n+1):
        line_id = f"L{i}"
        # choose 5-9 eligible SKUs
        eligible = RNG.choice(sku_df["sku"], size=int(RNG.integers(5, min(10, len(sku_df)))), replace=False)
        rate = int(RNG.integers(350, 900))  # cases per hour
        shift_hours = float(RNG.choice([16, 20, 24], p=[0.35,0.35,0.30]))
        downtime = float(RNG.integers(0, 120))  # minutes
        lines.append((line_id, rate, shift_hours, downtime, "|".join(eligible)))
    return pd.DataFrame(lines, columns=["line_id","rate_cph","shift_hours","downtime_min","eligible_skus"])

def _changeover(sku_df: pd.DataFrame) -> pd.DataFrame:
    # Simple rule: same family changeover low; otherwise higher. Add some asymmetry noise.
    skus = sku_df["sku"].tolist()
    fam = dict(zip(sku_df["sku"], sku_df["family"]))
    rows = []
    for a in skus:
        for b in skus:
            if a == b:
                m = 0
            elif fam[a] == fam[b]:
                m = int(RNG.integers(10, 25))
            else:
                m = int(RNG.integers(30, 90))
            # small noise
            m = int(max(0, m + RNG.integers(-3, 4)))
            rows.append((a,b,m))
    return pd.DataFrame(rows, columns=["from_sku","to_sku","changeover_min"])

def _bom(sku_df: pd.DataFrame) -> pd.DataFrame:
    # Materials: PREP (preform), CAP, LABEL, CARTON, PALLET, FILM
    rows = []
    for _, r in sku_df.iterrows():
        sku = r["sku"]
        pack = r["pack"]
        bottle_size = r["bottle_size"]
        # per case assumptions
        bottles_per_case = int(pack.replace("pk",""))
        rows += [
            (sku, "PREP", bottles_per_case),
            (sku, "CAP",  bottles_per_case),
            (sku, "LABEL",bottles_per_case),
            (sku, "CARTON",1),
            (sku, "FILM", 1),
            (sku, "PALLET", 1/max(1,int(r["pallet_units"]))),
        ]
    df = pd.DataFrame(rows, columns=["sku","material","usage_per_case"])
    return df

def _policies(sku_df: pd.DataFrame) -> pd.DataFrame:
    # Policy: min/target/max DOS by ABC; service levels by class
    # Assign ABC by unit_cost (proxy)
    df = sku_df[["sku","unit_cost"]].copy()
    df["abc"] = pd.qcut(df["unit_cost"], q=3, labels=["C","B","A"])
    dos_map = {"A":(6,10,14,0.98), "B":(5,8,12,0.95), "C":(4,6,10,0.90)}
    df["abc"] = df["abc"].astype(str)
    df[["min_dos","target_dos","max_dos","service_level"]] = df["abc"].apply(lambda x: pd.Series(dos_map[x]))
    # planning params placeholders
    df["lead_time_days"] = RNG.integers(3, 10, size=len(df))  # FG replenishment lead time concept
    df["moq_cases"] = RNG.integers(200, 900, size=len(df))
    df["pack_rounding"] = RNG.integers(20, 60, size=len(df))  # rounding to full pallets-ish
    return df[["sku","abc","min_dos","target_dos","max_dos","service_level","lead_time_days","moq_cases","pack_rounding"]]

def _shipping_calendar(start: date, horizon_days: int) -> pd.DataFrame:
    rows = []
    for d in range(horizon_days):
        day = start + timedelta(days=d)
        # shipping loads capacity varies by weekday; weekends lower
        if day.weekday() >= 5:
            loads = int(RNG.integers(8, 14))
        else:
            loads = int(RNG.integers(16, 26))
        cutoff = "16:00"
        rows.append((day.isoformat(), loads, cutoff))
    return pd.DataFrame(rows, columns=["date","load_capacity","dc_cutoff_local"])

def _inventories(sku_df: pd.DataFrame, bom_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    # FG on_hand/on_order, and materials on_hand/on_order with ETAs
    today = date.fromisoformat("2026-02-09")
    # FG
    fg = []
    for sku in sku_df["sku"]:
        on_hand = int(RNG.integers(300, 2500))
        on_order = int(RNG.integers(0, 1800))
        eta = (today + timedelta(days=int(RNG.integers(1,8)))).isoformat() if on_order>0 else ""
        fg.append((sku,on_hand,on_order,eta))
    fg_df = pd.DataFrame(fg, columns=["sku","on_hand_cases","on_order_cases","eta_date"])
    # materials
    mats = sorted(bom_df["material"].unique().tolist())
    mat_rows = []
    for m in mats:
        on_hand = float(RNG.integers(20000, 160000))
        on_order = float(RNG.integers(0, 120000))
        eta = (today + timedelta(days=int(RNG.integers(2,10)))).isoformat() if on_order>0 else ""
        mat_rows.append((m,on_hand,on_order,eta))
    mat_df = pd.DataFrame(mat_rows, columns=["material","on_hand_qty","on_order_qty","eta_date"])
    return fg_df, mat_df

def _forecast(start: date, horizon_days: int, sku_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sku in sku_df["sku"]:
        base = int(RNG.integers(300, 1200))
        for d in range(horizon_days):
            day = start + timedelta(days=d)
            weekday_factor = 1.1 if day.weekday() < 5 else 0.8
            promo = 1 if RNG.random() < 0.08 else 0
            qty = int(max(0, RNG.normal(base*weekday_factor*(1.25 if promo else 1.0), base*0.18)))
            rows.append((sku, day.isoformat(), qty, "baseline", promo))
    return pd.DataFrame(rows, columns=["sku","date","forecast_cases","baseline_method","promo_flag"])

def _orders(start: date, horizon_days: int, sku_df: pd.DataFrame, customers: int, per_day: int) -> pd.DataFrame:
    custs = [f"CUST{i:02d}" for i in range(1, customers+1)]
    rows = []
    oid = 100000
    for d in range(horizon_days):
        day = start + timedelta(days=d)
        for _ in range(per_day):
            oid += 1
            sku = str(RNG.choice(sku_df["sku"]))
            customer = str(RNG.choice(custs))
            qty = int(max(10, RNG.normal(200, 140)))
            qty = int(min(max(qty, 20), 1200))
            # due date: 0-5 days ahead; heavier weight on near term
            due_offset = int(RNG.choice([0,1,1,2,2,3,4,5]))
            due = (day + timedelta(days=due_offset)).isoformat()
            # priority class: key customers (CUST01-02) get higher
            pr = "HIGH" if customer in ["CUST01","CUST02"] and RNG.random() < 0.6 else ("MED" if RNG.random()<0.5 else "LOW")
            rows.append((f"SO{oid}", customer, sku, qty, day.isoformat(), due, pr))
    return pd.DataFrame(rows, columns=["order_id","customer","sku","qty_cases","order_date","due_date","priority_class"])

def main(out_dir: str):
    cfg = Config()
    os.makedirs(out_dir, exist_ok=True)
    start = date.fromisoformat(cfg.start_date)

    sku_df = _sku_catalog(cfg.skus)
    lines_df = _lines(cfg.lines, sku_df)
    change_df = _changeover(sku_df)
    bom_df = _bom(sku_df)
    policy_df = _policies(sku_df)
    ship_df = _shipping_calendar(start, cfg.horizon_days)
    fg_inv, mat_inv = _inventories(sku_df, bom_df)
    fcst = _forecast(start, cfg.horizon_days, sku_df)
    orders = _orders(start, cfg.horizon_days, sku_df, cfg.customers, cfg.orders_per_day)

    sku_df.to_csv(os.path.join(out_dir, "sku_catalog.csv"), index=False)
    lines_df.to_csv(os.path.join(out_dir, "lines.csv"), index=False)
    change_df.to_csv(os.path.join(out_dir, "changeover_matrix.csv"), index=False)
    bom_df.to_csv(os.path.join(out_dir, "bom_materials.csv"), index=False)
    policy_df.to_csv(os.path.join(out_dir, "policy.csv"), index=False)
    ship_df.to_csv(os.path.join(out_dir, "shipping_calendar.csv"), index=False)
    fg_inv.to_csv(os.path.join(out_dir, "fg_inventory.csv"), index=False)
    mat_inv.to_csv(os.path.join(out_dir, "material_inventory.csv"), index=False)
    fcst.to_csv(os.path.join(out_dir, "forecast.csv"), index=False)
    orders.to_csv(os.path.join(out_dir, "orders.csv"), index=False)

    print("✅ Mock Niagara-style datasets generated under:", out_dir)
    print("Key files: orders.csv, forecast.csv, fg_inventory.csv, material_inventory.csv, lines.csv, bom_materials.csv, policy.csv")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--out_dir", default=os.path.join(os.path.dirname(__file__), "..", "data"))
    args = p.parse_args()
    main(os.path.abspath(args.out_dir))