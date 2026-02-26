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
    # also safe for newlines in SQL string literals
    return s.replace("'", "''")


def sql_text_or_null(s: Optional[str]) -> str:
    s = norm(s)
    if s is None:
        return "NULL"
    return f"'{sql_escape_text(s)}'"


def sql_int_or_null(s: Optional[str]) -> str:
    s = norm(s)
    if s is None:
        return "NULL"
    try:
        return str(int(float(s)))
    except ValueError:
        return "NULL"


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


def id60_from_string(s: str, salt: str = "") -> int:
    """
    Deterministic positive bigint from string + salt.
    """
    raw = (salt + "|" + s).encode("utf-8")
    h = hashlib.sha1(raw).hexdigest()
    val = int(h[:15], 16)
    return val if val != 0 else 1


def customer_key(name: Optional[str], email: Optional[str], phone: Optional[str]) -> str:
    """
    Choose a stable identity key for dedup:
    prefer email, else phone, else name.
    """
    if email:
        return "email:" + email.lower()
    if phone:
        return "phone:" + phone
    return "name:" + (name or "UNKNOWN")


def map_nature(segment: Optional[str]) -> Optional[str]:
    seg = norm(segment)
    if not seg:
        return None
    if seg.lower() == "consumer":
        return "consumer"
    return "company_buyer"


def load_wallet_balances(wallet_path: Path) -> Dict[str, Dict[str, Optional[str]]]:
    """
    wallet_balances.csv:
      customer_name,customer_email,customer_phone,wallet_balance
    Return mapping keyed by identity key (email->phone->name) to wallet info.
    """
    out: Dict[str, Dict[str, Optional[str]]] = {}

    if not wallet_path.exists():
        return out

    with wallet_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = norm(row.get("customer_name"))
            email = norm(row.get("customer_email"))
            phone = norm(row.get("customer_phone"))
            bal = norm(row.get("wallet_balance"))

            k = customer_key(name, email, phone)
            out[k] = {
                "name": name,
                "email": email,
                "phone": phone,
                "balance": bal,
            }
    return out


def collect_customers(full_path: Path) -> Dict[str, Dict[str, Optional[str]]]:
    """
    BDBKala_full.csv customers:
      Customer Name, Customer Age, Email, Phone, Gender, Income, Customer Segment
    Deduplicate by identity key.
    """
    customers: Dict[str, Dict[str, Optional[str]]] = {}

    with full_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = norm(row.get("Customer Name"))
            if not name:
                continue

            email = norm(row.get("Email"))
            phone = norm(row.get("Phone"))
            age = norm(row.get("Customer Age"))
            gender = norm(row.get("Gender"))
            income = norm(row.get("Income"))  # will store as text
            segment = norm(row.get("Customer Segment"))

            k = customer_key(name, email, phone)
            rec = customers.get(k)
            if rec is None:
                customers[k] = {
                    "name": name,
                    "email": email,
                    "phone": phone,
                    "age": age,
                    "gender": gender,
                    "incomelevel": income,
                    "nature": map_nature(segment),
                    # not in CSV, keep null for now
                    "relationstatus": None,
                    "taxstatus": None,
                    "membershiptier": None,
                    "creditlimit": None,
                }
            else:
                # fill missing values if new row has them
                for field, val in [
                    ("email", email),
                    ("phone", phone),
                    ("age", age),
                    ("gender", gender),
                    ("incomelevel", income),
                ]:
                    if rec.get(field) is None and val is not None:
                        rec[field] = val
                if rec.get("nature") is None:
                    rec["nature"] = map_nature(segment)

    return customers


