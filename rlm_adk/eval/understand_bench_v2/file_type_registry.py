"""Populated file type registry for v2 benchmark documents.

Extends v1 registry with format-specific skill mappings and
multi-format support reflecting real-world document diversity.
"""

from __future__ import annotations

from rlm_adk.eval.understand_bench_v2.types import FormatSkill

# ---------------------------------------------------------------------------
# Format → required skills mapping
# ---------------------------------------------------------------------------

FORMAT_SKILLS: dict[str, list[FormatSkill]] = {
    "pdf": [FormatSkill.PDF_TEXT_EXTRACT],
    "pdf_form": [FormatSkill.PDF_TEXT_EXTRACT, FormatSkill.PDF_FORM_FIELD_EXTRACT],
    "pdf_table": [FormatSkill.PDF_TEXT_EXTRACT, FormatSkill.PDF_TABLE_EXTRACT],
    "pdf_scanned": [FormatSkill.IMAGE_OCR, FormatSkill.PDF_TEXT_EXTRACT],
    "csv": [FormatSkill.CSV_PARSE],
    "xlsx": [FormatSkill.EXCEL_PARSE],
    "xlsx_multi": [FormatSkill.EXCEL_PARSE, FormatSkill.EXCEL_MULTI_SHEET],
    "json": [FormatSkill.JSON_PARSE],
    "xml": [FormatSkill.XML_PARSE],
    "txt": [FormatSkill.PLAIN_TEXT_PARSE],
    "md": [FormatSkill.MARKDOWN_PARSE],
    "html": [FormatSkill.HTML_PARSE],
    "png": [FormatSkill.IMAGE_OCR],
    "jpg": [FormatSkill.IMAGE_OCR],
    "jpeg": [FormatSkill.IMAGE_OCR],
    "heic": [FormatSkill.IMAGE_OCR],
    "tiff": [FormatSkill.IMAGE_OCR],
}

# ---------------------------------------------------------------------------
# Document type definitions with typical formats found in the wild
# ---------------------------------------------------------------------------

