"""Generate the synthetic invoice-reconciliation dataset.

Everything here is fictional: the buyer, vendors, towns, phone numbers
(555-01xx), email domains (.example), and every amount. Deterministic: the
same seed always produces the same files.

Outputs (under data/):
  inbox/                     PDF invoices received by email, not yet keyed
  LedgerLoop_AP_Invoices_Export_2026-11-01.csv   invoices already in the AP tool
  ProcureHub_PO_Export_2026-11-01.csv            purchase orders
  GVB_Operating_x4417_Activity_2026-09-01_to_2026-10-31.csv      bank statement export
answer_key/answer_key.json   ground truth for every invoice and payment
"""

import csv
import io
import json
import random
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

SEED = 20261109
TOLERANCE = 1.00  # dollars: invoice subtotal vs PO total, payment vs invoice total

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
INBOX = DATA / "inbox"
KEY = ROOT / "answer_key"

rng = random.Random(SEED)

BUYER = {
    "name": "Copperline Home Goods, Inc.",
    "attn": "Accounts Payable",
    "street": "4100 Larkspur Way",
    "city": "Alder Falls, OR 97899",
    "email": "ap@copperline-home.example",
}


@dataclass
class Vendor:
    vid: str
    name: str            # vendor master name (procurement + AP tool)
    invoice_name: str    # how the vendor writes its own name on invoices
    bank_name: str       # how the bank memo truncates it
    street: str
    city: str
    phone: str
    email: str
    inv_fmt: str         # invoice number format
    tax_rate: float
    terms_days: int
    style: str           # pdf template
    color: str
    catalog: list = field(default_factory=list)


