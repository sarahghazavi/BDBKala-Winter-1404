#!/usr/bin/env python3
import argparse
import csv
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from collections import defaultdict

def norm(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s2 = s.strip()
    return s2 if s2 != "" else None

def to_float(s: Optional[str]) -> float:
    s = norm(s)
    if not s:
        return 0.0
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0

def parse_date(s: Optional[str]) -> Optional[datetime]:
    s = norm(s)
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

def sql_escape_text(s: str) -> str:
    return s.replace("'", "''")

def sql_text_or_null(s: Optional[str]) -> str:
    s = norm(s)
    if s is None:
        return "NULL"
    return f"'{sql_escape_text(s)}'"

def sql_timestamp(dt: datetime) -> str:
    return f"'{dt.strftime('%Y-%m-%d %H:%M:%S')}'::timestamp"

def money2(x: float) -> str:
    return f"{x:.2f}"

def repayment_id(orderid: int, k: int) -> int:
    """
    Deterministic bigint repaymentid from (orderid, installment_index).
    """
    raw = f"{orderid}|{k}|repayment".encode("utf-8")
    h = hashlib.sha1(raw).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1

def collect_order_totals_and_dates(full_path: Path) -> Tuple[Dict[int, float], Dict[int, datetime]]:
    """
    From BDBKala_full.csv compute:
    - total payable amount per order (sum qty*unit_price*(1-discount))
    - order date per order (first seen)
    """
    totals: Dict[int, float] = defaultdict(float)
    dates: Dict[int, datetime] = {}

    with full_path.open("r", newline="", encoding="utf-8-sig", errors="replace") as f:
        r = csv.DictReader(f, strict=False)
        for row in r:
            oid_raw = norm(row.get("Order ID"))
            if not oid_raw:
                continue
            try:
                oid = int(oid_raw)
            except ValueError:
                continue

            qty = to_float(row.get("Order Quantity"))
            unit_price = to_float(row.get("Unit Price"))
            disc = to_float(row.get("Discount"))  # discount like 0.21
            line_total = qty * unit_price * (1.0 - disc)
            totals[oid] += line_total

            if oid not in dates:
                odt = parse_date(row.get("Order Date"))
                if odt:
                    dates[oid] = odt

    # fallback dates for any missing
    for oid in totals.keys():
        if oid not in dates:
            dates[oid] = datetime(2020, 1, 1) + timedelta(days=(oid % 365))

    return dict(totals), dates

def write_insert(out_path: Path, totals: Dict[int, float], dates: Dict[int, datetime], method: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cols = ["repaymentid", "orderid", "amount", "date", "method"]
    rows_sql: List[str] = []

    for oid in sorted(totals.keys()):
        total = totals[oid]
        if total <= 0:
            continue

        # deterministic installment count: 1..3
        n_installments = (oid % 3) + 1

        # split into equal parts, fix rounding on last installment
        base_amt = round(total / n_installments, 2)
        amts = [base_amt] * n_installments
        amts[-1] = round(total - base_amt * (n_installments - 1), 2)

        start_date = dates[oid] + timedelta(days=7)

        for k in range(n_installments):
            rid = repayment_id(oid, k + 1)
            pay_date = start_date + timedelta(days=30 * k)

            rows_sql.append("(" + ", ".join([
                str(rid),
                str(oid),
                money2(amts[k]),
                sql_timestamp(pay_date),
                sql_text_or_null(method),
            ]) + ")")

    with out_path.open("w", encoding="utf-8") as f:
        f.write("-- Auto-generated repayment insert\n")
        f.write("-- Synthetic repayments based on order totals from BDBKala_full.csv\n")
        f.write("-- Each order gets 1..3 installments (deterministic by orderid)\n\n")
        if rows_sql:
            f.write(f"INSERT INTO repayment ({', '.join(cols)})\nVALUES\n")
            f.write(",\n".join(rows_sql))
            f.write(";\n")
        else:
            f.write("-- No repayments generated (order totals may be zero).\n")

    print(f"[OK] Wrote: {out_path}  (rows: {len(rows_sql)})")

def main():
    ap = argparse.ArgumentParser(description="Generate a single multi-row INSERT for repayment table.")
    ap.add_argument("--full", required=True, help="Path to BDBKala_full.csv")
    ap.add_argument("--out", default="sql/14_insert_repayment.sql", help="Output .sql file path")
    ap.add_argument("--method", default="Installment", help="Repayment method text")
    args = ap.parse_args()

    full_path = Path(args.full).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    totals, dates = collect_order_totals_and_dates(full_path)
    write_insert(out_path, totals, dates, method=args.method)

if __name__ == "__main__":
    main()
