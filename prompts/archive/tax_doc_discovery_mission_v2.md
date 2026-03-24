# Tax Document Discovery Mission v2
## Repeat procurement with gap-filling focus

---

## Preliminary Step: Review Existing Manifest

Before searching, read the procurement manifest from the first mission:

```
@rlm_adk/eval/understand_bench_v2/PROCUREMENT_MANIFEST.md
@rlm_adk/eval/understand_bench_v2/DISCOVERY_RETROSPECTIVE.md
```

These documents detail:
- **41 files already procured** (PDFs, CSVs, Excel, JSON, Markdown, TXT) stored in Google Drive folder `understand_bench_v2_corpus` (ID: `1du_RDmyErKaSPnGxPUib4283Io-MwvpH`)
- **50+ sources identified but not downloaded** (with URLs)
- **Format gaps**: IMAGE (JPG/PNG/HEIC), HTML, OFX/XML, Word (.docx), multi-sheet Excel
- **Content gaps**: No scanned/photographed forms, no state tax documents, no crypto/digital asset forms, no HSA/FSA statements

## Mission Objectives

### Objective 1: Fill Format Gaps (Priority)

Delegate **5 parallel agent teams**, each focused on a different format gap:

#### Agent 1: Image Documents (JPG/PNG)
Search for and download:
- [ ] **ICDAR 2019 SROIE scanned receipt dataset** — 1,000 real receipts with OCR ground truth. Try: Kaggle (https://www.kaggle.com/datasets/urbikn/sroie-datasetv2), HuggingFace (https://huggingface.co/datasets/Voxel51/scanned_receipts), or GitHub mirror
- [ ] **Sample scanned W-2 images** — Search for "scanned W-2 image example", "photographed W-2 form", university HR sample W-2 images
- [ ] **Receipt photo datasets** — Search HuggingFace for receipt OCR datasets, invoice image datasets
- [ ] **Handwritten notes images** — Search for handwritten financial notes, client notes images, IAM Handwriting Database subsets
- [ ] If downloads are blocked, use Chrome browser to navigate to sources and save files manually

#### Agent 2: HTML Financial Documents
Search for and download/create:
- [ ] **print-css.rocks account statement** — Clone from https://github.com/zopyx/print-css-rocks, extract the lesson-account-statement HTML
- [ ] **Sample HTML bank statements** — Search for Chase, Bank of America, Wells Fargo statement HTML templates or mockups
- [ ] **HTML brokerage account summaries** — Search for Fidelity, Schwab, Vanguard account summary HTML examples
- [ ] **HTML-format 1099 delivery** — Some brokerages deliver 1099s as HTML; search for examples
- [ ] **Online banking download pages** — Search for HTML export format documentation from major banks

#### Agent 3: OFX/XML and Structured Financial Data
Search for and download:
- [ ] **banking.js OFX test fixture** — https://github.com/euforic/banking.js/blob/master/test/fixtures/sample.ofx
- [ ] **ofxparse Python library fixtures** — https://github.com/jseutter/ofxparse (clone, extract test/fixtures/)
- [ ] **QFX/OFX sample files** — Search GitHub for "sample.ofx", "test.qfx", OFX banking data fixtures
- [ ] **IRS XML schemas** — Search for MeF (Modernized e-File) XML schema samples
- [ ] **XBRL financial reporting samples** — Search for individual tax XBRL examples
- [ ] **Plaid API sample responses** — Save JSON examples from https://plaid.com/docs/api/products/transactions/

#### Agent 4: Word Documents and Engagement Letters
Search for and download:
- [ ] **AICPA 1040 Engagement Letter** — https://www.aicpa-cima.com/resources/download/individual-tax-return-engagement-letter-form-1040
- [ ] **Journal of Accountancy Engagement Letter** — https://www.journalofaccountancy.com/wp-content/uploads/sites/3/2014/01/1040-engagement-letter-sample.doc
- [ ] **CPA.com Engagement Letter** — https://www.cpa.com/sites/cpa/files/media/engagement-letter-sample-for-sut.docx
- [ ] **Gilsbar Tax Engagement Letter** — https://www.gilsbar.com/sites/default/files/2024-01/Engagement-Letter-Template-Tax-(3).docx
- [ ] **Tax organizer questionnaires** — Search for downloadable .docx tax organizer/intake questionnaires from CPA firms
- [ ] **Client authorization forms** — Search for IRS Form 8821 (Tax Information Authorization) .docx templates

#### Agent 5: New Document Types Not in v1
Search for entirely new categories of tax documents:
- [ ] **State tax forms** — Search for filled/sample state income tax returns (CA 540, NY IT-201, GA 500, CO 104)
- [ ] **Crypto/Digital asset forms** — Search for Form 1099-DA samples, crypto tax reports from CoinTracker/TaxBit/Koinly
- [ ] **HSA/FSA statements** — Search for Form 5498-SA samples, HSA contribution statements
- [ ] **Student loan documents** — Search for 1098-E samples, PSLF certification forms
- [ ] **Property assessment records** — Search for county property tax assessment notices, home appraisal documents
- [ ] **Estate/Trust documents** — Search for Form 1041 samples, trust distribution statements
- [ ] **Foreign income forms** — Search for FBAR (FinCEN 114) samples, Form 2555 (Foreign Earned Income) examples
- [ ] **Estimated tax payment vouchers** — Search for Form 1040-ES samples with payment records

### Objective 2: Download Previously Identified Sources

Go back to the "Identified But Not Procured" section of the manifest and systematically download:
- [ ] VITA Resources Practice Scenarios — https://www.vitaresources.net/practice-scenarios.html
- [ ] TaxSlayer Pro Practice Returns — https://www.taxslayerpro.com/education/practice-tax-returns
- [ ] Wisconsin DOR VITA Training Workbook — https://www.revenue.wi.gov/Documents/2024-VITA-Training-Workbook.pdf
- [ ] H&R Block TKA Case Study — https://media.hrblock.com/media/KnowledgeDevelopment/Forms/Certification/2023_tka2ts_Case_Study_1_r3.pdf
- [ ] HalfPriceSoft filled 1099/1098 images — https://www.halfpricesoft.com/1099s_software/1099_sample_forms/
- [ ] University of Pittsburgh Sample W-2 — https://www.payroll.pitt.edu/sites/default/files/assets/Sample-W2.pdf
- [ ] Intuit Tax Prep Guide — https://digitalasset.intuit.com/render/content/dam/intuit/ic/en_us/intuit-academy/exam-resource-guides/tax-preparation-guide.pdf
- [ ] Intuit Tax Level 1 Guide — https://digitalasset.intuit.com/render/content/dam/intuit/ic/en_us/intuit-academy/exam-resource-guides/tax-level-1-guide.pdf
- [ ] Schedule E Rental Worksheet — https://www.kristels.com/docs/Kristels-SchEWorksheet.pdf
- [ ] Schedule C Worksheet — https://www.kristels.com/docs/Kristels-ScheduleC.pdf
- [ ] CASHMD Capital Gains Guide — https://cashmd.org/wp-content/uploads/7_Capital-Gains-Losses.pdf

### Objective 3: Generate Synthetic Image Corpus

If real image sources are blocked or insufficient, generate synthetic images:
- [ ] Use Python (Pillow/ReportLab) to render filled W-2 data onto a W-2 form template, save as JPG
- [ ] Create receipt-like images with vendor name, date, items, total — add realistic noise (rotation, shadow, blur)
- [ ] Render handwritten-style text using a handwriting font onto a note template, save as JPG
- [ ] Take the existing synthetic JSON/CSV data and render it into "photographed document" images with perspective distortion

### Objective 4: Organize and Upload

For all new documents:
1. Download to `/tmp/tax_docs_download_v2/`
2. Create new subfolders in Google Drive under `understand_bench_v2_corpus` (ID: `1du_RDmyErKaSPnGxPUib4283Io-MwvpH`):
   - `Image_Documents/` — receipt photos, scanned forms, handwritten notes
   - `HTML_Statements/` — bank/brokerage HTML exports
   - `OFX_XML_Data/` — OFX banking files, XML schemas
   - `Word_Documents/` — engagement letters, intake questionnaires
   - `State_Tax_Forms/` — state-specific returns and forms
   - `New_Document_Types/` — crypto, HSA, estate, foreign income
   - `Previously_Identified/` — downloads from v1 backlog
3. Upload using gdrive CLI: `.venv/bin/python -m scripts.gdrive_cli upload PATH --folder FOLDER_ID --json`
4. Update `PROCUREMENT_MANIFEST.md` with all new entries

### Objective 5: Accountant Reference & Instructional Corpus (Unlimited)

Build a comprehensive library of tax tutorial, workflow, and instructional materials written for practicing accountants and tax preparers. These documents are **not** included in the benchmark corpus (i.e., not input to the agent-under-eval). Instead they serve as **retrieval-order ground truth** — they define what a "complete" context set looks like for a given tax scenario, which in turn defines what the expected `retrieval_order` output should be.

**Guiding principle:** Cast the widest possible net. There is no upper bound on the number of documents in this category. More coverage = better-defined retrieval targets.

Upload all materials to a new Google Drive folder: `Accountant_Reference_Library/` under `understand_bench_v2_corpus`.

#### 5a: IRS Publications & Official Guidance
- [ ] **Publication 17** (Your Federal Income Tax) — the 300+ page comprehensive individual tax guide
- [ ] **Publication 334** (Tax Guide for Small Business)
- [ ] **Publication 535** (Business Expenses)
- [ ] **Publication 550** (Investment Income and Expenses)
- [ ] **Publication 551** (Basis of Assets)
- [ ] **Publication 559** (Survivors, Executors, and Administrators)
- [ ] **Publication 590-A/B** (IRAs — Contributions / Distributions)
- [ ] **Publication 946** (How to Depreciate Property — MACRS tables)
- [ ] **Publication 523** (Selling Your Home)
- [ ] **Publication 936** (Home Mortgage Interest Deduction)
- [ ] **Publication 970** (Tax Benefits for Education)
- [ ] **Publication 502/503** (Medical/Dental Expenses, Child and Dependent Care)
- [ ] **Instructions for every form referenced in benchmark cases** — 1040, Schedules A/B/C/D/E/SE, 1099 series, W-2, 8949, 4562, 8829, etc.
- [ ] **IRS Fact Sheets and News Releases** for the current tax year — search irs.gov/newsroom
- [ ] **Revenue Procedures and Revenue Rulings** relevant to common individual scenarios (standard mileage rates, safe harbor elections, etc.)

#### 5b: AICPA, NASBA & Professional Body Resources
- [ ] **AICPA Tax Section practice guides** — search aicpa-cima.com for individual tax practice aids
- [ ] **AICPA Statements on Standards for Tax Services (SSTS)** — all 7 statements
- [ ] **Circular 230** (Regulations Governing Practice before the IRS) — full text
- [ ] **AICPA Tax Practice Responsibilities Committee guidance**
- [ ] **State CPA society tax preparation checklists** — search for downloadable checklists from state societies (CA, NY, TX, FL, IL)
- [ ] **Enrolled Agent exam study guides** — search for EA exam Part 1 (Individuals) study materials

#### 5c: Tax Preparation Workflow Guides
- [ ] **VITA/TCE Volunteer Training** — IRS Publication 4012 (VITA/TCE Volunteer Resource Guide), Publication 4491 (VITA/TCE Training Guide), all Link & Learn Taxes modules
- [ ] **Drake Software workflow documentation** — search for Drake tax preparation workflow PDFs
- [ ] **Lacerte/ProConnect workflow guides** — search Intuit Accountants community for preparation workflow documentation
- [ ] **UltraTax CS workflow resources** — search Thomson Reuters tax & accounting workflow guides
- [ ] **Tax preparation quality review checklists** — search for peer review checklists, preparer review checklists, firm-level QC documents
- [ ] **Engagement-to-delivery workflow diagrams** — search for CPA firm tax season workflow templates, intake-to-filing process maps
- [ ] **Client communication templates** — organizer cover letters, missing-info request letters, extension notification letters, filing confirmation letters

#### 5d: Educational & Tutorial Content
- [ ] **IRS Understanding Taxes curriculum** — full lesson set from apps.irs.gov/app/understandingTaxes
- [ ] **VITA training scenarios with worked solutions** — all practice problems from Publication 4491-W and 4491-X
- [ ] **H&R Block Tax Knowledge Assessment study materials** — all publicly available TKA case studies and answer keys
- [ ] **Jackson Hewitt tax school materials** — search for publicly available training content
- [ ] **Becker CPA Review — REG section tax content** — search for sample chapters or practice questions
- [ ] **Gleim EA Review — Part 1** — search for sample content covering individual taxation
- [ ] **Surgent CPE tax update courses** — search for downloadable course materials, especially annual tax update summaries
- [ ] **Journal of Accountancy tax articles** — search journalofaccountancy.com for tax preparation best practices, common errors, recent changes
- [ ] **The Tax Adviser articles** — search thetaxadviser.com for practitioner-focused technical articles
- [ ] **Tax Notes and Tax Analysts summaries** — search for publicly accessible tax analysis content
- [ ] **University-level tax textbook supplements** — search for instructor resource PDFs from South-Western Federal Taxation, Pearson's Federal Taxation, McGraw-Hill's Taxation

#### 5e: Scenario-Specific Deep Dives
- [ ] **Multi-state filing guides** — search for CPA resources on part-year resident returns, reciprocity agreements, allocation/apportionment
- [ ] **Gig economy/1099-NEC guidance** — IRS gig economy tax center content, rideshare/delivery driver tax guides
- [ ] **Cryptocurrency taxation guides** — IRS Notice 2014-21, Rev. Rul. 2019-24, CPA-oriented crypto tax primers
- [ ] **Real estate professional status documentation** — material participation tests, hours log templates, case law summaries (Robison, Bailey)
- [ ] **Hobby loss rules (Section 183)** — IRS guidance, case law summaries, documentation best practices
- [ ] **Passive activity loss rules (Section 469)** — grouping elections, material participation tests, rental real estate professional exception
- [ ] **Net operating loss (NOL) carryback/carryforward** — current year rules, CARES Act changes, state conformity
- [ ] **Estimated tax penalty calculations** — safe harbor rules, annualized income installment method, Form 2210 walkthroughs
- [ ] **AMT calculation walkthroughs** — Form 6251 line-by-line tutorials, common AMT preference items
- [ ] **Retirement plan distribution rules** — RMD tables, early withdrawal exceptions, Roth conversion analysis, SECURE Act changes
- [ ] **Education credit/deduction decision trees** — AOTC vs. LLC vs. tuition deduction flowcharts, Coverdell/529 coordination
- [ ] **Charitable contribution substantiation** — contemporaneous written acknowledgment rules, qualified appraisal requirements, carryover rules
- [ ] **Casualty and theft loss rules** — federally declared disaster area requirements, Form 4684 walkthroughs
- [ ] **Divorce/separation tax implications** — alimony (pre/post-2019), property transfers, filing status changes, dependency exemption rules

#### 5f: Checklists, Decision Trees & Quick References
- [ ] **Tax bracket and rate tables** — current and prior 3 years, including capital gains rate schedules
- [ ] **Standard deduction and exemption amounts** — current and prior 3 years, including additional amounts for age/blindness
- [ ] **Filing status decision trees** — head of household qualification flowcharts, married filing separately analysis
- [ ] **Dependency tests quick reference** — qualifying child vs. qualifying relative, tie-breaker rules, support test worksheets
- [ ] **Above-the-line deduction checklists** — comprehensive list with phase-out ranges and documentation requirements
- [ ] **Itemized deduction checklists** — by schedule line, with substantiation requirements and common audit triggers
- [ ] **Due date calendars** — federal and state filing deadlines, extension deadlines, estimated payment dates
- [ ] **Penalty and interest rate tables** — underpayment rates, late filing/payment penalties, reasonable cause criteria

### Objective 6: Update Benchmark

After procurement:
1. Copy relevant new files into `rlm_adk/eval/understand_bench_v2/corpus/real_docs/`
2. Create new benchmark cases that exercise the newly-covered format skills:
   - A case with scanned/photographed W-2 (IMAGE_OCR + FORM_LAYOUT_UNDERSTAND)
   - A case with HTML bank statement + OFX export (HTML_PARSE + XML_PARSE)
   - A case with multi-sheet Excel brokerage statement (EXCEL_MULTI_SHEET + FINANCIAL_TABLE_INTERPRET)
   - A case with .docx engagement letter + handwritten notes (IMAGE_HANDWRITING_OCR)
3. Update `PROCUREMENT_MANIFEST.md` and `DISCOVERY_RETROSPECTIVE.md`
4. Re-run benchmark: `.venv/bin/python -m rlm_adk.eval.understand_bench_v2.runner`

## Success Criteria

- [ ] All 6 missing format classes have at least 2 real documents each
- [ ] At least 20 new files uploaded to Google Drive
- [ ] `PROCUREMENT_MANIFEST.md` updated with all new entries
- [ ] At least 1 new benchmark case exercising image OCR skills
- [ ] Benchmark runner passes with all cases loading cleanly
- [ ] `Accountant_Reference_Library/` folder created in Google Drive with subcategories matching 5a–5f
- [ ] At least 50 reference/instructional documents procured across the 5a–5f categories
- [ ] Reference corpus is clearly separated from benchmark corpus (not in `corpus/real_docs/`)
- [ ] Retrieval-order ground truth annotations started: for each benchmark case, a ranked list of reference documents that would constitute a "complete" context set
