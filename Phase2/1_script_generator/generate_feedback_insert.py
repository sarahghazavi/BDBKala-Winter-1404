#!/usr/bin/env python3
import argparse
import csv
import hashlib
from pathlib import Path
from typing import Optional, Dict, Tuple, List, Set

csv.field_size_limit(10**9)

def norm(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s2 = s.strip()
    return s2 if s2 != "" else None

def sql_escape_text(s: str) -> str:
    return s.replace("'", "''")

def product_id_from_key(name: str, category: Optional[str], subcategory: Optional[str]) -> int:
    raw = f"{name}|{category or ''}|{subcategory or ''}".encode("utf-8")
    h = hashlib.sha1(raw).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1

def feedback_id(orderid: int, productid: int) -> int:
    raw = f"{orderid}|{productid}".encode("utf-8")
    h = hashlib.sha1(raw).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1

def load_valid_order_ids(full_path: Path) -> Set[int]:
    ids: Set[int] = set()
    with full_path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            oid = norm(row.get("Order ID"))
            if not oid:
                continue
            try:
                ids.add(int(oid))
            except ValueError:
                pass
    return ids

def load_valid_product_ids(full_path: Path, props_path: Optional[Path]) -> Set[int]:
    ids: Set[int] = set()

    # from BDBKala_full.csv
    with full_path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            pname = norm(row.get("Product Name"))
            if not pname:
                continue
            cat = norm(row.get("Product Category"))
            sub = norm(row.get("Product Sub-Category"))
            ids.add(product_id_from_key(pname, cat, sub))

    # from products_properties(.csv)
    if props_path and props_path.exists():
        with props_path.open("r", newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                pname = norm(row.get("product_name"))
                if not pname:
                    continue
                cat = norm(row.get("category"))
                sub = norm(row.get("sub_category"))
                ids.add(product_id_from_key(pname, cat, sub))

    return ids

Key = Tuple[int, int]  # (orderid, productid)

def collect_feedback(
    reviews_path: Path,
    valid_orders: Set[int],
    valid_products: Set[int],
    max_image_chars: Optional[int]
) -> Dict[Key, Dict[str, Optional[str]]]:

    out: Dict[Key, Dict[str, Optional[str]]] = {}

    total = kept = dropped_fk = 0

    with reviews_path.open("r", newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f, strict=False)

        for row in reader:
            total += 1
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

            # FK filter
            if oid not in valid_orders or pid not in valid_products:
                dropped_fk += 1
                continue

            k: Key = (oid, pid)
            if k in out:
                continue

            comment = row.get("Comment")
            img = row.get("Image")
            if img is not None and max_image_chars is not None and len(img) > max_image_chars:
                img = img[:max_image_chars]

            out[k] = {
                "orderid": str(oid),
                "productid": str(pid),
                "comment": comment,
                "imagestring": img,
            }
            kept += 1

    print(f"[INFO] reviews rows read: {total}")
    print(f"[INFO] feedback rows kept: {kept}")
    print(f"[INFO] dropped due to missing Order/Product FK: {dropped_fk}")
    return out


def write_insert(out_path: Path, feedback: Dict[Key, Dict[str, Optional[str]]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cols = ["feedbackid", "orderid", "productid", "rating", "comment", "ispublic", "imagestring"]
    rows_sql: List[str] = []

    for (oid, pid) in sorted(feedback.keys()):
        rec = feedback[(oid, pid)]
        fid = feedback_id(oid, pid)

        comment = rec.get("comment")
        img = rec.get("imagestring")

        comment_sql = "NULL" if comment is None or str(comment).strip() == "" else f"'{sql_escape_text(str(comment))}'"
        img_sql = "NULL" if img is None or str(img).strip() == "" else f"'{sql_escape_text(str(img))}'"

        rows_sql.append("(" + ", ".join([
            str(fid),
            rec["orderid"],
            rec["productid"],
            "NULL",         # rating not present
            comment_sql,
            "TRUE",         # ispublic default
            img_sql,
        ]) + ")")

    with out_path.open("w", encoding="utf-8") as f:
        f.write("-- Auto-generated feedback insert\n\n")
        if rows_sql:
            f.write(f"INSERT INTO feedback ({', '.join(cols)})\nVALUES\n")
            f.write(",\n".join(rows_sql))
            f.write(";\n")
        else:
            f.write("-- No feedback rows found after FK filtering.\n")

    print(f"[OK] Wrote: {out_path}  (rows: {len(rows_sql)})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", required=True, help="Path to BDBKala_full.csv (for valid orders/products)")
    ap.add_argument("--props", default="", help="Path to products_properties.csv (optional)")
    ap.add_argument("--reviews", required=True, help="Path to reviews.csv")
    ap.add_argument("--out", default="insert_feedback.sql")
    ap.add_argument("--max_image_chars", type=int, default=200000, help="0 to disable truncation")
    args = ap.parse_args()

    full_path = Path(args.full).expanduser().resolve()
    props_path = Path(args.props).expanduser().resolve() if args.props else None
    reviews_path = Path(args.reviews).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    max_image = None if args.max_image_chars == 0 else args.max_image_chars

    valid_orders = load_valid_order_ids(full_path)
    valid_products = load_valid_product_ids(full_path, props_path)

    feedback = collect_feedback(reviews_path, valid_orders, valid_products, max_image)
    write_insert(out_path, feedback)


if __name__ == "__main__":
    main()
