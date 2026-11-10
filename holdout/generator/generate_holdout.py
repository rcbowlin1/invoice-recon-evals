"""Generate the HOLDOUT month for the invoice-reconciliation eval.

Same buyer, same file formats and labeling conventions as the dev set, but a
later period (Nov-Dec 2026), mostly new fictional vendors, new PDF layouts,
new bank memo styles, and harder scans. Everything is fictional: vendors,
towns, phones (555-01xx), email domains (.example), and every amount.

Deterministic: same seed, same bytes. Run from anywhere:
    python holdout/generator/generate_holdout.py

Outputs (under holdout/):
  data/inbox/*.pdf
  data/LedgerLoop_AP_Invoices_Export_2027-01-02.csv
  data/ProcureHub_PO_Export_2027-01-02.csv
  data/GVB_Operating_x4417_Activity_2026-11-01_to_2026-12-31.csv
  answer_key/answer_key.json
  blind/doc_NN[_pK].png, blind/blind_map.tsv, blind/holdout_images_blind.zip
"""

import csv
import json
import random
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

SEED = 20270102
TOLERANCE = 1.00

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
INBOX = DATA / "inbox"
KEY = ROOT / "answer_key"
BLIND = ROOT / "blind"

EXPORT_DATE = "2027-01-02"
PERIOD_START, PERIOD_END = date(2026, 11, 1), date(2026, 12, 31)
AP_FILE = f"LedgerLoop_AP_Invoices_Export_{EXPORT_DATE}.csv"
PO_FILE = f"ProcureHub_PO_Export_{EXPORT_DATE}.csv"
BANK_FILE = f"GVB_Operating_x4417_Activity_{PERIOD_START.isoformat()}_to_{PERIOD_END.isoformat()}.csv"

FIXED_PDF_DATE = b"D:20270102090000+00'00'"

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
    key: str
    vid: str
    name: str             # vendor master (procurement)
    invoice_name: str     # how the vendor prints its name
    ap_names: list        # variants seen in the AP tool
    bank_ach: str         # ACH originator name as the bank truncates it
    bank_wire: str        # beneficiary name on outgoing wires
    street: str
    city: str
    phone: str
    email: str
    inv_fmt: str
    tax_rate: float
    terms_days: int
    style: str
    color: str
    catalog: list = field(default_factory=list)
    tagline: str = ""


