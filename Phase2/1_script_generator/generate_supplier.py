#!/usr/bin/env python3
import argparse
import csv
import hashlib
from pathlib import Path
from typing import Optional, Dict, List


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


def supplier_id_from_name(name: str) -> int:
    """
    Deterministic BIGINT id from supplier name.
    """
    h = hashlib.sha1(name.encode("utf-8")).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1


SupplierRec = Dict[str, Optional[str]]


def collect_suppliers(bps_path: Path) -> Dict[str, SupplierRec]:
    suppliers: Dict[str, SupplierRec] = {}

    with bps_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sname = norm(row.get("supplier_name"))
            if not sname:
                continue

            phone = norm(row.get("supplier_phone"))
            addr = norm(row.get("supplier_address"))

            rec = suppliers.get(sname)
            if rec is None:
                suppliers[sname] = {
                    "name": sname,
                    "phone": phone,
                    "address": addr,
                }
            else:
                if rec.get("phone") is None and phone is not None:
                    rec["phone"] = phone
                if rec.get("address") is None and addr is not None:
                    rec["address"] = addr

    return suppliers


def write_insert(out_path: Path, suppliers: Dict[str, SupplierRec]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cols = ["supplierid", "name", "phone", "address"]

    rows_sql: List[str] = []
    for sname in sorted(suppliers.keys(), key=lambda x: x.lower()):
        rec = suppliers[sname]
        sid = supplier_id_from_name(sname)

        rows_sql.append("(" + ", ".join([
            str(sid),
            sql_text_or_null(rec.get("name")),
            sql_text_or_null(rec.get("phone")),
            sql_text_or_null(rec.get("address")),
        ]) + ")")

    with out_path.open("w", encoding="utf-8") as f:
        f.write("-- Auto-generated supplier insert\n")
        f.write("-- One INSERT statement inserting all suppliers\n\n")
        if rows_sql:
            f.write(f"INSERT INTO supplier ({', '.join(cols)})\nVALUES\n")
            f.write(",\n".join(rows_sql))
            f.write(";\n")
        else:
            f.write("-- No suppliers found in input CSV.\n")

    print(f"[OK] Wrote: {out_path}  (rows: {len(rows_sql)})")


def main():
    ap = argparse.ArgumentParser(description="Generate a single multi-row INSERT for supplier table.")
    ap.add_argument("--bps", required=True, help="Path to branch_product_suppliers.csv")
    ap.add_argument("--out", default="sql/04_insert_supplier.sql", help="Output .sql file path")
    args = ap.parse_args()

    bps_path = Path(args.bps).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    suppliers = collect_suppliers(bps_path)
    write_insert(out_path, suppliers)


if __name__ == "__main__":
    main()
