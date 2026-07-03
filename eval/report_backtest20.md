# Held-out evaluation — extraction vs human gold

**Scope:** 20 MDLs never used in development: 1431, 1700, 1871, 2185, 2187, 2391, 2440, 2570, 2592, 2595, 2666, 2669, 2741, 2775, 2801, 2817, 2820, 2836, 2859, 2878

Deterministic agreement (no LLM judge). Names matched on a normalized key (spelling/middle initials/suffixes ignored); firms compared representation-agnostically (row or attribute). 95% Wilson CIs in brackets.


## Tier 1 — Appointments (primary)

- **Individuals (the people):** recall **95.3%** (92.8, 97.0), precision **94.9%** (92.3, 96.6), F1 95.1% (gold 408, ours 410, matched 389)
- **Firms (representation-agnostic):** recall 95.9%, precision 91.9%, F1 93.9% (gold 345, ours 360, matched 331)
- **Combined (individuals + firms):** recall 95.6%, precision 93.5%, F1 94.6%
- **Role accuracy (Jaccard, partial credit):** 94.0% (reconciled 92.8%)
- **Side agreement:** 98.9%
- **Soft F1 (role-weighted headline):** recall 88.4%, precision 88.0%, **F1 88.2%**
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

- recall 95.3% (92.8, 97.0), precision 94.9% (92.3, 96.6), F1 95.1% (downstream of appointments; exact names/demographics out of scope)


## Per-MDL

| MDL | gold appt | our appt | matched | gold ord | our ord |
|---|---|---|---|---|---|
| 1431 | 57 | 56 | 55 | 2 | 0 |
| 1700 | 13 | 21 | 13 | 3 | 2 |
| 1871 | 55 | 49 | 48 | 12 | 9 |
| 2185 | 13 | 13 | 12 | 4 | 4 |
| 2187 | 146 | 146 | 145 | 12 | 13 |
| 2391 | 75 | 80 | 72 | 10 | 12 |
| 2440 | 54 | 50 | 49 | 5 | 4 |
| 2570 | 63 | 69 | 62 | 10 | 8 |
| 2592 | 28 | 31 | 26 | 7 | 8 |
| 2595 | 23 | 24 | 23 | 4 | 4 |
| 2666 | 49 | 47 | 46 | 3 | 2 |
| 2669 | 18 | 18 | 17 | 2 | 2 |
| 2741 | 16 | 22 | 16 | 3 | 3 |
| 2775 | 53 | 51 | 51 | 7 | 8 |
| 2801 | 2 | 2 | 2 | 4 | 5 |
| 2817 | 15 | 16 | 15 | 8 | 6 |
| 2820 | 18 | 18 | 17 | 2 | 2 |
| 2836 | 26 | 28 | 23 | 4 | 4 |
| 2859 | 21 | 21 | 20 | 3 | 3 |
| 2878 | 8 | 8 | 8 | 4 | 4 |

## Files

- eval/metrics_backtest20.json, appt_missing_backtest20.csv, appt_extra_backtest20.csv, role_disagreements_backtest20.csv