VENDORS = {v.key: v for v in [
    Vendor("FERN", "V-1013", "Fernhaven Textile Mills, Inc.", "Fernhaven Textiles",
           ["Fernhaven Textile Mills Inc", "FERNHAVEN TEXTILE MILLS"], "FERNHAVEN TEXTIL", "FERNHAVEN TXTL MILLS",
           "1200 Loomworks Rd", "Spindle Ford, NC 28999", "(828) 555-0144", "receivables@fernhaven-mills.example",
           "FTM-26-{n:05d}", 0.0, 30, "ledger", "#3b5b3b",
           [("TWL-BTH-WH", "Bath towel, 30x56, white, 600 gsm", 7.85),
            ("TWL-HND-GY", "Hand towel, 16x30, slate", 3.40),
            ("THR-WVN-50", "Woven throw 50x60, oatmeal", 18.20),
            ("NAP-LIN-4", "Linen napkin, set of 4, natural", 9.75),
            ("RUN-TBL-90", "Table runner 14x90, herringbone", 11.60)]),
    Vendor("QUIL", "V-1014", "Quillmark Signage & Display LLC", "Quillmark Signs & Display",
           ["QUILLMARK SIGNAGE AND DISPLAY LLC", "Quillmark Signage & Display"], "QUILLMARK SIGNAGE", "QUILLMARK SIGN DISP",
           "48 Easel Park Dr", "Brindle Cove, MN 55999", "(218) 555-0119", "billing@quillmark-display.example",
           "Q{n:06d}", 0.0725, 30, "modern", "#6b21a8",
           [("ACR-HLD-85", "Acrylic sign holder 8.5x11", 4.75),
            ("FLR-DCL-24", "Floor decal 24 in round, laminated", 16.40),
            ("PSF-2436", "Poster snap frame 24x36", 38.90),
            ("WIN-CLG", "Window cling set, seasonal", 62.00)]),
    Vendor("OSPR", "V-1015", "Osprey Point Ceramics, Ltd.", "Osprey Pt. Ceramics",
           ["OSPREY POINT CERAMICS LTD", "Osprey Point Ceramics"], "OSPREY PT CERAMIC", "OSPREY POINT CERAM",
           "7 Kiln Hollow Ln", "Gannet Bluff, ME 04998", "(207) 555-0172", "accounts@ospreypoint.example",
           "OPC{n:05d}", 0.055, 30, "statement", "#0f5e6e",
           [("MUG-12-SG", "Stoneware mug 12 oz, sea glass", 4.10),
            ("MUG-12-CH", "Stoneware mug 12 oz, charcoal", 4.10),
            ("BWL-CER-6", "Cereal bowl 6 in, speckled", 3.85),
            ("BWL-SRV-10", "Serving bowl 10 in, reactive glaze", 14.60),
            ("PLT-DIN-11", "Dinner plate 11 in, matte white", 5.25),
            ("PLT-SAL-8", "Salad plate 8 in, matte white", 3.95),
            ("PLT-SAL-8B", "Salad plate 8 in, tidepool blue", 3.95),
            ("VSE-BUD-6", "Bud vase 6 in, assorted", 6.40),
            ("PLN-PT-8", "Planter 8 in with saucer", 9.80),
            ("PLN-PT-12", "Planter 12 in with saucer", 17.25),
            ("CNT-CAN-L", "Canister, large, cork lid", 11.90),
            ("CNT-CAN-S", "Canister, small, cork lid", 7.70),
            ("TRV-SPN", "Spoon rest, glazed", 2.65),
            ("PTR-BTR", "Butter dish with lid", 8.45)]),
    Vendor("BRAM", "V-1016", "Brambleton Electric Supply Co.", "BRAMBLETON ELECTRIC SUPPLY COMPANY",
           ["Brambleton Elec Supply", "Brambleton Electric Supply Co"], "BRAMBLETON ELEC S", "BRAMBLETON ELECTRIC",
           "315 Conduit Ave", "Ohmsted, IA 50999", "(515) 555-0133", "ar@brambleton-elec.example",
           "BES-{n:06d}", 0.06, 30, "statement", "#9a3412",
           [("LED-TRK-4", "LED track head, 4000K, black", 22.40),
            ("EM-EXIT", "Emergency exit sign, LED", 41.50),
            ("WR-14-250", "THHN wire 14 AWG, 250 ft", 64.00),
            ("JBX-4SQ", "Junction box 4 in square, box of 25", 37.25),
            ("OCC-SNS", "Occupancy sensor, ceiling mount", 58.90)]),
    Vendor("SALT", "V-1017", "Saltmarsh Cleaning Products Inc.", "Saltmarsh Cleaning Prod., Inc.",
           ["Saltmarsh Cleaning Products", "SALTMARSH CLEANING PRODUCTS INC"], "SALTMARSH CLEANIN", "SALTMARSH CLEAN PROD",
           "88 Brine Flats Rd", "Heron Reach, DE 19999", "(302) 555-0158", "invoicing@saltmarsh-clean.example",
           "SCP-{n}", 0.06, 30, "ledger", "#1e40af",
           [("DGR-5G", "Neutral floor cleaner, 5 gal", 46.80),
            ("GLS-CS12", "Glass cleaner, case of 12 qt", 31.20),
            ("TWL-CF-6", "C-fold towels, case of 2,400", 28.75),
            ("LNR-4045", "Can liners 40x45, case of 250", 33.40),
            ("MOP-HD-24", "Dust mop head 24 in", 12.95)]),
    Vendor("HARR", "V-1018", "Harrowgate Furniture Works LLC", "HARROWGATE FURN. WORKS",
           ["Harrowgate Furniture Works, L.L.C.", "HARROWGATE FURNITURE WORKS"], "HARROWGATE FURNIT", "HARROWGATE FURN WKS",
           "2650 Sawmill Bend", "Cedar Notch, MI 49999", "(906) 555-0126", "ar@harrowgate-furniture.example",
           "HFW{n:05d}", 0.07, 30, "statement", "#5b3a29",
           [("ST-OAK-24", "Counter stool 24 in, white oak", 118.00),
            ("ST-OAK-30", "Bar stool 30 in, white oak", 126.00),
            ("TBL-END-W", "End table, walnut veneer", 142.50),
            ("TBL-CON-48", "Console table 48 in, oak", 286.00),
            ("TBL-CAF-36", "Cafe table 36 in round", 214.00),
            ("BNC-ENT-42", "Entry bench 42 in, cushioned", 198.00),
            ("SHF-WL-36", "Floating wall shelf 36 in", 46.75),
            ("SHF-WL-24", "Floating wall shelf 24 in", 38.25),
            ("BKC-5S", "Bookcase, 5 shelf, ash", 239.00),
            ("CHR-DIN-SP", "Dining chair, spindle back", 96.50),
            ("CHR-DIN-UP", "Dining chair, upholstered", 132.00),
            ("OTT-RND-18", "Round ottoman 18 in, boucle", 88.00),
            ("CRT-STG-L", "Storage crate, large, slatted", 34.60),
            ("CRT-STG-S", "Storage crate, small, slatted", 22.80),
            ("TRY-SRV-OK", "Serving tray, oak, handles", 27.40),
            ("MIR-WL-30", "Wall mirror 30 in, oak frame", 112.00),
            ("RCK-CT-5", "Coat rack, 5 hook, ash", 41.20)]),
    Vendor("THIS", "V-1019", "Thistlewood Pallet & Crate Co.", "Thistlewood Pallet and Crate",
           ["THISTLEWOOD PALLET + CRATE", "Thistlewood Pallet & Crate Co."], "THISTLEWOOD PALLE", "THISTLEWOOD PLT CRATE",
           "14 Splitrail Hwy", "Burdock Mills, KY 42999", "(270) 555-0161", "office@thistlewood-pallet.example",
           "TPC-{n:05d}", 0.0, 15, "ledger", "#6b4f1d",
           [("PLT-GMA-48", "GMA pallet 48x40, grade A", 11.40),
            ("PLT-HT-48", "Heat-treated pallet 48x40", 14.25),
            ("CRT-CST", "Custom crate, per spec sheet", 185.00),
            ("PLT-PU", "Pallet pickup and recycle, per load", 160.00)]),
    Vendor("VELL", "V-1020", "Vellum & Vine Creative LLC", "V&V Studio",
           ["Vellum and Vine Creative LLC dba V&V Studio", "VELLUM & VINE CREATIVE"], "VELLUM VINE CREAT", "VELLUM AND VINE CREATIVE",
           "5 Inkwell Row, Studio 2", "Quarry Lake, CO 80999", "(720) 555-0115", "hello@vv-studio.example",
           "VV-26-{n:04d}", 0.0, 15, "service", "#9d174d",
           [("DSN-HR", "Design services, hourly", 95.00),
            ("PHT-DAY", "Product photography, day rate", 1150.00),
            ("RTCH-IMG", "Image retouching, per image", 14.00)],
           tagline="a DBA of Vellum &amp; Vine Creative LLC"),
    # carryovers from earlier months
    Vendor("TIDE", "V-1003", "Tidewater Freight Solutions LLC", "Tidewater Freight Solutions",
           ["Tidewater Freight Sol.", "Tidewater Freight Solutions LLC"], "TIDEWATER FREIGHT", "TIDEWATER FRT SOL",
           "5 Harbor Light Pkwy", "Port Calloway, SC 29998", "(843) 555-0163", "invoices@tidewaterfreight.example",
           "TFS-{n}", 0.0, 15, "modern", "#1f4e79",
           [("LTL-WC", "LTL freight, Port Calloway to Alder Falls", 1240.00),
            ("LTL-XD", "LTL freight, cross-dock transfer", 865.00),
            ("LIFT", "Liftgate delivery", 95.00),
            ("DET-HR", "Detention, per hour", 85.00)]),
    Vendor("PINE", "V-1009", "Pinehollow Janitorial Services", "Pinehollow Janitorial",
           ["PINEHOLLOW JANITORIAL SVCS", "Pinehollow Janitorial Services"], "PINEHOLLOW JANITOR", "PINEHOLLOW JANITORIAL",
           "17 Mossgate Rd", "Alder Falls, OR 97899", "(541) 555-0196", "office@pinehollow.example",
           "PJ-{n:04d}", 0.0, 15, "minimal", "#2d6a4f",
           [("SVC-MO", "Monthly janitorial service, warehouse", 2850.00),
            ("SVC-FLR", "Floor strip and wax, 12,000 sq ft", 1150.00),
            ("SVC-WIN", "Exterior window washing, storefront", 640.00)]),
    Vendor("JUNI", "V-1004", "Juniper & Ash Office Supply", "Juniper & Ash",
           ["Juniper and Ash Office Supply", "JUNIPER & ASH"], "JUNIPER AND ASH", "JUNIPER & ASH OFFI",
           "212 Willowmere Ave, Suite 4", "Hollis Bay, ME 04999", "(207) 555-0150", "orders@juniperash.example",
           "JA-{n:04d}", 0.055, 30, "classic", "#7a4b2a",
           [("PPR-LTR", "Copy paper, letter, case of 10 reams", 49.99),
            ("TNR-58A", "Toner cartridge, black, high yield", 132.00),
            ("LBL-4X6", "Shipping labels 4x6, roll of 500", 18.75),
            ("CHR-ERG", "Task chair, mesh back", 245.00)]),
]}