VENDORS = [
    Vendor("V-1001", "Bristlecone Packaging Co.", "Bristlecone Packaging Company", "BRISTLECONE PACKAG",
           "88 Quarry Bend Rd", "Fenwick, OR 97851", "(541) 555-0142", "billing@bristlecone-pack.example",
           "BPC-{n:05d}", 0.0, 30, "classic", "#2f5d50",
           [("CB-1218", "Corrugated shipper 12x12x8, 200# test", 1.42),
            ("CB-1812", "Corrugated shipper 18x12x10", 2.18),
            ("TP-48C", "Carton tape 48mm clear, case of 36", 54.00),
            ("VF-200", "Void fill paper, 1,000 ft roll", 38.50)]),
    Vendor("V-1002", "Halvorsen Industrial Supply", "HALVORSEN INDUSTRIAL SUPPLY, LLC", "HALVORSEN IND SUP",
           "1907 Tanager St", "Marrow Creek, WI 54989", "(920) 555-0117", "ar@halvorsen-supply.example",
           "HIS{n:06d}", 0.055, 30, "minimal", "#333333",
           [("PL-4048", "Pallet jack, 5,500 lb capacity", 389.00),
            ("SH-7224", "Steel shelving unit 72x24x84", 214.75),
            ("GL-NIT-L", "Nitrile gloves, large, box of 100", 11.90),
            ("SF-VEST", "Hi-vis safety vest, class 2", 8.40)]),
    Vendor("V-1003", "Tidewater Freight Solutions LLC", "Tidewater Freight Solutions", "TIDEWATER FREIGHT",
           "5 Harbor Light Pkwy", "Port Calloway, SC 29998", "(843) 555-0163", "invoices@tidewaterfreight.example",
           "TFS-{n}", 0.0, 15, "modern", "#1f4e79",
           [("LTL-WC", "LTL freight, Port Calloway to Alder Falls", 1240.00),
            ("FSC", "Fuel surcharge", 186.00),
            ("LIFT", "Liftgate delivery", 95.00)]),
    Vendor("V-1004", "Juniper & Ash Office Supply", "Juniper & Ash", "JUNIPER AND ASH",
           "212 Willowmere Ave, Suite 4", "Hollis Bay, ME 04999", "(207) 555-0150", "orders@juniperash.example",
           "JA-{n:04d}", 0.055, 30, "classic", "#7a4b2a",
           [("PPR-LTR", "Copy paper, letter, case of 10 reams", 49.99),
            ("TNR-58A", "Toner cartridge, black, high yield", 132.00),
            ("CHR-ERG", "Task chair, mesh back", 245.00)]),
    Vendor("V-1005", "Redfern Electrical Components, Inc.", "Redfern Electrical Components Inc", "REDFERN ELECTRICAL",
           "4471 Calder Ridge Dr", "Sable Point, TX 79998", "(432) 555-0128", "ar@redfern-elec.example",
           "RE-{n:06d}", 0.0825, 30, "modern", "#8a1c1c",
           [("LED-PNL24", "LED panel 2x4, 5000K", 68.20),
            ("WR-12G-500", "THHN wire 12 AWG, 500 ft spool", 141.00),
            ("BRK-20A", "20A single-pole breaker", 9.85)]),
    Vendor("V-1006", "Kestrel Print Studio", "Kestrel Print Studio", "KESTREL PRINT STUD",
           "39 Foundry Lane", "Ashgrove, VT 05999", "(802) 555-0181", "studio@kestrelprint.example",
           "{n}", 0.06, 15, "minimal", "#444444",
           [("CAT-24P", "Product catalog, 24 pp, saddle stitch", 2.35),
            ("HNG-TAG", "Hang tags, 2x3.5, two-sided", 0.11),
            ("PST-1824", "Store poster 18x24", 6.80)]),
    Vendor("V-1007", "Ironvale Fasteners Corp.", "IRONVALE FASTENERS CORPORATION", "IRONVALE FASTENERS",
           "700 Smelter Row", "Cinder Hill, PA 16999", "(814) 555-0139", "billing@ironvale.example",
           "IVF-{n:05d}", 0.06, 30, "classic", "#4a4a6a",
           [("HX-38-16", "Hex bolt 3/8-16 x 1.5, zinc, box of 100", 18.40),
            ("NUT-38", "Nylon lock nut 3/8-16, box of 100", 7.95),
            ("WSH-38F", "Flat washer 3/8, box of 250", 6.10)]),
    Vendor("V-1008", "Lumen Ridge Lighting", "Lumen Ridge Lighting Co.", "LUMEN RIDGE LIGHTI",
           "1550 Prism Ct", "Glass Mesa, NM 87999", "(505) 555-0174", "ar@lumenridge.example",
           "LRL{n:05d}", 0.05125, 30, "modern", "#b7791f",
           [("PND-11", "Pendant lamp, brass, 11 in", 42.00),
            ("TBL-OAK", "Table lamp, oak base", 36.50),
            ("BLB-A19", "LED bulb A19, warm, 6-pack", 14.25)]),
    Vendor("V-1009", "Pinehollow Janitorial Services", "Pinehollow Janitorial", "PINEHOLLOW JANITOR",
           "17 Mossgate Rd", "Alder Falls, OR 97899", "(541) 555-0196", "office@pinehollow.example",
           "PJ-{n:04d}", 0.0, 15, "minimal", "#2d6a4f",
           [("SVC-MO", "Monthly janitorial service, warehouse", 2850.00),
            ("SVC-FLR", "Floor strip and wax, 12,000 sq ft", 1150.00)]),
    Vendor("V-1010", "Cobalt Bay Software, Inc.", "Cobalt Bay Software", "COBALT BAY SOFTWAR",
           "300 Lantern Wharf, Floor 6", "Brightwater, CA 94999", "(415) 555-0108", "billing@cobaltbay.example",
           "CBS-2026-{n:04d}", 0.0, 30, "modern", "#1d4ed8",
           [("WMS-ENT", "Warehouse management platform, monthly", 1875.00),
            ("WMS-SEAT", "Additional user seat, monthly", 45.00)]),
    Vendor("V-1011", "Marigold Catering Group", "Marigold Catering", "MARIGOLD CATERING",
           "62 Saffron St", "Alder Falls, OR 97899", "(541) 555-0123", "events@marigoldcatering.example",
           "MCG{n:04d}", 0.0, 15, "classic", "#c05621",
           [("LUNCH-50", "Staff lunch, 50 guests", 925.00),
            ("COFFEE", "Coffee service, half day", 140.00)]),
    Vendor("V-1012", "Stonebrook Logistics", "Stonebrook Logistics, Inc.", "STONEBROOK LOGISTI",
           "9 Gravel Pit Rd", "Ferris Gap, NV 89999", "(775) 555-0187", "ap@stonebrook.example",
           "SBL-{n:05d}", 0.0, 30, "minimal", "#374151",
           [("DRAY-40", "Drayage, 40 ft container", 780.00),
            ("STOR-WK", "Container storage, per week", 210.00),
            ("CHAS", "Chassis rental, per day", 45.00)]),
]

