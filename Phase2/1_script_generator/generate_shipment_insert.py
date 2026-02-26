#!/usr/bin/env python3
import argparse
import csv
from pathlib import Path
from typing import Optional, Dict, List, Tuple


def norm(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s2 = s.strip()
    return s2 if s2 != "" else None


def sql_escape_text(s: str) -> str:
    # safe for newlines too
    return s.replace("'", "''")


def sql_text_or_null(s: Optional[str]) -> str:
    s = norm(s)
    if s is None:
        return "NULL"
    return f"'{sql_escape_text(s)}'"


def sql_numeric_or_null(s: Optional[str]) -> str:
    s = norm(s)
    if s is None:
        return "NULL"
    s = s.replace(",", "")
    try:
        float(s)
        return s
    except ValueError:
        return "NULL"


def sql_timestamp_or_null(s: Optional[str]) -> str:
    """
    CSV has dates like 2020-01-16 (no time).
    We'll store as timestamp 'YYYY-MM-DD 00:00:00' by casting.
    """
    s = norm(s)
    if s is None:
        return "NULL"
    return f"'{sql_escape_text(s)}'::timestamp"


def parse_packaging(packaging: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Examples: 'Box Large', 'Envelope Small Bubble' (possible)
    We attempt:
      packagetype: first word (Box/Envelope/...)
      packagesize: second word if exists (Large/Small/...)
      packagestate: remaining keywords if any (Bubble/Normal/...)
    All stored as TEXT so it's fine.
    """
    p = norm(packaging)
    if not p:
        return None, None, None

    parts = [x for x in p.replace("-", " ").split() if x.strip()]
    if not parts:
        return None, None, None

    ptype = parts[0]
    psize = parts[1] if len(parts) >= 2 else None
    pstate = " ".join(parts[2:]) if len(parts) >= 3 else None
    return pstate, psize, ptype


def collect_shipments(full_path: Path) -> Dict[int, Dict[str, Optional[str]]]:
    """
    Create one shipment per order, keyed by shipmentid=Order ID.
    """
    shipments: Dict[int, Dict[str, Optional[str]]] = {}

    with full_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            oid = norm(row.get("Order ID"))
            if not oid:
                continue
            try:
                shipment_id = int(oid)
            except ValueError:
                # if not numeric, skip
                continue

            # only need one shipment row per order
            if shipment_id in shipments:
                continue

            postal = norm(row.get("Zip Code"))
            city = norm(row.get("City"))
            region = norm(row.get("Region"))
            ship_cost = norm(row.get("Shipping Cost"))
            ship_date = norm(row.get("Ship Date"))
            address = norm(row.get("Shipping Address"))
            ship_type = norm(row.get("Shipping Method"))
            ship_method = norm(row.get("Ship Mode"))
            packaging = norm(row.get("Packaging"))

            pack_state, pack_size, pack_type = parse_packaging(packaging)

            shipments[shipment_id] = {
                "shipmentid": str(shipment_id),
                "postalcode": postal,
                "destcity": city,
                "destregion": region,
                "shippingcost": ship_cost,
                "packagestate": pack_state,
                "packagesize": pack_size,
                "packagetype": pack_type,
                "shipdate": ship_date,
                "shipmethod": ship_method,
                "shiptype": ship_type,
                "address": address,
            }

    return shipments


def write_insert(out_path: Path, shipments: Dict[int, Dict[str, Optional[str]]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cols = [
        "shipmentid",
        "postalcode",
        "destcity",
        "destregion",
        "shippingcost",
        "packagestate",
        "packagesize",
        "packagetype",
        "shipdate",
        "shipmethod",
        "shiptype",
        "address",
    ]

    rows_sql: List[str] = []

    for sid in sorted(shipments.keys()):
        rec = shipments[sid]
        row = "(" + ", ".join([
            rec["shipmentid"],  # numeric already
            sql_text_or_null(rec.get("postalcode")),
            sql_text_or_null(rec.get("destcity")),
            sql_text_or_null(rec.get("destregion")),
            sql_numeric_or_null(rec.get("shippingcost")) if rec.get("shippingcost") is not None else "0",
            sql_text_or_null(rec.get("packagestate")),
            sql_text_or_null(rec.get("packagesize")),
            sql_text_or_null(rec.get("packagetype")),
            sql_timestamp_or_null(rec.get("shipdate")),
            sql_text_or_null(rec.get("shipmethod")),
            sql_text_or_null(rec.get("shiptype")),
            sql_text_or_null(rec.get("address")),
        ]) + ")"
        rows_sql.append(row)

    with out_path.open("w", encoding="utf-8") as f:
        f.write("-- Auto-generated shipment insert\n")
        f.write("-- One shipment row per Order (shipmentid = Order ID)\n\n")
        if rows_sql:
            f.write(f"INSERT INTO shipment ({', '.join(cols)})\nVALUES\n")
            f.write(",\n".join(rows_sql))
            f.write(";\n")
        else:
            f.write("-- No shipments found in input CSV.\n")

    print(f"[OK] Wrote: {out_path}  (rows: {len(rows_sql)})")


def main():
    ap = argparse.ArgumentParser(description="Generate a single multi-row INSERT for shipment table.")
    ap.add_argument("--full", required=True, help="Path to BDBKala_full.csv")
    ap.add_argument("--out", default="sql/06_insert_shipment.sql", help="Output .sql file path")
    args = ap.parse_args()

    full_path = Path(args.full).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    shipments = collect_shipments(full_path)
    write_insert(out_path, shipments)


if __name__ == "__main__":
    main()