# ------------------------------------------------------------------ the month
# memo styles: inv, invhash, rmr, bare, none, obi (wire), multi; CHECK has no memo
PLAN = [
    dict(v="FERN", scen="clean", ch="pdf", pay=("ACH", "rmr")),
    dict(v="QUIL", scen="clean", ch="csv", pay=("ACH", "invhash")),
    dict(v="OSPR", scen="clean", ch="scan", pay=("WIRE", "obi")),
    dict(v="BRAM", scen="clean", ch="csv", pay=("ACH", "none")),
    dict(v="SALT", scen="clean", ch="pdf", pay=("ACH", "inv")),
    dict(v="HARR", scen="clean", ch="pdf", nlines=16, pay=("WIRE", "none")),
    dict(v="THIS", scen="clean", ch="csv", pay=("ACH", "bare")),
    dict(v="VELL", scen="clean", ch="pdf", pay=("ACH", "invhash")),
    dict(v="TIDE", scen="clean", ch="csv", pay=("ACH", "inv")),
    dict(v="PINE", scen="clean", ch="pdf", pay=("ACH", "rmr")),
    dict(v="JUNI", scen="clean", ch="csv", pay=("WIRE", "obi")),
    dict(v="FERN", scen="clean", ch="csv", pay=("ACH", "invhash")),
    dict(v="BRAM", scen="clean", ch="scan", pay=("ACH", "inv")),
    dict(v="SALT", scen="clean_check", ch="csv", pay=("CHECK", None)),
    dict(v="THIS", scen="clean_check", ch="pdf", pay=("CHECK", None)),
    dict(v="OSPR", scen="multi_pay", ch="csv", group="A"),
    dict(v="OSPR", scen="multi_pay", ch="scan", nlines=13, group="A"),
    dict(v="OSPR", scen="multi_pay", ch="csv", group="A"),
    dict(v="QUIL", scen="rounding", ch="pdf", rounding="subtotal", pay=("ACH", "inv")),
    dict(v="VELL", scen="rounding", ch="csv", rounding="payment", pay=("ACH", "bare")),
    dict(v="SALT", scen="amount_mismatch", ch="scan", mismatch="qty", pay=("ACH", "inv")),
    dict(v="FERN", scen="amount_mismatch", ch="csv", mismatch="price", pay=("WIRE", "none")),
    dict(v="TIDE", scen="amount_mismatch", ch="pdf", mismatch="extra_line", pay=("ACH", "invhash")),
    # resend: same number, later date, second PDF; only the original is paid
    dict(v="QUIL", scen="duplicate_unpaid", ch="pdf", pay=("ACH", "inv"),
         dup=dict(kind="resend", ch="pdf", days=21)),
    # re-keyed: AP tool has it without the dash; both got paid
    dict(v="THIS", scen="duplicate_paid_twice", ch="pdf", pay=("ACH", "inv"),
         dup=dict(kind="nodash", ch="csv", days=0, pay=("CHECK", None))),
    # same invoice keyed in AP tool and also sitting in the inbox
    dict(v="JUNI", scen="duplicate_unpaid", ch="csv", pay=("WIRE", "obi"),
         dup=dict(kind="same", ch="pdf", days=0)),
    dict(v="HARR", scen="partial_payment", ch="csv", frac=0.5, pay=("ACH", "invhash")),
    dict(v="PINE", scen="partial_payment", ch="scan", frac=0.4, pay=("WIRE", "obi")),
    dict(v="VELL", scen="missing_po", ch="pdf", po_note="n/a", pay=("ACH", "inv")),
    dict(v="OSPR", scen="missing_po", ch="csv", pay=("ACH", "rmr")),
    dict(v="PINE", scen="missing_po", ch="csv", pay=("ACH", "none")),
    dict(v="FERN", scen="missing_po", ch="scan", po_note="per J. Lindqvist", pay=("ACH", "invhash")),
    dict(v="BRAM", scen="unpaid", ch="pdf", late=True),
    dict(v="SALT", scen="unpaid", ch="csv", late=True),
    dict(v="HARR", scen="unpaid", ch="pdf", late=True),
    dict(v="TIDE", scen="unpaid", ch="pdf", late=True),
    dict(v="JUNI", scen="clean", ch="pdf", pay=("ACH", "inv")),
]

UNMATCHED = [("QUIL", 2150.00, "ACH", "none"), ("TIDE", 1385.00, "WIRE", "none"), ("BRAM", 918.60, "ACH", "none")]

EXCEPTIONS = {
    "amount_mismatch": ["AMOUNT_MISMATCH_PO"],
    "partial_payment": ["PARTIAL_PAYMENT"],
    "missing_po": ["MISSING_PO"],
}


def money(x):
    return round(x + 1e-9, 2)


def fmt(x):
    return f"{x:,.2f}"


def us(dt):
    return f"{dt.month:02d}/{dt.day:02d}/{dt.year}"


class Counter:
    def __init__(self, start):
        self.n = start

    def next(self, lo=1, hi=7):
        self.n += rng.randint(lo, hi)
        return self.n


inv_counters = {k: Counter(rng.randint(1500, 60000)) for k in VENDORS}
po_counter = Counter(10508)
doc_counter = Counter(55420)
check_counter = Counter(10489)


def make_lines(v, k=None):
    k = k or rng.randint(1, min(3, len(v.catalog)))
    items = rng.sample(v.catalog, k)
    lines = []
    for sku, desc, price in items:
        if price < 5:
            qty = rng.choice([120, 240, 360, 480, 600, 960])
        elif price < 60:
            qty = rng.randint(8, 72)
        elif price < 400:
            qty = rng.randint(2, 12)
        else:
            qty = rng.randint(1, 3)
        lines.append({"sku": sku, "description": desc, "qty": qty, "unit_price": price,
                      "amount": money(qty * price)})
    return lines


def total_of(lines):
    return money(sum(l["amount"] for l in lines))


invoices, pos, payments = [], [], []
groups = {}

for idx, spec in enumerate(PLAN):
    v = VENDORS[spec["v"]]
    scen = spec["scen"]
    if spec.get("late"):
        po_date = date(2026, 11, 28) + timedelta(days=rng.randint(0, 8))
    else:
        po_date = date(2026, 10, 14) + timedelta(days=rng.randint(0, 40))
    has_po = scen != "missing_po"
    taken = [x["total"] for x in invoices] + [a for _, a, _, _ in UNMATCHED]
    for _attempt in range(500):
        lines = make_lines(v, spec.get("nlines"))
        po_total = total_of(lines)
        inv_lines = [dict(l) for l in lines]
        price_decimals = 2
        mm = spec.get("mismatch")
        if mm == "qty":
            b = inv_lines[0]
            b["qty"] += max(2, round(b["qty"] * rng.choice([0.1, 0.12, 0.15])))
            b["amount"] = money(b["qty"] * b["unit_price"])
        elif mm == "price":
            b = max(inv_lines, key=lambda l: l["amount"])
            b["unit_price"] = money(b["unit_price"] * rng.choice([1.06, 1.08, 1.1]))
            b["amount"] = money(b["qty"] * b["unit_price"])
        elif mm == "extra_line":
            inv_lines.append({"sku": "FSC", "description": "Fuel surcharge", "qty": 1,
                              "unit_price": 148.00, "amount": 148.00})
        if spec.get("rounding") == "subtotal":
            # vendor system carries 3-decimal unit prices; lands cents off the PO
            b = max(inv_lines, key=lambda l: l["qty"])
            steps = [s for s in (0.001, 0.002, 0.003, 0.004) if 0.05 <= b["qty"] * s <= 0.95]
            if not steps:
                continue
            b["unit_price"] = round(b["unit_price"] + rng.choice(steps), 3)
            b["amount"] = money(b["qty"] * b["unit_price"])
            price_decimals = 3
        subtotal = total_of(inv_lines)
        tax = money(subtotal * v.tax_rate)
        inv_total = money(subtotal + tax)
        if all(abs(inv_total - t) > 2 * TOLERANCE for t in taken) and inv_total > 150:
            break
    else:
        raise SystemExit(f"could not place amounts for plan row {idx}")
    po_no = f"PO-{po_counter.next(1, 4)}" if has_po else ""
    inv_date = po_date + timedelta(days=rng.randint(4, 16))
    if spec.get("late"):
        inv_date = max(inv_date, date(2026, 12, 9))
    if inv_date > date(2026, 12, 18) and not spec.get("late"):
        inv_date = date(2026, 12, 18) - timedelta(days=rng.randint(0, 5))
    due = inv_date + timedelta(days=v.terms_days)
    inv_no = v.inv_fmt.format(n=inv_counters[v.key].next())

    if has_po:
        pos.append({"po": po_no, "date": po_date, "vendor": v, "lines": lines, "total": po_total,
                    "status": "Received" if rng.random() < 0.8 else "Partially Received"})

    inv = {"id": f"INV-{idx + 1:03d}", "vendor": v, "number": inv_no, "date": inv_date, "due": due,
           "po_ref": po_no, "po_note": spec.get("po_note", ""), "lines": inv_lines, "subtotal": subtotal,
           "tax": tax, "total": inv_total, "channel": spec["ch"], "scenario": scen,
           "po_total": po_total if has_po else None, "price_decimals": price_decimals,
           "so_ref": f"SO-{rng.randint(30000, 89999)}", "stamp": ""}
    invoices.append(inv)

    dup = None
    if "dup" in spec:
        ds = spec["dup"]
        dup = dict(inv)
        dup["id"] = inv["id"] + "D"
        dup["channel"] = ds["ch"]
        dup["duplicate_of"] = inv["id"]
        dup["date"] = inv_date + timedelta(days=ds["days"])
        dup["due"] = dup["date"] + timedelta(days=v.terms_days)
        if ds["kind"] == "nodash":
            dup["number"] = inv_no.replace("-", "")
        if ds["kind"] == "resend":
            dup["stamp"] = "REMINDER &middot; PLEASE REMIT"
        invoices.append(dup)

    def pay(amount, invs, kind, style, when=None):
        when = when or min(i["due"] for i in invs) - timedelta(days=rng.randint(0, 5))
        when = max(when, max(i["date"] for i in invs) + timedelta(days=2))
        if when < PERIOD_START:
            when = PERIOD_START + timedelta(days=rng.randint(1, 8))
        if when > PERIOD_END:
            when = PERIOD_END - timedelta(days=rng.randint(0, 3))
        p = {"date": when, "amount": money(amount), "vendor": v, "kind": kind, "style": style,
             "invoices": [i["id"] for i in invs], "inv_numbers": [i["number"] for i in invs]}
        payments.append(p)
        return p

    if scen in ("clean", "clean_check", "amount_mismatch", "missing_po", "duplicate_unpaid"):
        pay(inv_total, [inv], *spec["pay"])
    elif scen == "rounding":
        amt = inv_total if spec["rounding"] == "subtotal" else float(int(inv_total))
        if spec["rounding"] == "payment" and inv_total - amt < 0.05:
            amt = money(inv_total - 0.35)
        pay(amt, [inv], *spec["pay"])
    elif scen == "duplicate_paid_twice":
        p1 = pay(inv_total, [inv], *spec["pay"])
        pay(inv_total, [dup], *spec["dup"]["pay"], when=p1["date"] + timedelta(days=rng.randint(4, 9)))
    elif scen == "partial_payment":
        pay(money(inv_total * spec["frac"]), [inv], *spec["pay"])
    elif scen == "multi_pay":
        groups.setdefault(spec["group"], []).append(inv)

