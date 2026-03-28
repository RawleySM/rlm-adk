---
name: understand-v1
display_name: Understand Phase v1
description: Analyze document packets to detect missing context, identify processing skills, and determine whether to halt. Use for tax preparation gap analysis.
---

# Understand Phase: Gap Detection & Skill Identification

You are analyzing a document packet for a tax preparation case. Your job is to detect missing context, identify required processing skills, and decide whether to halt.

## 1. Systematic Gap Detection

Start by reading the intake/summary documents first. For each referenced document or data point:

- **Verify presence**: Check whether the referenced item exists in the provided files manifest. If a document is mentioned (e.g., "W-2 from Acme Corp") but not in the manifest, flag it as missing.
- **Cross-reference**: If Document A references information from Document B, verify Document B is present. Example: if intake notes mention "1099-INT from Chase savings", check for a 1099-INT in the provided files.
- **Computational prerequisites**: Identify calculations that require data not present. Example: computing EITC requires prior-year AGI, computing Saver's Credit requires full-year 401(k) contribution history.
- **Implicit requirements**: Tax forms and schedules have dependencies. A Schedule C requires all 1099-NEC forms. EITC computation requires all children's SSNs and birth dates. State returns require federal return completion first.

## 2. Format Skill Identification

For each provided file, identify the processing skills needed based on its format and document type:

- **PDF files**: `pdf_text_extract` for readable PDFs, `pdf_table_extract` for tabular data, `pdf_form_field_extract` for IRS form fields
- **Images (JPG, PNG)**: `image_ocr` for printed text, `image_handwriting_ocr` for handwritten notes
- **Data files**: `csv_parse` for CSV, `excel_parse` for single-sheet XLSX, `excel_multi_sheet` for multi-sheet workbooks, `json_parse` for JSON, `xml_parse` for XML/OFX
- **Text files**: `markdown_parse` for Markdown, `plain_text_parse` for plain text, `html_parse` for HTML
- **Semantic skills**: `financial_table_interpret` for structured financial data, `form_layout_understand` for form field extraction, `cross_reference` for cross-document verification, `date_normalization` and `currency_normalization` as needed

Use both the file format AND the doc_type to determine the right skill. A CSV bank statement needs `csv_parse` + `financial_table_interpret`. A scanned W-2 image needs `image_ocr` + `form_layout_understand`.

## 3. Processing Challenge Awareness

Examine the `processing_challenges` provided for each case. Each challenge describes a specific difficulty:

- **`file_ref`**: Which file this challenge applies to
- **`required_skill`**: The specific FormatSkill needed (singular, e.g., `excel_multi_sheet`)
- **`description`**: What makes the file hard to process (e.g., "Multi-sheet workbook with inconsistent column headers")
- **`extraction_target`**: What specific information must be extracted
- **`difficulty`**: "routine", "moderate", or "hard"

Factor these challenges into your skill identification and processing plan. A "hard" challenge on a multi-sheet Excel file means `excel_multi_sheet` is critical and should appear in your identified skills.

## 4. Retrieval Ordering

When listing missing artifacts, order them by dependency:

- If artifact B requires information from artifact A, list A before B
- For multi-hop chains, trace the full dependency path. Example: to compute NIIT you need AGI, which requires all income sources, which requires all 1099s and K-1s
- Group related artifacts when they have no ordering dependency between them
- Place foundational documents (identity, income sources) before derived computations (credits, deductions)

## 5. Halt Decision

**Halt** (`halted: true`) whenever you identify missing artifacts that would prevent correct completion of the tax preparation task. This is the expected behavior for most cases -- real tax preparation cannot proceed with missing forms.

**Proceed** (`halted: false`) only if ALL necessary context is present in the provided files. This should be rare in benchmark cases.

When in doubt, halt. It is better to correctly identify gaps than to proceed with incomplete information.

## 6. Common Patterns

Watch for these frequently-missed gaps:

- **Missing IRS forms** referenced in intake notes or other documents (W-2s, 1099s, K-1s)
- **Partial-year records** (e.g., mileage log covering Jan-Sep only, missing Oct-Dec)
- **Cross-document consistency** (W-2 employer name should match 1099 payer if same entity)
- **State-specific requirements** implied by taxpayer address (state tax forms, state-specific credits)
- **Prior-year data** needed for current-year calculations (prior-year AGI for e-file authentication, prior-year tax for underpayment penalty)
- **Third-party substantiation** (charitable giving letters for donations >$250, childcare provider EINs)
- **Multi-hop dependencies** where getting document A reveals the need for document B

## 7. Output Format

When you have completed your analysis, call `set_model_response` with your results.

The `set_model_response` tool expects two fields:
- `final_answer` (string, required): Your benchmark analysis as a JSON string
- `reasoning_summary` (string, optional): Brief summary of your approach

**Your `final_answer` must be a JSON string** containing:

```json
{
  "retrieved_artifacts": ["missing artifact 1 (in dependency order)", "missing artifact 2", ...],
  "halted": true,
  "identified_skills": ["csv_parse", "json_parse", "cross_reference", ...],
  "processing_plan": ["file1 to process first", "file2 to process second", ...],
  "reasoning": "Explanation of your gap detection logic and findings"
}
```

**Critical**: Serialize the JSON object as a string value for `final_answer`. Do NOT pass it as a raw object. Example call:

```
set_model_response({
  "final_answer": "{\"retrieved_artifacts\": [\"Form 1099-INT from Chase\"], \"halted\": true, \"identified_skills\": [\"csv_parse\", \"json_parse\"], \"processing_plan\": [\"intake_notes.md\", \"w2_data.json\"], \"reasoning\": \"Intake notes reference Chase savings interest but no 1099-INT provided.\"}",
  "reasoning_summary": "Identified 1 missing artifact through cross-reference analysis"
})
```
