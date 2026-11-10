# Scorecard: runs/holdout-v1

**Overall: 55.2 / 100**

| Check | Weight | Result |
|---|---|---|
| Field extraction (PDFs) | 20 | 47% (clean 60%, scanned 10%) |
| Invoice status | 25 | 65% |
| Exceptions (F1) | 25 | 39% (precision 32%, recall 50%) |
| Payment matching | 15 | 57% |
| Unmatched payments found (F1) | 5 | 25% |
| Numbers traceable to source | 10 | 100% |

## At scale

| Measure | Result |
|---|---|
| Decided without a human | 100% |
| Sent to review (NEEDS_REVIEW) | 0% |
| Wrong among those it decided alone | 48% (19 invoices, $94,986.61) |

## By exception type

| Type | Precision | Recall | TP | FP | FN |
|---|---|---|---|---|---|
| AMOUNT_MISMATCH_PO | 100% | 67% | 2 | 0 | 1 |
| DUPLICATE_INVOICE | 100% | 0% | 0 | 0 | 4 |
| DUPLICATE_PAYMENT | 100% | 0% | 0 | 0 | 1 |
| PARTIAL_PAYMENT | 33% | 50% | 1 | 2 | 1 |
| MISSING_PO | 24% | 100% | 4 | 13 | 0 |

## Misses

| Source | Expected | Got | Expected exceptions | Got exceptions |
|---|---|---|---|---|
| Fernhaven_FTM-26-16700.pdf | RECONCILED | EXCEPTION | - | MISSING_PO |
| Osprey_OPC04952_scan.pdf | RECONCILED | EXCEPTION | - | MISSING_PO |
| Saltmarsh_SCP-7941.pdf | RECONCILED | EXCEPTION | - | MISSING_PO |
| Harrowgate_HFW43032.pdf | RECONCILED | EXCEPTION | - | MISSING_PO |
| VVStudio_VV-26-24502.pdf | RECONCILED | EXCEPTION | - | MISSING_PO |
| Brambleton_BES-011184_scan.pdf | RECONCILED | EXCEPTION | - | MISSING_PO |
| Thistlewood_TPC-58604.pdf | RECONCILED | EXCEPTION | - | MISSING_PO |
| Osprey_OPC04962_scan.pdf | RECONCILED | EXCEPTION | - | MISSING_PO |
| Saltmarsh_SCP-7948_scan.pdf | EXCEPTION | EXCEPTION | AMOUNT_MISMATCH_PO | MISSING_PO |
| Quillmark_Q058899-1.pdf | EXCEPTION | RECONCILED | DUPLICATE_INVOICE | - |
| Thistlewood_TPC-58606.pdf | EXCEPTION | EXCEPTION | DUPLICATE_INVOICE | MISSING_PO |
| LedgerLoop_AP_Invoices_Export_2027-01-02.csv#LL-55579 | EXCEPTION | RECONCILED | DUPLICATE_INVOICE, DUPLICATE_PAYMENT | - |
| Juniper_JA-54445.pdf | EXCEPTION | RECONCILED | DUPLICATE_INVOICE | - |
| Pinehollow_PJ-41457_scan.pdf | EXCEPTION | EXCEPTION | PARTIAL_PAYMENT | MISSING_PO |
| VVStudio_VV-26-24515.pdf | EXCEPTION | EXCEPTION | MISSING_PO | MISSING_PO, PARTIAL_PAYMENT |
| Brambleton_BES-011190.pdf | OPEN_UNPAID | EXCEPTION | - | MISSING_PO |
| Harrowgate_HFW43041.pdf | OPEN_UNPAID | EXCEPTION | - | MISSING_PO |
| Tidewater_TFS-37130.pdf | OPEN_UNPAID | EXCEPTION | - | PARTIAL_PAYMENT |