def merge_wallet_info(
    customers: Dict[str, Dict[str, Optional[str]]],
    wallets: Dict[str, Dict[str, Optional[str]]],
) -> None:
    """
    If wallet row exists for a customer key, set balance.
    Also, if a customer not found in full.csv but exists in wallet file, add it.
    """
    # attach balances
    for k, w in wallets.items():
        if k in customers:
            if customers[k].get("balance") is None:
                customers[k]["balance"] = w.get("balance")
        else:
            # add wallet-only customers (rare but possible)
            customers[k] = {
                "name": w.get("name") or "UNKNOWN",
                "email": w.get("email"),
                "phone": w.get("phone"),
                "age": None,
                "gender": None,
                "incomelevel": None,
                "nature": None,
                "relationstatus": None,
                "taxstatus": None,
                "membershiptier": None,
                "creditlimit": None,
                "balance": w.get("balance"),
            }

    # ensure all have a balance field (default uses DB default, but we can write explicit 0)
    for rec in customers.values():
        if "balance" not in rec:
            rec["balance"] = None


def write_insert(out_path: Path, customers: Dict[str, Dict[str, Optional[str]]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # We will include columns that exist from CSV + required NOT NULL columns.
    # customerid + name must be present. We'll also include walletid/balance if available.
    cols = [
        "customerid",
        "walletid",
        "balance",
        "name",
        "age",
        "gender",
        "phone",
        "email",
        "incomelevel",
        "creditlimit",
        "membershiptier",
        "totalpoints",
        "taxstatus",
        "nature",
        "relationstatus",
    ]

    rows_sql: List[str] = []

    # stable ordering by name then email
    def sort_key(item: Tuple[str, Dict[str, Optional[str]]]):
        k, rec = item
        return ((rec.get("name") or "").lower(), (rec.get("email") or "").lower(), k)

    for k, rec in sorted(customers.items(), key=sort_key):
        ident = k  # e.g. "email:..." or "phone:..." or "name:..."
        cid = id60_from_string(ident, salt="customer")
        wid = id60_from_string(ident, salt="wallet")

        # name NOT NULL
        name = rec.get("name") or "UNKNOWN"

        row = "(" + ", ".join([
            str(cid),
            str(wid),  # walletid (nullable in schema, but we populate it so wallettransaction FK works later)
            sql_numeric_or_null(rec.get("balance")) if rec.get("balance") is not None else "0",
            sql_text_or_null(name),
            sql_int_or_null(rec.get("age")),
            sql_text_or_null(rec.get("gender")),
            sql_text_or_null(rec.get("phone")),
            sql_text_or_null(rec.get("email")),
            sql_text_or_null(rec.get("incomelevel")),
            sql_numeric_or_null(rec.get("creditlimit")),
            sql_text_or_null(rec.get("membershiptier")),
            "0",  # totalpoints default; points computed later in phase 2 if needed
            sql_text_or_null(rec.get("taxstatus")),
            sql_text_or_null(rec.get("nature")),
            sql_text_or_null(rec.get("relationstatus")),
        ]) + ")"
        rows_sql.append(row)

    with out_path.open("w", encoding="utf-8") as f:
        f.write("-- Auto-generated customer insert\n")
        f.write("-- One INSERT statement inserting all customers\n")
        f.write("-- customerid/walletid are deterministic; balance comes from wallet_balances.csv when available\n\n")
        if rows_sql:
            f.write(f"INSERT INTO customer ({', '.join(cols)})\nVALUES\n")
            f.write(",\n".join(rows_sql))
            f.write(";\n")
        else:
            f.write("-- No customers found in input CSV(s).\n")

    print(f"[OK] Wrote: {out_path}  (rows: {len(rows_sql)})")


def main():
    ap = argparse.ArgumentParser(description="Generate a single multi-row INSERT for customer table.")
    ap.add_argument("--full", required=True, help="Path to BDBKala_full.csv")
    ap.add_argument("--wallet", required=False, default="", help="Path to wallet_balances.csv")
    ap.add_argument("--out", default="sql/05_insert_customer.sql", help="Output .sql file path")
    args = ap.parse_args()

    full_path = Path(args.full).expanduser().resolve()
    wallet_path = Path(args.wallet).expanduser().resolve() if args.wallet else None
    out_path = Path(args.out).expanduser().resolve()

    customers = collect_customers(full_path)

    wallets = {}
    if wallet_path and wallet_path.exists():
        wallets = load_wallet_balances(wallet_path)

    merge_wallet_info(customers, wallets)
    write_insert(out_path, customers)


if __name__ == "__main__":
    main()
