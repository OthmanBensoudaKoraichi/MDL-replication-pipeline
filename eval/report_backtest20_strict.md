# Held-out evaluation — extraction vs human gold

**Scope:** 20 MDLs never used in development: 1431, 1700, 1871, 2185, 2187, 2391, 2440, 2570, 2592, 2595, 2666, 2669, 2741, 2775, 2801, 2817, 2820, 2836, 2859, 2878

Deterministic agreement (no LLM judge). Names matched on a normalized key (spelling/middle initials/suffixes ignored); firms compared representation-agnostically (row or attribute). 95% Wilson CIs in brackets.


## Tier 1 — Appointments (primary)

- **Individuals (the people):** recall **90.7%** (87.6, 93.1), precision **92.5%** (89.5, 94.6), F1 91.6% (gold 432, ours 424, matched 392)
- **Firms (representation-agnostic):** recall 93.4%, precision 88.8%, F1 91.1% (gold 366, ours 385, matched 342)
- **Combined (individuals + firms):** recall 92.0%, precision 90.7%, F1 91.4%
- **Role accuracy (Jaccard, partial credit):** 94.1% (reconciled 92.7%)
- **Side agreement:** 98.7%
- **Soft F1 (role-weighted headline):** recall 84.1%, precision 85.7%, **F1 84.9%**
- *(secondary) interim agreement: 96.7%*


## Tier 2 — Orders (appointment-bearing)

- **Identity:** recall **87.2%** (79.6, 92.2), precision **92.2%** (85.4, 96.0), F1 89.6% (gold 109, ours 103, matched 95)

| analytic field | agreement | n |
|---|---|---|
| Contested | 90.5% (83.0, 94.9) | 86/95 |
| Date(meta) | 94.7% (88.3, 97.7) | 90/95 |
| IRPA_Duties_to_Clients | 91.6% (84.3, 95.7) | 87/95 |
| Judge(meta) | 76.8% (67.4, 84.2) | 73/95 |
| Limit_Nonleader_Practice | 84.2% (75.6, 90.2) | 80/95 |
| OU_Create | 72.6% (62.9, 80.6) | 69/95 |
| OU_Duties_to_Nonclients | 64.2% (54.2, 73.1) | 61/95 |
| OU_Functions | 81.1% (72.0, 87.7) | 77/95 |
| Order_Types(exact) | 66.3% (56.3, 75.0) | 63/95 |
| Rule_23 | 95.8% (89.7, 98.4) | 91/95 |

*Order_Types mean Jaccard: 79.8% (reconciled 76.9%)*

## Tier 3 — Attorneys (distinct individuals)

- recall 90.7% (87.6, 93.1), precision 92.5% (89.5, 94.6), F1 91.6% (downstream of appointments; exact names/demographics out of scope)


## Per-MDL

| MDL | gold appt | our appt | matched | gold ord | our ord |
|---|---|---|---|---|---|
| 1431 | 57 | 56 | 54 | 2 | 0 |
| 1700 | 13 | 21 | 13 | 3 | 2 |
| 1871 | 60 | 54 | 46 | 12 | 9 |
| 2185 | 13 | 13 | 10 | 4 | 4 |
| 2187 | 164 | 159 | 157 | 12 | 13 |
| 2391 | 80 | 86 | 75 | 10 | 12 |
| 2440 | 54 | 50 | 49 | 5 | 4 |
| 2570 | 69 | 71 | 63 | 10 | 8 |
| 2592 | 28 | 31 | 26 | 7 | 8 |
| 2595 | 24 | 24 | 23 | 4 | 4 |
| 2666 | 49 | 47 | 46 | 3 | 2 |
| 2669 | 20 | 20 | 19 | 2 | 2 |
| 2741 | 16 | 22 | 16 | 3 | 3 |
| 2775 | 59 | 54 | 53 | 7 | 8 |
| 2801 | 2 | 2 | 2 | 4 | 5 |
| 2817 | 15 | 18 | 15 | 8 | 6 |
| 2820 | 19 | 20 | 17 | 2 | 2 |
| 2836 | 26 | 29 | 22 | 4 | 4 |
| 2859 | 22 | 24 | 20 | 3 | 3 |
| 2878 | 8 | 8 | 8 | 4 | 4 |

## Files

- eval/metrics_backtest20_strict.json, appt_missing_backtest20_strict.csv, appt_extra_backtest20_strict.csv, role_disagreements_backtest20_strict.csv