DOC_TYPE_FORMATS: dict[str, dict] = {
    # IRS Forms — typically PDFs or structured data
    "w2": {
        "display_name": "W-2 (Wage and Tax Statement)",
        "typical_formats": ["pdf", "pdf_form", "json", "jpg"],
        "key_fields": [
            "employer_name",
            "employer_ein",
            "wages",
            "federal_withheld",
            "ss_wages",
            "ss_withheld",
            "medicare_wages",
            "medicare_withheld",
            "state",
            "state_wages",
            "state_withheld",
        ],
        "skills_by_format": {
            "pdf": [FormatSkill.PDF_FORM_FIELD_EXTRACT, FormatSkill.FORM_LAYOUT_UNDERSTAND],
            "jpg": [FormatSkill.IMAGE_OCR, FormatSkill.FORM_LAYOUT_UNDERSTAND],
            "json": [FormatSkill.JSON_PARSE],
        },
    },
    "1099_int": {
        "display_name": "1099-INT (Interest Income)",
        "typical_formats": ["pdf", "pdf_form", "json"],
        "key_fields": [
            "payer_name",
            "interest_income",
            "early_withdrawal_penalty",
            "tax_exempt_interest",
        ],
        "skills_by_format": {
            "pdf": [FormatSkill.PDF_FORM_FIELD_EXTRACT],
            "json": [FormatSkill.JSON_PARSE],
        },
    },
    "1099_div": {
        "display_name": "1099-DIV (Dividends)",
        "typical_formats": ["pdf", "json"],
        "key_fields": [
            "payer_name",
            "ordinary_dividends",
            "qualified_dividends",
            "capital_gains_distributions",
        ],
        "skills_by_format": {
            "pdf": [FormatSkill.PDF_FORM_FIELD_EXTRACT],
            "json": [FormatSkill.JSON_PARSE],
        },
    },
    "1099_nec": {
        "display_name": "1099-NEC (Nonemployee Compensation)",
        "typical_formats": ["pdf", "json", "jpg"],
        "key_fields": ["payer_name", "nonemployee_compensation"],
        "skills_by_format": {
            "pdf": [FormatSkill.PDF_FORM_FIELD_EXTRACT],
            "jpg": [FormatSkill.IMAGE_OCR, FormatSkill.FORM_LAYOUT_UNDERSTAND],
            "json": [FormatSkill.JSON_PARSE],
        },
    },
    "1099_b": {
        "display_name": "1099-B (Broker Transactions)",
        "typical_formats": ["pdf", "csv", "xlsx"],
        "key_fields": ["broker_name", "proceeds", "cost_basis", "gain_loss", "holding_period"],
        "skills_by_format": {
            "pdf": [FormatSkill.PDF_TABLE_EXTRACT, FormatSkill.FINANCIAL_TABLE_INTERPRET],
            "csv": [FormatSkill.CSV_PARSE, FormatSkill.FINANCIAL_TABLE_INTERPRET],
            "xlsx": [FormatSkill.EXCEL_PARSE, FormatSkill.FINANCIAL_TABLE_INTERPRET],
        },
    },
    "1099_r": {
        "display_name": "1099-R (Retirement Distributions)",
        "typical_formats": ["pdf", "json"],
        "key_fields": ["payer_name", "gross_distribution", "taxable_amount", "distribution_code"],
        "skills_by_format": {
            "pdf": [FormatSkill.PDF_FORM_FIELD_EXTRACT],
            "json": [FormatSkill.JSON_PARSE],
        },
    },
    "k1": {
        "display_name": "K-1 (Partner/S-Corp/Trust)",
        "typical_formats": ["pdf"],
        "key_fields": ["entity_name", "entity_ein", "ordinary_income", "rental_income", "qbi"],
        "skills_by_format": {
            "pdf": [FormatSkill.PDF_FORM_FIELD_EXTRACT, FormatSkill.PDF_TABLE_EXTRACT],
        },
    },
    "1098": {
        "display_name": "1098 (Mortgage Interest)",
        "typical_formats": ["pdf", "json"],
        "key_fields": ["lender_name", "mortgage_interest_received", "points_paid", "property_tax"],
        "skills_by_format": {
            "pdf": [FormatSkill.PDF_FORM_FIELD_EXTRACT],
            "json": [FormatSkill.JSON_PARSE],
        },
    },
    "1095_a": {
        "display_name": "1095-A (Marketplace Insurance)",
        "typical_formats": ["pdf"],
        "key_fields": ["monthly_premium", "monthly_slcsp", "monthly_aptc"],
        "skills_by_format": {
            "pdf": [FormatSkill.PDF_TABLE_EXTRACT, FormatSkill.FORM_LAYOUT_UNDERSTAND],
        },
    },
    # Third-party documents — wide format diversity
    "bank_statement": {
        "display_name": "Bank Statement",
        "typical_formats": ["pdf", "csv", "html"],
        "key_fields": ["account_number", "period", "deposits", "withdrawals", "ending_balance"],
        "skills_by_format": {
            "pdf": [FormatSkill.PDF_TABLE_EXTRACT, FormatSkill.FINANCIAL_TABLE_INTERPRET],
            "csv": [
                FormatSkill.CSV_PARSE,
                FormatSkill.DATE_NORMALIZATION,
                FormatSkill.CURRENCY_NORMALIZATION,
            ],
            "html": [FormatSkill.HTML_PARSE, FormatSkill.FINANCIAL_TABLE_INTERPRET],
        },
    },
    "brokerage_statement": {
        "display_name": "Brokerage Statement",
        "typical_formats": ["pdf", "csv", "xlsx"],
        "key_fields": [
            "account_number",
            "positions",
            "transactions",
            "realized_gains",
            "unrealized_gains",
        ],
        "skills_by_format": {
            "pdf": [FormatSkill.PDF_TABLE_EXTRACT, FormatSkill.FINANCIAL_TABLE_INTERPRET],
            "csv": [FormatSkill.CSV_PARSE, FormatSkill.FINANCIAL_TABLE_INTERPRET],
            "xlsx": [
                FormatSkill.EXCEL_PARSE,
                FormatSkill.EXCEL_MULTI_SHEET,
                FormatSkill.FINANCIAL_TABLE_INTERPRET,
            ],
        },
    },
    "property_tax_bill": {
        "display_name": "Property Tax Bill",
        "typical_formats": ["pdf", "jpg", "png"],
        "key_fields": ["parcel_number", "assessed_value", "tax_amount", "payment_due"],
        "skills_by_format": {
            "pdf": [FormatSkill.PDF_TEXT_EXTRACT],
            "jpg": [FormatSkill.IMAGE_OCR],
            "png": [FormatSkill.IMAGE_OCR],
        },
    },
    "charitable_receipt": {
        "display_name": "Charitable Donation Receipt",
        "typical_formats": ["pdf", "jpg", "png", "txt"],
        "key_fields": ["organization_name", "donation_date", "amount", "ein"],
        "skills_by_format": {
            "pdf": [FormatSkill.PDF_TEXT_EXTRACT],
            "jpg": [FormatSkill.IMAGE_OCR],
            "txt": [FormatSkill.PLAIN_TEXT_PARSE],
        },
    },
    "medical_expense_summary": {
        "display_name": "Medical Expense Summary",
        "typical_formats": ["xlsx", "csv", "pdf"],
        "key_fields": ["provider", "date", "amount_billed", "amount_paid", "insurance_paid"],
        "skills_by_format": {
            "xlsx": [FormatSkill.EXCEL_PARSE, FormatSkill.FINANCIAL_TABLE_INTERPRET],
            "csv": [FormatSkill.CSV_PARSE, FormatSkill.CURRENCY_NORMALIZATION],
            "pdf": [FormatSkill.PDF_TABLE_EXTRACT],
        },
    },
    "childcare_receipt": {
        "display_name": "Childcare Provider Receipt",
        "typical_formats": ["pdf", "jpg", "txt"],
        "key_fields": ["provider_name", "provider_ein", "amount_paid", "child_name"],
        "skills_by_format": {
            "pdf": [FormatSkill.PDF_TEXT_EXTRACT],
            "jpg": [FormatSkill.IMAGE_OCR],
            "txt": [FormatSkill.PLAIN_TEXT_PARSE],
        },
    },
    # User-generated documents — most format-diverse
    "mileage_log": {
        "display_name": "Mileage Log",
        "typical_formats": ["xlsx", "csv", "jpg", "txt"],
        "key_fields": ["date", "destination", "purpose", "miles"],
        "skills_by_format": {
            "xlsx": [FormatSkill.EXCEL_PARSE, FormatSkill.DATE_NORMALIZATION],
            "csv": [FormatSkill.CSV_PARSE, FormatSkill.DATE_NORMALIZATION],
            "jpg": [FormatSkill.IMAGE_HANDWRITING_OCR],
            "txt": [FormatSkill.PLAIN_TEXT_PARSE],
        },
    },
    "home_office_measurements": {
        "display_name": "Home Office Measurements",
        "typical_formats": ["txt", "jpg", "xlsx"],
        "key_fields": ["total_sqft", "office_sqft", "percentage"],
        "skills_by_format": {
            "txt": [FormatSkill.PLAIN_TEXT_PARSE],
            "jpg": [FormatSkill.IMAGE_HANDWRITING_OCR],
            "xlsx": [FormatSkill.EXCEL_PARSE],
        },
    },
    "intake_questionnaire": {
        "display_name": "Intake Questionnaire",
        "typical_formats": ["md", "txt", "pdf"],
        "key_fields": ["filing_status", "dependents", "income_sources", "deductions"],
        "skills_by_format": {
            "md": [FormatSkill.MARKDOWN_PARSE],
            "txt": [FormatSkill.PLAIN_TEXT_PARSE],
            "pdf": [FormatSkill.PDF_TEXT_EXTRACT],
        },
    },
    "prior_year_return": {
        "display_name": "Prior-Year Tax Return",
        "typical_formats": ["pdf", "json"],
        "key_fields": ["agi", "filing_status", "tax_liability", "refund", "carryforwards"],
        "skills_by_format": {
            "pdf": [FormatSkill.PDF_FORM_FIELD_EXTRACT, FormatSkill.PDF_TABLE_EXTRACT],
            "json": [FormatSkill.JSON_PARSE],
        },
    },
    "email_correspondence": {
        "display_name": "Email Thread with Client",
        "typical_formats": ["txt", "html", "md"],
        "key_fields": [],
        "skills_by_format": {
            "txt": [FormatSkill.PLAIN_TEXT_PARSE],
            "html": [FormatSkill.HTML_PARSE],
            "md": [FormatSkill.MARKDOWN_PARSE],
        },
    },
    "handwritten_notes": {
        "display_name": "Handwritten Client Notes",
        "typical_formats": ["jpg", "png", "heic"],
        "key_fields": [],
        "skills_by_format": {
            "jpg": [FormatSkill.IMAGE_HANDWRITING_OCR],
            "png": [FormatSkill.IMAGE_HANDWRITING_OCR],
            "heic": [FormatSkill.IMAGE_HANDWRITING_OCR],
        },
    },
    "receipt_photo": {
        "display_name": "Receipt Photo",
        "typical_formats": ["jpg", "png", "heic"],
        "key_fields": ["vendor", "date", "amount", "items"],
        "skills_by_format": {
            "jpg": [FormatSkill.IMAGE_OCR],
            "png": [FormatSkill.IMAGE_OCR],
            "heic": [FormatSkill.IMAGE_OCR],
        },
    },
}


def get_skills_for_file(doc_type: str, fmt: str) -> list[FormatSkill]:
    """Return the processing skills needed for a given doc_type + format combination."""
    entry = DOC_TYPE_FORMATS.get(doc_type)
    if entry is None:
        return FORMAT_SKILLS.get(fmt, [])
    skills = entry.get("skills_by_format", {}).get(fmt)
    if skills is not None:
        return list(skills)
    return FORMAT_SKILLS.get(fmt, [])