# Scenario plan: (vendor index, scenario, channel). channel: pdf | csv | scan
PLAN = [
    (0, "clean", "pdf"), (1, "clean", "csv"), (2, "clean", "pdf"), (3, "clean", "csv"),
    (4, "clean", "pdf"), (5, "clean", "csv"), (6, "clean", "pdf"), (7, "clean", "csv"),
    (8, "clean", "pdf"), (9, "clean", "csv"), (10, "clean", "pdf"), (11, "clean", "csv"),
    (0, "clean_check", "csv"), (4, "clean_check", "pdf"),
    (6, "multi_pay", "csv"), (6, "multi_pay", "pdf"), (6, "multi_pay", "csv"),
    (3, "rounding", "pdf"), (7, "rounding", "csv"),
    (1, "amount_mismatch", "pdf"), (4, "amount_mismatch", "csv"), (11, "amount_mismatch", "scan"),
    (2, "duplicate_paid_twice", "pdf"),   # + its duplicate generated below
    (5, "duplicate_unpaid", "csv"),       # + its duplicate generated below
    (10, "partial_payment", "pdf"), (8, "partial_payment", "csv"), (1, "partial_payment", "scan"),
    (5, "missing_po", "pdf"), (10, "missing_po", "csv"), (3, "missing_po", "scan"),
    (0, "unpaid", "csv"), (9, "unpaid", "pdf"), (7, "unpaid", "pdf"),
    (2, "clean", "scan"), (11, "clean", "pdf"), (9, "clean", "pdf"), (8, "clean", "csv"),
]

EXCEPTIONS = {
    "amount_mismatch": ["AMOUNT_MISMATCH_PO"],
    "duplicate_paid_twice": ["DUPLICATE_INVOICE", "DUPLICATE_PAYMENT"],
    "duplicate_unpaid": ["DUPLICATE_INVOICE"],
    "partial_payment": ["PARTIAL_PAYMENT"],
    "missing_po": ["MISSING_PO"],
}


def money(x):
    return round(x + 1e-9, 2)


def fmt(x):
    return f"{x:,.2f}"


def d(s):
    return date.fromisoformat(s)


class Counter:
    def __init__(self, start):
        self.n = start

    def next(self, step_lo=1, step_hi=7):
        self.n += rng.randint(step_lo, step_hi)
        return self.n


inv_counters = {v.vid: Counter(rng.randint(1200, 88000)) for v in VENDORS}
po_counter = Counter(10400)
doc_counter = Counter(55100)
check_counter = Counter(10470)


def make_lines(v):
    k = rng.randint(1, min(3, len(v.catalog)))
    items = rng.sample(v.catalog, k)
    lines = []
    for sku, desc, price in items:
        if price < 5:
            qty = rng.choice([500, 1000, 1500, 2000, 2500, 5000])
        elif price < 60:
            qty = rng.randint(6, 60)
        elif price < 400:
            qty = rng.randint(2, 12)
        else:
            qty = rng.randint(1, 3)
        lines.append({"sku": sku, "description": desc, "qty": qty, "unit_price": price,
                      "amount": money(qty * price)})
    return lines


def total_of(lines):
    return money(sum(l["amount"] for l in lines))


invoices, pos, payments, bank_noise = [], [], [], []
multi_group = []

