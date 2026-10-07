# Held-out evaluation — extraction vs human gold

**Scope:** 53 MDLs never used in development: 1836, 1916, 2020, 2067, 2084, 2153, 2158, 2184, 2197, 2327, 2329, 2332, 2357, 2382, 2419, 2433, 2445, 2452, 2475, 2495, 2541, 2555, 2557, 2573, 2586, 2587, 2606, 2615, 2624, 2641, 2642, 2677, 2691, 2704, 2705, 2737, 2738, 2750, 2752, 2754, 2776, 2777, 2779, 2782, 2792, 2804, 2809, 2827, 2828, 2833, 2841, 2843, 2879

Deterministic agreement (no LLM judge). Names matched on a normalized key (spelling/middle initials/suffixes ignored); firms compared representation-agnostically (row or attribute). 95% Wilson CIs in brackets.


## Tier 1 — Appointments (primary)

- **Individuals (the people):** recall **90.6%** (88.1, 92.6), precision **93.3%** (91.1, 95.0), F1 91.9% (gold 649, ours 630, matched 588)
- **Firms (representation-agnostic):** recall 85.6%, precision 94.7%, F1 89.9% (gold 568, ours 513, matched 486)
- **Combined (individuals + firms):** recall 88.2%, precision 94.0%, F1 91.0%
- **Role accuracy (Jaccard, partial credit):** 89.7% (reconciled 88.8%)
- **Side agreement:** 99.5%
- **Soft F1 (role-weighted headline):** recall 80.5%, precision 82.9%, **F1 81.7%**
- *(secondary) interim agreement: 93.2%*


## Tier 2 — Orders (appointment-bearing)

- **Identity:** recall **93.6%** (86.8, 97.0), precision **84.6%** (76.5, 90.3), F1 88.9% (gold 94, ours 104, matched 88)

| analytic field | agreement | n |
|---|---|---|
| Contested | 90.9% (83.1, 95.3) | 80/88 |
| Date(meta) | 88.6% (80.3, 93.7) | 78/88 |
| IRPA_Duties_to_Clients | 77.3% (67.5, 84.8) | 68/88 |
| Judge(meta) | 86.4% (77.7, 92.0) | 76/88 |
| Limit_Nonleader_Practice | 70.5% (60.2, 79.0) | 62/88 |
| OU_Create | 56.8% (46.4, 66.7) | 50/88 |
| OU_Duties_to_Nonclients | 38.6% (29.1, 49.1) | 34/88 |
| OU_Functions | 72.7% (62.6, 80.9) | 64/88 |
| Order_Types(exact) | 64.8% (54.4, 73.9) | 57/88 |
| Rule_23 | 98.9% (93.8, 99.8) | 87/88 |

*Order_Types mean Jaccard: 78.6% (reconciled 77.4%)*

## Tier 3 — Attorneys (distinct individuals)

- recall 90.6% (88.1, 92.6), precision 93.3% (91.1, 95.0), F1 91.9% (downstream of appointments; exact names/demographics out of scope)


## Per-MDL

| MDL | gold appt | our appt | matched | gold ord | our ord |
|---|---|---|---|---|---|
| 1836 | 16 | 16 | 15 | 1 | 1 |
| 1916 | 6 | 5 | 5 | 2 | 3 |
| 2020 | 21 | 24 | 21 | 2 | 2 |
| 2067 | 8 | 8 | 8 | 1 | 1 |
| 2084 | 11 | 11 | 11 | 1 | 1 |
| 2153 | 10 | 10 | 10 | 1 | 1 |
| 2158 | 7 | 10 | 7 | 1 | 1 |
| 2184 | 6 | 6 | 6 | 1 | 1 |
| 2197 | 80 | 80 | 80 | 2 | 2 |
| 2327 | 37 | 37 | 37 | 3 | 2 |
| 2329 | 2 | 2 | 2 | 1 | 1 |
| 2332 | 32 | 40 | 31 | 3 | 5 |
| 2357 | 14 | 15 | 14 | 1 | 3 |
| 2382 | 8 | 8 | 8 | 1 | 1 |
| 2419 | 17 | 17 | 17 | 2 | 2 |
| 2433 | 18 | 18 | 16 | 2 | 2 |
| 2445 | 27 | 40 | 27 | 2 | 2 |
| 2452 | 44 | 44 | 44 | 1 | 2 |
| 2475 | 4 | 4 | 4 | 1 | 1 |
| 2495 | 20 | 21 | 20 | 1 | 1 |
| 2541 | 3 | 3 | 3 | 2 | 2 |
| 2555 | 23 | 16 | 14 | 2 | 2 |
| 2557 | 5 | 5 | 5 | 2 | 3 |
| 2573 | 2 | 2 | 2 | 2 | 3 |
| 2586 | 16 | 14 | 5 | 1 | 1 |
| 2587 | 36 | 33 | 33 | 2 | 2 |
| 2606 | 47 | 22 | 22 | 4 | 4 |
| 2615 | 5 | 5 | 5 | 1 | 1 |
| 2624 | 10 | 10 | 10 | 1 | 2 |
| 2641 | 51 | 51 | 49 | 2 | 2 |
| 2642 | 26 | 27 | 26 | 1 | 1 |
| 2677 | 13 | 13 | 12 | 1 | 1 |
| 2691 | 25 | 27 | 24 | 1 | 1 |
| 2704 | 9 | 9 | 9 | 2 | 2 |
| 2705 | 24 | 23 | 23 | 1 | 2 |
| 2737 | 7 | 4 | 4 | 2 | 1 |
| 2738 | 38 | 38 | 38 | 5 | 5 |
| 2750 | 28 | 28 | 28 | 1 | 2 |
| 2752 | 10 | 10 | 10 | 1 | 1 |
| 2754 | 31 | 31 | 30 | 1 | 2 |
| 2776 | 13 | 13 | 13 | 1 | 1 |
| 2777 | 23 | 24 | 22 | 2 | 2 |
| 2779 | 22 | 22 | 21 | 1 | 1 |
| 2782 | 30 | 30 | 30 | 2 | 2 |
| 2792 | 26 | 26 | 26 | 4 | 4 |
| 2804 | 93 | 28 | 28 | 7 | 4 |
| 2809 | 32 | 32 | 31 | 2 | 2 |
| 2827 | 78 | 78 | 74 | 2 | 3 |
| 2828 | 21 | 21 | 21 | 1 | 1 |
| 2833 | 15 | 8 | 7 | 2 | 2 |
| 2841 | 8 | 8 | 8 | 1 | 1 |
| 2843 | 4 | 11 | 4 | 1 | 3 |
| 2879 | 55 | 55 | 54 | 3 | 3 |

## Files

- eval/metrics_heldout55.json, appt_missing_heldout55.csv, appt_extra_heldout55.csv, role_disagreements_heldout55.csv