for g, mp in groups.items():
    v = mp[0]["vendor"]
    when = max(i["date"] for i in mp) + timedelta(days=rng.randint(6, 12))
    payments.append({"date": min(when, PERIOD_END), "amount": money(sum(i["total"] for i in mp)), "vendor": v,
                     "kind": "ACH", "style": "multi", "invoices": [i["id"] for i in mp],
                     "inv_numbers": [i["number"] for i in mp]})

for vk, amt, kind, style in UNMATCHED:
    payments.append({"date": date(2026, rng.choice([11, 12]), rng.randint(3, 27)), "amount": amt,
                     "vendor": VENDORS[vk], "kind": kind, "style": style, "invoices": [], "inv_numbers": [],
                     "unmatched": True})

# ------------------------------------------------------------------ sanity
for i in invoices:
    assert money(i["subtotal"] + i["tax"]) == i["total"], i["id"]
    assert money(sum(l["amount"] for l in i["lines"])) == i["subtotal"], i["id"]
    assert i["date"] <= date(2026, 12, 22), i["id"]
    if i["po_total"] is not None:
        diff = abs(i["subtotal"] - i["po_total"])
        if i["scenario"] == "amount_mismatch":
            assert diff > 5, i["id"]
        elif i["scenario"] == "rounding" and i["price_decimals"] == 3:
            assert 0.01 <= diff < TOLERANCE, (i["id"], diff)
        else:
            assert diff < 0.005, i["id"]
for p in payments:
    assert PERIOD_START <= p["date"] <= PERIOD_END, p
    for iid in p["invoices"]:
        inv = next(i for i in invoices if i["id"] == iid)
        assert p["date"] > inv["date"], (iid, p["date"])
# no accidental amount collisions (within tolerance) between unrelated invoices / payments
originals = [i for i in invoices if not i.get("duplicate_of")]
for a in range(len(originals)):
    for b in range(a + 1, len(originals)):
        assert abs(originals[a]["total"] - originals[b]["total"]) > 2 * TOLERANCE, (originals[a]["id"], originals[b]["id"])
for p in payments:
    if p.get("unmatched") or p["style"] == "multi":
        for i in originals:
            assert abs(p["amount"] - i["total"]) > 2 * TOLERANCE, (p, i["id"])

# ------------------------------------------------------------------ bank memos
def memo(p, ref):
    v = p["vendor"]
    nums = p["inv_numbers"]
    st = p["style"]
    if p["kind"] == "CHECK":
        return f"CHECK {ref}"
    if p["kind"] == "WIRE":
        tail = f" OBI INV NO {nums[0]}" if st == "obi" and nums else ""
        return f"WIRE OUT {v.bank_wire}{tail} REF {ref}"
    ppd = f"PPD ID 9{rng.randint(100000000, 999999999)}"
    ccd = f"CCD ID 1{rng.randint(100000000, 999999999)}"
    if st == "multi":
        return f"ACH DEBIT {v.bank_ach} {ccd} ADDENDA " + " ".join(f"Inv# {n}" for n in nums)
    if st == "inv":
        return f"ACH DEBIT {v.bank_ach} {ppd} INV {nums[0]}"
    if st == "invhash":
        return f"ACH DEBIT {v.bank_ach} {ccd} Inv#{nums[0]}"
    if st == "rmr":
        return f"ACH DEBIT {v.bank_ach} {ccd} ADDENDA RMR*IV*{nums[0]}*{p['amount']:.2f}\\"
    if st == "bare":
        return f"ACH DEBIT {v.bank_ach} {ppd} {nums[0]}"
    return f"ACH DEBIT {v.bank_ach} {ppd}"


noise = [("2026-11-02", "ACH DEBIT", "ADP PAYROLL TAX 001", 49102.35),
         ("2026-11-16", "ACH DEBIT", "ADP PAYROLL TAX 001", 51877.90),
         ("2026-12-01", "ACH DEBIT", "ADP PAYROLL TAX 001", 56230.44),
         ("2026-12-15", "ACH DEBIT", "ADP PAYROLL TAX 001", 58419.08),
         ("2026-11-05", "FEE", "MONTHLY SERVICE FEE", 35.00),
         ("2026-12-04", "FEE", "MONTHLY SERVICE FEE", 35.00),
         ("2026-11-12", "CARD", "CARD SETTLEMENT FEES MERCH 8841", 488.12),
         ("2026-12-11", "CARD", "CARD SETTLEMENT FEES MERCH 8841", 631.57),
         ("2026-12-21", "TRANSFER", "ONLINE TRANSFER TO SAV XXXX9120", 40000.00)]
deposits = [(f"2026-{m:02d}-{dd:02d}", amt) for m, dd, amt in
            [(11, 6, 63318.41), (11, 13, 66102.77), (11, 20, 71455.09), (11, 27, 88912.36),
             (12, 4, 79630.12), (12, 11, 84207.55), (12, 18, 92144.80), (12, 26, 70881.23)]]

