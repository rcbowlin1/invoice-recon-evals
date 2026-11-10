"""Invoice reconciliation agent, v1 (frozen baseline: OCR + regex, rule-based matching).

    python agent/reconcile_v1.py --out runs/dev-v1                              # dev set
    python agent/reconcile_v1.py --data holdout/data --out runs/holdout-v1      # holdout

Design: a model may help *read* documents; code owns every match, every number
and every status. Explanations are generated from the facts the code found.
"""

import argparse
import csv
import json
import re
import subprocess
import sys
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOL = 1.00


def set_data(d):
    """Point the agent at a data folder (dev: data/, holdout: holdout/data/). Logic is unchanged."""
    global DATA, AP_FILE, PO_FILE, BANK_FILE
    DATA = Path(d) if Path(d).is_absolute() else ROOT / d
    AP_FILE = next(DATA.glob("LedgerLoop_AP_Invoices_Export_*.csv"))
    PO_FILE = next(DATA.glob("ProcureHub_PO_Export_*.csv"))
    BANK_FILE = next(DATA.glob("GVB_Operating_*.csv"))


set_data("data")

FIELDS = ["vendor_name", "invoice_number", "invoice_date", "po_number", "subtotal", "tax", "total"]


# ------------------------------------------------------------------ helpers
def num(s):
    if s is None:
        return None
    s = str(s).replace("$", "").replace(",", "").strip()
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def norm(name):
    name = name.lower().replace("&", " and ")
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    stop = {"inc", "llc", "co", "corp", "corporation", "company", "incorporated", "the", "group", "and"}
    return " ".join(w for w in name.split() if w not in stop)


def similar(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a.startswith(b) or b.startswith(a):
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


# ------------------------------------------------------------------ sources
def load_pos():
    pos = {}
    vendors = {}
    for r in csv.DictReader(open(PO_FILE)):
        pos[r["PO Number"]] = {"po": r["PO Number"], "vendor_id": r["Supplier ID"], "total": num(r["PO Total"])}
        vendors[r["Supplier ID"]] = r["Supplier Name"]
    return pos, vendors


def load_bank():
    lines = open(BANK_FILE).read().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("Posting Date"))
    rows = []
    for r in csv.DictReader(lines[start:]):
        if not r["Debit"]:
            continue
        rows.append({"ref": r["Reference"], "date": r["Posting Date"], "type": r["Transaction Type"],
                     "memo": r["Description"], "amount": abs(num(r["Debit"]))})
    return rows


def match_vendor(name, vendors):
    best, score = None, 0.0
    for vid, vname in vendors.items():
        s = similar(name, vname)
        if s > score:
            best, score = vid, s
    return best if score >= 0.6 else None


# ------------------------------------------------------------------ extraction
def pdf_text(path):
    txt = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True).stdout
    if len(txt.strip()) > 40:
        return txt, "text"
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", str(path), f"{td}/p"], check=True)
        out = []
        for png in sorted(Path(td).glob("p*.png")):
            out.append(subprocess.run(["tesseract", str(png), "-", "--psm", "4"],
                                      capture_output=True, text=True).stdout)
        return "\n".join(out), "ocr"


MONEY = r"\$?\s*([\d,]+\.\d{2})"


def extract_rules(path):
    """Baseline: regex over pdftotext / tesseract output."""
    text, mode = pdf_text(path)
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    def grab(pattern):
        m = re.search(pattern, text, re.I)
        return m.group(1).strip() if m else None

    inv = grab(r"Invoice\s*#\s*:?\s*([A-Z0-9][A-Z0-9\-]+)")
    po = grab(r"PO\s*#\s*:?\s*(PO-\d+)")
    date = grab(r"Invoice date\s*:?\s*([A-Za-z]+ \d{1,2}, \d{4})")
    subtotal = num(grab(r"Subtotal\s+" + MONEY))
    tax = num(grab(r"(?:Sales tax[^\n\d]*\([\d.]+%\)|Tax)\s+" + MONEY))
    total = num(grab(r"Total due[^\n$\d]*" + MONEY))
    vendor = next((l for l in lines if re.search(r"[A-Za-z]{3}", l) and "invoice" not in l.lower()
                   and not re.fullmatch(r"[A-Z]{1,3}", l)), "")
    vendor = re.split(r"\s{2,}", vendor)[0]
    return {"vendor_name": vendor, "invoice_number": inv, "invoice_date": date, "po_number": po,
            "subtotal": subtotal, "tax": tax, "total": total, "read_mode": mode}


