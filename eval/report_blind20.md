# Held-out evaluation — extraction vs human gold

**Scope:** 20 MDLs never used in development: 1871, 2047, 2221, 2311, 2326, 2437, 2472, 2548, 2575, 2580, 2595, 2645, 2656, 2657, 2666, 2709, 2742, 2768, 2862, 2885

Deterministic agreement (no LLM judge). Names matched on a normalized key (spelling/middle initials/suffixes ignored); firms compared representation-agnostically (row or attribute). 95% Wilson CIs in brackets.


## Tier 1 — Appointments (primary)

- **Individuals (the people):** recall **82.9%** (78.8, 86.4), precision **92.7%** (89.4, 95.0), F1 87.5% (gold 381, ours 341, matched 316)
- **Firms (representation-agnostic):** recall 83.8%, precision 97.5%, F1 90.2% (gold 328, ours 282, matched 275)
- **Combined (individuals + firms):** recall 83.4%, precision 94.9%, F1 88.7%
- **Role accuracy (Jaccard, partial credit):** 83.9% (reconciled 81.5%)
- **Side agreement:** 94.0%
- **Soft F1 (role-weighted headline):** recall 67.6%, precision 75.6%, **F1 71.4%**
- *(secondary) interim agreement: 95.9%*


## Tier 2 — Orders (appointment-bearing)

- **Identity:** recall **89.3%** (81.9, 93.9), precision **87.6%** (80.0, 92.6), F1 88.5% (gold 103, ours 105, matched 92)

| analytic field | agreement | n |
|---|---|---|
| Contested | 93.5% (86.5, 97.0) | 86/92 |
| Date(meta) | 93.5% (86.5, 97.0) | 86/92 |
| IRPA_Duties_to_Clients | 85.9% (77.3, 91.6) | 79/92 |
| Judge(meta) | 90.2% (82.4, 94.8) | 83/92 |
| Limit_Nonleader_Practice | 79.3% (70.0, 86.4) | 73/92 |
| OU_Create | 76.1% (66.4, 83.6) | 70/92 |
| OU_Duties_to_Nonclients | 48.9% (38.9, 59.0) | 45/92 |
| OU_Functions | 58.7% (48.5, 68.2) | 54/92 |
| Order_Types(exact) | 55.4% (45.3, 65.2) | 51/92 |
| Rule_23 | 92.4% (85.1, 96.3) | 85/92 |

*Order_Types mean Jaccard: 75.4% (reconciled 72.1%)*

## Tier 3 — Attorneys (distinct individuals)

- recall 82.9% (78.8, 86.4), precision 92.7% (89.4, 95.0), F1 87.5% (downstream of appointments; exact names/demographics out of scope)


## Per-MDL

| MDL | gold appt | our appt | matched | gold ord | our ord |
|---|---|---|---|---|---|
| 1871 | 55 | 49 | 48 | 12 | 9 |
| 2047 | 89 | 88 | 80 | 17 | 20 |
| 2221 | 10 | 10 | 10 | 3 | 3 |
| 2311 | 17 | 17 | 17 | 3 | 3 |
| 2326 | 131 | 41 | 39 | 5 | 3 |
| 2437 | 13 | 14 | 13 | 5 | 5 |
| 2472 | 35 | 48 | 33 | 6 | 9 |
| 2548 | 4 | 4 | 4 | 4 | 5 |
| 2575 | 10 | 10 | 10 | 2 | 2 |
| 2580 | 7 | 7 | 7 | 4 | 3 |
| 2595 | 23 | 24 | 23 | 4 | 4 |
| 2645 | 3 | 4 | 3 | 4 | 5 |
| 2656 | 11 | 11 | 11 | 4 | 5 |
| 2657 | 39 | 39 | 38 | 4 | 4 |
| 2666 | 49 | 47 | 46 | 3 | 2 |
| 2709 | 39 | 39 | 39 | 3 | 3 |
| 2742 | 4 | 4 | 4 | 3 | 3 |
| 2768 | 34 | 34 | 34 | 2 | 1 |
| 2862 | 6 | 6 | 6 | 5 | 5 |
| 2885 | 130 | 127 | 126 | 10 | 11 |

## Files

- eval/metrics_blind20.json, appt_missing_blind20.csv, appt_extra_blind20.csv, role_disagreements_blind20.csv