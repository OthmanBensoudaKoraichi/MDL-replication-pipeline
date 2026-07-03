# Extraction vs human gold — evaluation report

**Scope:** 10 MDLs (extracted ∩ gold-labeled): 2263, 2428, 2504, 2570, 2664, 2687, 2741, 2818, 2873, 2878

Two metric families. **Set metrics** (precision/recall/F1) answer *did we find the same things?* **Agreement metrics** (accuracy) answer *for a thing both sides have, do the values match?* We do not use accuracy for the set level because it would require counting the unbounded set of true negatives (every doc correctly not an order, every attorney not appointed), pinning it near 100%.


## 1. Orders — set identity (key = MDL-Docket)

- gold **47** · ours **51** · matched **45**
- **Recall 95.7%** — of gold orders, we also have 45/47 (2 missing)
- **Precision 88.2%** — of our orders, gold also has 45/51 (6 extra). Of those extras, **0 carry 0 appointees** (procedural, add no appointment data) and **6 carry people**.
- **Adjusted precision 88.2%** (charging only appointee-bearing extras)
- **F1 91.8%**


### 1b. Adjudicated orders (LLM judge read the text; humans miss/err too)

- **Precision 88.2% → 96.1%** — of our 'extra' orders, **4 were real orders the human MISSED** (not our error) and 2 were genuine over-includes (0 unresolved).
- **Recall 95.7% → 100.0%** — of our 'missing' orders, 0 were genuine misses and **2 were actually gold OVER-includes** (0 unresolved).
- *unresolved (neither / both_defensible / no-text) excluded from the adjudicated denominators; the judge is an LLM, so treat as adjudication evidence not ground truth*


## 2. Appointments — same people? (pooled per MDL = the roster view)

- distinct individuals — gold **179** · ours **185** · matched **172**
- **Recall 96.1%** · **Precision 93.0%** · **F1 94.5%**
- firms — gold 9 · ours 12 · matched 9


## 3. Order similarity — of the orders BOTH sides have, do the rosters agree?

- appointee roster **identical: 20/45 (44.4%)** · partial (≥0.5 overlap): 18 · divergent: 7
- mean appointee-set Jaccard overlap: 78.7%


## 4. Field agreement (accuracy on matched items)

### Order-level
| field | agree/total | % |
|---|---|---|
| Contested | 40/45 | 88.9% |
| Date | 42/45 | 93.3% |
| Judge | 45/45 | 100.0% |
| Judge_Type | 45/45 | 100.0% |
| OU_Create | 36/45 | 80.0% |
| Order_Types (exact set) | 23/45 | 51.1% |
| Rule_23 | 43/45 | 95.6% |

*Order_Types mean Jaccard: 75.2%*

### Appointment-level (people both sides list, in matched orders)
| field | agree/total | % |
|---|---|---|
| Plaintiff/Defendant | 471/471 | 100.0% |
| appoint | 470/471 | 99.8% |
| interim | 420/471 | 89.2% |
| remove | 471/471 | 100.0% |
| roles (exact set) | 357/471 | 75.8% |

*roles mean Jaccard: 79.2%*

### 4b. Field accuracy crediting the Coordination↔Management call as ours-correct

_Coordination<->Management counted as ours-correct (Defense Coordination Committee). Other differences (e.g. our extra LeadCounsel tag) still count as errors._

| column | raw | adjudicated |
|---|---|---|
| Appointment **roles** (exact set) | 75.8% | **93.2%** |
| Appointment roles (Jaccard, partial credit) | 79.2% | 95.5% |
| Order **Order_Types** (exact set) | 51.1% | **64.4%** |
| Order_Types (Jaccard, partial credit) | 75.2% | 81.9% |

All other columns are unaffected by the role call: Plaintiff/Defendant, Appoint, Remove, Appointee Type stay at their raw values; Interim, Judge, Date, Rule_23, Contested, OU_Create are unrelated to Coordination/Management.


### Role disagreements, clustered (one row = one recurring pattern)

