# Held-out evaluation — extraction vs human gold

**Scope:** 10 MDLs never used in development: 1869, 2262, 2295, 2387, 2420, 2492, 2543, 2695, 2740, 2850

Deterministic agreement (no LLM judge). Names matched on a normalized key (spelling/middle initials/suffixes ignored). 95% Wilson CIs in brackets.


## Tier 1 — Appointments (primary)

- **Identity (the right people/firms):** recall **96.2%** (91.9, 98.2), precision **91.0%** (85.6, 94.4), F1 93.5% (gold 157, ours 166, matched 151)
- **Role accuracy (Jaccard, partial credit):** 86.9% (reconciled 86.3%)
- **Side agreement:** 100.0%
- **Soft F1 (role-weighted headline):** recall 83.0%, precision 78.5%, **F1 80.7%**
- *(secondary) interim agreement: 94.7%*


## Tier 2 — Orders (appointment-bearing)

- **Identity:** recall **100.0%** (94.6, 100.0), precision **88.2%** (79.0, 93.6), F1 93.7% (gold 67, ours 76, matched 67)

| analytic field | agreement | n |
|---|---|---|
| Contested | 82.1% (71.3, 89.4) | 55/67 |
| Date(meta) | 92.5% (83.7, 96.8) | 62/67 |
| IRPA_Duties_to_Clients | 94.0% (85.6, 97.7) | 63/67 |
| Judge(meta) | 83.6% (72.9, 90.6) | 56/67 |
| Limit_Nonleader_Practice | 86.6% (76.4, 92.8) | 58/67 |
| OU_Create | 68.7% (56.8, 78.5) | 46/67 |
| OU_Duties_to_Nonclients | 52.2% (40.5, 63.7) | 35/67 |
| OU_Functions | 62.7% (50.7, 73.3) | 42/67 |
| Order_Types(exact) | 46.3% (34.9, 58.1) | 31/67 |
| Rule_23 | 91.0% (81.8, 95.8) | 61/67 |

*Order_Types mean Jaccard: 73.4% (reconciled 71.0%)*

## Tier 3 — Attorneys (distinct individuals)

- recall 98.3% (93.9, 99.5), precision 89.0% (82.3, 93.3), F1 93.4% (downstream of appointments; exact names/demographics out of scope)


## Per-MDL

| MDL | gold appt | our appt | matched | gold ord | our ord |
|---|---|---|---|---|---|
| 1869 | 10 | 11 | 10 | 6 | 7 |
| 2262 | 13 | 13 | 13 | 21 | 22 |
| 2295 | 8 | 6 | 6 | 3 | 3 |
| 2387 | 17 | 17 | 17 | 4 | 5 |
| 2420 | 26 | 26 | 25 | 12 | 12 |
| 2492 | 7 | 8 | 5 | 1 | 2 |
| 2543 | 15 | 19 | 15 | 3 | 4 |
| 2695 | 17 | 18 | 17 | 3 | 3 |
| 2740 | 41 | 45 | 40 | 11 | 15 |
| 2850 | 3 | 3 | 3 | 3 | 3 |

## Files

- eval/metrics_heldout.json, appt_missing_heldout.csv, appt_extra_heldout.csv, role_disagreements_heldout.csv