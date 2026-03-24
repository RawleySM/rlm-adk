# Procurement Manifest -- understand_bench_v2 Corpus

## 1. Mission Summary

| Field | Value |
|-------|-------|
| **Date** | 2026-03-22 |
| **Purpose** | Procure real-world tax/accounting documents to build a multi-format corpus for the understand_bench_v2 benchmark, which evaluates an RLM-ADK agent's ability to detect missing context and identify format-processing skills across diverse file types |
| **Method** | 5 parallel research agents dispatched via RLM worker pool + manual web searches for gap-filling |
| **Research scope** | IRS training materials, blank forms, completed sample returns, brokerage guides, financial templates, third-party practice returns |
| **Storage** | Google Drive folder `understand_bench_v2_corpus` (ID: `1du_RDmyErKaSPnGxPUib4283Io-MwvpH`) + local synthetic corpus at `rlm_adk/eval/understand_bench_v2/corpus/generated/` |
| **Total procured** | 41 files across 6 categories in Google Drive + 14 synthetic files in 4 persona directories |

---

## 2. Procured Documents

### IRS Training Materials (7 files)

| # | Filename | Source URL | Format | Size | Quality | Description |
|---|----------|-----------|--------|------|---------|-------------|
| 1 | `IRS_Pub4491_VITA_Training.pdf` | https://www.irs.gov/pub/irs-pdf/p4491.pdf | PDF | 27 MB | ★★★★★ | VITA/TCE Training Guide -- complete textbook with worked examples for all major form types. Covers W-2, 1099 series, Schedules A/C/D/E, credits, and deductions |
| 2 | `IRS_Pub4491X_Supplement.pdf` | https://www.irs.gov/pub/irs-pdf/p4491x.pdf | PDF | 2.8 MB | ★★★★ | Training supplement with practice scenarios and errata for Pub 4491 |
| 3 | `IRS_Form6744_VITA_Test.pdf` | https://www.irs.gov/pub/irs-pdf/f6744.pdf | PDF | 6 MB | ★★★★★ | VITA volunteer certification test with ~15-20 complete taxpayer scenarios including filled W-2s, 1099s, and intake sheets. **GOLD STANDARD** source -- these are the closest thing to real client document packets publicly available |
| 4 | `IRS_Pub5379_VITA_Cert.pdf` | https://www.irs.gov/pub/irs-pdf/p5379.pdf | PDF | 645 KB | ★★★ | Link & Learn Taxes certification FAQ. Useful for understanding VITA assessment methodology |
| 5 | `IRS_Pub4012_Volunteer_Guide.pdf` | https://www.irs.gov/pub/irs-pdf/p4012.pdf | PDF | 55 MB | ★★★★★ | Volunteer resource guide with decision trees, form completion charts, and reference tables. Contains the algorithmic logic an agent should replicate |
| 6 | `IRS_VITA_Capital_Gains_Teaching.pdf` | https://apps.irs.gov/app/vita/content/globalmedia/4491_capital_gain.pdf | PDF | 87 KB | ★★★★ | Capital gains teaching material with filled Form 8949 and Schedule D examples |
| 7 | `IRS_Form_13614C_Intake.pdf` | https://www.irs.gov/pub/irs-pdf/f13614c.pdf | PDF | 279 KB | ★★★★★ | Standardized VITA intake/interview sheet template. This is the canonical intake form used across all VITA sites -- critical for understanding what information the agent should expect from clients |

### IRS Form Blanks (18 files)

| # | Filename | Source URL | Format | Size | Description |
|---|----------|-----------|--------|------|-------------|
| 1 | `IRS_W2_blank.pdf` | https://www.irs.gov/pub/irs-pdf/fw2.pdf | PDF | -- | Wage and Tax Statement |
| 2 | `IRS_1040_2025.pdf` | https://www.irs.gov/pub/irs-pdf/f1040.pdf | PDF | -- | U.S. Individual Income Tax Return |
| 3 | `IRS_1099B_blank.pdf` | https://www.irs.gov/pub/irs-pdf/f1099b.pdf | PDF | -- | Proceeds From Broker and Barter Exchange Transactions |
| 4 | `IRS_1099NEC_blank.pdf` | https://www.irs.gov/pub/irs-pdf/f1099nec.pdf | PDF | -- | Nonemployee Compensation |
| 5 | `IRS_1099INT.pdf` | https://www.irs.gov/pub/irs-pdf/f1099int.pdf | PDF | -- | Interest Income |
| 6 | `IRS_1099DIV.pdf` | https://www.irs.gov/pub/irs-pdf/f1099div.pdf | PDF | -- | Dividends and Distributions |
| 7 | `IRS_1099R.pdf` | https://www.irs.gov/pub/irs-pdf/f1099r.pdf | PDF | -- | Distributions From Pensions, Annuities, Retirement/Profit-Sharing Plans, IRAs, Insurance Contracts |
| 8 | `IRS_1098_blank.pdf` | https://www.irs.gov/pub/irs-pdf/f1098.pdf | PDF | -- | Mortgage Interest Statement |
| 9 | `IRS_1095A.pdf` | https://www.irs.gov/pub/irs-pdf/f1095a.pdf | PDF | -- | Health Insurance Marketplace Statement |
| 10 | `IRS_Schedule_A.pdf` | https://www.irs.gov/pub/irs-pdf/f1040sa.pdf | PDF | -- | Schedule A (Form 1040) -- Itemized Deductions |
| 11 | `IRS_Schedule_C.pdf` | https://www.irs.gov/pub/irs-pdf/f1040sc.pdf | PDF | -- | Schedule C (Form 1040) -- Profit or Loss From Business |
| 12 | `IRS_Schedule_D.pdf` | https://www.irs.gov/pub/irs-pdf/f1040sd.pdf | PDF | -- | Schedule D (Form 1040) -- Capital Gains and Losses |
| 13 | `IRS_Schedule_E.pdf` | https://www.irs.gov/pub/irs-pdf/f1040se.pdf | PDF | -- | Schedule E (Form 1040) -- Supplemental Income and Loss |
| 14 | `IRS_Form_8949.pdf` | https://www.irs.gov/pub/irs-pdf/f8949.pdf | PDF | -- | Sales and Other Dispositions of Capital Assets |
| 15 | `IRS_Form_8962.pdf` | https://www.irs.gov/pub/irs-pdf/f8962.pdf | PDF | -- | Premium Tax Credit (PTC) |
| 16 | `IRS_Form_8880.pdf` | https://www.irs.gov/pub/irs-pdf/f8880.pdf | PDF | -- | Credit for Qualified Retirement Savings Contributions (Saver's Credit) |
| 17 | `IRS_Form_2441.pdf` | https://www.irs.gov/pub/irs-pdf/f2441.pdf | PDF | -- | Child and Dependent Care Expenses |
| 18 | `IRS_K1_1065.pdf` | https://www.irs.gov/pub/irs-pdf/f1065sk1.pdf | PDF | -- | Schedule K-1 (Form 1065) -- Partner's Share of Income, Deductions, Credits |

