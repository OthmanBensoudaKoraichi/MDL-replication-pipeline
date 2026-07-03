# Held-out evaluation — extraction vs human gold

**Scope:** 20 MDLs never used in development: 1566, 2151, 2187, 2243, 2406, 2434, 2567, 2670, 2672, 2743, 2773, 2775, 2795, 2800, 2817, 2836, 2842, 2848, 2859, 2867

Deterministic agreement (no LLM judge). Names matched on a normalized key (spelling/middle initials/suffixes ignored). 95% Wilson CIs in brackets.


## Tier 1 — Appointments (primary)

- **Identity (the right people/firms):** recall **90.1%** (87.1, 92.5), precision **94.0%** (91.5, 95.8), F1 92.0% (gold 486, ours 466, matched 438)
- **Role accuracy (Jaccard, partial credit):** 73.6% (reconciled 72.7%)
- **Side agreement:** 99.1%
- **Soft F1 (role-weighted headline):** recall 65.6%, precision 68.4%, **F1 67.0%**
- *(secondary) interim agreement: 93.4%*


## Tier 2 — Orders (appointment-bearing)

- **Identity:** recall **85.7%** (78.5, 90.8), precision **85.0%** (77.8, 90.2), F1 85.4% (gold 126, ours 127, matched 108)

| analytic field | agreement | n |
|---|---|---|
| Contested | 88.9% (81.6, 93.5) | 96/108 |
| Date(meta) | 96.3% (90.9, 98.6) | 104/108 |
| IRPA_Duties_to_Clients | 95.4% (89.6, 98.0) | 103/108 |
| Judge(meta) | 87.0% (79.4, 92.1) | 94/108 |
| Limit_Nonleader_Practice | 86.1% (78.3, 91.4) | 93/108 |
| OU_Create | 75.0% (66.1, 82.2) | 81/108 |
| OU_Duties_to_Nonclients | 61.1% (51.7, 69.8) | 66/108 |
| OU_Functions | 62.0% (52.6, 70.6) | 67/108 |
| Order_Types(exact) | 49.1% (39.8, 58.4) | 53/108 |
| Rule_23 | 96.3% (90.9, 98.6) | 104/108 |

*Order_Types mean Jaccard: 71.5% (reconciled 72.7%)*

## Tier 3 — Attorneys (distinct individuals)

- recall 94.7% (92.1, 96.5), precision 93.6% (90.9, 95.6), F1 94.2% (downstream of appointments; exact names/demographics out of scope)


## Per-MDL

| MDL | gold appt | our appt | matched | gold ord | our ord |
|---|---|---|---|---|---|
| 1566 | 13 | 13 | 12 | 18 | 15 |
| 2151 | 27 | 28 | 27 | 4 | 7 |
| 2187 | 79 | 78 | 78 | 12 | 13 |
| 2243 | 17 | 17 | 15 | 5 | 5 |
| 2406 | 107 | 110 | 99 | 9 | 8 |
| 2434 | 19 | 19 | 19 | 4 | 4 |
| 2567 | 13 | 9 | 9 | 4 | 3 |
| 2670 | 11 | 11 | 11 | 9 | 8 |
| 2672 | 30 | 32 | 30 | 9 | 11 |
| 2743 | 7 | 6 | 6 | 4 | 4 |
| 2773 | 4 | 4 | 4 | 3 | 3 |
| 2775 | 31 | 29 | 29 | 7 | 8 |
| 2795 | 29 | 28 | 22 | 4 | 4 |
| 2800 | 26 | 26 | 26 | 4 | 5 |
| 2817 | 9 | 9 | 9 | 8 | 6 |
| 2836 | 26 | 20 | 16 | 4 | 4 |
| 2842 | 7 | 7 | 7 | 7 | 8 |
| 2848 | 14 | 3 | 3 | 5 | 4 |
| 2859 | 12 | 12 | 11 | 3 | 3 |
| 2867 | 5 | 5 | 5 | 3 | 4 |

## Files

- eval/metrics_new20.json, appt_missing_new20.csv, appt_extra_new20.csv, role_disagreements_new20.csv