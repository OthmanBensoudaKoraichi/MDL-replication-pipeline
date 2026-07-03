# Held-out evaluation — extraction vs human gold

**Scope:** 30 MDLs never used in development: 1566, 1869, 2151, 2187, 2243, 2262, 2295, 2387, 2406, 2420, 2434, 2492, 2543, 2567, 2670, 2672, 2695, 2740, 2743, 2773, 2775, 2795, 2800, 2817, 2836, 2842, 2848, 2850, 2859, 2867

Deterministic agreement (no LLM judge). Names matched on a normalized key (spelling/middle initials/suffixes ignored). 95% Wilson CIs in brackets.


## Tier 1 — Appointments (primary)

- **Identity (the right people/firms):** recall **91.6%** (89.2, 93.5), precision **93.2%** (91.0, 94.9), F1 92.4% (gold 643, ours 632, matched 589)
- **Role accuracy (Jaccard, partial credit):** 77.0% (reconciled 76.2%)
- **Side agreement:** 99.3%
- **Soft F1 (role-weighted headline):** recall 69.8%, precision 71.0%, **F1 70.4%**
- *(secondary) interim agreement: 93.7%*


## Tier 2 — Orders (appointment-bearing)

- **Identity:** recall **90.7%** (85.7, 94.0), precision **86.2%** (80.8, 90.3), F1 88.4% (gold 193, ours 203, matched 175)

| analytic field | agreement | n |
|---|---|---|
| Contested | 86.3% (80.4, 90.6) | 151/175 |
| Date(meta) | 94.9% (90.5, 97.3) | 166/175 |
| IRPA_Duties_to_Clients | 94.9% (90.5, 97.3) | 166/175 |
| Judge(meta) | 85.7% (79.8, 90.1) | 150/175 |
| Limit_Nonleader_Practice | 86.3% (80.4, 90.6) | 151/175 |
| OU_Create | 72.6% (65.5, 78.6) | 127/175 |
| OU_Duties_to_Nonclients | 57.7% (50.3, 64.8) | 101/175 |
| OU_Functions | 62.3% (54.9, 69.1) | 109/175 |
| Order_Types(exact) | 48.0% (40.7, 55.4) | 84/175 |
| Rule_23 | 94.3% (89.8, 96.9) | 165/175 |

*Order_Types mean Jaccard: 72.2% (reconciled 72.0%)*

## Tier 3 — Attorneys (distinct individuals)

- recall 95.5% (93.4, 96.9), precision 92.5% (90.0, 94.4), F1 94.0% (downstream of appointments; exact names/demographics out of scope)


## Per-MDL

| MDL | gold appt | our appt | matched | gold ord | our ord |
|---|---|---|---|---|---|
| 1566 | 13 | 13 | 12 | 18 | 15 |
| 1869 | 10 | 11 | 10 | 6 | 7 |
| 2151 | 27 | 28 | 27 | 4 | 7 |
| 2187 | 79 | 78 | 78 | 12 | 13 |
| 2243 | 17 | 17 | 15 | 5 | 5 |
| 2262 | 13 | 13 | 13 | 21 | 22 |
| 2295 | 8 | 6 | 6 | 3 | 3 |
| 2387 | 17 | 17 | 17 | 4 | 5 |
| 2406 | 107 | 110 | 99 | 9 | 8 |
| 2420 | 26 | 26 | 25 | 12 | 12 |
| 2434 | 19 | 19 | 19 | 4 | 4 |
| 2492 | 7 | 8 | 5 | 1 | 2 |
| 2543 | 15 | 19 | 15 | 3 | 4 |
| 2567 | 13 | 9 | 9 | 4 | 3 |
| 2670 | 11 | 11 | 11 | 9 | 8 |
| 2672 | 30 | 32 | 30 | 9 | 11 |
| 2695 | 17 | 18 | 17 | 3 | 3 |
| 2740 | 41 | 45 | 40 | 11 | 15 |
| 2743 | 7 | 6 | 6 | 4 | 4 |
| 2773 | 4 | 4 | 4 | 3 | 3 |
| 2775 | 31 | 29 | 29 | 7 | 8 |
| 2795 | 29 | 28 | 22 | 4 | 4 |
| 2800 | 26 | 26 | 26 | 4 | 5 |
| 2817 | 9 | 9 | 9 | 8 | 6 |
| 2836 | 26 | 20 | 16 | 4 | 4 |
| 2842 | 7 | 7 | 7 | 7 | 8 |
| 2848 | 14 | 3 | 3 | 5 | 4 |
| 2850 | 3 | 3 | 3 | 3 | 3 |
| 2859 | 12 | 12 | 11 | 3 | 3 |
| 2867 | 5 | 5 | 5 | 3 | 4 |

## Files

- eval/metrics_pooled30.json, appt_missing_pooled30.csv, appt_extra_pooled30.csv, role_disagreements_pooled30.csv