### Sample Completed Returns (8 files)

| # | Filename | Source URL | Format | Size | Quality | Description |
|---|----------|-----------|--------|------|---------|-------------|
| 1 | `IRS_sample_1040A_filled.pdf` | https://www.irs.gov/pub/newsroom/1040a.pdf | PDF | -- | ★★★★★ | Official IRS example marked "EXAMPLE ONLY DO NOT FILE" -- authoritative reference for expected form completion |
| 2 | `EconEdLink_1040_answer_key.pdf` | https://www.econedlink.org/wp-content/uploads/2019/03/1040-form-answer-key.pdf | PDF | -- | ★★★★ | Completed 1040 with answer explanations, designed for classroom use. Shows reasoning behind each line entry |
| 3 | `SCHR_2020_1040_sample.pdf` | https://www.schr.org/wp-content/uploads/2021/03/2020-1040-with-sample.pdf | PDF | -- | ★★★ | Completed 2020 Form 1040 (tax year may be slightly dated but form structure is representative) |
| 4 | `MontgomeryCollege_1040_2021.pdf` | https://www.montgomerycollege.edu/_documents/high-school/irs_f1040_2021_form.pdf | PDF | -- | ★★★ | Sample filled-in 2021 Form 1040 from educational institution |
| 5 | `ADP_Interactive_Sample_W2.pdf` | https://support.adp.com/adp_payroll/content/hybrid/PDF/W2_Interactive.pdf | PDF | -- | ★★★★★ | Interactive PDF W-2 with hover descriptions for each box. Excellent for form-layout-understanding skill validation |
| 6 | `Enact_Schedule_E_Rental_Example.pdf` | https://content.enactmi.com/documents/training/course/CalculatingRentalIncome.ScheduleE.2018.pdf | PDF | -- | ★★★★ | Completed Schedule E with rental income/expense data -- directly relevant to `retired_investor` persona |
| 7 | `RealTaxTools_Sample_1099NEC.pdf` | https://cdn.realtaxtools.com/docs/sample-1099-nec-form.pdf | PDF | -- | ★★★ | Filled 1099-NEC example |
| 8 | `Fresno_Example_Return.pdf` | https://www.fresnocitycollege.edu/uploaded-files/documents/admissions-aid/financial-aid/financial-aid-forms/25-26_fa_forms/25-26-example-tax-return.pdf | PDF | -- | ★★★★ | Completed 1040 with schedules from Fresno City College financial aid office |

### Drake Practice Returns (3 files)

| # | Filename | Source URL | Format | Size | Quality | Description |
|---|----------|-----------|--------|------|---------|-------------|
| 1 | `Drake_Practice_Return_1.pdf` | https://www.drakesoftware.com/sharedassets/education/practice/practice1.pdf | PDF | -- | ★★★★★ | Single parent, W-2, dependent child. Complete source document packet with intake sheet |
| 2 | `Drake_Practice_Return_2.pdf` | https://support.drakesoftware.com/pdf/practice/Practice2.pdf | PDF | -- | ★★★★★ | W-2, 1099-INT, 1099-DIV, stock sales. Multi-source-document scenario |
| 3 | `Drake_Practice_Return_4.pdf` | https://support.drakesoftware.com/pdf/practice/Practice4.pdf | PDF | -- | ★★★★★ | Multiple W-2s, 1099-DIVs, 1098-T. Complex filing with education credits |

### Brokerage Statement Guides (2 files)

| # | Filename | Source URL | Format | Size | Quality | Description |
|---|----------|-----------|--------|------|---------|-------------|
| 1 | `RaymondJames_Composite_1099_Guide.pdf` | https://www.raymondjames.com/-/media/rj/dotcom/files/client-resources/tax-reporting/cost_basiscomposite_brochure.pdf | PDF | -- | ★★★★★ | Annotated composite 1099 with sample brokerage pages. Essential for the `retired_investor` cost-basis multi-hop scenario |
| 2 | `WellsFargo_1099_Statement_Guide.pdf` | https://www.wellsfargoadvisors.com/pdf/how-to-read.pdf | PDF | -- | ★★★★ | Annotated brokerage 1099 pages explaining each section and box |

### Financial Templates (3 files)

| # | Filename | Source URL | Format | Size | Quality | Description |
|---|----------|-----------|--------|------|---------|-------------|
| 1 | `sample_bank_statement.xlsx` | https://smsfwarehouse.com.au/wp-content/uploads/2017/10/Sample-CSV-Bank-Statement.xlsx | XLSX | -- | ★★★ | Sample bank statement in spreadsheet format. Tests `excel_parse` skill |
| 2 | `mileage_log_template.xlsx` | https://www.vertex42.com/ExcelTemplates/download/mileage-tracking-log.xlsx | XLSX | -- | ★★★★ | Mileage tracking log template. Relevant to `freelance_photographer` and `gig_worker_family` personas |
| 3 | `Montana_Health_Expense.xlsx` | https://www.montana.edu/extensionecon/familyeconomics/healthexpenseworksheet.xlsx | XLSX | -- | ★★★ | Health/medical expense tracking worksheet. Relevant to `retired_investor` medical deductions |

### Root Level (1 file)

| # | Filename | Format | Description |
|---|----------|--------|-------------|
| 1 | `RESEARCH_FINDINGS.md` | MD | Research summary documenting the web research mission findings, agent dispatches, and source evaluations |

