# Scorecard: runs/v1

**Overall: 92.2 / 100**

| Check | Weight | Result |
|---|---|---|
| Field extraction (PDFs) | 20 | 90% (clean 100%, scanned 45%) |
| Invoice status | 25 | 95% |
| Exceptions (F1) | 25 | 92% (precision 100%, recall 85%) |
| Payment matching | 15 | 95% |
| Unmatched payments found (F1) | 5 | 67% |
| Numbers traceable to source | 10 | 100% |

## By exception type

| Type | Precision | Recall | TP | FP | FN |
|---|---|---|---|---|---|
| AMOUNT_MISMATCH_PO | 100% | 67% | 2 | 0 | 1 |
| DUPLICATE_INVOICE | 100% | 100% | 3 | 0 | 0 |
| DUPLICATE_PAYMENT | 100% | 100% | 1 | 0 | 0 |
| PARTIAL_PAYMENT | 100% | 67% | 2 | 0 | 1 |
| MISSING_PO | 100% | 100% | 3 | 0 | 0 |

## Misses

| Source | Expected | Got | Expected exceptions | Got exceptions |
|---|---|---|---|---|
| Stonebrook_SBL-13710_scan.pdf | EXCEPTION | RECONCILED | AMOUNT_MISMATCH_PO | - |
| HALVORSEN_HIS007450_scan.pdf | EXCEPTION | OPEN_UNPAID | PARTIAL_PAYMENT | - |
