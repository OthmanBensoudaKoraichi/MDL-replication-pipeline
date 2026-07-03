# Held-out evaluation — extraction vs human gold

**Scope:** 20 MDLs never used in development: 1663, 1700, 2034, 2036, 2179, 2185, 2296, 2323, 2325, 2338, 2391, 2441, 2516, 2599, 2626, 2734, 2753, 2789, 2819, 2846

Deterministic agreement (no LLM judge). Names matched on a normalized key (spelling/middle initials/suffixes ignored); firms compared representation-agnostically (row or attribute). 95% Wilson CIs in brackets.


## Tier 1 — Appointments (primary)

- **Individuals (the people):** recall **86.4%** (82.5, 89.6), precision **86.4%** (82.5, 89.6), F1 86.4% (gold 361, ours 361, matched 312)
- **Firms (representation-agnostic):** recall 88.7%, precision 85.7%, F1 87.2% (gold 310, ours 321, matched 275)
- **Combined (individuals + firms):** recall 87.5%, precision 86.1%, F1 86.8%
- **Role accuracy (Jaccard, partial credit):** 90.4% (reconciled 89.6%)
- **Side agreement:** 100.0%
- **Soft F1 (role-weighted headline):** recall 77.4%, precision 77.4%, **F1 77.4%**
- *(secondary) interim agreement: 93.6%*


## Tier 2 — Orders (appointment-bearing)

- **Identity:** recall **91.9%** (86.1, 95.4), precision **88.7%** (82.4, 92.9), F1 90.3% (gold 136, ours 141, matched 125)

| analytic field | agreement | n |
|---|---|---|
| Contested | 91.2% (84.9, 95.0) | 114/125 |
| Date(meta) | 88.0% (81.1, 92.6) | 110/125 |
| IRPA_Duties_to_Clients | 88.8% (82.1, 93.2) | 111/125 |
| Judge(meta) | 72.0% (63.6, 79.1) | 90/125 |
| Limit_Nonleader_Practice | 88.8% (82.1, 93.2) | 111/125 |
| OU_Create | 64.8% (56.1, 72.6) | 81/125 |
| OU_Duties_to_Nonclients | 51.2% (42.5, 59.8) | 64/125 |
| OU_Functions | 54.4% (45.7, 62.9) | 68/125 |
| Order_Types(exact) | 52.0% (43.3, 60.6) | 65/125 |
| Rule_23 | 94.4% (88.9, 97.3) | 118/125 |

*Order_Types mean Jaccard: 71.8% (reconciled 71.9%)*

## Tier 3 — Attorneys (distinct individuals)

- recall 86.4% (82.5, 89.6), precision 86.4% (82.5, 89.6), F1 86.4% (downstream of appointments; exact names/demographics out of scope)


## Per-MDL

| MDL | gold appt | our appt | matched | gold ord | our ord |
|---|---|---|---|---|---|
| 1663 | 9 | 8 | 7 | 4 | 4 |
| 1700 | 13 | 21 | 13 | 3 | 2 |
| 2034 | 19 | 16 | 16 | 5 | 5 |
| 2036 | 75 | 26 | 23 | 26 | 22 |
| 2179 | 36 | 51 | 35 | 13 | 16 |
| 2185 | 13 | 13 | 12 | 4 | 4 |
| 2296 | 75 | 74 | 71 | 6 | 5 |
| 2323 | 36 | 35 | 34 | 6 | 5 |
| 2325 | 18 | 40 | 17 | 1 | 3 |
| 2338 | 6 | 6 | 5 | 5 | 5 |
| 2391 | 75 | 80 | 72 | 10 | 12 |
| 2441 | 60 | 61 | 59 | 5 | 6 |
| 2516 | 35 | 40 | 34 | 4 | 4 |
| 2599 | 19 | 17 | 17 | 19 | 20 |
| 2626 | 9 | 13 | 9 | 7 | 7 |
| 2734 | 38 | 46 | 38 | 3 | 3 |
| 2753 | 26 | 16 | 16 | 3 | 3 |
| 2789 | 43 | 43 | 43 | 4 | 4 |
| 2819 | 32 | 35 | 32 | 4 | 5 |
| 2846 | 34 | 41 | 34 | 4 | 6 |

## Files

- eval/metrics_valid20.json, appt_missing_valid20.csv, appt_extra_valid20.csv, role_disagreements_valid20.csv