# Held-out evaluation — extraction vs human gold

**Scope:** 20 MDLs never used in development: 1566, 1663, 2034, 2187, 2286, 2391, 2406, 2434, 2440, 2441, 2504, 2613, 2664, 2669, 2687, 2693, 2814, 2850, 2878, 2887

Deterministic agreement (no LLM judge). Names matched on a normalized key (spelling/middle initials/suffixes ignored); firms compared representation-agnostically (row or attribute). 95% Wilson CIs in brackets.


## Tier 1 — Appointments (primary)

- **Individuals (the people):** recall **89.9%** (86.5, 92.5), precision **86.1%** (82.3, 89.1), F1 87.9% (gold 385, ours 402, matched 346)
- **Firms (representation-agnostic):** recall 95.0%, precision 92.9%, F1 93.9% (gold 301, ours 308, matched 286)
- **Combined (individuals + firms):** recall 92.1%, precision 89.0%, F1 90.5%
- **Role accuracy (Jaccard, partial credit):** 83.2% (reconciled 82.9%)
- **Side agreement:** 99.1%
- **Soft F1 (role-weighted headline):** recall 74.5%, precision 71.4%, **F1 72.9%**
- *(secondary) interim agreement: 95.7%*


## Tier 2 — Orders (appointment-bearing)

- **Identity:** recall **90.0%** (82.6, 94.5), precision **86.5%** (78.7, 91.8), F1 88.2% (gold 100, ours 104, matched 90)

| analytic field | agreement | n |
|---|---|---|
| Contested | 91.1% (83.4, 95.4) | 82/90 |
| Date(meta) | 86.7% (78.1, 92.2) | 78/90 |
| IRPA_Duties_to_Clients | 85.6% (76.8, 91.4) | 77/90 |
| Judge(meta) | 81.1% (71.8, 87.9) | 73/90 |
| Limit_Nonleader_Practice | 82.2% (73.1, 88.8) | 74/90 |
| OU_Create | 68.9% (58.7, 77.5) | 62/90 |
| OU_Duties_to_Nonclients | 56.7% (46.4, 66.4) | 51/90 |
| OU_Functions | 70.0% (59.9, 78.5) | 63/90 |
| Order_Types(exact) | 57.8% (47.5, 67.5) | 52/90 |
| Rule_23 | 98.9% (94.0, 99.8) | 89/90 |

*Order_Types mean Jaccard: 75.9% (reconciled 76.3%)*

## Tier 3 — Attorneys (distinct individuals)

- recall 89.9% (86.5, 92.5), precision 86.1% (82.3, 89.1), F1 87.9% (downstream of appointments; exact names/demographics out of scope)


## Per-MDL

| MDL | gold appt | our appt | matched | gold ord | our ord |
|---|---|---|---|---|---|
| 1566 | 17 | 16 | 15 | 18 | 15 |
| 1663 | 9 | 8 | 6 | 4 | 4 |
| 2034 | 19 | 16 | 16 | 5 | 5 |
| 2187 | 164 | 159 | 157 | 12 | 13 |
| 2286 | 10 | 15 | 10 | 2 | 4 |
| 2391 | 80 | 86 | 75 | 10 | 12 |
| 2406 | 108 | 117 | 88 | 9 | 8 |
| 2434 | 34 | 34 | 34 | 4 | 4 |
| 2440 | 54 | 50 | 49 | 5 | 4 |
| 2441 | 61 | 62 | 60 | 5 | 6 |
| 2504 | 5 | 8 | 5 | 3 | 4 |
| 2613 | 9 | 18 | 9 | 1 | 2 |
| 2664 | 10 | 17 | 9 | 1 | 2 |
| 2669 | 20 | 20 | 19 | 2 | 2 |
| 2687 | 32 | 32 | 30 | 8 | 8 |
| 2693 | 19 | 17 | 16 | 2 | 2 |
| 2814 | 1 | 1 | 1 | 1 | 1 |
| 2850 | 6 | 6 | 5 | 3 | 3 |
| 2878 | 8 | 8 | 8 | 4 | 4 |
| 2887 | 20 | 20 | 20 | 1 | 1 |

## Files

- eval/metrics_demo20_strict.json, appt_missing_demo20_strict.csv, appt_extra_demo20_strict.csv, role_disagreements_demo20_strict.csv