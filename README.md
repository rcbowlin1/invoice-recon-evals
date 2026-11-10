# Invoice Reconciliation Evals

A realistic, fully synthetic accounts-payable dataset for building and **measuring** an AI agent that reconciles invoices against purchase orders and bank payments.

Every company, town, phone number, email address, and amount here is made up.

## The task

Copperline Home Goods (a fictional retailer) has a few months of messy AP data in three places. An agent has to:

1. **Read every invoice:** clean PDFs, image-only scanned PDFs, and rows already keyed into the AP tool
2. **Match each invoice** to its purchase order and to the bank payment(s) that paid it
3. **Flag every exception** with a reason an accountant can act on
4. **Account for every vendor payment** in the bank file, including ones with no invoice behind them

## The data

| File | What it is | Why it's messy |
|---|---|---|
| `data/inbox/*.pdf` | 22 invoices received by email, not yet keyed | Three vendor layouts; 4 are crooked, noisy scans with no text layer |
| `data/LedgerLoop_AP_Invoices_Export_2026-11-01.csv` | 17 invoices already in the AP tool (portal / EDI) | Supplier names don't always match the vendor master |
| `data/ProcureHub_PO_Export_2026-11-01.csv` | Purchase orders, one row per PO line | Totals repeat on every line |
| `data/GVB_Operating_x4417_Activity_2026-09-01_to_2026-10-31.csv` | Bank account activity | Preamble rows, truncated vendor names, memos with or without invoice numbers, checks with no memo, payroll and deposits mixed in |

## What's hiding in it

| Situation | Count | Expected result |
|---|---|---|
| Clean match | 24 | Reconciled (includes check payments, rounding within $1.00, and one payment covering three invoices) |
| Billed more than the PO | 3 | `AMOUNT_MISMATCH_PO` |
| Duplicate invoice | 3 | `DUPLICATE_INVOICE` (one was paid twice: `DUPLICATE_PAYMENT`) |
| Partial payment | 3 | `PARTIAL_PAYMENT` |
| No purchase order | 3 | `MISSING_PO` |
| Not paid yet | 3 | `OPEN_UNPAID` |
| Payment with no invoice | 2 | `UNMATCHED_PAYMENT` |

## Matching rules

- Compare the invoice **subtotal** (before tax) to the **PO total**. Within $1.00 is a match.
- Compare **payments** to the invoice **total** (after tax). Within $1.00 is a match.
- One payment can cover several invoices; one invoice can't be paid more than once.

## Answer key

`answer_key/answer_key.json` holds the right answer for every invoice and vendor payment. Keep it out of the agent's context: it is only for scoring.

## Regenerate

```bash
pip install playwright pillow && python -m playwright install chromium
python generator/generate.py   # deterministic: same seed, same files
```

## Coming next

- A baseline agent
- The eval harness: match accuracy, exception precision and recall, a "no invented numbers" check, and an LLM judge for whether each explanation is usable
- Results: v1 score, what failed, what changed, v2 score
