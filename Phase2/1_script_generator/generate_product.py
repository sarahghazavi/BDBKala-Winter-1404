#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Dict, Tuple, Optional, Any, List

ProductKey = Tuple[str, Optional[str], Optional[str]]  # (name, category, subcategory)


def norm(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s2 = s.strip()
    return s2 if s2 != "" else None


def sql_escape_text(s: str) -> str:
    """Escape text for SQL single-quoted literal."""
    return s.replace("'", "''")


def sql_literal(value: Any) -> str:
    """Convert python value to SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    # Decimal strings should already be validated; treat as text if passed in here.
    return f"'{sql_escape_text(str(value))}'"


def sql_numeric_or_null(s: Optional[str]) -> Optional[str]:
    """Return normalized numeric string or None."""
    s = norm(s)
    if s is None:
        return None
    # accept "95356.99" or "0.21" etc.
    # remove commas if any (e.g. "1,234.56")
    s = s.replace(",", "")
    try:
        float(s)
        return s
    except ValueError:
        return None


def product_id_from_key(key: ProductKey) -> int:
    """
    Deterministic BIGINT from key using SHA1.
    Keeps it positive and within BIGINT range.
    """
    raw = f"{key[0]}|{key[1] or ''}|{key[2] or ''}".encode("utf-8")
    h = hashlib.sha1(raw).hexdigest()  # 40 hex chars
    # Take first 15 hex digits (~60 bits) => fits in signed bigint safely
    val = int(h[:15], 16)
    # avoid 0 just in case
    return val if val != 0 else 1


def load_properties(props_path: Path) -> Dict[ProductKey, str]:
    """
    Load product properties:
      product_name,category,sub_category,attributes (JSON string)
    Return mapping -> canonical JSON text (minified) or raw if already json.
    """
    props: Dict[ProductKey, str] = {}

    if not props_path.exists():
        return props

    with props_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = norm(row.get("product_name"))
            cat = norm(row.get("category"))
            sub = norm(row.get("sub_category"))
            attrs = row.get("attributes")
            if not name or attrs is None:
                continue

            # Ensure attributes is valid JSON; if not, store as NULL later.
            attrs = attrs.strip()
            try:
                obj = json.loads(attrs)
                attrs_min = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
                props[(name, cat, sub)] = attrs_min
            except json.JSONDecodeError:
                # keep raw string; could still be valid-ish JSON
                props[(name, cat, sub)] = attrs

    return props


def collect_products_from_full(full_path: Path) -> Dict[ProductKey, Dict[str, Optional[str]]]:
    """
    From BDBKala_full.csv collect product fields:
      - name, category, subcategory, costprice (Unit Cost), discount
    Keep the first seen non-null cost/discount for a product.
    """
    products: Dict[ProductKey, Dict[str, Optional[str]]] = {}

    if not full_path.exists():
        return products

    with full_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = norm(row.get("Product Name"))
            cat = norm(row.get("Product Category"))
            sub = norm(row.get("Product Sub-Category"))

            if not name:
                continue

            key: ProductKey = (name, cat, sub)

            unit_cost = sql_numeric_or_null(row.get("Unit Cost"))
            discount = sql_numeric_or_null(row.get("Discount"))
            taxstatus = norm(row.get("Tax Status")
                             or row.get("taxstatus")
                             or row.get("TaxStatus")
                             or row.get("Tax")
                             )

            rec = products.get(key)
            if rec is None:
                rec = {
                    "name": name,
                    "category": cat,
                    "subcategory": sub,
                    "taxstatus": taxstatus,
                    "costprice": unit_cost,
                    "discount": discount,
                }
                products[key] = rec
            else:
                # fill missing fields if we encounter a better row later
                if rec.get("costprice") is None and unit_cost is not None:
                    rec["costprice"] = unit_cost
                if rec.get("discount") is None and discount is not None:
                    rec["discount"] = discount
                if rec.get("taxstatus") is None and taxstatus is not None:
                    rec["taxstatus"] = taxstatus

    return products


def write_insert_sql(
    out_path: Path,
    products: Dict[ProductKey, Dict[str, Optional[str]]],
    props: Dict[ProductKey, str],
) -> None:
    """
    Generate ONE INSERT statement with many VALUES rows.
    Columns included: productid, name, category, subcategory, costprice, discount, specifications
    (taxstatus omitted because not present in provided CSVs)
    """
    # Sort for stable output
    keys_sorted = sorted(products.keys(), key=lambda k: (k[0].lower(), (k[1] or "").lower(), (k[2] or "").lower()))

    cols = ["productid", "name", "category", "subcategory", "taxstatus", "costprice", "discount", "specifications"]

    values_sql: List[str] = []
    for key in keys_sorted:
        rec = products[key]
        pid = product_id_from_key(key)

        name = rec["name"]
        category = rec.get("category")
        subcategory = rec.get("subcategory")
        taxstatus = rec.get("taxstatus")
        costprice = rec.get("costprice")
        discount = rec.get("discount")

        specs_json = props.get(key)
        if specs_json is not None:
            # store JSON as jsonb literal
            # Use ::jsonb to ensure correct type
            specs_literal = f"'{sql_escape_text(specs_json)}'::jsonb"
        else:
            specs_literal = "NULL"

        row_parts = [
            str(pid),                                       # productid BIGINT
            sql_literal(name),                              # name TEXT NOT NULL
            sql_literal(category),                          # category TEXT
            sql_literal(subcategory),                       # subcategory TEXT
            sql_literal(taxstatus),
            costprice if costprice is not None else "NULL", # numeric
            discount if discount is not None else "NULL",   # numeric
            specs_literal,                                  # jsonb
        ]
        values_sql.append("(" + ",".join(row_parts) + ")")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as f:
        f.write("-- Auto-generated product insert\n")
        f.write("-- One INSERT statement inserting all products\n\n")
        f.write(f"INSERT INTO product ({', '.join(cols)})\nVALUES\n")
        if values_sql:
            f.write(",\n".join(values_sql))
            f.write(";\n")
        else:
            # Still produce a valid SQL file
            f.write("-- No rows found in input CSV(s).\n")

    print(f"[OK] Wrote: {out_path}  (rows: {len(values_sql)})")


def main():
    ap = argparse.ArgumentParser(description="Generate a single multi-row INSERT for product table.")
    ap.add_argument("--full", required=True, help="Path to BDBKala_full.csv")
    ap.add_argument("--props", required=False, default="", help="Path to products_properties.csv (or file without .csv)")
    ap.add_argument("--out", required=False, default="sql/02_insert_product.sql", help="Output .sql file path")
    args = ap.parse_args()

    full_path = Path(args.full).expanduser().resolve()

    props_path = Path(args.props).expanduser().resolve() if args.props else None
    # Allow filename 'products_properties' without extension
    if props_path and (not props_path.exists()) and props_path.suffix == "":
        # try adding .csv
        alt = Path(str(props_path) + ".csv")
        if alt.exists():
            props_path = alt

    out_path = Path(args.out).expanduser().resolve()

    products = collect_products_from_full(full_path)

    props: Dict[ProductKey, str] = {}
    if props_path and props_path.exists():
        props = load_properties(props_path)

    # Merge: ensure products from properties file also exist (even if not in full)
    for key in props.keys():
        if key not in products:
            name, cat, sub = key
            products[key] = {
                "name": name,
                "category": cat,
                "subcategory": sub,
                "costprice": None,
                "discount": None,
            }

    write_insert_sql(out_path, products, props)


if __name__ == "__main__":
    main()

