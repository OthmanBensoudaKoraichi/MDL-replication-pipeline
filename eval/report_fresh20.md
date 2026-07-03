# Held-out evaluation — extraction vs human gold

**Scope:** 20 MDLs never used in development: 1720, 1917, 1964, 2244, 2286, 2440, 2460, 2522, 2545, 2551, 2591, 2592, 2627, 2667, 2724, 2785, 2801, 2816, 2875, 2886

Deterministic agreement (no LLM judge). Names matched on a normalized key (spelling/middle initials/suffixes ignored); firms compared representation-agnostically (row or attribute). 95% Wilson CIs in brackets.


## Tier 1 — Appointments (primary)

- **Individuals (the people):** recall **93.3%** (90.4, 95.3), precision **96.2%** (93.8, 97.7), F1 94.7% (gold 402, ours 390, matched 375)
- **Firms (representation-agnostic):** recall 92.5%, precision 95.5%, F1 94.0% (gold 321, ours 311, matched 297)
- **Combined (individuals + firms):** recall 92.9%, precision 95.9%, F1 94.4%
- **Role accuracy (Jaccard, partial credit):** 90.0% (reconciled 88.3%)
- **Side agreement:** 99.2%
- **Soft F1 (role-weighted headline):** recall 82.4%, precision 84.9%, **F1 83.6%**
- *(secondary) interim agreement: 97.1%*


## Tier 2 — Orders (appointment-bearing)

- **Identity:** recall **93.9%** (87.9, 97.0), precision **90.7%** (84.1, 94.7), F1 92.2% (gold 114, ours 118, matched 107)

| analytic field | agreement | n |
|---|---|---|
| Contested | 92.5% (85.9, 96.2) | 99/107 |
| Date(meta) | 95.3% (89.5, 98.0) | 102/107 |
| IRPA_Duties_to_Clients | 91.6% (84.8, 95.5) | 98/107 |
| Judge(meta) | 86.9% (79.2, 92.0) | 93/107 |
| Limit_Nonleader_Practice | 92.5% (85.9, 96.2) | 99/107 |
| OU_Create | 81.3% (72.9, 87.6) | 87/107 |
| OU_Duties_to_Nonclients | 56.1% (46.6, 65.1) | 60/107 |
| OU_Functions | 62.6% (53.2, 71.2) | 67/107 |
| Order_Types(exact) | 60.7% (51.3, 69.5) | 65/107 |
| Rule_23 | 93.5% (87.1, 96.8) | 100/107 |

*Order_Types mean Jaccard: 75.7% (reconciled 74.5%)*

## Tier 3 — Attorneys (distinct individuals)

- recall 93.3% (90.4, 95.3), precision 96.2% (93.8, 97.7), F1 94.7% (downstream of appointments; exact names/demographics out of scope)


## Per-MDL

| MDL | gold appt | our appt | matched | gold ord | our ord |
|---|---|---|---|---|---|
| 1720 | 10 | 10 | 10 | 4 | 4 |
| 1917 | 10 | 6 | 6 | 9 | 9 |
| 1964 | 19 | 19 | 19 | 9 | 10 |
| 2244 | 86 | 84 | 82 | 6 | 7 |
| 2286 | 10 | 14 | 10 | 2 | 4 |
| 2440 | 54 | 50 | 49 | 5 | 4 |
| 2460 | 35 | 36 | 33 | 4 | 3 |
| 2522 | 45 | 45 | 44 | 6 | 6 |
| 2545 | 89 | 89 | 88 | 5 | 5 |
| 2551 | 18 | 18 | 18 | 3 | 3 |
| 2591 | 40 | 40 | 40 | 4 | 4 |
| 2592 | 28 | 31 | 26 | 7 | 8 |
| 2627 | 19 | 18 | 17 | 4 | 4 |
| 2667 | 5 | 5 | 5 | 6 | 7 |
| 2724 | 77 | 80 | 77 | 18 | 18 |
| 2785 | 18 | 21 | 17 | 6 | 7 |
| 2801 | 2 | 2 | 2 | 4 | 5 |
| 2816 | 17 | 17 | 17 | 2 | 2 |
| 2875 | 121 | 96 | 92 | 8 | 6 |
| 2886 | 20 | 20 | 20 | 2 | 2 |

## Files

- eval/metrics_fresh20.json, appt_missing_fresh20.csv, appt_extra_fresh20.csv, role_disagreements_fresh20.csv