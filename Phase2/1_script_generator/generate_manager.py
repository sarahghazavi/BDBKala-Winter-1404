#!/usr/bin/env python3
import argparse
import csv
import hashlib
from pathlib import Path
from typing import Optional, Set, List


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
    Deterministic BIGINT id from manager name.
    Uses SHA1 and takes first 15 hex chars (~60 bits) => safe positive bigint.
    """
    h = hashlib.sha1(name.encode("utf-8")).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1


def collect_manager_names(branch_suppliers_path: Path) -> Set[str]:
    names: Set[str] = set()
    with branch_suppliers_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            m = norm(row.get("manager_name"))
            if m:
                names.add(m)
    return names


def write_insert(out_path: Path, manager_names: Set[str]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows: List[str] = []

    for name in sorted(manager_names, key=lambda x: x.lower()):
        mid = manager_id_from_name(name)
        rows.append(f"({mid}, {sql_text_or_null(name)})")

    with out_path.open("w", encoding="utf-8") as f:
        f.write("-- Auto-generated manager insert\n")
        f.write("-- One INSERT statement inserting all managers\n\n")
        if rows:
            f.write("INSERT INTO manager (managerid, name)\nVALUES\n")
            f.write(",\n".join(rows))
            f.write(";\n")
        else:
            f.write("-- No managers found in input CSV.\n")

    print(f"[OK] Wrote: {out_path}  (rows: {len(rows)})")


def main():
    ap = argparse.ArgumentParser(description="Generate a single multi-row INSERT for manager table.")
    ap.add_argument("--bps", required=True, help="Path to branch_product_suppliers.csv")
    ap.add_argument("--out", default="sql/02_insert_manager.sql", help="Output .sql file path")
    args = ap.parse_args()

    bps_path = Path(args.bps).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    manager_names = collect_manager_names(bps_path)
    write_insert(out_path, manager_names)


if __name__ == "__main__":
    main()
