#!/usr/bin/env python3
import argparse
import csv
import hashlib
from pathlib import Path
from typing import Optional, Dict, List, Tuple


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


def sql_timestamp_or_null(s: Optional[str]) -> str:
    s = norm(s)
    if s is None:
        return "NULL"
    return f"'{sql_escape_text(s)}'::timestamp"


def id60_from_string(s: str, salt: str = "") -> int:
    raw = (salt + "|" + s).encode("utf-8")
    h = hashlib.sha1(raw).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1


def customer_key(name: Optional[str], email: Optional[str], phone: Optional[str]) -> str:
    if email:
        return "email:" + email.lower()
    if phone:
        return "phone:" + phone
    return "name:" + (name or "UNKNOWN")


def branch_id_from_name(name: str) -> int:
    # must match generate_branch_insert.py
    h = hashlib.sha1(name.encode("utf-8")).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1


def load_branches(bps_path: Path) -> List[int]:
    """
    Read branch_product_suppliers.csv and build a stable list of branch IDs.
    """
    branch_names = set()
    with bps_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            b = norm(row.get("branch_name"))
            if b:
                branch_names.add(b)

    # stable sorted order
    sorted_names = sorted(branch_names, key=lambda x: x.lower())
    return [branch_id_from_name(n) for n in sorted_names]


def assign_branch(order_id: int, branch_ids: List[int]) -> int:
    # deterministic, no randomness
    if not branch_ids:
        # cannot be NULL in schema; fail loudly
        raise RuntimeError("No branches found for branch assignment.")
    return branch_ids[order_id % len(branch_ids)]


def collect_orders(full_path: Path, branch_ids: List[int]) -> Dict[int, Dict[str, Optional[str]]]:
    """
    One order per Order ID. If multiple rows exist per order (multiple items),
    keep the first encountered order-level fields.
    """
    orders: Dict[int, Dict[str, Optional[str]]] = {}

    with full_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            oid_raw = norm(row.get("Order ID"))
            if not oid_raw:
                continue
            try:
                oid = int(oid_raw)
            except ValueError:
                continue

            if oid in orders:
                continue

            # customer identity -> deterministic customerid (must match generate_customer_insert.py)
            cname = norm(row.get("Customer Name"))
            email = norm(row.get("Email"))
            phone = norm(row.get("Phone"))
            ckey = customer_key(cname, email, phone)
            customer_id = id60_from_string(ckey, salt="customer")

            order_date = norm(row.get("Order Date"))
            status = norm(row.get("Order Status"))
            priority = norm(row.get("Order Priority"))

            orders[oid] = {
                "orderid": str(oid),
                "customerid": str(customer_id),
                "shipmentid": str(oid),  # by our shipment script
                "branchid": str(assign_branch(oid, branch_ids)),
                "status": status,
                "priority": priority,
                "date": order_date,
                # leave loyaltydiscount and earned_points default/0
            }

    return orders


def write_insert(out_path: Path, orders: Dict[int, Dict[str, Optional[str]]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cols = [
        "orderid",
        "customerid",
        "shipmentid",
        "branchid",
        "status",
        "priority",
        "date",
        "loyalitydiscount",
        "earned_points",
    ]

    rows_sql: List[str] = []

    for oid in sorted(orders.keys()):
        rec = orders[oid]
        row = "(" + ", ".join([
            rec["orderid"],
            rec["customerid"],
            rec["shipmentid"],
            rec["branchid"],
            sql_text_or_null(rec.get("status")),
            sql_text_or_null(rec.get("priority")),
            sql_timestamp_or_null(rec.get("date")),  # NOT NULL
            "0",  # loyalitydiscount
            "0",  # earned_points
        ]) + ")"
        rows_sql.append(row)

    with out_path.open("w", encoding="utf-8") as f:
        f.write('-- Auto-generated "Order" insert\n')
        f.write("-- One order row per Order ID\n")
        f.write("-- shipmentid = orderid (must match shipment script)\n")
        f.write("-- branchid assigned deterministically by orderid % num_branches\n\n")
        if rows_sql:
            f.write(f'INSERT INTO "Order" ({", ".join(cols)})\nVALUES\n')
            f.write(",\n".join(rows_sql))
            f.write(";\n")
        else:
            f.write("-- No orders found in input CSV.\n")

    print(f"[OK] Wrote: {out_path}  (rows: {len(rows_sql)})")


def main():
    ap = argparse.ArgumentParser(description='Generate a single multi-row INSERT for "Order" table.')
    ap.add_argument("--full", required=True, help="Path to BDBKala_full.csv")
    ap.add_argument("--bps", required=True, help="Path to branch_product_suppliers.csv (for branches)")
    ap.add_argument("--out", default="sql/07_insert_order.sql", help="Output .sql file path")
    args = ap.parse_args()

    full_path = Path(args.full).expanduser().resolve()
    bps_path = Path(args.bps).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    branch_ids = load_branches(bps_path)
    orders = collect_orders(full_path, branch_ids)
    write_insert(out_path, orders)


if __name__ == "__main__":
    main()