for idx, (vi, scen, channel) in enumerate(PLAN):
    v = VENDORS[vi]
    po_date = date(2026, 8, 18) + timedelta(days=rng.randint(0, 35))
    lines = make_lines(v)
    po_total = total_of(lines)
    has_po = scen != "missing_po"
    po_no = f"PO-{po_counter.next(1, 4)}" if has_po else ""

    inv_lines = [dict(l) for l in lines]
    if scen == "amount_mismatch":
        # vendor shipped/billed more than the PO allowed
        bump = inv_lines[0]
        extra = max(1, round(bump["qty"] * rng.choice([0.08, 0.1, 0.15])))
        bump["qty"] += extra
        bump["amount"] = money(bump["qty"] * bump["unit_price"])
    if scen == "rounding":
        # vendor's system rounds the unit price differently: off by cents
        r = inv_lines[0]
        r["amount"] = money(r["amount"] + rng.choice([0.02, 0.03, -0.02, 0.37]))

    subtotal = total_of(inv_lines)
    tax = money(subtotal * v.tax_rate)
    inv_total = money(subtotal + tax)
    inv_date = po_date + timedelta(days=rng.randint(4, 20))
    if inv_date > date(2026, 10, 20):
        inv_date = date(2026, 10, 20) - timedelta(days=rng.randint(0, 6))
    due = inv_date + timedelta(days=v.terms_days)
    inv_no = v.inv_fmt.format(n=inv_counters[v.vid].next())

    if has_po:
        pos.append({"po": po_no, "date": po_date, "vendor": v, "lines": lines, "total": po_total,
                    "status": "Received" if rng.random() < 0.8 else "Partially Received"})

    inv = {"id": f"INV-{idx+1:03d}", "vendor": v, "number": inv_no, "date": inv_date, "due": due,
           "po_ref": po_no, "lines": inv_lines, "subtotal": subtotal, "tax": tax, "total": inv_total,
           "channel": channel, "scenario": scen, "po_total": po_total if has_po else None}
    invoices.append(inv)

    # duplicates: same content, new invoice number, a few days later
    dup = None
    if scen.startswith("duplicate"):
        dup = dict(inv)
        dup["id"] = f"INV-{idx+1:03d}D"
        dup["number"] = inv_no + "-R"
        dup["date"] = inv_date + timedelta(days=rng.randint(5, 9))
        dup["due"] = dup["date"] + timedelta(days=v.terms_days)
        dup["channel"] = "csv" if channel != "csv" else "pdf"
        dup["duplicate_of"] = inv["id"]
        invoices.append(dup)

    # payments
    def pay(amount, invs, kind=None, when=None):
        kind = kind or rng.choice(["ACH", "ACH", "ACH", "WIRE"])
        when = when or min(i["due"] for i in invs) - timedelta(days=rng.randint(0, 4))
        when = max(when, max(i["date"] for i in invs) + timedelta(days=2))
        if when > date(2026, 10, 31):
            when = date(2026, 10, 31) - timedelta(days=rng.randint(0, 3))
        p = {"date": when, "amount": money(amount), "vendor": v, "kind": kind,
             "invoices": [i["id"] for i in invs], "inv_numbers": [i["number"] for i in invs]}
        payments.append(p)
        return p

    if scen in ("clean", "rounding", "amount_mismatch", "missing_po"):
        pay(inv_total, [inv])
    elif scen == "clean_check":
        pay(inv_total, [inv], kind="CHECK")
    elif scen == "duplicate_paid_twice":
        pay(inv_total, [inv])
        pay(inv_total, [dup])
    elif scen == "duplicate_unpaid":
        pay(inv_total, [inv])
    elif scen == "partial_payment":
        frac = rng.choice([0.5, 0.6, 0.75])
        pay(money(inv_total * frac), [inv])
    elif scen == "multi_pay":
        multi_group.append(inv)
    elif scen == "unpaid":
        pass

# one ACH covering the three multi_pay invoices
mp = multi_group
v = mp[0]["vendor"]
payments.append({"date": max(i["due"] for i in mp) - timedelta(days=8), "amount": money(sum(i["total"] for i in mp)),
                 "vendor": v, "kind": "ACH", "invoices": [i["id"] for i in mp],
                 "inv_numbers": [i["number"] for i in mp]})
if payments[-1]["date"] < max(i["date"] for i in mp):
    payments[-1]["date"] = max(i["date"] for i in mp) + timedelta(days=3)

# payments with no invoice behind them
for vi, amt in ((7, 4180.00), (3, 612.40)):
    payments.append({"date": date(2026, 10, rng.randint(6, 27)), "amount": amt, "vendor": VENDORS[vi],
                     "kind": "ACH", "invoices": [], "inv_numbers": [], "unmatched": True})

# bank noise: not vendor payments
noise = [("2026-10-01", "PAYROLL", "ADP PAYROLL TAX 001", 48211.60),
         ("2026-10-15", "PAYROLL", "ADP PAYROLL TAX 001", 47980.15),
         ("2026-10-05", "FEE", "MONTHLY SERVICE FEE", 35.00),
         ("2026-10-12", "CARD", "CARD SETTLEMENT FEES MERCH 8841", 412.77),
         ("2026-10-20", "TRANSFER", "ONLINE TRANSFER TO SAV XXXX9120", 25000.00)]
