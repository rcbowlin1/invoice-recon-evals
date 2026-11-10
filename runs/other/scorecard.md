# Scorecard: runs/other

**Overall: 100.0 / 100**

| Check | Weight | Result |
|---|---|---|
| Field extraction (PDFs) | 20 | 100% (clean 100%, scanned 100%) |
| Invoice status | 25 | 100% |
| Exceptions (F1) | 25 | 100% (precision 100%, recall 100%) |
| Payment matching | 15 | 100% |
| Unmatched payments found (F1) | 5 | 100% |
| Numbers traceable to source | 10 | 100% |

## By exception type

| Type | Precision | Recall | TP | FP | FN |
|---|---|---|---|---|---|
| AMOUNT_MISMATCH_PO | 100% | 100% | 3 | 0 | 0 |
| DUPLICATE_INVOICE | 100% | 100% | 3 | 0 | 0 |
| DUPLICATE_PAYMENT | 100% | 100% | 1 | 0 | 0 |
| PARTIAL_PAYMENT | 100% | 100% | 3 | 0 | 0 |
| MISSING_PO | 100% | 100% | 3 | 0 | 0 |

## Misses

| Source | Expected | Got | Expected exceptions | Got exceptions |
|---|---|---|---|---|
