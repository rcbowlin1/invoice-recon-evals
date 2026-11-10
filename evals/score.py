"""Score an agent run against the answer key.

    python evals/score.py runs/v1            # code checks only
    python evals/score.py runs/v2 --judge    # + Claude grades each exception note (needs ANTHROPIC_API_KEY)

Writes runs/<name>/scorecard.md and scorecard.json.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = json.load(open(ROOT / "answer_key" / "answer_key.json"))
TOL = 0.01
EXCEPTION_TYPES = ["AMOUNT_MISMATCH_PO", "DUPLICATE_INVOICE", "DUPLICATE_PAYMENT", "PARTIAL_PAYMENT", "MISSING_PO"]

# weights for the headline score (sum to 100)
WEIGHTS = {"extraction": 20, "status": 25, "exceptions": 25, "payment_matching": 15,
           "unmatched_payments": 5, "traceable_numbers": 10}


def same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= TOL
    return (a or None) == (b or None)


def f1(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def judge_notes(pairs, model):
    """LLM-as-judge: is each exception note correct and actionable? 1-5."""
    import anthropic
    client = anthropic.Anthropic()
    rubric = ("You review notes an AP agent wrote about invoice exceptions. Given the true situation and the "
              "agent's note, score 1-5: 5 = correct and an accountant could act on it without opening the "
              "documents; 3 = right idea but vague or missing the amount; 1 = wrong or misleading. "
              'Reply only with JSON: {"score": n, "why": "..."}')
    out = []
    for truth, note in pairs:
        msg = client.messages.create(model=model, max_tokens=200, system=rubric,
                                     messages=[{"role": "user", "content": f"True situation: {truth}\nAgent note: {note}"}])
        t = msg.content[0].text
        out.append(json.loads(t[t.find("{"): t.rfind("}") + 1]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    a = ap.parse_args()
    run = ROOT / a.run
    rep = json.load(open(run / "report.json"))
    got = {}
    for i in rep["invoices"]:
        src = i["source"]
        if "#" in src:
            src = "LedgerLoop_AP_Invoices_Export_2026-11-01.csv#" + src.split("#")[1]
        got[src] = i

    m = {}
    # 1) extraction: PDF invoices only (AP export rows are already structured)
    ext = defaultdict(lambda: [0, 0])
    for k in KEY["invoices"]:
        if k["source_type"] == "ap_export":
            continue
        g = got.get(k["source"], {})
        bucket = "scanned" if k["source_type"] == "scanned_pdf" else "clean"
        for fld, kf in (("invoice_number", "vendor_invoice_number"), ("po_number", "po_number"),
                        ("subtotal", "subtotal"), ("tax", "tax"), ("total", "total")):
            ext[bucket][1] += 1
            ext[bucket][0] += same(g.get(fld), k[kf])
    tot_ok = sum(v[0] for v in ext.values())
    tot_n = sum(v[1] for v in ext.values())
    m["extraction"] = tot_ok / tot_n
    m["extraction_clean"] = ext["clean"][0] / ext["clean"][1]
    m["extraction_scanned"] = ext["scanned"][0] / ext["scanned"][1]

    # 2) status
    rows, status_ok = [], 0
    for k in KEY["invoices"]:
        g = got.get(k["source"], {})
        ok = g.get("status") == k["status"]
        status_ok += ok
        rows.append((k, g, ok))
    m["status"] = status_ok / len(KEY["invoices"])

    # 3) exceptions: precision / recall per type
    per = {}
    TP = FP = FN = 0
    for t in EXCEPTION_TYPES:
        tp = fp = fn = 0
        for k in KEY["invoices"]:
            g = set(got.get(k["source"], {}).get("exceptions") or [])
            truth = t in k["exceptions"]
            pred = t in g
            tp += truth and pred
            fp += pred and not truth
            fn += truth and not pred
        per[t] = f1(tp, fp, fn) + (tp, fp, fn)
        TP, FP, FN = TP + tp, FP + fp, FN + fn
    p, r, f = f1(TP, FP, FN)
    m["exceptions"], m["exception_precision"], m["exception_recall"] = f, p, r

    # 4) payment matching: exact set of bank refs per invoice
    pm = sum(set(got.get(k["source"], {}).get("bank_refs") or []) == set(k["bank_refs"]) for k in KEY["invoices"])
    m["payment_matching"] = pm / len(KEY["invoices"])

    # 5) unmatched payments
    truth_un = {p["bank_ref"] for p in KEY["vendor_payments"] if p["status"] == "UNMATCHED_PAYMENT"}
    pred_un = {p["bank_ref"] for p in rep["payments"] if p["status"] == "UNMATCHED_PAYMENT"}
    up, ur, uf = f1(len(truth_un & pred_un), len(pred_un - truth_un), len(truth_un - pred_un))
    m["unmatched_payments"] = uf

    # 6) traceable numbers: every amount the agent reports must be a real amount for that invoice
    true_amounts, reported, bad = 0, 0, []
    for k in KEY["invoices"]:
        g = got.get(k["source"], {})
        real = {k["subtotal"], k["tax"], k["total"], k["amount_paid"]} | ({k["po_total"]} if k["po_total"] else set())
        for fld in ("subtotal", "tax", "total"):
            v = g.get(fld)
            if v is None:
                continue
            reported += 1
            if any(abs(v - x) <= TOL for x in real):
                true_amounts += 1
            else:
                bad.append((k["source"], fld, v))
    m["traceable_numbers"] = true_amounts / reported if reported else 0.0

    score = sum(WEIGHTS[x] * m[x] for x in WEIGHTS)

    judge = None
    if a.judge:
        pairs = []
        for k, g, _ in rows:
            if k["exceptions"] and g.get("notes"):
                truth = f"{k['scenario']}: exceptions {k['exceptions']}, invoice total {k['total']}, " \
                        f"PO total {k['po_total']}, paid {k['amount_paid']}"
                pairs.append((truth, " ".join(g["notes"])))
        res = judge_notes(pairs, a.model)
        judge = sum(r["score"] for r in res) / len(res) if res else None

    # ---------------------------------------------------------- write scorecard
    misses = [(k["source"], k["status"], g.get("status"), k["exceptions"], g.get("exceptions"))
              for k, g, ok in rows if not ok or set(k["exceptions"]) != set(g.get("exceptions") or [])]
    md = [f"# Scorecard: {a.run}", "", f"**Overall: {score:.1f} / 100**", "",
          "| Check | Weight | Result |", "|---|---|---|",
          f"| Field extraction (PDFs) | {WEIGHTS['extraction']} | {m['extraction']:.0%} "
          f"(clean {m['extraction_clean']:.0%}, scanned {m['extraction_scanned']:.0%}) |",
          f"| Invoice status | {WEIGHTS['status']} | {m['status']:.0%} |",
          f"| Exceptions (F1) | {WEIGHTS['exceptions']} | {m['exceptions']:.0%} "
          f"(precision {m['exception_precision']:.0%}, recall {m['exception_recall']:.0%}) |",
          f"| Payment matching | {WEIGHTS['payment_matching']} | {m['payment_matching']:.0%} |",
          f"| Unmatched payments found (F1) | {WEIGHTS['unmatched_payments']} | {m['unmatched_payments']:.0%} |",
          f"| Numbers traceable to source | {WEIGHTS['traceable_numbers']} | {m['traceable_numbers']:.0%} |"]
    if judge is not None:
        md += [f"| Exception notes (LLM judge, 1-5) | not weighted | {judge:.1f} |"]
    md += ["", "## By exception type", "", "| Type | Precision | Recall | TP | FP | FN |", "|---|---|---|---|---|---|"]
    for t, (p_, r_, f_, tp, fp, fn) in per.items():
        md.append(f"| {t} | {p_:.0%} | {r_:.0%} | {tp} | {fp} | {fn} |")
    md += ["", "## Misses", "", "| Source | Expected | Got | Expected exceptions | Got exceptions |",
           "|---|---|---|---|---|"]
    for s, es, gs, ee, ge in misses:
        md.append(f"| {s.split('/')[-1]} | {es} | {gs} | {', '.join(ee) or '-'} | {', '.join(ge or []) or '-'} |")
    if bad:
        md += ["", "## Numbers not found on the source", ""] + [f"- {s.split('/')[-1]}: {f} = {v}" for s, f, v in bad]
    (run / "scorecard.md").write_text("\n".join(md) + "\n")
    json.dump({"score": round(score, 1), "metrics": m, "judge": judge}, open(run / "scorecard.json", "w"), indent=2)
    print("\n".join(md[:13]))


if __name__ == "__main__":
    main()