deposits = [("2026-10-02", "DEPOSIT", "CARD SETTLEMENT MERCH 8841", 61240.18),
            ("2026-10-09", "DEPOSIT", "CARD SETTLEMENT MERCH 8841", 58113.42),
            ("2026-10-16", "DEPOSIT", "CARD SETTLEMENT MERCH 8841", 64901.07),
            ("2026-10-23", "DEPOSIT", "CARD SETTLEMENT MERCH 8841", 59877.30),
            ("2026-10-30", "DEPOSIT", "CARD SETTLEMENT MERCH 8841", 62450.66)]

# ---------------------------------------------------------------- bank memos
def memo(p, ref):
    v = p["vendor"]
    if p["kind"] == "CHECK":
        return f"CHECK {ref}"
    if p["kind"] == "WIRE":
        inv_part = f" INV {p['inv_numbers'][0]}" if p["inv_numbers"] and rng.random() < 0.6 else ""
        return f"WIRE OUT {v.bank_name}{inv_part} REF {ref}"
    nums = p["inv_numbers"]
    style = rng.random()
    if len(nums) > 1:
        tail = " INV " + ",".join(nums)
    elif nums and style < 0.55:
        tail = f" INV {nums[0]}"
    elif nums and style < 0.75:
        tail = f" {nums[0]}"
    else:
        tail = ""
    return f"ACH DEBIT {v.bank_name} PPD ID 9{rng.randint(100000000, 999999999)}{tail}"[:96]


bank_rows = []
for i, p in enumerate(sorted(payments, key=lambda x: x["date"])):
    if p["kind"] == "CHECK":
        ref = str(check_counter.next(1, 3))
    else:
        ref = f"{rng.randint(10**9, 10**10 - 1)}"
    p["bank_ref"] = ref
    p["memo"] = memo(p, ref)
    bank_rows.append({"date": p["date"], "type": {"ACH": "ACH DEBIT", "WIRE": "WIRE OUT", "CHECK": "CHECK"}[p["kind"]],
                      "desc": p["memo"], "ref": ref, "debit": p["amount"], "credit": None})
for ds, t, desc, amt in noise:
    bank_rows.append({"date": d(ds), "type": t if t != "PAYROLL" else "ACH DEBIT", "desc": desc,
                      "ref": f"{rng.randint(10**9, 10**10 - 1)}", "debit": amt, "credit": None})
for ds, t, desc, amt in deposits:
    bank_rows.append({"date": d(ds), "type": "ACH CREDIT", "desc": desc,
                      "ref": f"{rng.randint(10**9, 10**10 - 1)}", "debit": None, "credit": amt})
bank_rows.sort(key=lambda r: (r["date"], r["debit"] is None))

# ---------------------------------------------------------------- write CSVs
DATA.mkdir(parents=True, exist_ok=True)
INBOX.mkdir(parents=True, exist_ok=True)
KEY.mkdir(parents=True, exist_ok=True)


def us(dt):
    return f"{dt.month:02d}/{dt.day:02d}/{dt.year}"


# Procurement tool PO export
with open(DATA / "ProcureHub_PO_Export_2026-11-01.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["PO Number", "PO Date", "Supplier ID", "Supplier Name", "Line", "Item Code", "Item Description",
                "Qty Ordered", "UOM", "Unit Price", "Line Total", "PO Total", "Currency", "PO Status",
                "Buyer", "Cost Center", "Approved By"])
    buyers = ["M. Okafor", "J. Lindqvist", "R. Bowman"]
    for po in sorted(pos, key=lambda x: x["po"]):
        for n, l in enumerate(po["lines"], 1):
            w.writerow([po["po"], po["date"].isoformat(), po["vendor"].vid, po["vendor"].name, n, l["sku"],
                        l["description"], l["qty"], "EA", f"{l['unit_price']:.2f}", f"{l['amount']:.2f}",
                        f"{po['total']:.2f}", "USD", po["status"], rng.choice(buyers),
                        rng.choice(["CC-310 Warehouse", "CC-120 Operations", "CC-450 Marketing", "CC-200 Facilities"]),
                        rng.choice(["D. Reyes", "S. Patel"])])

