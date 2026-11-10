# Invoice Reconciliation Evals

An AI agent that reconciles invoices against purchase orders and bank payments, and the eval that tells you where it's failing and what to fix next.

Every company, town, phone number, email address, and amount here is made up.

## Results

Both versions were scored once on a **holdout month** of 40 invoices. They were built before the holdout existed, and neither was changed after seeing it.

| | v1: OCR + rules | v2: model reads + general rules |
|---|---|---|
| **Overall (out of 100)** | **55.2** | **90.1** |
| Field extraction (PDFs) | 47% (scans 10%) | 100% (scans 100%) |
| Invoice status | 65% | 92% |
| Exceptions found (F1) | 39% | 84% |
| Payment matching | 57% | 90% |
| Payments with no invoice found (F1) | 25% | 50% |
| Wrong with no human in the loop | 19 of 40 invoices ($95K) | 5 of 40 invoices ($27K) |

On the dev month it was built on, v1 scored 92.2. On new data it fell to 55.2. That drop is the point of a holdout: a dev score tells you the code runs, and a holdout score tells you whether it works.

## What the eval says to fix next

The eval's job is to show where to invest, not only to give a score.

- **v1 → v2: reading was the bottleneck.** v1's OCR couldn't handle new layouts or scans, and every check downstream failed with it. Moving reading to a model took extraction from 47% to 100%.
- **v2 → v3: duplicates are now the bottleneck.** All of v2's misses involve duplicates. An invoice resent with the same number had its payment matched to the wrong copy. One legitimate invoice was flagged as a duplicate, one real duplicate was missed, and one of two payments with no invoice went unflagged.
- **The safety net has a gap.** v2 sends an invoice to a person when the facts don't add up (a bad read, a total that doesn't tie out, a PO from another vendor). On the holdout it sent none and still made 5 silent errors. Its checks cover bad reads, not ambiguous duplicates, so the next version should route unclear duplicates to review instead of guessing.

Any v3 needs a **fresh holdout** before it gets a score, because this holdout has now been seen.

## How the eval is kept fair

1. **Dev set** (`data/`): one month, 39 invoices. Everything was built and tuned here. A perfect dev score (v2: 100) only means the code works.
2. **Holdout** (`holdout/`): a new month built by a separate agent that never saw the agent code. Its rules: mostly new vendors, new invoice layouts, two-page invoices, harder scans, new bank memo styles, and duplicates that don't follow the dev pattern. Its answers stayed sealed until scoring.
3. **Blind reads:** the invoice page images went to a different model under shuffled names, with no answers and no filenames.
4. **Scored once:** each version was scored once on the holdout and reported as-is.

## Limits

- **40 invoices is small.** One error moves a check by 2 to 3 points, so treat the results as directional.
- **The data is synthetic, and an AI made it.** The holdout reuses the dev file formats. Real invoices are messier.
- **One model, one read.** The 100% extraction comes from a single run.

## The task

Copperline Home Goods (fictional) has messy AP data in three places. The agent has to:

1. **Read every invoice:** clean PDFs, image-only scanned PDFs, and rows already keyed into the AP tool
2. **Match each invoice** to its purchase order and to the bank payment(s) that paid it
3. **Flag every exception** with a reason an accountant can act on
4. **Account for every vendor payment** in the bank file, including ones with no invoice behind them

Design rule: the model reads documents, and code owns every match, number, and status.

| File | What it is | Why it's messy |
|---|---|---|
| `inbox/*.pdf` | Invoices received by email, not yet keyed | Several vendor layouts; some are crooked, noisy scans with no text layer |
| `LedgerLoop_AP_Invoices_Export_*.csv` | Invoices already in the AP tool | Supplier names don't always match the vendor master |
| `ProcureHub_PO_Export_*.csv` | Purchase orders, one row per PO line | Totals repeat on every line |
| `GVB_Operating_*_Activity_*.csv` | Bank account activity | Preamble rows, truncated vendor names, memos with or without invoice numbers, checks, payroll and deposits mixed in |

Exceptions: `AMOUNT_MISMATCH_PO`, `DUPLICATE_INVOICE`, `DUPLICATE_PAYMENT`, `PARTIAL_PAYMENT`, `MISSING_PO`. Unpaid invoices are `OPEN_UNPAID`. Bank debits with no invoice are `UNMATCHED_PAYMENT`.

Matching rules: the invoice subtotal (before tax) is compared to the PO total, and payments are compared to the invoice total (after tax). Within $1.00 is a match. One payment can cover several invoices.

## What gets scored

| Check | Weight |
|---|---|
| Field extraction from PDFs (clean and scanned reported separately) | 20 |
| Invoice status | 25 |
| Exceptions: precision and recall per type | 25 |
| Payment matching: exact set of bank payments per invoice | 15 |
| Payments with no invoice found | 5 |
| Numbers traceable to the source (no invented amounts) | 10 |

The scorecard also reports how many invoices the agent decided on its own and how many of those were wrong, in count and dollars. At volume, those silent errors are what cost money. An optional LLM judge (`--judge`) grades whether each exception note is something an accountant could act on.

## Run it

```bash
# v1 (no model needed)
python agent/reconcile_v1.py --data holdout/data --out runs/holdout-v1
# v2 (model reads of the inbox PDFs, keyed by filename)
python agent/reconcile_v2.py --data holdout/data --reads runs/holdout-v2/reads.json --out runs/holdout-v2
# score
python evals/score.py runs/holdout-v2 --key holdout/answer_key/answer_key.json
```

Regenerate the data: `python generator/generate.py` (dev) and `python holdout/generator/generate_holdout.py` (holdout). Both are deterministic. Each run folder holds `report.json` and `scorecard.md`.
