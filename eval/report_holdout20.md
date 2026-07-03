# Held-out evaluation — extraction vs human gold

**Scope:** 20 MDLs never used in development: 1916, 2067, 2184, 2327, 2357, 2419, 2433, 2445, 2475, 2495, 2541, 2555, 2557, 2573, 2586, 2615, 2704, 2752, 2754, 2782

Deterministic agreement (no LLM judge). Names matched on a normalized key (spelling/middle initials/suffixes ignored); firms compared representation-agnostically (row or attribute). 95% Wilson CIs in brackets.


## Tier 1 — Appointments (primary)

- **Individuals (the people):** recall **93.0%** (87.6, 96.2), precision **97.1%** (92.7, 98.9), F1 95.0% (gold 143, ours 137, matched 133)
- **Firms (representation-agnostic):** recall 89.9%, precision 97.1%, F1 93.3% (gold 148, ours 137, matched 133)
- **Combined (individuals + firms):** recall 91.4%, precision 97.1%, F1 94.2%
- **Role accuracy (Jaccard, partial credit):** 94.7% (reconciled 95.0%)
- **Side agreement:** 98.5%
- **Soft F1 (role-weighted headline):** recall 88.3%, precision 92.2%, **F1 90.2%**
- *(secondary) interim agreement: 91.7%*


## Tier 2 — Orders (appointment-bearing)

- **Identity:** recall **96.9%** (84.3, 99.4), precision **83.8%** (68.9, 92.3), F1 89.9% (gold 32, ours 37, matched 31)

| analytic field | agreement | n |
|---|---|---|
| Contested | 90.3% (75.1, 96.7) | 28/31 |
| Date(meta) | 87.1% (71.1, 94.9) | 27/31 |
| IRPA_Duties_to_Clients | 74.2% (56.8, 86.3) | 23/31 |
| Judge(meta) | 83.9% (67.4, 92.9) | 26/31 |
| Limit_Nonleader_Practice | 71.0% (53.4, 83.9) | 22/31 |
| OU_Create | 67.7% (50.1, 81.4) | 21/31 |
| OU_Duties_to_Nonclients | 35.5% (21.1, 53.1) | 11/31 |
| OU_Functions | 77.4% (60.2, 88.6) | 24/31 |
| Order_Types(exact) | 64.5% (46.9, 78.9) | 20/31 |
| Rule_23 | 100.0% (89.0, 100.0) | 31/31 |

*Order_Types mean Jaccard: 81.5% (reconciled 81.7%)*

## Tier 3 — Attorneys (distinct individuals)

- recall 93.0% (87.6, 96.2), precision 97.1% (92.7, 98.9), F1 95.0% (downstream of appointments; exact names/demographics out of scope)


## Per-MDL

| MDL | gold appt | our appt | matched | gold ord | our ord |
|---|---|---|---|---|---|
| 1916 | 6 | 5 | 5 | 2 | 3 |
| 2067 | 8 | 8 | 8 | 1 | 1 |
| 2184 | 6 | 6 | 6 | 1 | 1 |
| 2327 | 37 | 37 | 37 | 3 | 2 |
| 2357 | 14 | 15 | 14 | 1 | 3 |
| 2419 | 17 | 17 | 17 | 2 | 2 |
| 2433 | 18 | 18 | 16 | 2 | 2 |
| 2445 | 27 | 27 | 27 | 2 | 2 |
| 2475 | 4 | 4 | 4 | 1 | 1 |
| 2495 | 20 | 21 | 20 | 1 | 1 |
| 2541 | 3 | 3 | 3 | 2 | 2 |
| 2555 | 23 | 16 | 14 | 2 | 2 |
| 2557 | 5 | 5 | 5 | 2 | 3 |
| 2573 | 2 | 3 | 2 | 2 | 3 |
| 2586 | 16 | 4 | 4 | 1 | 1 |
| 2615 | 5 | 5 | 5 | 1 | 1 |
| 2704 | 9 | 9 | 9 | 2 | 2 |
| 2752 | 10 | 10 | 10 | 1 | 1 |
| 2754 | 31 | 31 | 30 | 1 | 2 |
| 2782 | 30 | 30 | 30 | 2 | 2 |

## Files

- eval/metrics_holdout20.json, appt_missing_holdout20.csv, appt_extra_holdout20.csv, role_disagreements_holdout20.csv