---

## 3. Local Corpus (Synthetic)

Generated files located at `rlm_adk/eval/understand_bench_v2/corpus/generated/`. These are synthetic documents crafted to create specific benchmark scenarios with known gaps.

### simple_w2_filer/

| Filename | Format | Size | Description |
|----------|--------|------|-------------|
| `intake_notes.md` | Markdown | 1.6 KB | Client intake interview notes -- mentions 401(k) contributions and savings interest that create the "missing document" gaps |
| `w2_datapoint_2025.json` | JSON | 1.1 KB | Structured W-2 data for single employer (DataPoint Systems, Austin TX) |
| `bank_statement_dec2025.csv` | CSV | 1.2 KB | December 2025 bank statement showing interest payments -- creates the 1099-INT gap |

### freelance_photographer/

| Filename | Format | Size | Description |
|----------|--------|------|-------------|
| `intake_notes.md` | Markdown | 3.3 KB | Detailed intake notes for freelance photographer with mixed W-2/1099 income, mentions ACA marketplace coverage |
| `1099_nec_bloom_events.json` | JSON | 577 B | 1099-NEC from Bloom Events (one of multiple expected clients) |
| `mileage_log_2025.csv` | CSV | 3.1 KB | Full-year mileage log for business travel |
| `home_office_measurements.txt` | TXT | 664 B | Home office square footage measurements for simplified method deduction |

### gig_worker_family/

| Filename | Format | Size | Description |
|----------|--------|------|-------------|
| `intake_notes.md` | Markdown | 3.2 KB | Intake notes for MFJ couple with gig work (DoorDash, Instacart), childcare, mentions ACA coverage |
| `doordash_1099_nec.csv` | CSV | 215 B | DoorDash 1099-NEC data (only one of multiple gig platforms represented) |
| `stride_mileage_jan_aug.csv` | CSV | 2.0 KB | Stride app mileage data covering only Jan-Aug (incomplete year -- tests gap detection) |
| `childcare_receipt.txt` | TXT | 724 B | Childcare payment receipt with provider EIN for Form 2441 |

### retired_investor/

| Filename | Format | Size | Description |
|----------|--------|------|-------------|
| `intake_notes.md` | Markdown | 4.0 KB | Complex intake notes for retired couple with trust income, multiple brokerages, rental property, and large medical expenses |
| `medical_expenses_2025.csv` | CSV | 2.9 KB | Itemized medical expenses for Schedule A threshold calculation |
| `rental_income_expense_2025.csv` | CSV | 1.2 KB | Rental property income and expenses for Schedule E |

---

## 4. Identified But Not Procured

### Interactive / Requires Account

| Source | URL | Format | Why Not Downloaded | Value |
|--------|-----|--------|-------------------|-------|
| TaxSlayer VITA Practice Lab | https://vita.taxslayerpro.com/IRSTraining | Web app | Requires access code (`TRAINPROWEB`) and account creation; interactive web application, not downloadable documents | ★★★★★ -- would provide realistic software-based filing scenarios |
| IRS Understanding Taxes Simulations | https://apps.irs.gov/app/understandingTaxes/student/simulations.jsp | Web app | 20 interactive browser-based scenarios; cannot be downloaded as static files | ★★★★ -- good variety of taxpayer situations |
| IRS Link & Learn Taxes | https://apps.irs.gov/app/vita/ | Web app | 6 certification courses delivered via browser; content is dynamic/interactive | ★★★★ -- official IRS training with built-in assessment |

### Paywalled / Faculty-Only

| Source | URL | Format | Why Not Downloaded | Value |
|--------|-----|--------|-------------------|-------|
| PwC Tax Case Studies | https://www.pwc.com/us/en/careers/university-relations/tax-case-studies.html | PDF | Requires faculty request/institutional access | ★★★★ -- professional-grade case studies |
| Whittenburg *Income Tax Fundamentals* (Cengage, 43rd Ed) | -- | Textbook | $100-200 paywalled textbook | ★★★★★ -- source documents "identical to real clients" per publisher description |
| South-Western Federal Taxation (Cengage) | -- | Textbook | Comprehensive paywalled textbook | ★★★★ -- standard university-level tax course text |
| Surgent Income Tax School | https://www.surgent.com/income-tax-school/ | Web course | Free sample available but full content paywalled | ★★★ |
| Intuit Academy courses | https://academy.intuit.com/ | Web course | Free courses but requires account; content is interactive modules, not downloadable packets | ★★★★ |
| Intuit Tax Prep Guide | https://digitalasset.intuit.com/render/content/dam/intuit/ic/en_us/intuit-academy/exam-resource-guides/tax-preparation-guide.pdf | PDF | May require Intuit Academy enrollment to access | ★★★ |
| Intuit Tax Level 1 Guide | https://digitalasset.intuit.com/render/content/dam/intuit/ic/en_us/intuit-academy/exam-resource-guides/tax-level-1-guide.pdf | PDF | May require Intuit Academy enrollment to access | ★★★ |

### Datasets Requiring Special Download

| Source | URL | Format | Why Not Downloaded | Value |
|--------|-----|--------|-------------------|-------|
| ICDAR 2019 SROIE Receipt Dataset | https://www.kaggle.com/datasets/urbikn/sroie-datasetv2 | Images + annotations | 1,000 real scanned receipts with OCR ground truth. Requires Kaggle account and large download (~500MB+) | ★★★★★ -- would enable `image_ocr` skill testing |
| Kaggle USA Banking Transactions CSV | https://www.kaggle.com/datasets/pradeepkumar2424/usa-banking-transactions-dataset-2023-2024 | CSV | 5,000 realistic transaction records. Requires Kaggle account | ★★★★ -- realistic transaction volume |
| ExcelBIAnalytics Bank Transaction CSVs | https://excelbianalytics.com/wp/downloads-20-sample-csv-files-data-sets-for-testing-till-2-million-records-bank-transactions/ | CSV | Multiple large files up to 2M records. Primarily for scale testing, not tax-specific | ★★★ |

### Additional Valuable Sources Not Downloaded

