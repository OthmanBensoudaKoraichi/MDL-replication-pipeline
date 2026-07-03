# Held-out evaluation — extraction vs human gold

**Scope:** 30 MDLs never used in development: 1431, 1570, 1738, 1913, 2002, 2009, 2272, 2331, 2353, 2418, 2436, 2493, 2542, 2566, 2590, 2613, 2633, 2669, 2673, 2693, 2744, 2767, 2796, 2797, 2807, 2814, 2820, 2865, 2874, 2887

Deterministic agreement (no LLM judge). Names matched on a normalized key (spelling/middle initials/suffixes ignored); firms compared representation-agnostically (row or attribute). 95% Wilson CIs in brackets.


## Tier 1 — Appointments (primary)

- **Individuals (the people):** recall **97.1%** (93.8, 98.7), precision **86.3%** (81.3, 90.1), F1 91.4% (gold 207, ours 233, matched 201)
- **Firms (representation-agnostic):** recall 97.7%, precision 94.6%, F1 96.1% (gold 217, ours 224, matched 212)
- **Combined (individuals + firms):** recall 97.4%, precision 90.4%, F1 93.8%
- **Role accuracy (Jaccard, partial credit):** 92.6% (reconciled 92.1%)
- **Side agreement:** 99.5%
- **Soft F1 (role-weighted headline):** recall 89.5%, precision 79.5%, **F1 84.2%**
- *(secondary) interim agreement: 94.5%*


## Tier 2 — Orders (appointment-bearing)

- **Identity:** recall **89.6%** (77.8, 95.5), precision **82.7%** (70.3, 90.6), F1 86.0% (gold 48, ours 52, matched 43)

| analytic field | agreement | n |
|---|---|---|
| Contested | 88.4% (75.5, 94.9) | 38/43 |
| Date(meta) | 90.7% (78.4, 96.3) | 39/43 |
| IRPA_Duties_to_Clients | 83.7% (70.0, 91.9) | 36/43 |
| Judge(meta) | 76.7% (62.3, 86.8) | 33/43 |
| Limit_Nonleader_Practice | 72.1% (57.3, 83.3) | 31/43 |
| OU_Create | 74.4% (59.8, 85.1) | 32/43 |
| OU_Duties_to_Nonclients | 44.2% (30.4, 58.9) | 19/43 |
| OU_Functions | 79.1% (64.8, 88.6) | 34/43 |
| Order_Types(exact) | 67.4% (52.5, 79.5) | 29/43 |
| Rule_23 | 95.3% (84.5, 98.7) | 41/43 |

*Order_Types mean Jaccard: 76.6% (reconciled 76.0%)*

## Tier 3 — Attorneys (distinct individuals)

- recall 97.1% (93.8, 98.7), precision 86.3% (81.3, 90.1), F1 91.4% (downstream of appointments; exact names/demographics out of scope)


## Per-MDL

| MDL | gold appt | our appt | matched | gold ord | our ord |
|---|---|---|---|---|---|
| 1431 | 57 | 56 | 55 | 2 | 0 |
| 1570 | 30 | 43 | 29 | 2 | 5 |
| 1738 | 6 | 6 | 6 | 1 | 1 |
| 1913 | 2 | 2 | 2 | 2 | 2 |
| 2002 | 15 | 16 | 15 | 2 | 2 |
| 2009 | 2 | 2 | 2 | 1 | 1 |
| 2272 | 40 | 42 | 40 | 2 | 1 |
| 2331 | 31 | 31 | 31 | 2 | 2 |
| 2353 | 2 | 2 | 2 | 1 | 1 |
| 2418 | 6 | 6 | 6 | 2 | 2 |
| 2436 | 20 | 20 | 20 | 2 | 2 |
| 2493 | 4 | 13 | 4 | 1 | 2 |
| 2542 | 4 | 4 | 4 | 2 | 2 |
| 2566 | 13 | 13 | 11 | 2 | 2 |
| 2590 | 8 | 8 | 8 | 2 | 2 |
| 2613 | 9 | 18 | 9 | 1 | 2 |
| 2633 | 15 | 15 | 15 | 2 | 2 |
| 2669 | 18 | 18 | 17 | 2 | 2 |
| 2673 | 9 | 9 | 9 | 2 | 3 |
| 2693 | 17 | 16 | 15 | 2 | 2 |
| 2744 | 14 | 14 | 13 | 2 | 1 |
| 2767 | 28 | 30 | 28 | 2 | 2 |
| 2796 | 22 | 22 | 22 | 1 | 1 |
| 2797 | 7 | 7 | 7 | 1 | 1 |
| 2807 | 2 | 2 | 2 | 1 | 2 |
| 2814 | 1 | 1 | 1 | 1 | 1 |
| 2820 | 18 | 18 | 17 | 2 | 2 |
| 2865 | 2 | 2 | 2 | 1 | 2 |
| 2874 | 2 | 1 | 1 | 1 | 1 |
| 2887 | 20 | 20 | 20 | 1 | 1 |

## Files

- eval/metrics_small30.json, appt_missing_small30.csv, appt_extra_small30.csv, role_disagreements_small30.csv