# AP tool export: invoices that came in by portal / EDI (already keyed)
ap_rows = [i for i in invoices if i["channel"] == "csv"]
with open(DATA / "LedgerLoop_AP_Invoices_Export_2026-11-01.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Document ID", "Supplier", "Supplier Invoice No.", "Invoice Date", "Due Date", "PO No.",
                "Net Amount", "Tax Amount", "Gross Amount", "Currency", "Received Via", "Approval Status",
                "Entered By", "Entered On"])
    for i in sorted(ap_rows, key=lambda x: x["date"]):
        i["doc_id"] = f"LL-{doc_counter.next(3, 19)}"
        w.writerow([i["doc_id"], i["vendor"].invoice_name if rng.random() < 0.5 else i["vendor"].name,
                    i["number"], us(i["date"]), us(i["due"]), i["po_ref"], fmt(i["subtotal"]), fmt(i["tax"]),
                    fmt(i["total"]), "USD", rng.choice(["Supplier Portal", "Supplier Portal", "EDI 810"]),
                    rng.choice(["Approved", "Approved", "Pending Approval"]), "system",
                    us(i["date"] + timedelta(days=rng.randint(0, 2)))])

# Bank statement export, with the preamble real bank downloads have
with open(DATA / "GVB_Operating_x4417_Activity_2026-09-01_to_2026-10-31.csv", "w", newline="") as f:
    f.write("Granite Valley Bank\n")
    f.write("Account: Business Operating Checking ****4417\n")
    f.write("Activity Period: 09/01/2026 - 10/31/2026\n")
    f.write("\n")
    w = csv.writer(f)
    w.writerow(["Posting Date", "Transaction Type", "Description", "Reference", "Debit", "Credit", "Balance"])
    bal = 412_905.33
    for r in bank_rows:
        bal = money(bal - (r["debit"] or 0) + (r["credit"] or 0))
        w.writerow([us(r["date"]), r["type"], r["desc"], r["ref"],
                    f"-{r['debit']:.2f}" if r["debit"] else "", f"{r['credit']:.2f}" if r["credit"] else "",
                    f"{bal:.2f}"])

# ---------------------------------------------------------------- PDFs
TEMPLATE_CSS = {
    "classic": """
      body{font-family:Georgia,'Times New Roman',serif;color:#222;margin:0;padding:48px 56px;font-size:12px}
      .top{display:flex;justify-content:space-between;border-bottom:3px double ACCENT;padding-bottom:14px}
      .mark{width:46px;height:46px;border-radius:50%;background:ACCENT;color:#fff;display:flex;
            align-items:center;justify-content:center;font-weight:bold;font-size:17px;margin-bottom:8px}
      h1{font-size:26px;letter-spacing:4px;color:ACCENT;margin:0;text-align:right}
      th{border-bottom:1px solid #222;text-align:left;padding:6px 4px;font-size:11px;text-transform:uppercase}
      td{padding:6px 4px;border-bottom:1px solid #ddd}
    """,
    "modern": """
      body{font-family:Helvetica,Arial,sans-serif;color:#1f2937;margin:0;font-size:12px}
      .band{background:ACCENT;color:#fff;padding:28px 48px;display:flex;justify-content:space-between;align-items:center}
      .band h1{margin:0;font-size:30px;font-weight:300;letter-spacing:2px}
      .mark{width:40px;height:40px;border-radius:8px;background:rgba(255,255,255,.2);display:flex;
            align-items:center;justify-content:center;font-weight:700;margin-right:12px}
      .wrap{padding:28px 48px}
      th{background:#f3f4f6;text-align:left;padding:8px;font-size:11px;color:#4b5563}
      td{padding:8px;border-bottom:1px solid #e5e7eb}
    """,
    "minimal": """
      body{font-family:'Courier New',monospace;color:#111;margin:0;padding:44px 52px;font-size:11.5px}
      h1{font-size:20px;margin:0 0 4px 0}
      th{text-align:left;border-top:1px solid #111;border-bottom:1px solid #111;padding:5px 3px}
      td{padding:5px 3px}
    """,
}


def initials(name):
    words = [w for w in name.replace("&", "").split() if w[0].isalpha()]
    return (words[0][0] + (words[1][0] if len(words) > 1 else "")).upper()