def extract_claude(path, model):
    """v2: Claude reads the page images and returns the fields as JSON."""
    import base64
    import anthropic
    client = anthropic.Anthropic()
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["pdftoppm", "-r", "150", "-png", str(path), f"{td}/p"], check=True)
        images = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                               "data": base64.b64encode(p.read_bytes()).decode()}}
                  for p in sorted(Path(td).glob("p*.png"))]
    prompt = ("Read this vendor invoice. Return only JSON with keys: vendor_name, invoice_number, "
              "invoice_date (YYYY-MM-DD), po_number (null if none), subtotal, tax, total (numbers, no "
              "currency symbols). Copy values exactly as printed; use null for anything not on the page.")
    msg = client.messages.create(model=model, max_tokens=500,
                                 messages=[{"role": "user", "content": images + [{"type": "text", "text": prompt}]}])
    raw = msg.content[0].text
    data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    for k in ("subtotal", "tax", "total"):
        data[k] = num(data.get(k))
    data["read_mode"] = "claude"
    return data


def extract_precomputed(path, reads):
    """Reads produced earlier by a Claude agent that saw only the page images."""
    r = dict(reads[path.name])
    for k in ("subtotal", "tax", "total"):
        r[k] = num(r.get(k))
    r["read_mode"] = "claude"
    return r


def load_invoices(extractor, model, reads=None):
    out = []
    for r in csv.DictReader(open(AP_FILE)):
        out.append({"source": f"{AP_FILE.name}#{r['Document ID']}", "source_type": "ap_export",
                    "vendor_name": r["Supplier"], "invoice_number": r["Supplier Invoice No."],
                    "invoice_date": r["Invoice Date"], "po_number": r["PO No."] or None,
                    "subtotal": num(r["Net Amount"]), "tax": num(r["Tax Amount"]), "total": num(r["Gross Amount"]),
                    "read_mode": "csv"})
    for pdf in sorted((DATA / "inbox").glob("*.pdf")):
        if extractor == "rules":
            fields = extract_rules(pdf)
        elif extractor == "precomputed":
            fields = extract_precomputed(pdf, reads)
        else:
            fields = extract_claude(pdf, model)
        fields.update({"source": f"inbox/{pdf.name}", "source_type": "pdf"})
        out.append(fields)
    return out


