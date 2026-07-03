# WHO LEADS IN MASS LITIGATION? EVIDENCE FROM MDL: Replication Materials

This repository contains the datasets and analysis code used to generate all figures and statistics in "WHO LEADS IN MASS LITIGATION? EVIDENCE FROM MDL" submitted to the Yale Law Review.

**Contents:**
- `datasets/` — Raw data files (appointments, attorneys, MDLs, orders, ABA law schools)
- `analysis.ipynb` — Complete Jupyter notebook with data cleaning, analysis, and visualization code

## Notebook Structure

### 1. Data Cleaning

**Section 1.1–1.4**: Raw data import and preparation
- Import and standardize column names across five core datasets: ABA law schools, appointments, attorneys, MDLs, and orders
- Clean appointments: firm name standardization, attorney ID extraction, MDL number validation
- Build attorney × MDL dataset with canonical names, firm assignments, and plaintiff/defendant classification
- Consolidate attorney and firm data: merge attorney demographics, deduplicate firm names using token-based clustering, create combined attorney × MDL and firm × MDL dataset

### 2. Main Paper Figures (Figures 6–13)

**Section 2.1**: Figure 6 — Distribution of Repeated Co-Appointment Across MDLs
- All attorney pairs, count shared MDLs, display distribution with counts and percentages

**Section 2.2**: Figure 7 — Frequency of Co-Appointments for Top 20 MDL Attorneys
- Heatmap of co-appointment patterns among most-appointed attorneys

**Section 2.3**: Figure 8 — Prevalence of One-Off Collaborations
- Measure collaboration diversity: share of collaborators appearing only once per attorney

**Section 2.4**: Figure 9 — Distribution of Repeated Co-Appointment Across MDLs (Firms)
- Parallel to Figure 6 but for firm-level co-appointments

**Section 2.5**: Figure 10 — Frequency of Co-Appointments for Top 20 MDL Firms
- Heatmap of firm co-appointment patterns

**Section 2.6**: Figure 11 — Actual vs. Expected Co-Appointments Under Capacity-Constrained Random Allocation
- Monte Carlo simulation (1,000 iterations) comparing observed co-appointments to null distribution
- Tests whether observed co-appointments exceed what capacity constraints alone would predict

**Section 2.7**: Figure 12 — New MDL Entrants Over Time
- Naive measure: first-ever MDL appearance
- Rolling 3-year measure: no appearance in prior three years
- Tracks entry patterns from 2007–present

**Section 2.8**: Figure 13 — Variation in Judges' Appointments of First-Time Leaders
- Judge-level analysis: proportion of leadership slots given to first-time appointees
- Identifies substantial variation across judges in openness to newcomers

### 3. Appendix Figures (Appendix C)

**Section 3.1–3.2**: Figures 1–2 — Geographic Distribution of Individual Appointments
- Choropleth and bar chart of all appointments by bar state

**Section 3.3–3.4**: Figures 3–4 — Geographic Distribution of Lead Counsel Appointments
- Choropleth and bar chart restricted to LeadCounsel role

**Section 3.5–3.6**: Figures 5–6 — Gender Distribution
- All appointments and LeadCounsel appointments separately

**Section 3.7–3.8**: Figures 7–8 — Age Distribution at Time of MDL Transfer
- All appointments and LeadCounsel appointments with mean/median lines

### 4. Part III.2: Cycling in Attorney Leadership Roles

**Section 4**: Cycling Detection
- Identifies attorney pairs that reverse hierarchical positions across different MDLs
- Computes cycling rate as percentage of co-appearing pairs that exhibit rank reversal
- Result cited in Part III.2 of the paper

## Data Requirements

All code assumes the following datasets are available in the notebook environment:

- `appointments.csv` — Raw appointment records from court documents
- `attorneys.csv` — Attorney demographic and educational data
- `mdls.csv` — MDL case metadata including filing and transfer dates
- `orders.csv` — MDL orders with assigned judges
- `aba_law_schools.csv` — ABA-approved law school directory

## Key Features

- **Publication-quality styling**: All figures use Times New Roman, 300 DPI, with removed top/right spines and consistent formatting
- **Commented code**: Each section includes explanatory comments describing data transformations, calculations, and visualization choices
- **Reproducibility**: All statistics, counts, and percentages are computed directly from the data; no hard-coded numbers
- **Testable assumptions**: Filtering criteria (e.g. plaintiff-side only) are explicit and documented