def invoice_html(i):
    v = i["vendor"]
    css = TEMPLATE_CSS[v.style].replace("ACCENT", v.color)
    rows = "".join(
        f"<tr><td>{l['sku']}</td><td>{l['description']}</td><td style='text-align:right'>{l['qty']:,}</td>"
        f"<td style='text-align:right'>{fmt(l['unit_price'])}</td><td style='text-align:right'>{fmt(l['amount'])}</td></tr>"
        for l in i["lines"])
    po_line = f"<div><b>PO #:</b> {i['po_ref']}</div>" if i["po_ref"] else ""
    tax_label = f"Sales tax ({v.tax_rate*100:.3g}%)" if v.tax_rate else "Tax"
    meta = (f"<div><b>Invoice #:</b> {i['number']}</div><div><b>Invoice date:</b> {i['date'].strftime('%B %d, %Y')}</div>"
            f"<div><b>Due date:</b> {i['due'].strftime('%B %d, %Y')}</div><div><b>Terms:</b> Net {v.terms_days}</div>{po_line}")
    vendor_block = f"<b>{v.invoice_name}</b><br>{v.street}<br>{v.city}<br>{v.phone}<br>{v.email}"
    bill_to = (f"<div style='font-size:10px;color:#666;text-transform:uppercase;letter-spacing:1px'>Bill to</div>"
               f"<b>{BUYER['name']}</b><br>Attn: {BUYER['attn']}<br>{BUYER['street']}<br>{BUYER['city']}")
    totals = (f"<table style='width:280px;margin-left:auto;margin-top:14px'>"
              f"<tr><td>Subtotal</td><td style='text-align:right'>{fmt(i['subtotal'])}</td></tr>"
              f"<tr><td>{tax_label}</td><td style='text-align:right'>{fmt(i['tax'])}</td></tr>"
              f"<tr><td><b>Total due (USD)</b></td><td style='text-align:right'><b>${fmt(i['total'])}</b></td></tr></table>")
    remit = (f"<div style='margin-top:36px;font-size:10.5px;color:#555'>Please remit by ACH to account ending 7{rng.randint(100,999)} "
             f"(routing on file) and reference invoice {i['number']}. Questions: {v.email}. Thank you for your business.</div>")
    table = (f"<table style='width:100%;border-collapse:collapse;margin-top:22px'><tr><th>Item</th><th>Description</th>"
             f"<th style='text-align:right'>Qty</th><th style='text-align:right'>Unit price</th>"
             f"<th style='text-align:right'>Amount</th></tr>{rows}</table>")
    if v.style == "modern":
        body = (f"<div class='band'><div style='display:flex;align-items:center'><div class='mark'>{initials(v.invoice_name)}</div>"
                f"<div><b style='font-size:15px'>{v.invoice_name}</b><br><span style='opacity:.85'>{v.street}, {v.city}</span></div></div>"
                f"<h1>INVOICE</h1></div><div class='wrap'><div style='display:flex;justify-content:space-between'>"
                f"<div>{bill_to}</div><div style='text-align:right'>{meta}</div></div>{table}{totals}{remit}</div>")
    elif v.style == "classic":
        body = (f"<div class='top'><div><div class='mark'>{initials(v.invoice_name)}</div>{vendor_block}</div>"
                f"<div><h1>INVOICE</h1><div style='text-align:right;margin-top:10px'>{meta}</div></div></div>"
                f"<div style='margin-top:20px'>{bill_to}</div>{table}{totals}{remit}")
    else:
        body = (f"<h1>{v.invoice_name.upper()}</h1><div>{v.street} | {v.city} | {v.phone}</div>"
                f"<div style='margin:18px 0 8px 0'>INVOICE {i['number']}</div>"
                f"<div style='display:flex;justify-content:space-between'><div>{bill_to}</div><div>{meta}</div></div>"
                f"{table}{totals}{remit}")
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"


pdf_invoices = [i for i in invoices if i["channel"] in ("pdf", "scan")]
for i in pdf_invoices:
    slug = "".join(ch for ch in i["vendor"].invoice_name.split()[0] if ch.isalnum())
    i["file"] = f"{slug}_{i['number']}.pdf".replace("/", "-")


def render_pdfs():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        for i in pdf_invoices:
            pg.set_content(invoice_html(i))
            pg.pdf(path=str(INBOX / i["file"]), format="Letter", print_background=True)
        b.close()