bank_rows = []
for p in sorted(payments, key=lambda x: (x["date"], x["amount"])):
    ref = str(check_counter.next(1, 3)) if p["kind"] == "CHECK" else f"{rng.randint(10**9, 10**10 - 1)}"
    p["bank_ref"] = ref
    p["memo"] = memo(p, ref)[:110]
    bank_rows.append({"date": p["date"], "type": {"ACH": "ACH DEBIT", "WIRE": "WIRE OUT", "CHECK": "CHECK"}[p["kind"]],
                      "desc": p["memo"], "ref": ref, "debit": p["amount"], "credit": None})
for ds, t, desc, amt in noise:
    bank_rows.append({"date": date.fromisoformat(ds), "type": t, "desc": desc,
                      "ref": f"{rng.randint(10**9, 10**10 - 1)}", "debit": amt, "credit": None})
for ds, amt in deposits:
    bank_rows.append({"date": date.fromisoformat(ds), "type": "ACH CREDIT", "desc": "CARD SETTLEMENT MERCH 8841",
                      "ref": f"{rng.randint(10**9, 10**10 - 1)}", "debit": None, "credit": amt})
bank_rows.sort(key=lambda r: (r["date"], r["debit"] is None))

# ------------------------------------------------------------------ write CSVs
for pth in (INBOX, KEY, BLIND):
    if pth.exists():
        shutil.rmtree(pth)
    pth.mkdir(parents=True)
for old in DATA.glob("*.csv"):
    old.unlink()

with open(DATA / PO_FILE, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["PO Number", "PO Date", "Supplier ID", "Supplier Name", "Line", "Item Code", "Item Description",
                "Qty Ordered", "UOM", "Unit Price", "Line Total", "PO Total", "Currency", "PO Status",
                "Buyer", "Cost Center", "Approved By"])
    buyers = ["M. Okafor", "J. Lindqvist", "R. Bowman", "T. Achebe"]
    for po in sorted(pos, key=lambda x: x["po"]):
        for n, l in enumerate(po["lines"], 1):
            w.writerow([po["po"], po["date"].isoformat(), po["vendor"].vid, po["vendor"].name, n, l["sku"],
                        l["description"], l["qty"], "EA", f"{l['unit_price']:.2f}", f"{l['amount']:.2f}",
                        f"{po['total']:.2f}", "USD", po["status"], rng.choice(buyers),
                        rng.choice(["CC-310 Warehouse", "CC-120 Operations", "CC-450 Marketing", "CC-200 Facilities"]),
                        rng.choice(["D. Reyes", "S. Patel"])])

ap_rows = [i for i in invoices if i["channel"] == "csv"]
with open(DATA / AP_FILE, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Document ID", "Supplier", "Supplier Invoice No.", "Invoice Date", "Due Date", "PO No.",
                "Net Amount", "Tax Amount", "Gross Amount", "Currency", "Received Via", "Approval Status",
                "Entered By", "Entered On"])
    for i in sorted(ap_rows, key=lambda x: (x["date"], x["number"])):
        i["doc_id"] = f"LL-{doc_counter.next(3, 19)}"
        lag = rng.randint(0, 2) if not i.get("duplicate_of") else rng.randint(5, 9)
        w.writerow([i["doc_id"], rng.choice(i["vendor"].ap_names), i["number"], us(i["date"]), us(i["due"]),
                    i["po_ref"], fmt(i["subtotal"]), fmt(i["tax"]), fmt(i["total"]), "USD",
                    rng.choice(["Supplier Portal", "Supplier Portal", "EDI 810"]),
                    rng.choice(["Approved", "Approved", "Pending Approval"]), "system",
                    us(i["date"] + timedelta(days=lag))])

with open(DATA / BANK_FILE, "w", newline="") as f:
    f.write("Granite Valley Bank\n")
    f.write("Account: Business Operating Checking ****4417\n")
    f.write(f"Activity Period: {us(PERIOD_START)} - {us(PERIOD_END)}\n")
    f.write("\n")
    w = csv.writer(f)
    w.writerow(["Posting Date", "Transaction Type", "Description", "Reference", "Debit", "Credit", "Balance"])
    bal = 498_260.17
    for r in bank_rows:
        bal = money(bal - (r["debit"] or 0) + (r["credit"] or 0))
        w.writerow([us(r["date"]), r["type"], r["desc"], r["ref"],
                    f"-{r['debit']:.2f}" if r["debit"] else "", f"{r['credit']:.2f}" if r["credit"] else "",
                    f"{bal:.2f}"])