| Source | URL | Format | Why Not Downloaded | Value |
|--------|-----|--------|-------------------|-------|
| VITA Resources Practice Scenarios | https://www.vitaresources.net/practice-scenarios.html | Web/PDF | Named scenarios (Andrew Anderson, Jason January, etc.) -- site availability uncertain | ★★★★ |
| TaxSlayer Pro Practice Returns | https://www.taxslayerpro.com/education/practice-tax-returns | PDF | 8 complete practice returns -- may require account | ★★★★ |
| United Way Greater Richmond VITA Practice | https://www.yourunitedway.org/volunteer/vita/training/ | Web | Organization-specific training materials | ★★★ |
| Wisconsin DOR VITA Training Workbook | https://www.revenue.wi.gov/Documents/2024-VITA-Training-Workbook.pdf | PDF | State-specific, less general applicability | ★★★ |
| H&R Block TKA Case Study | https://media.hrblock.com/media/KnowledgeDevelopment/Forms/Certification/2023_tka2ts_Case_Study_1_r3.pdf | PDF | H&R Block internal certification material | ★★★★ |
| SSA POMS SSA-1099 Examples | https://secure.ssa.gov/poms.nsf/lnx/0205002300 | Web | SSA internal policy manual -- useful for Social Security income scenarios | ★★★ |
| HalfPriceSoft Filled 1099/1098 Forms | https://www.halfpricesoft.com/1099s_software/1099_sample_forms/ | Images | Software marketing material with sample output | ★★ |
| University of Pittsburgh Sample W-2 | https://www.payroll.pitt.edu/sites/default/files/assets/Sample-W2.pdf | PDF | Single-institution sample, limited incremental value over ADP interactive | ★★ |
| Monmouth University Sample W-2 | https://www.monmouth.edu/eof/documents/2021/08/sample-form-w2-for-parents-and-students.pdf/ | PDF | Single-institution sample | ★★ |
| CU Boulder Tax Document Examples | https://www.colorado.edu/financialaid/forms/examples-tax-documents | Web | University financial aid examples | ★★★ |
| UC Merced Sample 2020 Return | https://financialaid.ucmerced.edu/sites/financialaid.ucmerced.edu/files/documents/22-23/2020_sample_tax_return.pdf | PDF | Similar to other sample returns already procured | ★★ |
| Coursera Federal Taxation I (UIUC) | https://www.coursera.org/learn/federal-taxation-individuals | Web course | Full course requires enrollment; video-based content | ★★★ |
| OFX banking test fixtures | https://github.com/euforic/banking.js/blob/master/test/fixtures/sample.ofx | OFX | OFX format is niche; would test `xml_parse` but low priority | ★★ |
| ofxparse Python library fixtures | https://github.com/jseutter/ofxparse | OFX | Same rationale as above | ★★ |
| print-css.rocks HTML Account Statement | https://github.com/zopyx/print-css-rocks | HTML | HTML-rendered account statements; would test `html_parse` | ★★ |
| Kristels Schedule E Rental Worksheet | https://www.kristels.com/docs/Kristels-SchEWorksheet.pdf | PDF | Already covered by Enact Schedule E example | ★★ |
| Kristels Schedule C Worksheet | https://www.kristels.com/docs/Kristels-ScheduleC.pdf | PDF | Supplementary to existing IRS blanks | ★★ |
| AICPA 1040 Engagement Letter | https://www.aicpa-cima.com/resources/download/individual-tax-return-engagement-letter-form-1040 | PDF | Professional engagement letters -- useful for realism but not for tax data extraction | ★★ |
| Journal of Accountancy Engagement Letter | https://www.journalofaccountancy.com/wp-content/uploads/sites/3/2014/01/1040-engagement-letter-sample.doc | DOC | Same -- engagement workflow, not tax data | ★★ |
| CPA.com Engagement Letter | https://www.cpa.com/sites/cpa/files/media/engagement-letter-sample-for-sut.docx | DOCX | Same | ★★ |
| Schwab 1099 Guide | https://www.schwab.com/learn/story/how-to-read-your-brokerage-1099-form | Web | Guide content -- already covered by Raymond James and Wells Fargo guides | ★★★ |
| CASHMD Capital Gains Guide | https://cashmd.org/wp-content/uploads/7_Capital-Gains-Losses.pdf | PDF | Teaching material -- already covered by IRS VITA capital gains teaching doc | ★★ |
| Driversnote Mileage Log Template | https://www.driversnote.com/blog/irs-mileage-log-template-free-excel-pdf-versions | XLSX/PDF | Already have Vertex42 mileage template | ★★ |
| Driversnote Small Business Spreadsheet | https://www.driversnote.com/blog/small-business-income-expenses-spreadsheet-template | XLSX | Income/expense tracking -- supplementary | ★★ |
| DiMercurio Medical Expense Worksheet | https://www.dimercurioadvisors.com/medical-expense-summary-worksheet | Web | Medical expense summary -- already have Montana Health Expense template | ★★ |
| Triage Cancer Medical Bill Tracker | https://triagecancer.org/medical-bill-tracker | XLSX | Specialized medical bill tracking | ★★ |
| HSA Medical Expense Tracking | https://www.youngadultmoney.com/hsa-medical-expense-tracking-spreadsheet/ | XLSX | HSA-specific, narrow use case | ★★ |

---

## 5. Format Coverage Matrix

| Format | Procured (GDrive) | Synthetic (Local) | Coverage Status | Notes |
|--------|-------------------|-------------------|----------------|-------|
| **PDF** (text) | 39 files | -- | STRONG | IRS forms, training docs, sample returns, brokerage guides |
| **PDF** (fillable forms) | 18 blank forms + interactive W-2 | -- | STRONG | Tests `pdf_form_field_extract` skill |
| **PDF** (scanned/image) | -- | -- | GAP | No scanned/photographed documents. Would need SROIE dataset or similar for `image_ocr` testing |
| **CSV** | -- | 6 files | MODERATE | Bank statement, mileage logs, 1099 data, medical expenses, rental data |
| **JSON** | -- | 2 files | MODERATE | W-2 structured data, 1099-NEC data |
| **XLSX** | 3 files | -- | MODERATE | Bank statement, mileage template, health expense worksheet |
| **Markdown** | 1 file (research findings) | 4 files (intake notes) | MODERATE | Intake notes serve as primary narrative documents |
| **TXT** | -- | 2 files | LIGHT | Home office measurements, childcare receipt |
| **HTML** | -- | -- | GAP | No HTML documents procured. Would test `html_parse` skill |
| **Images** (JPG/PNG) | -- | -- | GAP | No photographed receipts or handwritten documents. Critical gap for `image_ocr` and `image_handwriting_ocr` skills |
| **XML/OFX** | -- | -- | GAP | No banking OFX or XML documents. Would test `xml_parse` skill |
| **DOC/DOCX** | -- | -- | GAP | No Word documents. Low priority -- not typical for tax source documents |

