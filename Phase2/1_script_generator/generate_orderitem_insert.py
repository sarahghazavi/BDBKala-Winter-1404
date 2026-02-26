#!/usr/bin/env python3
import argparse
import csv
import hashlib
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


def sql_int(s: Optional[str], default: int = 1) -> int:
    s = norm(s)
    if s is None:
        return default
    try:
        return int(float(s))
    except ValueError:
        return default


def sql_numeric_str_or_none(s: Optional[str]) -> Optional[str]:
    s = norm(s)
    if s is None:
        return None
    s = s.replace(",", "")
    try:
        float(s)
        return s
    except ValueError:
        return None


def product_id_from_key(name: str, category: Optional[str], subcategory: Optional[str]) -> int:
    """
    MUST match your product generator:
    sha1(name|category|subcategory) -> first 15 hex chars
    """
    raw = f"{name}|{category or ''}|{subcategory or ''}".encode("utf-8")
    h = hashlib.sha1(raw).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1


Key = Tuple[int, int]  # (orderid, productid)


def collect_orderitems(full_path: Path) -> Dict[Key, Dict[str, Optional[str]]]:
    """
    Aggregate by (orderid, productid) because PK is composite.
    Sum quantity. Keep first non-null purchaseprice/paymentmethod/itemstatus.
    """
    items: Dict[Key, Dict[str, Optional[str]]] = {}

    with full_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
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

            qty = sql_int(row.get("Order Quantity"), default=1)
            unit_price = sql_numeric_str_or_none(row.get("Unit Price"))
            pay_method = norm(row.get("Payment Method"))
            item_status = norm(row.get("Order Status"))

            k: Key = (oid, pid)
            rec = items.get(k)
            if rec is None:
                items[k] = {
                    "orderid": str(oid),
                    "productid": str(pid),
                    "quantity": str(qty),
                    "purchaseprice": unit_price,
                    "paymentmethod": pay_method,
                    "itemstatus": item_status,
                }
            else:
                # aggregate quantity
                rec["quantity"] = str(int(rec["quantity"]) + qty)

                # keep first non-null for these fields
                if rec.get("purchaseprice") is None and unit_price is not None:
                    rec["purchaseprice"] = unit_price
                if rec.get("paymentmethod") is None and pay_method is not None:
                    rec["paymentmethod"] = pay_method
                if rec.get("itemstatus") is None and item_status is not None:
                    rec["itemstatus"] = item_status

    return items


def write_insert(out_path: Path, items: Dict[Key, Dict[str, Optional[str]]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cols = ["orderid", "productid", "itemstatus", "quantity", "purchaseprice", "paymentmethod"]

    rows_sql: List[str] = []

    for (oid, pid) in sorted(items.keys()):
        rec = items[(oid, pid)]
        row = "(" + ", ".join([
            rec["orderid"],
            rec["productid"],
            sql_text_or_null(rec.get("itemstatus")),
            rec["quantity"],  # NOT NULL
            rec["purchaseprice"] if rec.get("purchaseprice") is not None else "NULL",
            sql_text_or_null(rec.get("paymentmethod")),
        ]) + ")"
        rows_sql.append(row)

    with out_path.open("w", encoding="utf-8") as f:
        f.write("-- Auto-generated orderitem insert\n")
        f.write("-- Aggregated by (orderid, productid) to respect composite PK\n\n")
        if rows_sql:
            f.write(f"INSERT INTO orderitem ({', '.join(cols)})\nVALUES\n")
            f.write(",\n".join(rows_sql))
            f.write(";\n")
        else:
            f.write("-- No order items found in input CSV.\n")

    print(f"[OK] Wrote: {out_path}  (rows: {len(rows_sql)})")


def main():
    ap = argparse.ArgumentParser(description="Generate a single multi-row INSERT for orderitem table.")
    ap.add_argument("--full", required=True, help="Path to BDBKala_full.csv")
    ap.add_argument("--out", default="sql/08_insert_orderitem.sql", help="Output .sql file path")
    args = ap.parse_args()

    full_path = Path(args.full).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    items = collect_orderitems(full_path)
    write_insert(out_path, items)


if __name__ == "__main__":
    main()