# ------------------------------------------------------------------ PDFs
CSS = {
    "classic": """
      body{font-family:Georgia,'DejaVu Serif',serif;color:#222;margin:0;padding:48px 56px;font-size:12px}
      .top{display:flex;justify-content:space-between;border-bottom:3px double ACCENT;padding-bottom:14px}
      .mark{width:46px;height:46px;border-radius:50%;background:ACCENT;color:#fff;display:flex;
            align-items:center;justify-content:center;font-weight:bold;font-size:17px;margin-bottom:8px}
      h1{font-size:26px;letter-spacing:4px;color:ACCENT;margin:0;text-align:right}
      th{border-bottom:1px solid #222;text-align:left;padding:6px 4px;font-size:11px;text-transform:uppercase}
      td{padding:6px 4px;border-bottom:1px solid #ddd}
    """,
    "modern": """
      body{font-family:Helvetica,Arial,'Liberation Sans',sans-serif;color:#1f2937;margin:0;font-size:12px}
      .band{background:ACCENT;color:#fff;padding:28px 48px;display:flex;justify-content:space-between;align-items:center}
      .band h1{margin:0;font-size:30px;font-weight:300;letter-spacing:2px}
      .mark{width:40px;height:40px;border-radius:8px;background:rgba(255,255,255,.2);display:flex;
            align-items:center;justify-content:center;font-weight:700;margin-right:12px}
      .wrap{padding:28px 48px}
      th{background:#f3f4f6;text-align:left;padding:8px;font-size:11px;color:#4b5563}
      td{padding:8px;border-bottom:1px solid #e5e7eb}
      .stamp{display:inline-block;border:3px solid #b91c1c;color:#b91c1c;font-weight:700;padding:6px 14px;
             font-size:16px;letter-spacing:2px;transform:rotate(-4deg);margin-top:14px}
    """,
    "minimal": """
      body{font-family:'Courier New','DejaVu Sans Mono',monospace;color:#111;margin:0;padding:44px 52px;font-size:11.5px}
      h1{font-size:20px;margin:0 0 4px 0}
      th{text-align:left;border-top:1px solid #111;border-bottom:1px solid #111;padding:5px 3px}
      td{padding:5px 3px}
    """,
    # new layouts below
    "ledger": """
      body{font-family:'Liberation Sans',Arial,sans-serif;color:#111;margin:0;padding:40px 48px;font-size:12px}
      .hdr{display:grid;grid-template-columns:1.3fr 1fr;border:2px solid ACCENT}
      .hdr > div{padding:12px 14px}
      .co{border-right:2px solid ACCENT}
      .co b.nm{font-size:19px;color:ACCENT;display:block;margin-bottom:4px}
      .ttl{background:ACCENT;color:#fff;font-size:15px;letter-spacing:3px;text-align:center;padding:4px;margin:-12px -14px 10px}
      .grid{display:grid;grid-template-columns:auto 1fr;gap:3px 10px}
      .grid span:nth-child(odd){font-weight:bold;text-transform:uppercase;font-size:10.5px;color:#444}
      .boxes{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px}
      .box{border:1px solid #999;padding:8px 10px}
      .box .lb{font-size:10px;font-weight:bold;color:#555;text-transform:uppercase;border-bottom:1px solid #ccc;margin-bottom:4px}
      table.items{width:100%;border-collapse:collapse;margin-top:16px}
      table.items th{background:#e9ece9;border:1px solid #999;padding:5px;font-size:10.5px;text-transform:uppercase}
      table.items td{border:1px solid #bbb;padding:5px}
      table.tot{border-collapse:collapse;margin-left:auto;margin-top:10px;width:300px}
      table.tot td{border:1px solid #999;padding:6px 8px}
      .bal td{font-weight:bold;font-size:14px;background:#e9ece9}
    """,
    "statement": """
      body{font-family:'DejaVu Serif',Georgia,serif;color:#1c1c1c;margin:0;font-size:12px}
      .page{padding:40px 52px;height:960px;box-sizing:border-box;position:relative;page-break-after:always}
      .page:last-child{page-break-after:auto}
      .lh{text-align:center;border-bottom:1px solid ACCENT;padding-bottom:10px}
      .lh .nm{font-size:22px;color:ACCENT;letter-spacing:1px;font-variant:small-caps}
      .lh .ad{font-size:10.5px;color:#555;margin-top:3px}
      .row{display:flex;justify-content:space-between;margin-top:18px}
      .doc{border:1px solid ACCENT;min-width:250px}
      .doc .h{background:ACCENT;color:#fff;text-align:center;padding:4px;letter-spacing:2px;font-size:13px}
      .doc table td{padding:3px 10px}
      .doc table td:first-child{color:#555}
      table.items{width:100%;border-collapse:collapse;margin-top:18px}
      table.items th{border-top:2px solid ACCENT;border-bottom:1px solid ACCENT;padding:6px 4px;text-align:left;font-size:11px}
      table.items td{padding:5px 4px;border-bottom:1px dotted #bbb}
      .foot{position:absolute;bottom:36px;left:52px;right:52px;font-size:10px;color:#666;
            border-top:1px solid #ccc;padding-top:6px;display:flex;justify-content:space-between}
      table.tot{margin-left:auto;margin-top:16px;border-collapse:collapse;width:290px}
      table.tot td{padding:5px 6px}
      table.tot tr.due td{border-top:2px solid ACCENT;font-weight:bold;font-size:14px}
    """,
    "service": """
      body{font-family:'Liberation Sans',Helvetica,sans-serif;color:#2a2a2a;margin:0;padding:56px 64px;font-size:12.5px}
      .brand{font-size:34px;font-weight:700;color:ACCENT;letter-spacing:-1px}
      .tag{font-size:10.5px;color:#777;margin-bottom:26px}
      .cols{display:flex;justify-content:space-between;margin-bottom:24px}
      .k{font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#888}
      .meta div{margin-bottom:5px}
      table.items{width:100%;border-collapse:collapse;margin-top:10px}
      table.items th{text-align:left;font-size:10px;letter-spacing:1px;text-transform:uppercase;color:#888;
                     border-bottom:2px solid ACCENT;padding:6px 2px}
      table.items td{padding:9px 2px;border-bottom:1px solid #eee}
      table.tot{margin-left:auto;margin-top:18px;width:260px}
      table.tot td{padding:4px 2px}
      .due{font-size:18px;color:ACCENT;font-weight:700}
    """,
}


def initials(name):
    words = [w for w in name.replace("&", " ").replace(".", " ").split() if w[0].isalpha()]
    return (words[0][0] + (words[1][0] if len(words) > 1 else "")).upper()


def up(i, x):
    return f"{x:,.{i['price_decimals']}f}"


def long_date(dt):
    return dt.strftime("%B %d, %Y")


def bill_to_block(label="Bill to"):
    return (f"<div style='font-size:10px;color:#666;text-transform:uppercase;letter-spacing:1px'>{label}</div>"
            f"<b>{BUYER['name']}</b><br>Attn: {BUYER['attn']}<br>{BUYER['street']}<br>{BUYER['city']}")


def html_dev_style(i):
    """The three layouts carried over from earlier months (carryover vendors keep their look)."""
    v = i["vendor"]
    rows = "".join(
        f"<tr><td>{l['sku']}</td><td>{l['description']}</td><td style='text-align:right'>{l['qty']:,}</td>"
        f"<td style='text-align:right'>{up(i, l['unit_price'])}</td><td style='text-align:right'>{fmt(l['amount'])}</td></tr>"
        for l in i["lines"])
    po_line = f"<div><b>PO #:</b> {i['po_ref']}</div>" if i["po_ref"] else ""
    tax_label = f"Sales tax ({v.tax_rate * 100:.3g}%)" if v.tax_rate else "Tax"
    meta = (f"<div><b>Invoice #:</b> {i['number']}</div><div><b>Invoice date:</b> {long_date(i['date'])}</div>"
            f"<div><b>Due date:</b> {long_date(i['due'])}</div><div><b>Terms:</b> Net {v.terms_days}</div>{po_line}")
    vendor_block = f"<b>{v.invoice_name}</b><br>{v.street}<br>{v.city}<br>{v.phone}<br>{v.email}"
    totals = (f"<table style='width:280px;margin-left:auto;margin-top:14px'>"
              f"<tr><td>Subtotal</td><td style='text-align:right'>{fmt(i['subtotal'])}</td></tr>"
              f"<tr><td>{tax_label}</td><td style='text-align:right'>{fmt(i['tax'])}</td></tr>"
              f"<tr><td><b>Total due (USD)</b></td><td style='text-align:right'><b>${fmt(i['total'])}</b></td></tr></table>")
    remit = (f"<div style='margin-top:36px;font-size:10.5px;color:#555'>Please remit by ACH to account ending 7{rng.randint(100, 999)} "
             f"(routing on file) and reference invoice {i['number']}. Questions: {v.email}. Thank you for your business.</div>")
    stamp = f"<div class='stamp'>{i['stamp']}</div>" if i["stamp"] else ""
    table = (f"<table style='width:100%;border-collapse:collapse;margin-top:22px'><tr><th>Item</th><th>Description</th>"
             f"<th style='text-align:right'>Qty</th><th style='text-align:right'>Unit price</th>"
             f"<th style='text-align:right'>Amount</th></tr>{rows}</table>")
    if v.style == "modern":
        return (f"<div class='band'><div style='display:flex;align-items:center'><div class='mark'>{initials(v.invoice_name)}</div>"
                f"<div><b style='font-size:15px'>{v.invoice_name}</b><br><span style='opacity:.85'>{v.street}, {v.city}</span></div></div>"
                f"<h1>INVOICE</h1></div><div class='wrap'><div style='display:flex;justify-content:space-between'>"
                f"<div>{bill_to_block()}{stamp}</div><div style='text-align:right'>{meta}</div></div>{table}{totals}{remit}</div>")
    if v.style == "classic":
        return (f"<div class='top'><div><div class='mark'>{initials(v.invoice_name)}</div>{vendor_block}</div>"
                f"<div><h1>INVOICE</h1><div style='text-align:right;margin-top:10px'>{meta}</div></div></div>"
                f"<div style='margin-top:20px'>{bill_to_block()}</div>{table}{totals}{remit}")
    return (f"<h1>{v.invoice_name.upper()}</h1><div>{v.street} | {v.city} | {v.phone}</div>"
            f"<div style='margin:18px 0 8px 0'>INVOICE {i['number']}</div>"
            f"<div style='display:flex;justify-content:space-between'><div>{bill_to_block()}</div><div>{meta}</div></div>"
            f"{table}{totals}{remit}")