### Skill Coverage Summary

| Skill | Covered By | Status |
|-------|-----------|--------|
| `pdf_text_extract` | 39 PDF files | COVERED |
| `pdf_table_extract` | Training docs, sample returns with tables | COVERED |
| `pdf_form_field_extract` | 18 blank forms, interactive W-2 | COVERED |
| `image_ocr` | -- | NOT COVERED (need scanned documents) |
| `image_handwriting_ocr` | -- | NOT COVERED (need handwritten samples) |
| `csv_parse` | 6 synthetic CSV files | COVERED |
| `excel_parse` | 3 XLSX templates | COVERED |
| `excel_multi_sheet` | Mileage/health templates (if multi-sheet) | PARTIAL |
| `json_parse` | 2 synthetic JSON files | COVERED |
| `xml_parse` | -- | NOT COVERED |
| `markdown_parse` | 5 MD files (4 intake + 1 research) | COVERED |
| `plain_text_parse` | 2 TXT files | COVERED |
| `html_parse` | -- | NOT COVERED |
| `financial_table_interpret` | Bank statement CSV, brokerage guides | COVERED |
| `form_layout_understand` | IRS blanks, interactive W-2, filled returns | COVERED |
| `cross_reference` | Multi-document persona packets | COVERED |
| `date_normalization` | CSV dates, intake notes dates | COVERED |
| `currency_normalization` | Throughout corpus | COVERED |

**Coverage: 14/18 skills covered (78%).** Gaps are `image_ocr`, `image_handwriting_ocr`, `xml_parse`, and `html_parse`.

---

## 6. Google Drive Location

| Field | Value |
|-------|-------|
| **Folder name** | `understand_bench_v2_corpus` |
| **Folder ID** | `1du_RDmyErKaSPnGxPUib4283Io-MwvpH` |
| **Direct link** | https://drive.google.com/drive/folders/1du_RDmyErKaSPnGxPUib4283Io-MwvpH |

### Folder Structure

```
understand_bench_v2_corpus/
├── RESEARCH_FINDINGS.md
│
├── IRS_Training_Materials/           (7 files, ~92 MB total)
│   ├── IRS_Pub4491_VITA_Training.pdf
│   ├── IRS_Pub4491X_Supplement.pdf
│   ├── IRS_Form6744_VITA_Test.pdf
│   ├── IRS_Pub5379_VITA_Cert.pdf
│   ├── IRS_Pub4012_Volunteer_Guide.pdf
│   ├── IRS_VITA_Capital_Gains_Teaching.pdf
│   └── IRS_Form_13614C_Intake.pdf
│
├── IRS_Form_Blanks/                  (18 files)
│   ├── IRS_W2_blank.pdf
│   ├── IRS_1040_2025.pdf
│   ├── IRS_1099B_blank.pdf
│   ├── IRS_1099NEC_blank.pdf
│   ├── IRS_1099INT.pdf
│   ├── IRS_1099DIV.pdf
│   ├── IRS_1099R.pdf
│   ├── IRS_1098_blank.pdf
│   ├── IRS_1095A.pdf
│   ├── IRS_Schedule_A.pdf
│   ├── IRS_Schedule_C.pdf
│   ├── IRS_Schedule_D.pdf
│   ├── IRS_Schedule_E.pdf
│   ├── IRS_Form_8949.pdf
│   ├── IRS_Form_8962.pdf
│   ├── IRS_Form_8880.pdf
│   ├── IRS_Form_2441.pdf
│   └── IRS_K1_1065.pdf
│
├── Sample_Completed_Returns/         (8 files)
│   ├── IRS_sample_1040A_filled.pdf
│   ├── EconEdLink_1040_answer_key.pdf
│   ├── SCHR_2020_1040_sample.pdf
│   ├── MontgomeryCollege_1040_2021.pdf
│   ├── ADP_Interactive_Sample_W2.pdf
│   ├── Enact_Schedule_E_Rental_Example.pdf
│   ├── RealTaxTools_Sample_1099NEC.pdf
│   └── Fresno_Example_Return.pdf
│
├── Drake_Practice_Returns/           (3 files)
│   ├── Drake_Practice_Return_1.pdf
│   ├── Drake_Practice_Return_2.pdf
│   └── Drake_Practice_Return_4.pdf
│
├── Brokerage_Statement_Guides/       (2 files)
│   ├── RaymondJames_Composite_1099_Guide.pdf
│   └── WellsFargo_1099_Statement_Guide.pdf
│
└── Financial_Templates/              (3 files)
    ├── sample_bank_statement.xlsx
    ├── mileage_log_template.xlsx
    └── Montana_Health_Expense.xlsx
```

---

*Generated 2026-03-22 as part of the understand_bench_v2 corpus build.*

---

## 7. V2 Procurement (2026-03-22, Gap-Filling Mission)

### Mission Summary

| Field | Value |
|-------|-------|
| **Date** | 2026-03-22 |
| **Purpose** | Fill format gaps identified in v1: IMAGE, HTML, OFX/XML, Word (.docx), plus new document types (state forms, crypto, HSA, FBAR, property tax) |
| **Method** | 5 parallel agent teams + synthetic image generation |
| **New files procured** | 96 files across 7 categories |
| **Total size** | ~50 MB |

### Image Documents (7 files) — NEW FORMAT CLASS

