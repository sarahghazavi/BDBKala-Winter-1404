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


def sql_int_or_none(s: Optional[str]) -> Optional[int]:
    s = norm(s)
    if s is None:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def branch_id_from_name(name: str) -> int:
    # must match generate_branch_insert.py
    h = hashlib.sha1(name.encode("utf-8")).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1


def supplier_id_from_name(name: str) -> int:
    # must match generate_supplier_insert.py
    h = hashlib.sha1(name.encode("utf-8")).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1


def product_id_from_key(name: str, category: Optional[str], subcategory: Optional[str]) -> int:
    # must match product generator
    raw = f"{name}|{category or ''}|{subcategory or ''}".encode("utf-8")
    h = hashlib.sha1(raw).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1


Key = Tuple[int, int, int]  # (branchid, supplierid, productid)


def collect_supplies(bps_path: Path) -> Dict[Key, Dict[str, Optional[str]]]:
    supplies: Dict[Key, Dict[str, Optional[str]]] = {}

    with bps_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bname = norm(row.get("branch_name"))
            sname = norm(row.get("supplier_name"))
            pname = norm(row.get("product_name"))
            cat = norm(row.get("category"))
            sub = norm(row.get("sub_category"))

            if not bname or not sname or not pname:
                continue

            bid = branch_id_from_name(bname)
            sid = supplier_id_from_name(sname)
            pid = product_id_from_key(pname, cat, sub)

            supply_price = sql_numeric_str_or_none(row.get("supply_price"))
            lead_days = sql_int_or_none(row.get("lead_time_days"))

            k: Key = (bid, sid, pid)
            if k in supplies:
                continue

            supplies[k] = {
                "branchid": str(bid),
                "supplierid": str(sid),
                "productid": str(pid),
                "supplyprice": supply_price,
                "lead_days": str(lead_days) if lead_days is not None else None,
            }

    return supplies


def lead_days_to_timestamp_sql(lead_days: Optional[str]) -> str:
    """
    Store lead time (days) into a timestamp column.
    We'll encode as: '2020-01-01'::timestamp + lead_days * interval '1 day'
    """
    if lead_days is None:
        return "NULL"
    try:
        d = int(lead_days)
        return f"('2020-01-01'::timestamp + ({d} * INTERVAL '1 day'))"
    except ValueError:
        return "NULL"


def write_insert(out_path: Path, supplies: Dict[Key, Dict[str, Optional[str]]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cols = ["branchid", "supplierid", "productid", "supplyprice", "supplytime"]
    rows_sql: List[str] = []

    for (bid, sid, pid) in sorted(supplies.keys()):
        rec = supplies[(bid, sid, pid)]
        row = "(" + ", ".join([
            rec["branchid"],
            rec["supplierid"],
            rec["productid"],
            rec["supplyprice"] if rec.get("supplyprice") is not None else "NULL",
            lead_days_to_timestamp_sql(rec.get("lead_days")),
        ]) + ")"
        rows_sql.append(row)

    with out_path.open("w", encoding="utf-8") as f:
        f.write("-- Auto-generated supplies insert\n")
        f.write("-- supplytime encodes lead_time_days as a timestamp offset from 2020-01-01\n\n")
        if rows_sql:
            f.write(f"INSERT INTO supplies ({', '.join(cols)})\nVALUES\n")
            f.write(",\n".join(rows_sql))
            f.write(";\n")
        else:
            f.write("-- No supplies rows found in input CSV.\n")

    print(f"[OK] Wrote: {out_path}  (rows: {len(rows_sql)})")


def main():
    ap = argparse.ArgumentParser(description="Generate a single multi-row INSERT for supplies table.")
    ap.add_argument("--bps", required=True, help="Path to branch_product_suppliers.csv")
    ap.add_argument("--out", default="sql/09_insert_supplies.sql", help="Output .sql file path")
    args = ap.parse_args()

    bps_path = Path(args.bps).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    supplies = collect_supplies(bps_path)
    write_insert(out_path, supplies)


if __name__ == "__main__":
    main()