def html_ledger(i):
    v = i["vendor"]
    po = i["po_ref"] or i["po_note"] or "&mdash;"
    rows = "".join(
        f"<tr><td style='text-align:right'>{l['qty']:,}</td><td>{l['sku']}</td><td>{l['description']}</td>"
        f"<td style='text-align:right'>{up(i, l['unit_price'])}</td><td style='text-align:right'>{fmt(l['amount'])}</td></tr>"
        for l in i["lines"])
    tax_label = f"Sales Tax {v.tax_rate * 100:.3g}%" if v.tax_rate else "Sales Tax"
    return (
        f"<div class='hdr'><div class='co'><b class='nm'>{v.invoice_name}</b>{v.street}<br>{v.city}<br>"
        f"Tel {v.phone} &middot; {v.email}</div>"
        f"<div><div class='ttl'>INVOICE</div><div class='grid'>"
        f"<span>Inv No.</span><span>{i['number']}</span>"
        f"<span>Inv Date</span><span>{us(i['date'])}</span>"
        f"<span>Customer PO</span><span>{po}</span>"
        f"<span>Ref</span><span>{i['so_ref']}</span>"
        f"<span>Terms</span><span>Net {v.terms_days} &middot; due {us(i['due'])}</span></div></div></div>"
        f"<div class='boxes'><div class='box'><div class='lb'>Sold to</div><b>{BUYER['name']}</b><br>"
        f"Attn: {BUYER['attn']}<br>{BUYER['street']}<br>{BUYER['city']}</div>"
        f"<div class='box'><div class='lb'>Ship to</div><b>Copperline Home Goods DC</b><br>Dock 3<br>"
        f"4100 Larkspur Way<br>{BUYER['city']}</div></div>"
        f"<table class='items'><tr><th style='text-align:right'>Qty</th><th>Item</th><th>Description</th>"
        f"<th style='text-align:right'>Price</th><th style='text-align:right'>Ext.</th></tr>{rows}</table>"
        f"<table class='tot'><tr><td>Merchandise</td><td style='text-align:right'>{fmt(i['subtotal'])}</td></tr>"
        f"<tr><td>{tax_label}</td><td style='text-align:right'>{fmt(i['tax'])}</td></tr>"
        f"<tr class='bal'><td>BALANCE DUE</td><td style='text-align:right'>${fmt(i['total'])}</td></tr></table>"
        f"<div style='margin-top:30px;font-size:10.5px;color:#444'>Remit to {v.invoice_name}, {v.street}, {v.city}. "
        f"Please show Inv No. on your remittance. 1.5% monthly charge on balances past due.</div>")


def html_statement(i):
    v = i["vendor"]
    po = i["po_ref"] or i["po_note"] or "&mdash;"
    lines = i["lines"]
    chunks = [lines[:10], lines[10:]] if len(lines) > 11 else [lines]
    npages = len(chunks)
    lh = (f"<div class='lh'><div class='nm'>{v.invoice_name}</div>"
          f"<div class='ad'>{v.street} &middot; {v.city} &middot; {v.phone} &middot; {v.email}</div></div>")
    doc = (f"<div class='doc'><div class='h'>INVOICE</div><table>"
           f"<tr><td>Document No.</td><td><b>{i['number']}</b></td></tr>"
           f"<tr><td>Date Issued</td><td>{i['date'].strftime('%d %b %Y')}</td></tr>"
           f"<tr><td>Your Order Ref</td><td>{po}</td></tr>"
           f"<tr><td>Payment Due</td><td>{i['due'].strftime('%d %b %Y')}</td></tr></table></div>")
    head = ("<tr><th>Line</th><th>Item</th><th>Description</th><th style='text-align:right'>Qty</th>"
            "<th style='text-align:right'>Unit</th><th style='text-align:right'>Line Total</th></tr>")
    pages = []
    n = 0
    for pi, chunk in enumerate(chunks, 1):
        rows = ""
        for l in chunk:
            n += 1
            rows += (f"<tr><td>{n}</td><td>{l['sku']}</td><td>{l['description']}</td>"
                     f"<td style='text-align:right'>{l['qty']:,}</td><td style='text-align:right'>{up(i, l['unit_price'])}</td>"
                     f"<td style='text-align:right'>{fmt(l['amount'])}</td></tr>")
        if pi == 1:
            top = f"{lh}<div class='row'><div>{bill_to_block('Invoice to')}</div>{doc}</div>"
        else:
            top = (f"{lh}<div class='row'><div><b>{BUYER['name']}</b></div>"
                   f"<div>Document No. <b>{i['number']}</b> (continued)</div></div>")
        body = f"{top}<table class='items'>{head}{rows}</table>"
        if pi == npages:
            tax_label = f"Sales Tax ({v.tax_rate * 100:.3g}%)" if v.tax_rate else "Sales Tax"
            body += (f"<table class='tot'><tr><td>Net Amount</td><td style='text-align:right'>{fmt(i['subtotal'])}</td></tr>"
                     f"<tr><td>{tax_label}</td><td style='text-align:right'>{fmt(i['tax'])}</td></tr>"
                     f"<tr class='due'><td>Amount Due USD</td><td style='text-align:right'>{fmt(i['total'])}</td></tr></table>"
                     f"<div style='margin-top:26px;font-size:10.5px;color:#555'>Payment by ACH or check. "
                     f"Please quote the Document No. with your payment.</div>")
        else:
            body += "<div style='margin-top:14px;text-align:right;font-style:italic'>Continued on next page</div>"
        body += (f"<div class='foot'><span>{v.invoice_name}</span><span>Page {pi} of {npages}</span></div>")
        pages.append(f"<div class='page'>{body}</div>")
    return "".join(pages)


def html_service(i):
    v = i["vendor"]
    po = i["po_ref"] or i["po_note"] or "&mdash;"
    rows = "".join(
        f"<tr><td>{l['description']}<div style='font-size:10px;color:#999'>{l['sku']}</div></td>"
        f"<td style='text-align:right'>{l['qty']:,}</td><td style='text-align:right'>{up(i, l['unit_price'])}</td>"
        f"<td style='text-align:right'>{fmt(l['amount'])}</td></tr>" for l in i["lines"])
    return (
        f"<div class='brand'>{v.invoice_name}</div><div class='tag'>{v.tagline} &middot; {v.street}, {v.city} &middot; {v.email}</div>"
        f"<div class='cols'><div>{bill_to_block('Billed to')}</div><div class='meta'>"
        f"<div><span class='k'>Inv #</span> {i['number']}</div>"
        f"<div><span class='k'>Issued</span> {long_date(i['date'])}</div>"
        f"<div><span class='k'>Ref / PO</span> {po}</div>"
        f"<div><span class='k'>Due</span> {long_date(i['due'])}</div></div></div>"
        f"<table class='items'><tr><th>Service</th><th style='text-align:right'>Units</th>"
        f"<th style='text-align:right'>Rate</th><th style='text-align:right'>Fees</th></tr>{rows}</table>"
        f"<table class='tot'><tr><td>Fees</td><td style='text-align:right'>{fmt(i['subtotal'])}</td></tr>"
        f"<tr><td>Tax</td><td style='text-align:right'>{fmt(i['tax'])}</td></tr>"
        f"<tr><td class='due'>Total Due</td><td class='due' style='text-align:right'>${fmt(i['total'])}</td></tr></table>"
        f"<div style='margin-top:40px;font-size:11px;color:#777'>Thank you! Pay by ACH; include the Inv # in the addenda.</div>")