| # | Filename | Format | Size | Description |
|---|----------|--------|------|-------------|
| 1 | `synthetic_w2_scan_harrison_2025.jpg` | JPG | 153 KB | Synthetic scanned W-2 — DataPoint Systems, Austin TX, $87,450 wages |
| 2 | `synthetic_1099nec_scan_peterson_2025.jpg` | JPG | 99 KB | Synthetic scanned 1099-NEC — Bloom Events LLC, $12,400 nonemployee comp |
| 3 | `receipt_coffee_shop_2025.jpg` | JPG | 27 KB | Synthetic receipt — Bean & Brew Coffee, Austin TX |
| 4 | `receipt_office_supplies_2025.jpg` | JPG | 33 KB | Synthetic receipt — Office Depot, printer supplies |
| 5 | `receipt_gas_station_2025.jpg` | JPG | 27 KB | Synthetic receipt — Shell gas station |
| 6 | `receipt_restaurant_business_lunch_2025.jpg` | JPG | 29 KB | Synthetic receipt — Trattoria Sofia business lunch |
| 7 | `handwritten_client_notes_peterson.jpg` | JPG | 170 KB | Synthetic handwritten client meeting notes on legal pad |

### HTML Statements (5 files) — NEW FORMAT CLASS

| # | Filename | Format | Size | Description |
|---|----------|--------|------|-------------|
| 1 | `print_css_rocks_account_statement.html` | HTML | 13 KB | Account statement from print-css.rocks GitHub project |
| 2 | `chase_statement_dec2025.html` | HTML | 21 KB | Synthetic Chase bank statement — Sarah M. Thompson, Dec 2025 |
| 3 | `fidelity_account_summary_2025.html` | HTML | 19 KB | Synthetic Fidelity brokerage account summary — Robert J. Chen, 8-10 positions |
| 4 | `schwab_1099div_2025.html` | HTML | 24 KB | Synthetic Schwab 1099-DIV delivery — Maria L. Santos, multiple fund payers |
| 5 | `optum_hsa_statement_2025.html` | HTML | 25 KB | Synthetic Optum HSA annual statement — James K. Patel, contributions/distributions/investments |

### OFX/XML Data (26 files) — NEW FORMAT CLASS

| # | Filename | Format | Size | Description |
|---|----------|--------|------|-------------|
| 1 | `banking_js_sample.ofx` | OFX | 3.8 KB | banking.js test fixture — checking account transactions |
| 2 | `annacruz_sample.ofx` | OFX | 7.7 KB | GitHub gist — comprehensive OFX sample |
| 3 | `gist_jvz_sample.ofx` | OFX | 590 B | GitHub gist — minimal OFX sample |
| 4 | `gist_pferreira_sample.ofx` | OFX | 1.0 KB | GitHub gist — OFX credit card sample |
| 5 | `ofx_java_example.ofx` | OFX | 1.9 KB | Java OFX library test fixture |
| 6-26 | `ofxparse_fixtures/*.ofx` (21 files) | OFX | 53 KB total | ofxparse Python library test fixtures — checking, savings, investment, 401k, multi-account, Fidelity, Vanguard, TD Ameritrade, TIAA-CREF |

### Word Documents (22 files) — NEW FORMAT CLASS

| # | Filename | Format | Size | Description |
|---|----------|--------|------|-------------|
| 1 | `journal_accountancy_1040_engagement_letter.doc` | DOC | 54 KB | Journal of Accountancy 1040 engagement letter template |
| 2 | `cpa_com_engagement_letter_sut.docx` | DOCX | 249 KB | CPA.com engagement letter — sales & use tax |
| 3 | `gilsbar_engagement_letter_tax.docx` | DOCX | 45 KB | Gilsbar tax engagement letter template |
| 4 | `esign_tax_client_intake_form.docx` | DOCX | 57 KB | eSign tax client intake questionnaire |
| 5 | `esign_bookkeeping_intake_form.docx` | DOCX | 54 KB | eSign bookkeeping client intake form |
| 6 | `esign_accounting_engagement_letter.docx` | DOCX | 41 KB | eSign accounting engagement letter |
| 7 | `eforms_sample_engagement_letter.docx` | DOCX | 86 KB | eForms general engagement letter template |
| 8 | `eforms_accountant_bookkeeping_engagement_letter.docx` | DOCX | 66 KB | eForms accountant bookkeeping engagement letter |
| 9 | `lindgren_2023_engagement_letter.docx` | DOCX | 34 KB | Lindgren CPA 2023 engagement letter |
| 10 | `vmde_2024_tax_organizer_new_clients.docx` | DOCX | 86 KB | VMDE 2024 tax organizer for new clients |
| 11 | `documentero_tax_preparation_checklist.docx` | DOCX | 62 KB | Tax preparation checklist template |
| 12 | `aicpa_2023_audit_representation_engagement_letter.docx` | DOCX | 105 KB | AICPA IRS audit representation engagement letter |
| 13 | `aicpa_section_7216_sample_consent_forms.docx` | DOCX | 167 KB | AICPA Section 7216 disclosure/consent forms (4 samples) |
| 14 | `esign_financial_planner_intake_form.docx` | DOCX | 65 KB | eSign financial planner intake form |
| 15 | `naea_irc_7216_disclosure_consent.docx` | DOCX | 14 KB | NAEA IRC 7216 mandatory disclosure and consent |
| 16 | `documentero_expense_report.docx` | DOCX | 37 KB | Expense report for tax deduction tracking |
| 17 | `documentero_invoice_with_tax_breakdown.docx` | DOCX | 42 KB | Invoice template with tax breakdown |
| 18 | `documentero_mileage_log_reimbursement.docx` | DOCX | 45 KB | Mileage log for tax reimbursement |
| 19 | `documentero_profit_and_loss_statement.docx` | DOCX | 37 KB | P&L statement for tax reporting |
| 20 | `spidell_disengagement_letter.doc` | DOC | 24 KB | Client disengagement letter |
| 21 | `strategic_tax_group_examination_letter.doc` | DOC | 27 KB | Tax examination engagement letter |
| 22 | `techguruplus_payment_voucher.docx` | DOCX | 16 KB | Payment voucher template |

### State Tax Forms (4 files) — NEW CATEGORY

