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


def manager_id_from_name(name: str) -> int:
    """
    Must match the function used in generate_manager_insert.py
    """
    h = hashlib.sha1(name.encode("utf-8")).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1


def branch_id_from_name(name: str) -> int:
    """
    Deterministic BIGINT id from branch name.
    """
    h = hashlib.sha1(name.encode("utf-8")).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1


BranchRec = Dict[str, Optional[str]]


def collect_branches(bps_path: Path) -> Dict[str, BranchRec]:
    branches: Dict[str, BranchRec] = {}

    with bps_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bname = norm(row.get("branch_name"))
            if not bname:
                continue

            addr = norm(row.get("address"))
            phone = norm(row.get("phone"))
            mname = norm(row.get("manager_name"))

            rec = branches.get(bname)
            if rec is None:
                branches[bname] = {
                    "name": bname,
                    "address": addr,
                    "phone": phone,
                    "manager_name": mname,
                }
            else:
                # fill missing pieces if we see better data later
                if rec.get("address") is None and addr is not None:
                    rec["address"] = addr
                if rec.get("phone") is None and phone is not None:
                    rec["phone"] = phone
                if rec.get("manager_name") is None and mname is not None:
                    rec["manager_name"] = mname

    return branches


def write_insert(out_path: Path, branches: Dict[str, BranchRec]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # columns we will include (totalsales left to default)
    cols = ["branchid", "managerid", "name", "phone", "address"]

    rows_sql: List[str] = []

    # stable order
    for bname in sorted(branches.keys(), key=lambda x: x.lower()):
        rec = branches[bname]

        manager_name = rec.get("manager_name")
        if not manager_name:
            # managerid is NOT NULL in schema, so we must have one
            # if missing, we deterministically create a placeholder manager name
            manager_name = f"UNKNOWN_MANAGER_FOR::{bname}"

        bid = branch_id_from_name(bname)
        mid = manager_id_from_name(manager_name)

        row = "(" + ", ".join([
            str(bid),
            str(mid),
            sql_text_or_null(rec.get("name")),
            sql_text_or_null(rec.get("phone")),
            sql_text_or_null(rec.get("address")),
        ]) + ")"
        rows_sql.append(row)

    with out_path.open("w", encoding="utf-8") as f:
        f.write("-- Auto-generated branch insert\n")
        f.write("-- One INSERT statement inserting all branches\n")
        f.write("-- Note: totalsales is left as DEFAULT (0) since CSV doesn't provide it\n\n")
        if rows_sql:
            f.write(f"INSERT INTO branch ({', '.join(cols)})\nVALUES\n")
            f.write(",\n".join(rows_sql))
            f.write(";\n")
        else:
            f.write("-- No branches found in input CSV.\n")

    print(f"[OK] Wrote: {out_path}  (rows: {len(rows_sql)})")


def main():
    ap = argparse.ArgumentParser(description="Generate a single multi-row INSERT for branch table.")
    ap.add_argument("--bps", required=True, help="Path to branch_product_suppliers.csv")
    ap.add_argument("--out", default="sql/03_insert_branch.sql", help="Output .sql file path")
    args = ap.parse_args()

    bps_path = Path(args.bps).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    branches = collect_branches(bps_path)
    write_insert(out_path, branches)


if __name__ == "__main__":
    main()