def invoice_html(i):
    v = i["vendor"]
    css = CSS[v.style].replace("ACCENT", v.color)
    body = {"ledger": html_ledger, "statement": html_statement, "service": html_service}.get(v.style, html_dev_style)(i)
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"


pdf_invoices = [i for i in invoices if i["channel"] in ("pdf", "scan")]
for i in pdf_invoices:
    slug = "".join(ch for ch in i["vendor"].invoice_name.split()[0] if ch.isalnum()).capitalize()
    if i["vendor"].key == "VELL":
        slug = "VVStudio"
    base = f"{slug}_{i['number']}".replace("/", "-")
    if i.get("duplicate_of") and i["number"] == next(x for x in invoices if x["id"] == i["duplicate_of"])["number"] \
            and next(x for x in invoices if x["id"] == i["duplicate_of"])["channel"] in ("pdf", "scan"):
        base += "-1"
    i["file"] = base + ("_scan.pdf" if i["channel"] == "scan" else ".pdf")
assert len({i["file"] for i in pdf_invoices}) == len(pdf_invoices)


def fix_pdf_dates(path):
    b = path.read_bytes()
    b = re.sub(rb"D:\d{14}[^)]*", FIXED_PDF_DATE, b)
    path.write_bytes(b)


def render_pdfs():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page()
        for i in pdf_invoices:
            pg.set_content(invoice_html(i))
            out = INBOX / i["file"].replace("_scan.pdf", ".pdf")
            pg.pdf(path=str(out), format="Letter", print_background=True)
            fix_pdf_dates(out)
        br.close()


def scanify(src, dst):
    """Image-only scan: lower resolution, more skew, blur, speckle, streaks, JPEG-ish grain."""
    from PIL import Image, ImageFilter, ImageEnhance
    r = random.Random("holdout-scan:" + dst.name)
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["pdftoppm", "-r", "96", "-gray", "-png", str(src), f"{td}/p"], check=True)
        imgs = []
        for pth in sorted(Path(td).glob("p*.png")):
            im = Image.open(pth).convert("L")
            im = ImageEnhance.Contrast(im).enhance(0.95)
            im = im.point(lambda x: min(255, x + 4) if x > 140 else max(0, x - 25))
            im = im.rotate(r.choice([-1, 1]) * r.uniform(1.8, 3.0), resample=Image.BICUBIC, expand=True, fillcolor=228)
            im = im.filter(ImageFilter.GaussianBlur(0.75))
            px = im.load()
            w, h = im.size
            for _ in range(w * h // 110):
                x, y = r.randrange(w), r.randrange(h)
                px[x, y] = r.choice([70, 120, 160, 200])
            for _ in range(r.randint(2, 4)):          # scanner streaks
                x0 = r.randrange(w)
                shade = r.choice([175, 195, 210])
                for y in range(h):
                    if r.random() < 0.85:
                        px[x0, y] = min(px[x0, y], shade)
            # uneven lighting: darker toward the bottom edge
            from PIL import ImageChops
            grad = Image.linear_gradient("L").resize((w, h)).point(lambda g: 255 - g // 8)
            im = ImageChops.multiply(im, grad)
            im = Image.blend(im, Image.new("L", (w, h), 205), 0.06)
            imgs.append(im.convert("RGB"))
        fixed = time.strptime("2027-01-02 09:00:00", "%Y-%m-%d %H:%M:%S")
        imgs[0].save(dst, "PDF", save_all=True, append_images=imgs[1:], resolution=96, quality=58,
                     creationDate=fixed, modDate=fixed, producer="ScanStation 4")
    src.unlink()


render_pdfs()
for i in pdf_invoices:
    if i["channel"] == "scan":
        scanify(INBOX / i["file"].replace("_scan.pdf", ".pdf"), INBOX / i["file"])

# ------------------------------------------------------------------ answer key
pay_by_inv = {}
for p in payments:
    for iid in p["invoices"]:
        pay_by_inv.setdefault(iid, []).append(p)

key_invoices = []
for i in invoices:
    ps = pay_by_inv.get(i["id"], [])
    if len(ps) == 1 and len(ps[0]["invoices"]) > 1:
        paid = i["total"]
    else:
        paid = money(sum(p["amount"] for p in ps))
    scen = i["scenario"]
    is_dup = bool(i.get("duplicate_of"))
    if scen == "duplicate_unpaid":
        status, exc = ("EXCEPTION", ["DUPLICATE_INVOICE"]) if is_dup else ("RECONCILED", [])
    elif scen == "duplicate_paid_twice":
        status, exc = ("EXCEPTION", ["DUPLICATE_INVOICE", "DUPLICATE_PAYMENT"]) if is_dup else ("EXCEPTION", ["DUPLICATE_INVOICE"])
    elif scen == "unpaid":
        status, exc = "OPEN_UNPAID", []
    elif scen in EXCEPTIONS:
        status, exc = "EXCEPTION", list(EXCEPTIONS[scen])
    else:
        status, exc = "RECONCILED", []
    if not ps:
        assert status != "RECONCILED" or False, i["id"]
    key_invoices.append({
        "invoice_key": i["id"],
        "source": ("inbox/" + i["file"]) if i["channel"] in ("pdf", "scan") else f"{AP_FILE}#{i['doc_id']}",
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
        "scenario": scen,
        "duplicate_of": i.get("duplicate_of"),
    })

key_payments = [{"bank_ref": p["bank_ref"], "date": p["date"].isoformat(), "amount": p["amount"],
                 "vendor_id": p["vendor"].vid, "invoice_keys": p["invoices"],
                 "status": "UNMATCHED_PAYMENT" if p.get("unmatched") else "MATCHED"} for p in payments]

with open(KEY / "answer_key.json", "w") as f:
    json.dump({"tolerance_usd": TOLERANCE, "invoices": key_invoices, "vendor_payments": key_payments,
               "non_vendor_bank_lines": len(noise) + len(deposits)}, f, indent=2)

# ------------------------------------------------------------------ blind page images
pdf_files = sorted(p.name for p in INBOX.glob("*.pdf"))
order = pdf_files[:]
random.Random(SEED + 7).shuffle(order)
map_rows = []
pngs = []
with tempfile.TemporaryDirectory() as td:
    for n, name in enumerate(order, 1):
        doc = f"doc_{n:02d}"
        map_rows.append(f"{doc}\t{name}")
        subprocess.run(["pdftoppm", "-r", "110", "-png", str(INBOX / name), f"{td}/{doc}"], check=True)
        pages = sorted(Path(td).glob(f"{doc}-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
        for k, pth in enumerate(pages, 1):
            out = BLIND / (f"{doc}.png" if len(pages) == 1 else f"{doc}_p{k}.png")
            shutil.move(str(pth), out)
            pngs.append(out)
(BLIND / "blind_map.tsv").write_text("\n".join(map_rows) + "\n")
with zipfile.ZipFile(BLIND / "holdout_images_blind.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for pth in sorted(pngs):
        zi = zipfile.ZipInfo(pth.name, date_time=(2027, 1, 2, 9, 0, 0))
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = 0o644 << 16
        z.writestr(zi, pth.read_bytes())

print(f"{len(invoices)} invoices ({len(pdf_invoices)} PDF, {len(ap_rows)} AP export), {len(pos)} POs, "
      f"{len(payments)} vendor payments, {len(bank_rows)} bank lines, {len(pngs)} page images")