| count | GOLD | OURS | MDLs |
|---|---|---|---|
| 67 | coordination | management | 2873×67 |
| 9 | management | leadcounsel,management | 2428×8, 2570×1 |
| 8 | communications,coordination | communications,management | 2873×8 |
| 7 | coordination,leadcounsel | leadcounsel,management | 2873×7 |
| 6 | management | coordination | 2873×6 |
| 5 | coordination | communications,coordination | 2570×5 |
| 4 | classcounsel | classcounsel,leadcounsel | 2664×1, 2878×3 |
| 3 | coordination | leadcounsel,management | 2873×3 |
| 2 | communications,management | communications,leadcounsel,management | 2428×2 |
| 2 | coordination | communications,management | 2873×2 |
| 1 | leadcounsel | leadcounsel,management | 2687×1 |

## 5. Counts per MDL

| MDL | gold ord | our ord | gold ppl | our ppl |
|---|---|---|---|---|
| 2263 | 1 | 1 | 11 | 11 |
| 2428 | 2 | 2 | 19 | 21 |
| 2504 | 3 | 4 | 0 | 0 |
| 2570 | 10 | 8 | 41 | 39 |
| 2664 | 1 | 2 | 5 | 8 |
| 2687 | 8 | 8 | 16 | 16 |
| 2741 | 3 | 3 | 9 | 12 |
| 2818 | 1 | 1 | 4 | 4 |
| 2873 | 14 | 18 | 71 | 71 |
| 2878 | 4 | 4 | 3 | 3 |

## 6. LLM-judge adjudication (read the order text)