def scanify(path):
    """Turn a clean PDF into a crooked, noisy, image-only scan (no text layer)."""
    import subprocess
    import tempfile
    from PIL import Image, ImageFilter
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["pdftoppm", "-r", "110", "-gray", "-png", str(path), f"{td}/p"], check=True)
        pages = sorted(Path(td).glob("p*.png"))
        imgs = []
        r = random.Random(path.name)
        for pth in pages:
            im = Image.open(pth).convert("L")
            im = im.rotate(r.uniform(-1.6, 1.6), expand=True, fillcolor=245)
            im = im.filter(ImageFilter.GaussianBlur(0.6))
            px = im.load()
            w, h = im.size
            for _ in range(w * h // 180):
                x, y = r.randrange(w), r.randrange(h)
                px[x, y] = r.choice([90, 140, 200])
            imgs.append(im.convert("RGB"))
        imgs[0].save(path, save_all=True, append_images=imgs[1:], resolution=110)


render_pdfs()
for i in pdf_invoices:
    if i["channel"] == "scan":
        i["file"] = i["file"].replace(".pdf", "_scan.pdf")
        (INBOX / i["file"].replace("_scan.pdf", ".pdf")).rename(INBOX / i["file"])
        scanify(INBOX / i["file"])

# ---------------------------------------------------------------- answer key
pay_by_inv = {}
for p in payments:
    for iid in p["invoices"]:
        pay_by_inv.setdefault(iid, []).append(p)

key_invoices = []
for i in invoices:
    ps = pay_by_inv.get(i["id"], [])
    paid = money(sum(p["amount"] / len(p["invoices"]) if len(p["invoices"]) > 1 else p["amount"] for p in ps))
    if len(ps) == 1 and len(ps[0]["invoices"]) > 1:
        paid = i["total"]
    exc = list(EXCEPTIONS.get(i["scenario"], []))
    if i.get("duplicate_of"):
        exc = ["DUPLICATE_INVOICE"] + (["DUPLICATE_PAYMENT"] if i["scenario"] == "duplicate_paid_twice" else [])
    if not ps and i["scenario"] != "duplicate_unpaid":
        status = "OPEN_UNPAID"
    elif exc:
        status = "EXCEPTION"
    else:
        status = "RECONCILED"
    if i.get("duplicate_of") and i["scenario"] == "duplicate_unpaid":
        status = "EXCEPTION"
    if i["scenario"] == "duplicate_unpaid" and not i.get("duplicate_of"):
        status, exc = "RECONCILED", []
    if i["scenario"] == "duplicate_paid_twice" and not i.get("duplicate_of"):
        status, exc = "EXCEPTION", ["DUPLICATE_INVOICE"]
    key_invoices.append({
        "invoice_key": i["id"],
        "source": ("inbox/" + i["file"]) if i["channel"] in ("pdf", "scan") else
                  f"LedgerLoop_AP_Invoices_Export_2026-11-01.csv#{i['doc_id']}",
        "source_type": {"pdf": "pdf", "scan": "scanned_pdf", "csv": "ap_export"}[i["channel"]],
        "vendor_id": i["vendor"].vid,
        "vendor_invoice_number": i["number"],
        "invoice_date": i["date"].isoformat(),
        "po_number": i["po_ref"] or None,
        "subtotal": i["subtotal"], "tax": i["tax"], "total": i["total"],
        "po_total": i["po_total"],
        "bank_refs": [p["bank_ref"] for p in ps],
        "amount_paid": paid if ps else 0.0,
        "status": status,
        "exceptions": exc,
        "scenario": i["scenario"],
        "duplicate_of": i.get("duplicate_of"),
    })

key_payments = [{"bank_ref": p["bank_ref"], "date": p["date"].isoformat(), "amount": p["amount"],
                 "vendor_id": p["vendor"].vid, "invoice_keys": p["invoices"],
                 "status": "UNMATCHED_PAYMENT" if p.get("unmatched") else "MATCHED"} for p in payments]

with open(KEY / "answer_key.json", "w") as f:
    json.dump({"tolerance_usd": TOLERANCE, "invoices": key_invoices, "vendor_payments": key_payments,
               "non_vendor_bank_lines": len(noise) + len(deposits)}, f, indent=2)

print(f"{len(invoices)} invoices ({len(pdf_invoices)} PDF, {len(ap_rows)} AP export), "
      f"{len(pos)} POs, {len(payments)} vendor payments, {len(bank_rows)} bank lines")
