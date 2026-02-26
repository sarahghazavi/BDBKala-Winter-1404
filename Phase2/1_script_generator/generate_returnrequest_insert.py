#!/usr/bin/env python3
import argparse
import csv
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Tuple, List

def norm(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s2 = s.strip()
    return s2 if s2 != "" else None

def sql_escape_text(s: str) -> str:
    return s.replace("'", "''")

def sql_text_or_null(s: Optional[str]) -> str:
    s = norm(s)
    if s is None:
        return "NULL"
    return f"'{sql_escape_text(s)}'"

def sql_timestamp(dt: datetime) -> str:
    return f"'{dt.strftime('%Y-%m-%d %H:%M:%S')}'::timestamp"

def product_id_from_key(name: str, category: Optional[str], subcategory: Optional[str]) -> int:
    """
    MUST match product/orderitem scripts:
    sha1(name|category|subcategory) -> first 15 hex chars
    """
    raw = f"{name}|{category or ''}|{subcategory or ''}".encode("utf-8")
    h = hashlib.sha1(raw).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1

def return_id(orderid: int, productid: int) -> int:
    """
    Deterministic BIGINT returnid for PK.
    """
    raw = f"{orderid}|{productid}|return".encode("utf-8")
    h = hashlib.sha1(raw).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1

def h01(orderid: int, productid: int) -> float:
    """
    Deterministic pseudo-random float in [0,1).
    """
    raw = f"{orderid}|{productid}".encode("utf-8")
    h = hashlib.sha1(raw).hexdigest()
    v = int(h[:8], 16)  # 32-bit
    return v / 2**32

def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    s = norm(date_str)
    if not s:
        return None
    # expected: YYYY-MM-DD
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

Key = Tuple[int, int]  # (orderid, productid)

REASONS = [
    "Damaged item",
    "Wrong item received",
    "Item not as described",
    "Late delivery",
    "Changed mind",
    "Defective product",
    "Missing parts",
    "Better price found",
]

def collect_orderitems_and_dates(full_path: Path) -> Dict[Key, Dict[str, Optional[str]]]:
    """
    Extract unique (orderid, productid) pairs from BDBKala_full.csv and store order date.
    This matches your orderitem logic: productid from (Product Name, Category, Sub-Category).
    """
    items: Dict[Key, Dict[str, Optional[str]]] = {}

    # use utf-8-sig to safely handle BOM if present
    with full_path.open("r", newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f, strict=False)
        for row in reader:
            oid_raw = norm(row.get("Order ID"))
            pname = norm(row.get("Product Name"))
            if not oid_raw or not pname:
                continue
            try:
                oid = int(oid_raw)
            except ValueError:
                continue

            cat = norm(row.get("Product Category"))
            sub = norm(row.get("Product Sub-Category"))
            pid = product_id_from_key(pname, cat, sub)

            k: Key = (oid, pid)
            if k in items:
                continue

            odt = parse_date(row.get("Order Date"))
            items[k] = {
                "orderid": str(oid),
                "productid": str(pid),
                "order_date": odt.strftime("%Y-%m-%d") if odt else None,
            }

    return items

def generate_return_rows(
    items: Dict[Key, Dict[str, Optional[str]]],
    return_rate: float,
) -> List[Tuple[int, int, datetime, Optional[datetime], str, str]]:
    """
    Returns list of tuples:
      (returnid, orderid, requestdate, decisiondate, result, reason)
    """
    rows = []

    for (oid, pid), rec in items.items():
        # decide if this (order, product) is returned
        if h01(oid, pid) >= return_rate:
            continue

        # base order date or fallback
        odt = parse_date(rec.get("order_date")) or datetime(2020, 1, 1)

        # request date: 7..30 days after order date (deterministic)
        req_days = 7 + int(h01(oid, pid) * 24)  # 7..30
        request_dt = odt + timedelta(days=req_days, hours=(oid % 24))

        # decision date: 1..10 days after request date (deterministic)
        dec_days = 1 + (pid % 10)
        decision_dt = request_dt + timedelta(days=dec_days, hours=(pid % 24))

        # approval probability (e.g., 75%)
        approved = (h01(pid, oid) < 0.75)
        result = "Approved" if approved else "Rejected"

        # deterministic reason
        reason = REASONS[(oid + pid) % len(REASONS)]

        rid = return_id(oid, pid)
        rows.append((rid, oid, pid, request_dt, decision_dt, result, reason))

    return rows

def write_insert(out_path: Path, rows: List[Tuple[int, int, int, datetime, datetime, str, str]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cols = ["returnid", "orderid", "productid", "decisiondate", "result", "reason", "requestdate"]
    values_sql: List[str] = []

    for (rid, oid, pid, req_dt, dec_dt, result, reason) in rows:
        values_sql.append("(" + ", ".join([
            str(rid),
            str(oid),
            str(pid),
            sql_timestamp(dec_dt),
            sql_text_or_null(result),
            sql_text_or_null(reason),
            sql_timestamp(req_dt),  # NOT NULL
        ]) + ")")

    with out_path.open("w", encoding="utf-8") as f:
        f.write("-- Auto-generated returnrequest insert\n")
        f.write("-- Synthetic returns generated deterministically from order items\n\n")
        if values_sql:
            f.write(f"INSERT INTO returnrequest ({', '.join(cols)})\nVALUES\n")
            f.write(",\n".join(values_sql))
            f.write(";\n")
        else:
            f.write("-- No return rows generated (try increasing --return_rate).\n")

    print(f"[OK] Wrote: {out_path}  (rows: {len(values_sql)})")

def main():
    ap = argparse.ArgumentParser(description="Generate a single multi-row INSERT for returnrequest table.")
    ap.add_argument("--full", required=True, help="Path to BDBKala_full.csv")
    ap.add_argument("--out", default="sql/13_insert_returnrequest.sql", help="Output .sql file path")
    ap.add_argument("--return_rate", type=float, default=0.05, help="Fraction of order-items to return (e.g., 0.05 = 5%)")
    args = ap.parse_args()

    full_path = Path(args.full).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    items = collect_orderitems_and_dates(full_path)
    rows = generate_return_rows(items, return_rate=args.return_rate)
    write_insert(out_path, rows)

if __name__ == "__main__":
    main()