| # | Filename | Format | Size | Description |
|---|----------|--------|------|-------------|
| 1 | `CA_Form_540.pdf` | PDF | 235 KB | California Form 540 — Resident Income Tax Return |
| 2 | `NY_IT-201.pdf` | PDF | 724 KB | New York IT-201 — Resident Income Tax Return |
| 3 | `GA_Form_500_2025.pdf` | PDF | 2.2 MB | Georgia Form 500 — Individual Income Tax Return (2025) |
| 4 | `CO_DR0104.pdf` | PDF | 1.1 MB | Colorado DR 0104 — Individual Income Tax Return |

### New Document Types (21 files) — NEW CATEGORIES

| # | Filename | Format | Size | Description |
|---|----------|--------|------|-------------|
| 1 | `Form_1099-DA.pdf` | PDF | 625 KB | IRS Form 1099-DA — Digital Asset Proceeds (NEW for 2025) |
| 2 | `Form_8949_Crypto.pdf` | PDF | 129 KB | IRS Form 8949 — Sales and Dispositions of Capital Assets |
| 3 | `Sample_Crypto_Capital_Gains_Report.csv` | CSV | 1.6 KB | Synthetic crypto capital gains report (CoinTracker-style) |
| 4 | `Form_5498-SA.pdf` | PDF | 83 KB | IRS Form 5498-SA — HSA/Archer MSA Information |
| 5 | `Form_1098-E.pdf` | PDF | 482 KB | IRS Form 1098-E — Student Loan Interest Statement |
| 6 | `Form_1041.pdf` | PDF | 181 KB | IRS Form 1041 — U.S. Income Tax Return for Estates and Trusts |
| 7 | `Form_2555.pdf` | PDF | 156 KB | IRS Form 2555 — Foreign Earned Income |
| 8 | `Form_1040-ES.pdf` | PDF | 331 KB | IRS Form 1040-ES — Estimated Tax for Individuals |
| 9 | `FinCEN_Form_114_FBAR_Reference.pdf` | PDF | 260 KB | FinCEN Form 114 reference — FBAR |
| 10 | `FinCEN_Form_114a.pdf` | PDF | 541 KB | FinCEN Form 114a — Record of Authorization |
| 11 | `FBAR_EFiling_Instructions.pdf` | PDF | 1.1 MB | FBAR e-filing instructions |
| 12 | `FBAR_XML_Filing_Requirements.pdf` | PDF | 1.2 MB | FBAR XML filing requirements |
| 13 | `Schedule_D.pdf` | PDF | 98 KB | IRS Schedule D — Capital Gains and Losses |
| 14 | `CA_Assessment_Notices_Guide.pdf` | PDF | 129 KB | California property assessment notices guide |
| 15 | `MD_Property_Assessment_Notice_Sample.pdf` | PDF | 6.5 MB | Maryland property assessment notice sample |
| 16 | `MI_Understanding_Assessment_Notice.pdf` | PDF | 551 KB | Michigan understanding assessment notices |
| 17 | `MN_Property_Tax_Overview.pdf` | PDF | 661 KB | Minnesota property tax overview |
| 18 | `MN_Property_Tax_Statement_Instructions.pdf` | PDF | 970 KB | Minnesota property tax statement instructions |
| 19 | `SanJoaquin_CA_Tax_Bill_Sample_2025.pdf` | PDF | 253 KB | San Joaquin County CA tax bill sample |
| 20 | `TX_Property_Tax_Bill_Model.pdf` | PDF | 749 KB | Texas property tax bill model |
| 21 | `WI_Property_Tax_Bill_Sample.pdf` | PDF | 115 KB | Wisconsin property tax bill sample |
| 22 | `fidelity_brokerage_statement_2025.xlsx` | XLSX | 11 KB | Multi-sheet (5) Fidelity brokerage statement — Account Summary, Holdings, Transactions, Dividends & Interest, Realized Gains |

### Previously Identified v1 Backlog (10 files)

| # | Filename | Format | Size | Description |
|---|----------|--------|------|-------------|
| 1 | `Wisconsin_VITA_Training_Workbook_2024.pdf` | PDF | 18.2 MB | Wisconsin DOR VITA Training Workbook 2024 |
| 2 | `HRBlock_TKA_Case_Study_1.pdf` | PDF | 1.2 MB | H&R Block Tax Knowledge Assessment Case Study |
| 3 | `UPitt_Sample_W2.pdf` | PDF | 1.5 MB | University of Pittsburgh Sample W-2 |
| 4 | `Intuit_Tax_Prep_Guide.pdf` | PDF | 283 KB | Intuit Tax Preparation Guide |
| 5 | `Intuit_Tax_Level1_Guide.pdf` | PDF | 203 KB | Intuit Tax Level 1 Guide |
| 6 | `Kristels_Schedule_E_Worksheet.pdf` | PDF | 154 KB | Kristels Schedule E Rental Worksheet |
| 7 | `Kristels_Schedule_C_Worksheet.pdf` | PDF | 204 KB | Kristels Schedule C Business Worksheet |
| 8 | `CASHMD_Capital_Gains_Losses.pdf` | PDF | 2.2 MB | CASHMD Capital Gains & Losses Guide |
| 9 | `VITA_Resources_Practice_Scenarios.html` | HTML | 140 KB | VITA Resources practice scenarios page |
| 10 | `TaxSlayer_Practice_Returns.html` | HTML | 7 KB | TaxSlayer Pro practice returns page |

---

## 8. Updated Format Coverage Matrix (Post-V2)

| Format | V1 Count | V2 Count | Total | Coverage Status |
|--------|----------|----------|-------|----------------|
| **PDF** (text) | 39 | 36 | 75 | STRONG |
| **PDF** (fillable forms) | 18 + interactive W-2 | -- | 19 | STRONG |
| **CSV** | 6 (synthetic) | 1 | 7 | MODERATE |
| **JSON** | 2 (synthetic) | -- | 2 | MODERATE |
| **XLSX** | 3 | **1 multi-sheet** | **4** | **STRONG** |
| **Markdown** | 5 | -- | 5 | MODERATE |
| **TXT** | 2 | -- | 2 | LIGHT |
| **JPG/PNG** (images) | 0 | **7** | **7** | **NEW — COVERED** |
| **HTML** | 0 | **5** | **5** | **NEW — COVERED** |
| **OFX** (banking) | 0 | **26** | **26** | **NEW — COVERED** |
| **DOC/DOCX** (Word) | 0 | **22** | **22** | **NEW — COVERED** |

