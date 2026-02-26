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


def branch_id_from_name(name: str) -> int:
    h = hashlib.sha1(name.encode("utf-8")).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1


def product_id_from_key(name: str, category: Optional[str], subcategory: Optional[str]) -> int:
    raw = f"{name}|{category or ''}|{subcategory or ''}".encode("utf-8")
    h = hashlib.sha1(raw).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1


def deterministic_quantity(branchid: int, productid: int, max_qty: int = 200) -> int:
    """
    Deterministic pseudo-random quantity in [0, max_qty]
    based on hashing (branchid, productid).
    """
    raw = f"{branchid}|{productid}".encode("utf-8")
    h = hashlib.sha1(raw).hexdigest()
    # take 8 hex digits -> 32-bit int
    v = int(h[:8], 16)
    return v % (max_qty + 1)


# (branchid, productid)
Key = Tuple[int, int]


def collect_branch_products(bps_path: Path) -> Dict[Key, Dict[str, Optional[str]]]:
    """
    Build the set of (branch, product) pairs from branch_product_suppliers.csv
    """
    pairs: Dict[Key, Dict[str, Optional[str]]] = {}
    with bps_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bname = norm(row.get("branch_name"))
            pname = norm(row.get("product_name"))
            cat = norm(row.get("category"))
            sub = norm(row.get("sub_category"))
            if not bname or not pname:
                continue
            bid = branch_id_from_name(bname)
            pid = product_id_from_key(pname, cat, sub)
            k: Key = (bid, pid)
            if k not in pairs:
                pairs[k] = {"branchid": str(bid), "productid": str(pid)}
    return pairs


def compute_product_avg_unit_price(full_path: Path) -> Dict[int, float]:
    """
    From BDBKala_full.csv compute avg Unit Price per productid.
    """
    sums: Dict[int, float] = {}
    counts: Dict[int, int] = {}

    with full_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pname = norm(row.get("Product Name"))
            if not pname:
                continue
            cat = norm(row.get("Product Category"))
            sub = norm(row.get("Product Sub-Category"))
            pid = product_id_from_key(pname, cat, sub)

            price_str = sql_numeric_str_or_none(row.get("Unit Price"))
            if price_str is None:
                continue
            price = float(price_str)

            sums[pid] = sums.get(pid, 0.0) + price
            counts[pid] = counts.get(pid, 0) + 1

    avg: Dict[int, float] = {}
    for pid, total in sums.items():
        avg[pid] = total / counts[pid]
    return avg


def write_insert(
    out_path: Path,
    pairs: Dict[Key, Dict[str, Optional[str]]],
    avg_prices: Dict[int, float],
    max_qty: int,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cols = ["branchid", "productid", "saleprice", "quantity"]
    rows_sql: List[str] = []

    for (bid, pid) in sorted(pairs.keys()):
        saleprice = avg_prices.get(pid)
        saleprice_sql = f"{saleprice:.2f}" if saleprice is not None else "NULL"
        qty = deterministic_quantity(bid, pid, max_qty=max_qty)

        rows_sql.append(f"({bid}, {pid}, {saleprice_sql}, {qty})")

    with out_path.open("w", encoding="utf-8") as f:
        f.write("-- Auto-generated stocks insert\n")
        f.write("-- Rows come from branch_product_suppliers.csv (branch-product availability)\n")
        f.write("-- saleprice is avg(Unit Price) from BDBKala_full.csv when available\n")
        f.write(f"-- quantity is deterministic in [0, {max_qty}]\n\n")
        if rows_sql:
            f.write(f"INSERT INTO stocks ({', '.join(cols)})\nVALUES\n")
            f.write(",\n".join(rows_sql))
            f.write(";\n")
        else:
            f.write("-- No stock rows found.\n")

    print(f"[OK] Wrote: {out_path}  (rows: {len(rows_sql)})")


def main():
    ap = argparse.ArgumentParser(description="Generate a single multi-row INSERT for stocks table.")
    ap.add_argument("--bps", required=True, help="Path to branch_product_suppliers.csv")
    ap.add_argument("--full", required=True, help="Path to BDBKala_full.csv (for Unit Price)")
    ap.add_argument("--out", default="sql/10_insert_stocks.sql", help="Output .sql file path")
    ap.add_argument("--max_qty", type=int, default=200, help="Max quantity to generate (inclusive)")
    args = ap.parse_args()

    bps_path = Path(args.bps).expanduser().resolve()
    full_path = Path(args.full).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    pairs = collect_branch_products(bps_path)
    avg_prices = compute_product_avg_unit_price(full_path)
    write_insert(out_path, pairs, avg_prices, max_qty=args.max_qty)


if __name__ == "__main__":
    main()
