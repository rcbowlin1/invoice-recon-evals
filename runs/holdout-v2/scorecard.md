# Scorecard: runs/holdout-v2

**Overall: 90.1 / 100**

| Check | Weight | Result |
|---|---|---|
| Field extraction (PDFs) | 20 | 100% (clean 100%, scanned 100%) |
| Invoice status | 25 | 92% |
| Exceptions (F1) | 25 | 84% (precision 76%, recall 93%) |
| Payment matching | 15 | 90% |
| Unmatched payments found (F1) | 5 | 50% |
| Numbers traceable to source | 10 | 100% |

## At scale

| Measure | Result |
|---|---|
| Decided without a human | 100% |
| Sent to review (NEEDS_REVIEW) | 0% |
| Wrong among those it decided alone | 12% (5 invoices, $27,067.66) |

## By exception type

| Type | Precision | Recall | TP | FP | FN |
|---|---|---|---|---|---|
| AMOUNT_MISMATCH_PO | 100% | 100% | 3 | 0 | 0 |
| DUPLICATE_INVOICE | 60% | 75% | 3 | 2 | 1 |
| DUPLICATE_PAYMENT | 50% | 100% | 1 | 1 | 0 |
| PARTIAL_PAYMENT | 67% | 100% | 2 | 1 | 0 |
| MISSING_PO | 100% | 100% | 4 | 0 | 0 |

## Misses

| Source | Expected | Got | Expected exceptions | Got exceptions |
|---|---|---|---|---|
| Quillmark_Q058899.pdf | RECONCILED | EXCEPTION | - | DUPLICATE_INVOICE |
| Quillmark_Q058899-1.pdf | EXCEPTION | EXCEPTION | DUPLICATE_INVOICE | DUPLICATE_INVOICE, DUPLICATE_PAYMENT, PARTIAL_PAYMENT |
| LedgerLoop_AP_Invoices_Export_2027-01-02.csv#LL-55550 | RECONCILED | EXCEPTION | - | DUPLICATE_INVOICE |
| Juniper_JA-54445.pdf | EXCEPTION | RECONCILED | DUPLICATE_INVOICE | - |