### Updated Skill Coverage

| Skill | V1 Status | V2 Status | Files |
|-------|-----------|-----------|-------|
| `image_ocr` | NOT COVERED | **COVERED** | 7 synthetic images (W-2, 1099-NEC, receipts) |
| `image_handwriting_ocr` | NOT COVERED | **COVERED** | 1 handwritten notes image |
| `html_parse` | NOT COVERED | **COVERED** | 2 HTML files (bank statement, print-css account) |
| `xml_parse` / `ofx_parse` | NOT COVERED | **COVERED** | 26 OFX files (banking, investment, 401k) |
| `docx_parse` | NOT COVERED | **COVERED** | 22 Word documents (engagement letters, intake forms, consent forms, checklists) |

**Coverage: 18/18 skills covered (100%).** All format gaps from v1 have been filled.

---

## 9. V2 Google Drive Folder Structure

```
understand_bench_v2_corpus/
├── (v1 folders — unchanged)
│
├── Image_Documents/               (7 files, ~538 KB)
│   ├── synthetic_w2_scan_harrison_2025.jpg
│   ├── synthetic_1099nec_scan_peterson_2025.jpg
│   ├── receipt_coffee_shop_2025.jpg
│   ├── receipt_office_supplies_2025.jpg
│   ├── receipt_gas_station_2025.jpg
│   ├── receipt_restaurant_business_lunch_2025.jpg
│   └── handwritten_client_notes_peterson.jpg
│
├── HTML_Statements/               (5 files, ~102 KB)
│   ├── print_css_rocks_account_statement.html
│   ├── chase_statement_dec2025.html
│   ├── fidelity_account_summary_2025.html
│   ├── schwab_1099div_2025.html
│   └── optum_hsa_statement_2025.html
│
├── OFX_XML_Data/                  (26 files, ~69 KB)
│   ├── banking_js_sample.ofx
│   ├── annacruz_sample.ofx
│   ├── gist_jvz_sample.ofx
│   ├── gist_pferreira_sample.ofx
│   ├── ofx_java_example.ofx
│   └── ofxparse_fixtures/ (21 files)
│
├── Word_Documents/                (22 files, ~1.4 MB)
│   ├── journal_accountancy_1040_engagement_letter.doc
│   ├── cpa_com_engagement_letter_sut.docx
│   ├── gilsbar_engagement_letter_tax.docx
│   ├── esign_tax_client_intake_form.docx
│   ├── esign_bookkeeping_intake_form.docx
│   ├── esign_financial_planner_intake_form.docx
│   ├── esign_accounting_engagement_letter.docx
│   ├── eforms_sample_engagement_letter.docx
│   ├── eforms_accountant_bookkeeping_engagement_letter.docx
│   ├── lindgren_2023_engagement_letter.docx
│   ├── vmde_2024_tax_organizer_new_clients.docx
│   ├── documentero_tax_preparation_checklist.docx
│   ├── aicpa_2023_audit_representation_engagement_letter.docx
│   ├── aicpa_section_7216_sample_consent_forms.docx
│   ├── naea_irc_7216_disclosure_consent.docx
│   ├── documentero_expense_report.docx
│   ├── documentero_invoice_with_tax_breakdown.docx
│   ├── documentero_mileage_log_reimbursement.docx
│   ├── documentero_profit_and_loss_statement.docx
│   ├── spidell_disengagement_letter.doc
│   ├── strategic_tax_group_examination_letter.doc
│   └── techguruplus_payment_voucher.docx
│
├── State_Tax_Forms/               (4 files, ~4.3 MB)
│   ├── CA_Form_540.pdf
│   ├── NY_IT-201.pdf
│   ├── GA_Form_500_2025.pdf
│   └── CO_DR0104.pdf
│
├── New_Document_Types/            (21 files, ~15.1 MB)
│   ├── Form_1099-DA.pdf
│   ├── Form_5498-SA.pdf
│   ├── Form_1098-E.pdf
│   ├── Form_1041.pdf
│   ├── Form_2555.pdf
│   ├── Form_1040-ES.pdf
│   ├── Form_8949_Crypto.pdf
│   ├── Schedule_D.pdf
│   ├── Sample_Crypto_Capital_Gains_Report.csv
│   ├── FinCEN_Form_114_FBAR_Reference.pdf
│   ├── FinCEN_Form_114a.pdf
│   ├── FBAR_EFiling_Instructions.pdf
│   ├── FBAR_XML_Filing_Requirements.pdf
│   ├── CA_Assessment_Notices_Guide.pdf
│   ├── MD_Property_Assessment_Notice_Sample.pdf
│   ├── MI_Understanding_Assessment_Notice.pdf
│   ├── MN_Property_Tax_Overview.pdf
│   ├── MN_Property_Tax_Statement_Instructions.pdf
│   ├── SanJoaquin_CA_Tax_Bill_Sample_2025.pdf
│   ├── TX_Property_Tax_Bill_Model.pdf
│   └── WI_Property_Tax_Bill_Sample.pdf
│
└── Previously_Identified/         (10 files, ~24 MB)
    ├── Wisconsin_VITA_Training_Workbook_2024.pdf
    ├── HRBlock_TKA_Case_Study_1.pdf
    ├── UPitt_Sample_W2.pdf
    ├── Intuit_Tax_Prep_Guide.pdf
    ├── Intuit_Tax_Level1_Guide.pdf
    ├── Kristels_Schedule_E_Worksheet.pdf
    ├── Kristels_Schedule_C_Worksheet.pdf
    ├── CASHMD_Capital_Gains_Losses.pdf
    ├── VITA_Resources_Practice_Scenarios.html
    └── TaxSlayer_Practice_Returns.html
```

---

*V2 gap-filling mission completed 2026-03-22. Total corpus now: 136 files (41 v1 GDrive + 14 synthetic local + 95 v2 new) across all major format classes.*