# ------------------------------------------------------------------ reconcile
def reconcile(invoices, pos, vendors, bank):
    vendor_debits = []
    for b in bank:
        vid = None
        for v, vname in vendors.items():
            first = norm(vname).split()[0]
            if first and first.upper() in b["memo"].upper():
                vid = v
                break
        b["vendor_id"] = vid
        b["remaining"] = b["amount"]
        b["invoices"] = []
        if vid or b["type"] == "CHECK":
            vendor_debits.append(b)

    for inv in invoices:
        inv["vendor_id"] = match_vendor(inv.get("vendor_name") or "", vendors)
        if not inv["vendor_id"] and inv.get("po_number") in pos:
            inv["vendor_id"] = pos[inv["po_number"]]["vendor_id"]
        inv.update({"bank_refs": [], "amount_paid": 0.0, "exceptions": [], "notes": []})

    # 1) explicit references: the memo names the invoice number
    for b in vendor_debits:
        named = [i for i in invoices if i.get("invoice_number")
                 and re.search(rf"(?<![\w-]){re.escape(i['invoice_number'])}(?![\w-])", b["memo"])]
        if named:
            for i in named:
                share = b["amount"] if len(named) == 1 else i.get("total") or 0
                i["bank_refs"].append(b["ref"])
                i["amount_paid"] = round(i["amount_paid"] + share, 2)
                b["invoices"].append(i["source"])
            b["remaining"] = 0

    # 2) amount match within vendor (or checks, which carry no vendor name)
    for i in invoices:
        if i["bank_refs"] or i.get("total") is None:
            continue
        cands = [b for b in vendor_debits if b["remaining"] > 0
                 and (b["vendor_id"] == i["vendor_id"] or b["type"] == "CHECK")
                 and abs(b["amount"] - i["total"]) <= TOL]
        if cands:
            b = cands[0]
            i["bank_refs"].append(b["ref"])
            i["amount_paid"] = b["amount"]
            b["remaining"] = 0
            b["invoices"].append(i["source"])

    # 3) leftover vendor debits smaller than an open invoice: partial payment
    for i in invoices:
        if i["bank_refs"] or i.get("total") is None:
            continue
        cands = [b for b in vendor_debits if b["remaining"] > 0 and b["vendor_id"] == i["vendor_id"]
                 and b["amount"] < i["total"] - TOL]
        if cands:
            b = cands[0]
            i["bank_refs"].append(b["ref"])
            i["amount_paid"] = b["amount"]
            b["remaining"] = 0
            b["invoices"].append(i["source"])

    # duplicates: same vendor, same total, one number extends the other
    for a in invoices:
        for b in invoices:
            if a is b or a["vendor_id"] != b["vendor_id"] or a.get("total") != b.get("total"):
                continue
            na, nb = a.get("invoice_number") or "", b.get("invoice_number") or ""
            if na and nb and nb.startswith(na) and nb != na:
                b["exceptions"].append("DUPLICATE_INVOICE")
                b["notes"].append(f"Same vendor and amount as invoice {na}; looks like a reissue.")
                if b["bank_refs"]:
                    a["exceptions"].append("DUPLICATE_INVOICE")
                    b["exceptions"].append("DUPLICATE_PAYMENT")
                    b["notes"].append(f"Both {na} and {nb} were paid; one payment should be recovered.")

    for i in invoices:
        po = pos.get(i.get("po_number") or "")
        if not po:
            i["exceptions"].append("MISSING_PO")
            i["notes"].append("No matching purchase order in ProcureHub.")
        elif i.get("subtotal") is not None and abs(i["subtotal"] - po["total"]) > TOL:
            i["exceptions"].append("AMOUNT_MISMATCH_PO")
            i["notes"].append(f"Billed {i['subtotal']:,.2f} before tax against a PO for {po['total']:,.2f} "
                              f"({i['subtotal'] - po['total']:+,.2f}).")
        if i["bank_refs"] and i.get("total") and i["amount_paid"] < i["total"] - TOL:
            i["exceptions"].append("PARTIAL_PAYMENT")
            i["notes"].append(f"Paid {i['amount_paid']:,.2f} of {i['total']:,.2f}; "
                              f"{i['total'] - i['amount_paid']:,.2f} still owed.")
        i["exceptions"] = sorted(set(i["exceptions"]))
        if not i["bank_refs"] and "DUPLICATE_INVOICE" not in i["exceptions"]:
            i["status"] = "OPEN_UNPAID" if not i["exceptions"] else "EXCEPTION"
        else:
            i["status"] = "EXCEPTION" if i["exceptions"] else "RECONCILED"

    payments = [{"bank_ref": b["ref"], "amount": b["amount"], "vendor_id": b["vendor_id"],
                 "invoice_sources": b["invoices"],
                 "status": "MATCHED" if b["invoices"] else "UNMATCHED_PAYMENT"} for b in vendor_debits]
    return invoices, payments


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extractor", choices=["rules", "claude", "precomputed"], default="rules")
    ap.add_argument("--reads", help="JSON of precomputed reads, keyed by PDF filename")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--out", default="runs/v1")
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    set_data(a.data)
    pos, vendors = load_pos()
    invoices, payments = reconcile(load_invoices(a.extractor, a.model, json.load(open(a.reads)) if a.reads else None), pos, vendors, load_bank())
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    keep = ["source", "source_type", "read_mode", "vendor_id"] + FIELDS + ["bank_refs", "amount_paid", "status",
                                                                            "exceptions", "notes"]
    json.dump({"invoices": [{k: i.get(k) for k in keep} for i in invoices], "payments": payments},
              open(out / "report.json", "w"), indent=2)
    print(f"wrote {out / 'report.json'}: {len(invoices)} invoices, {len(payments)} vendor payments")


if __name__ == "__main__":
    main()
