#!/usr/bin/env python3
import argparse
import csv
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Tuple, List

csv.field_size_limit(10**9)

def norm(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s2 = s.strip()
    return s2 if s2 != "" else None

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

def wallet_id_for_customer(ckey: str) -> int:
    # MUST match generate_customer_insert.py
    return id60_from_string(ckey, salt="wallet")

def sql_escape_text(s: str) -> str:
    return s.replace("'", "''")

def sql_text(s: str) -> str:
    return f"'{sql_escape_text(s)}'"

def sql_timestamp(dt: datetime) -> str:
    return sql_text(dt.strftime("%Y-%m-%d %H:%M:%S"))

def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    s = norm(date_str)
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

def to_float(s: Optional[str]) -> Optional[float]:
    s = norm(s)
    if not s:
        return None
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None

def money2(x: float) -> str:
    return f"{x:.2f}"

def load_wallet_balances(wallet_path: Path) -> Dict[str, float]:
    """
    wallet_balances.csv:
      customer_name,customer_email,customer_phone,wallet_balance
    Returns mapping customer_key -> FINAL balance
    """
    out: Dict[str, float] = {}
    if not wallet_path.exists():
        return out

    with wallet_path.open("r", newline="", encoding="utf-8-sig", errors="replace") as f:
        r = csv.DictReader(f, strict=False)
        for row in r:
            name = norm(row.get("customer_name"))
            email = norm(row.get("customer_email"))
            phone = norm(row.get("customer_phone"))
            bal = to_float(row.get("wallet_balance"))
            if bal is None:
                continue
            ckey = customer_key(name, email, phone)
            out[ckey] = bal
    return out

def collect_wallet_payments(full_path: Path) -> Tuple[
    Dict[Tuple[str, int], float],   # (customer_key, orderid) -> wallet payment total (positive)
    Dict[str, datetime],            # customer_key -> earliest order date
]:
    """
    From BDBKala_full.csv:
    - Take rows where Payment Method contains 'wallet' (case-insensitive)
    - Aggregate total payment per (customer, order)
    Payment computed as: qty * unit_price * (1 - discount)
    """
    payments: Dict[Tuple[str, int], float] = defaultdict(float)
    earliest: Dict[str, datetime] = {}

    with full_path.open("r", newline="", encoding="utf-8-sig", errors="replace") as f:
        r = csv.DictReader(f, strict=False)
        for row in r:
            pm = norm(row.get("Payment Method"))
            if not pm or "wallet" not in pm.lower():
                continue

            oid_raw = norm(row.get("Order ID"))
            if not oid_raw:
                continue
            try:
                oid = int(oid_raw)
            except ValueError:
                continue

            cname = norm(row.get("Customer Name"))
            email = norm(row.get("Email"))
            phone = norm(row.get("Phone"))
            ckey = customer_key(cname, email, phone)

            odt = parse_date(row.get("Order Date"))
            if odt:
                if ckey not in earliest or odt < earliest[ckey]:
                    earliest[ckey] = odt

            qty = to_float(row.get("Order Quantity")) or 0.0
            unit_price = to_float(row.get("Unit Price")) or 0.0
            disc = to_float(row.get("Discount"))
            if disc is None:
                disc = 0.0

            line_total = qty * unit_price * (1.0 - disc)
            payments[(ckey, oid)] += line_total

    return payments, earliest

def txid_deposit(walletid: int) -> int:
    return id60_from_string(str(walletid), salt="deposit")

def txid_payment(walletid: int, orderid: int) -> int:
    return id60_from_string(f"{walletid}|{orderid}", salt="payment")

def write_wallettransaction_sql(
    out_path: Path,
    wallet_balances: Dict[str, float],                # FINAL balance
    payments: Dict[Tuple[str, int], float],           # per-order wallet spend (positive)
    earliest_order_date: Dict[str, datetime],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cols = ["transactionid", "walletid", "amount", "date", "type"]
    rows: List[str] = []

    spend_by_customer: Dict[str, float] = defaultdict(float)
    for (ckey, _oid), amt in payments.items():
        spend_by_customer[ckey] += amt

    # 1) deposit transactions:
    for ckey, final_bal in sorted(wallet_balances.items(), key=lambda x: x[0]):
        wid = wallet_id_for_customer(ckey)
        tid = txid_deposit(wid)

        total_spend = spend_by_customer.get(ckey, 0.0)
        deposit_amount = final_bal + total_spend

        base = earliest_order_date.get(ckey, datetime(2019, 12, 31))
        dep_date = base - timedelta(days=1)

        rows.append("(" + ", ".join([
            str(tid),
            str(wid),
            money2(deposit_amount),
            sql_timestamp(dep_date),
            sql_text("deposit"),
        ]) + ")")

    # 2) payment transactions (negative)
    for (ckey, oid), amt in sorted(payments.items(), key=lambda x: (x[0][0], x[0][1])):
        wid = wallet_id_for_customer(ckey)
        tid = txid_payment(wid, oid)

        pay_date = datetime(2020, 1, 1) + timedelta(days=(oid % 365))

        rows.append("(" + ", ".join([
            str(tid),
            str(wid),
            money2(-amt),
            sql_timestamp(pay_date),
            sql_text("payment"),
        ]) + ")")

    with out_path.open("w", encoding="utf-8") as f:
        f.write("-- Auto-generated wallettransaction insert\n")
        f.write("-- deposit is reconstructed so that: deposit - sum(payments) = final wallet balance\n")
        f.write("-- final wallet balance comes from wallet_balances.csv\n")
        f.write("-- payment: one per (customer, order) where Payment Method contains 'wallet' in BDBKala_full.csv\n\n")
        if rows:
            f.write(f"INSERT INTO wallettransaction ({', '.join(cols)})\nVALUES\n")
            f.write(",\n".join(rows))
            f.write(";\n")
        else:
            f.write("-- No wallet transactions generated (check inputs).\n")

    print(f"[OK] Wrote: {out_path}  (rows: {len(rows)})")

def main():
    ap = argparse.ArgumentParser(description="Generate a single multi-row INSERT for wallettransaction table.")
    ap.add_argument("--full", required=True, help="Path to BDBKala_full.csv")
    ap.add_argument("--wallet", required=True, help="Path to wallet_balances.csv")
    ap.add_argument("--out", default="sql/12_insert_wallettransaction.sql", help="Output .sql file path")
    args = ap.parse_args()

    full_path = Path(args.full).expanduser().resolve()
    wallet_path = Path(args.wallet).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    wallet_balances = load_wallet_balances(wallet_path)
    payments, earliest = collect_wallet_payments(full_path)

    write_wallettransaction_sql(out_path, wallet_balances, payments, earliest)

if __name__ == "__main__":
    main()