| kind | ref | who is right | rationale |
|---|---|---|---|
| extra_order | 2504-353 | **gold** | The excerpt is a Rule 23 preliminary-approval/conditional class-certification order that discusses the adequacy and fees of “proposed class counsel,” but it does not show any operative appointment, removal, or modification of named class counsel or an MDL leadership role. |
| extra_order | 2664-8 | **ours** | Paragraph 18 expressly states that, pending appointment of Lead and Liaison Counsel, named individuals “will serve as interim Liaison Counsel” for plaintiffs and defendants, which is a leadership/communications appointment. |
| extra_order | 2873-4754 | **gold** | The excerpt describes a final settlement approval/class certification order and only recites that prior CMOs had appointed Co-Lead Counsel, PEC members, and Advisory Counsel; it does not itself appoint, remove, or modify any counsel or committee. |
| extra_order | 2873-5110 | **ours** | The order expressly states that the Court “provisionally appoints” Michael A. London/Douglas & London, Scott Summy/Baron & Budd, Paul J. Napoli/Napoli Shkolnik, and Joe Rice/Motley Rice “as Class Counsel under Rule 23(g)(3),” which is a leadership appointment under the dataset definitions. |
| extra_order | 2873-5147 | **ours** | The order expressly states that the Court “provisionally appoints” Michael A. London/Douglas & London, Scott Summy/Baron & Budd, Paul J. Napoli/Napoli Shkolnik, and Joe Rice/Motley Rice “as Class Counsel under Rule 23(g)(3).” |
| extra_order | 2873-5253 | **ours** | The order expressly states that the Court “provisionally appoints” Michael A. London/Douglas & London, Scott Summy/Baron & Budd, Paul J. Napoli/Napoli Shkolnik, and Joe Rice/Motley Rice “as Class Counsel under Rule 23(g)(3).” |
| missing_order | 2570-51 | **ours** | The text describes plaintiffs' counsel submitting a “preliminary Leadership Structure” and requesting two more weeks for comment, rather than the court appointing, removing, or modifying any counsel or committee. |
| missing_order | 2570-64 | **ours** | The order merely grants Teresa Toriseva's request to withdraw her motion to be appointed co-lead counsel and directs plaintiffs to file a proposed leadership structure later; it does not appoint, remove, or modify any counsel or committee. |
| missing_order | 2687-1173 | **gold** | Paragraph 4 states that “Interim IPP Lead Counsel is appointed as class counsel for the Indirect Purchaser Settlement Class pursuant to Rules 23(c)(1)(B) and (g),” which is an explicit Rule 23 class counsel appointment. |
| missing_order | 2687-1281 | **gold** | Paragraph 5 expressly states that “Interim DPP Lead Counsel is appointed as class counsel for the Direct Purchaser Settlement Class pursuant to Fed.R.Civ.P. 23(c)(1)(B) and (g),” which is a Rule 23 ClassCounsel appointment. |
| missing_order | 2687-1388 | **gold** | Paragraph 5 expressly states that “Interim DPP Lead Counsel is appointed as class counsel for the Direct Purchaser Settlement Class pursuant to Fed.R.Civ.P. 23(e)(1)(B) and (g),” even if only for settlement purposes. |
| missing_order | 2687-1420 | **gold** | Paragraph 5 expressly states that “Interim DPP Lead Counsel is appointed as class counsel for the Direct Purchaser Settlement Class pursuant to Fed.R.Civ.P. 23(c)(1)(B) and (g),” which is a Rule 23 class-counsel appointment. |
| missing_order | 2741-16401 | **gold** | Paragraph 5 states that the Court 'confirms its appointment' of the named plaintiffs as Class Representatives and 'the appointment of Class Counsel as counsel for the Settlement Class,' which is a Rule 23 class counsel appointment. |
| role_cluster | coordination -> management (x67) | **neither** | The excerpt appoints a Plaintiffs' Executive Committee, which is a Management role, but also appoints a Defendants' Coordination Committee, whose name leans Coordination under the coding rules, so a blanket management-or-coordination label for all appointees is not supported. |
| role_cluster | management -> leadcounsel,management (x10) | **gold** | The disputed appointees are appointed to the Plaintiffs' Steering Committee, while the order separately states that the “Plaintiffs' Executive Committee shall serve as Lead Counsel,” so PSC members are supported as Management only. |
| role_cluster | communications,coordination -> communications,management (x8) | **gold** | The order expressly appoints attorneys to the “Defendants' Coordination Committee (DCC)” and separately appoints “Defendants' Co-Liaison Counsel,” supporting communications plus coordination rather than a generic management/steering committee label. |
| role_cluster | coordination,leadcounsel -> leadcounsel,management (x7) | **gold** | The order expressly appoints the relevant attorneys to the “Defendants' Coordination Committee ("DCC")” and also appoints some as Defendants' Co-Lead Counsel, so the text supports Coordination rather than a generic Management committee label. |
| role_cluster | coordination -> communications,coordination (x5) | **ours** | The order expressly designates a “State/Federal Liaison Counsel,” so “State/Federal” supports cross-jurisdiction Coordination while “Liaison Counsel” also fits the Communications role definition. |
| role_cluster | coordination -> leadcounsel,management (x3) | **ours** | The three appointees are expressly named as “Plaintiffs’ Co-Lead Counsel,” and the order further says the “PEC is chaired by Plaintiffs’ Co-Lead Counsel,” whereas their role is not a state/foreign coordination committee role. |
| role_cluster | communications,management -> communications,leadcounsel,management (x2) | **ours** | The order expressly says “The Plaintiffs’ Executive Committee shall serve as Lead Counsel,” and Anthony Tarricone is both on the PEC and appointed Plaintiffs’ Liaison Counsel, so appointees holding PEC/liaison roles are supported as Communications, Management, and LeadCounsel. |
| role_cluster | coordination -> communications,management (x2) | **neither** | The two attorneys are expressly appointed as “Defendants' Co-Liaison Counsel,” supporting Communications, and also to the “Defendants' Coordination Committee,” whose name supports Coordination rather than a generic Management committee. |

## Files

- `eval/orders_missing.csv`, `eval/orders_extra.csv`, `eval/appt_disagreements.csv`, `eval/metrics.json`, `eval/llm_verdicts.csv`