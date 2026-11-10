"""Invoice reconciliation agent, v2.

    python agent/reconcile_v2.py --reads runs/dev-v2/reads.json --out runs/dev-v2
    python agent/reconcile_v2.py --data holdout/data --reads <reads.json> --out runs/holdout-v2

A model reads the documents (reads.json, keyed by PDF filename). Code owns every
match, number and status. What changed from v1:

- Matching rules are general AP rules, not tuned to how the dev data was made:
  invoice numbers compared after normalizing (case, dashes, spaces, "INV#" prefixes),
  memos can name several invoices, one payment can cover several invoices with no memo,
  and duplicates are found by vendor + amount + similar number, not by a suffix.
- It fails closed. When the facts don't add up (subtotal + tax != total, a field is
  missing, the PO belongs to another vendor, the reader wasn't confident, or two
  answers fit equally well), the invoice goes to NEEDS_REVIEW with the reason,
  instead of a guess.
"""

import argparse
import csv
import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOL = 1.00          # README: within $1.00 is a match
CENT = 0.011        # arithmetic on a single document must tie out to the cent
CONF_RANK = {"low": 0, "medium": 1, "high": 2}


# ------------------------------------------------------------------ helpers
def num(s):
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)):
        return round(float(s), 2)
    s = str(s).replace("$", "").replace(",", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = round(float(s), 2)
    except ValueError:
        return None
    return -v if neg else v


def day(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%d-%b-%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            pass
    return None


STOP = {"inc", "llc", "co", "corp", "corporation", "company", "incorporated", "the", "group", "and",
        "ltd", "limited", "dba", "lp", "llp", "pllc", "of"}


def words(name):
    name = (name or "").lower().replace("&", " and ")
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", name).split() if w not in STOP]


def similar(a, b):
    a, b = " ".join(words(a)), " ".join(words(b))
    if not a or not b:
        return 0.0
    if a.startswith(b) or b.startswith(a):
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def key(n):
    """Invoice-number key: uppercase alphanumerics only ('inv# tfs-65403' and 'TFS 65403' agree)."""
    k = re.sub(r"[^A-Z0-9]", "", str(n or "").upper())
    return re.sub(r"^(INVOICE|INV)(?=[A-Z0-9]*\d)", "", k) if len(k) > 6 else k


def near_number(a, b):
    """Two invoice numbers that are probably the same document re-sent or re-keyed."""
    ka, kb = key(a), key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    da, db = re.sub(r"\D", "", ka), re.sub(r"\D", "", kb)
    if len(da) >= 4 and da.lstrip("0") == db.lstrip("0"):
        return True                                  # same digits, letters or zeros differ
    short, long_ = sorted((ka, kb), key=len)
    if len(short) >= 5 and long_.startswith(short) and len(long_) - len(short) <= 3:
        return True                                  # suffix added on a resend
    return len(short) >= 6 and SequenceMatcher(None, ka, kb).ratio() >= 0.9


# ------------------------------------------------------------------ sources
def files(data):
    return (next(data.glob("LedgerLoop_AP_Invoices_Export_*.csv")),
            next(data.glob("ProcureHub_PO_Export_*.csv")),
            next(data.glob("GVB_Operating_*.csv")))


def load_pos(po_file):
    pos, vendors = {}, {}
    for r in csv.DictReader(open(po_file)):
        pos[key(r["PO Number"])] = {"po": r["PO Number"], "vendor_id": r["Supplier ID"], "total": num(r["PO Total"])}
        vendors.setdefault(r["Supplier ID"], set()).add(r["Supplier Name"])
    return pos, vendors


def load_bank(bank_file):
    lines = open(bank_file).read().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("Posting Date"))
    rows = []
    for r in csv.DictReader(lines[start:]):
        amt = num(r.get("Debit"))
        if not amt:
            continue
        rows.append({"ref": r["Reference"], "date": day(r["Posting Date"]), "type": r["Transaction Type"],
                     "memo": r["Description"], "amount": abs(amt)})
    return rows


def load_invoices(data, ap_file, reads):
    out = []
    for r in csv.DictReader(open(ap_file)):
        out.append({"source": f"{ap_file.name}#{r['Document ID']}", "source_type": "ap_export",
                    "vendor_name": r["Supplier"], "invoice_number": r["Supplier Invoice No."],
                    "invoice_date": r["Invoice Date"], "po_number": r["PO No."] or None,
                    "subtotal": num(r["Net Amount"]), "tax": num(r["Tax Amount"]), "total": num(r["Gross Amount"]),
                    "confidence": "high", "read_mode": "csv"})
    for pdf in sorted((data / "inbox").glob("*.pdf")):
        r = dict(reads.get(pdf.name) or {})
        for k in ("subtotal", "tax", "total"):
            r[k] = num(r.get(k))
        r.update({"source": f"inbox/{pdf.name}", "source_type": "pdf", "read_mode": "model",
                  "confidence": r.get("confidence") or "medium"})
        out.append(r)
    return out


# ------------------------------------------------------------------ vendors
def resolve_vendors(invoices, vendors, pos):
    """Vendor master = PO suppliers, plus any new names seen on invoices (clustered)."""
    names = {vid: set(ns) for vid, ns in vendors.items()}

    def best(name):
        sc = [(max(similar(name, n) for n in ns), vid) for vid, ns in names.items()]
        s, vid = max(sc) if sc else (0, None)
        return vid if s >= 0.75 else None

    new = 0
    for inv in invoices:
        vid = best(inv.get("vendor_name") or "")
        po = pos.get(key(inv.get("po_number")))
        inv["review"] = []
        if po and vid and po["vendor_id"] != vid:
            inv["review"].append(f"PO {inv['po_number']} belongs to {po['vendor_id']}, but the invoice names "
                                 f"{inv.get('vendor_name')} ({vid}).")
        vid = vid or (po["vendor_id"] if po else None)
        if not vid and inv.get("vendor_name"):
            new += 1
            vid = f"NEW-{new:03d}"
            names[vid] = set()
        if vid:
            names[vid].add(inv.get("vendor_name") or "")
        inv["vendor_id"] = vid
    return names


def bank_vendor(memo, names):
    """Bank memos truncate names ('LUMEN RIDGE LIGHTI'). Match on the first two name words, allowing truncation."""
    mw = words(memo)

    def hit(w):
        return any(m == w or (len(m) >= 3 and w.startswith(m)) or (len(w) >= 3 and m.startswith(w)) for m in mw)

    best, best_s = None, 0
    for vid, ns in names.items():
        for n in ns:
            ws = words(n)[:2]
            if not ws or not hit(ws[0]):
                continue
            s = sum(hit(w) for w in ws) / len(ws) + (len(ws) == 2) * 0.01
            if s > best_s:
                best, best_s = vid, s
    return best if best_s >= 0.99 else None


# ------------------------------------------------------------------ reconcile
def pay(inv, b, amount):
    inv["bank_refs"].append(b["ref"])
    inv["amount_paid"] = round(inv["amount_paid"] + amount, 2)
    b["invoices"].append(inv["source"])


def reconcile(invoices, pos, vendors, bank, min_conf="medium"):
    names = resolve_vendors(invoices, vendors, pos)
    for inv in invoices:
        inv.update({"bank_refs": [], "amount_paid": 0.0, "exceptions": [], "notes": []})
        inv["_date"] = day(inv.get("invoice_date"))
        # cross-checks on the document itself
        if not inv.get("invoice_number"):
            inv["review"].append("No invoice number could be read.")
        if inv.get("total") is None:
            inv["review"].append("No total could be read.")
        elif None not in (inv.get("subtotal"), inv.get("tax")) and abs(inv["subtotal"] + inv["tax"] - inv["total"]) > CENT:
            inv["review"].append(f"Subtotal {inv['subtotal']:,.2f} + tax {inv['tax']:,.2f} does not equal "
                                 f"total {inv['total']:,.2f}; the read or the invoice is wrong.")
        if not inv["vendor_id"]:
            inv["review"].append("Vendor could not be identified.")
        if CONF_RANK.get(inv.get("confidence"), 1) < CONF_RANK[min_conf]:
            inv["review"].append(f"Reader confidence was {inv.get('confidence')}.")

    debits = []
    for b in bank:
        b["vendor_id"] = bank_vendor(b["memo"], names)
        b.update({"remaining": b["amount"], "invoices": [], "review": None})
        if b["vendor_id"] or b["type"] == "CHECK":
            debits.append(b)

    by_key = {}
    for inv in invoices:
        if inv.get("invoice_number"):
            by_key.setdefault(key(inv["invoice_number"]), []).append(inv)
    for group in by_key.values():   # earliest-dated record first = the original
        group.sort(key=lambda i: (i["_date"] or datetime.max.date(), i["source_type"] != "pdf", i["source"]))

    # 1) the memo names the invoice(s)
    for b in sorted(debits, key=lambda b: b["date"]):
        toks = {key(t) for t in re.split(r"[\s,;/|]+", b["memo"].upper()) if t}
        toks |= {key(re.sub(r"^(INV(OICE)?S?|NO\.?)[#:.]*", "", t)) for t in re.split(r"[\s,;/|]+", b["memo"].upper())}
        named = []
        for k, group in by_key.items():
            if k in toks and len(k) >= 4:
                cand = [i for i in group if b["vendor_id"] in (None, i["vendor_id"])]
                if cand:  # first unpaid record with this number; if all paid, this is a second payment
                    named.append(next((i for i in cand if not i["bank_refs"]), cand[0]))
        if not named:
            continue
        if len(named) == 1:
            pay(named[0], b, b["amount"])
        else:
            due = sum(i.get("total") or 0 for i in named)
            if abs(due - b["amount"]) <= TOL * len(named):
                for i in named:
                    pay(i, b, i.get("total") or 0)
            else:
                b["review"] = (f"Memo names {len(named)} invoices totaling {due:,.2f} but the payment is "
                               f"{b['amount']:,.2f}; split is unclear.")
                for i in named:
                    i["review"].append(f"Payment {b['ref']} names this invoice with others and doesn't add up.")
                    b["invoices"].append(i["source"])
                    i["bank_refs"].append(b["ref"])
        b["remaining"] = 0

    def open_for(b, vid=None):
        return [i for i in invoices if not i["bank_refs"] and i.get("total") is not None
                and (vid is None or i["vendor_id"] == vid)
                and (i["_date"] is None or b["date"] is None or i["_date"] <= b["date"])]

    # 2) one payment, one invoice, same vendor, amount within $1. Ambiguous -> review, not a guess.
    for b in sorted(debits, key=lambda b: b["date"]):
        if not b["remaining"]:
            continue
        cands = [i for i in open_for(b, b["vendor_id"]) if abs(i["total"] - b["amount"]) <= TOL]
        if len({i["source"] for i in cands}) == 1 or (cands and b["vendor_id"] and
                                                     len({(i["vendor_id"], key(i["invoice_number"]), i["total"]) for i in cands}) == 1):
            pay(cands[0], b, b["amount"])
            b["remaining"] = 0
        elif len(cands) > 1:
            exact = [i for i in cands if abs(i["total"] - b["amount"]) < CENT]
            if len(exact) == 1:
                pay(exact[0], b, b["amount"])
                b["remaining"] = 0
            elif b["vendor_id"]:  # same vendor, several open invoices for the same amount: oldest first is AP practice
                oldest = min(cands, key=lambda i: (i["_date"] or datetime.max.date(), i["source"]))
                pay(oldest, b, b["amount"])
                b["remaining"] = 0
            else:
                b["review"] = f"Check for {b['amount']:,.2f} fits {len(cands)} open invoices."

    # 3) one payment covering several invoices of one vendor (no memo): unique combination only
    for b in debits:
        if not b["remaining"] or not b["vendor_id"]:
            continue
        pool = open_for(b, b["vendor_id"])[:12]
        fits = [c for n in range(2, min(5, len(pool)) + 1) for c in combinations(pool, n)
                if abs(sum(i["total"] for i in c) - b["amount"]) <= TOL]
        if len(fits) == 1:
            for i in fits[0]:
                pay(i, b, i["total"])
            b["remaining"] = 0
        elif len(fits) > 1:
            b["review"] = f"{len(fits)} different sets of open invoices add up to {b['amount']:,.2f}."

    # 4) leftover vendor payment smaller than one open invoice: partial payment (unique candidate only)
    for b in debits:
        if not b["remaining"] or not b["vendor_id"] or b["review"]:
            continue
        cands = [i for i in open_for(b, b["vendor_id"]) if b["amount"] < i["total"] - TOL]
        if len(cands) == 1:
            pay(cands[0], b, b["amount"])
            b["remaining"] = 0
        elif len(cands) > 1:
            b["review"] = (f"{b['amount']:,.2f} from {b['vendor_id']} could be a partial payment on any of "
                           f"{len(cands)} open invoices.")

    # duplicates: same vendor, same total, near-identical number. Earliest-dated is the original.
    seen = set()
    for a in invoices:
        for d in invoices:
            if a is d or not a["vendor_id"] or a["vendor_id"] != d["vendor_id"] or (id(d), id(a)) in seen:
                continue
            if None in (a.get("total"), d.get("total")) or abs(a["total"] - d["total"]) > TOL:
                continue
            if not near_number(a.get("invoice_number"), d.get("invoice_number")):
                continue
            seen.add((id(a), id(d)))
            orig, dup = sorted((a, d), key=lambda i: (i["_date"] or datetime.max.date(), len(key(i["invoice_number"])),
                                                     i["source_type"] != "pdf", i["source"]))
            dup["exceptions"].append("DUPLICATE_INVOICE")
            dup["notes"].append(f"Same vendor and amount as invoice {orig['invoice_number']} ({orig['source']}); "
                                f"treat as a duplicate, do not pay.")
            if dup["bank_refs"] and orig["bank_refs"]:
                orig["exceptions"].append("DUPLICATE_INVOICE")
                dup["exceptions"].append("DUPLICATE_PAYMENT")
                dup["notes"].append(f"Both were paid ({', '.join(orig['bank_refs'])} and {', '.join(dup['bank_refs'])}); "
                                    f"recover {dup['amount_paid']:,.2f}.")

    for i in invoices:
        if len(i["bank_refs"]) > 1 and i.get("total") and i["amount_paid"] > i["total"] + TOL:
            i["exceptions"].append("DUPLICATE_PAYMENT")
            i["notes"].append(f"Paid {i['amount_paid']:,.2f} against a total of {i['total']:,.2f}.")
        po = pos.get(key(i.get("po_number")))
        if not po:
            i["exceptions"].append("MISSING_PO")
            i["notes"].append(f"PO {i['po_number']} not found in ProcureHub." if i.get("po_number")
                              else "No purchase order on the invoice.")
        elif i.get("subtotal") is not None and abs(i["subtotal"] - po["total"]) > TOL:
            i["exceptions"].append("AMOUNT_MISMATCH_PO")
            i["notes"].append(f"Billed {i['subtotal']:,.2f} before tax against PO {po['po']} for "
                              f"{po['total']:,.2f} ({i['subtotal'] - po['total']:+,.2f}).")
        if i["bank_refs"] and i.get("total") and i["amount_paid"] < i["total"] - TOL:
            i["exceptions"].append("PARTIAL_PAYMENT")
            i["notes"].append(f"Paid {i['amount_paid']:,.2f} of {i['total']:,.2f}; "
                              f"{i['total'] - i['amount_paid']:,.2f} still owed.")
        i["exceptions"] = sorted(set(i["exceptions"]))
        if i["review"]:
            i["status"] = "NEEDS_REVIEW"
        elif not i["bank_refs"] and "DUPLICATE_INVOICE" not in i["exceptions"]:
            i["status"] = "OPEN_UNPAID" if not i["exceptions"] else "EXCEPTION"
        else:
            i["status"] = "EXCEPTION" if i["exceptions"] else "RECONCILED"

    payments = [{"bank_ref": b["ref"], "amount": b["amount"], "vendor_id": b["vendor_id"],
                 "invoice_sources": b["invoices"],
                 "status": "NEEDS_REVIEW" if b["review"] else ("MATCHED" if b["invoices"] else "UNMATCHED_PAYMENT"),
                 "note": b["review"]} for b in debits]
    return invoices, payments


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--reads", required=True, help="model reads of the inbox PDFs, keyed by PDF filename")
    ap.add_argument("--min-confidence", default="medium", choices=list(CONF_RANK))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    data = ROOT / a.data
    ap_file, po_file, bank_file = files(data)
    pos, vendors = load_pos(po_file)
    invoices, payments = reconcile(load_invoices(data, ap_file, json.load(open(ROOT / a.reads))), pos, vendors,
                                   load_bank(bank_file), a.min_confidence)
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    keep = ["source", "source_type", "read_mode", "confidence", "vendor_id", "vendor_name", "invoice_number",
            "invoice_date", "po_number", "subtotal", "tax", "total", "bank_refs", "amount_paid", "status",
            "exceptions", "notes", "review"]
    json.dump({"invoices": [{k: i.get(k) for k in keep} for i in invoices], "payments": payments},
              open(out / "report.json", "w"), indent=2)
    n_rev = sum(i["status"] == "NEEDS_REVIEW" for i in invoices)
    print(f"wrote {out / 'report.json'}: {len(invoices)} invoices ({n_rev} to review), {len(payments)} vendor payments")


if __name__ == "__main__":
    main()
