"""Tax-preparation workflow decomposition for v2.

Same workflow as v1 but annotated with format-processing skill
requirements at each step, reflecting the multi-format reality
of v2 benchmark cases.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from rlm_adk.eval.understand_bench_v2.types import FormatSkill


class WorkflowStepV2(BaseModel):
    """A single step in the tax-preparation workflow (v2)."""

    step_number: int
    name: str
    description: str = ""
    dependencies: list[str] = Field(default_factory=list)
    potential_gaps: list[str] = Field(default_factory=list)
    depends_on_steps: list[int] = Field(default_factory=list)
    typical_formats: list[str] = Field(
        default_factory=list,
        description="File formats commonly encountered at this step",
    )
    skills_needed: list[FormatSkill] = Field(
        default_factory=list,
        description="Processing skills typically needed at this step",
    )


TAX_WORKFLOW_V2: list[WorkflowStepV2] = [
    WorkflowStepV2(
        step_number=1,
        name="Gather Taxpayer Identity Information",
        description="Collect SSNs, DOBs, filing status, address for all household members.",
        dependencies=["SSNs", "DOBs", "filing status", "address"],
        potential_gaps=["CREDENTIAL (IP PIN)", "DOCUMENT (dependent SSNs)"],
        depends_on_steps=[],
        typical_formats=["md", "txt", "pdf"],
        skills_needed=[FormatSkill.MARKDOWN_PARSE, FormatSkill.PLAIN_TEXT_PARSE],
    ),
    WorkflowStepV2(
        step_number=2,
        name="Inventory Income Sources",
        description="Catalog all W-2s, 1099s, K-1s, rental income records.",
        dependencies=["All W-2s", "1099s", "K-1s", "rental income records"],
        potential_gaps=["DOCUMENT (missing W-2)", "CROSS_DOMAIN_LINK (missing K-1)"],
        depends_on_steps=[],
        typical_formats=["pdf", "json", "csv", "jpg"],
        skills_needed=[
            FormatSkill.PDF_FORM_FIELD_EXTRACT,
            FormatSkill.JSON_PARSE,
            FormatSkill.CSV_PARSE,
            FormatSkill.IMAGE_OCR,
            FormatSkill.FORM_LAYOUT_UNDERSTAND,
        ],
    ),
    WorkflowStepV2(
        step_number=3,
        name="Identify Adjustments to Income",
        description="Student loan interest, IRA contributions, SE health insurance.",
        dependencies=["Student loan interest", "IRA contributions", "SE health insurance"],
        potential_gaps=["HISTORICAL_RECORD (prior-year IRA basis)"],
        depends_on_steps=[],
        typical_formats=["pdf", "json"],
        skills_needed=[FormatSkill.PDF_FORM_FIELD_EXTRACT],
    ),
    WorkflowStepV2(
        step_number=4,
        name="Determine Deduction Strategy",
        description="Evaluate standard vs. itemized; mortgage interest, SALT, charitable.",
        dependencies=["Mortgage interest", "SALT", "charitable contributions"],
        potential_gaps=[
            "DOCUMENT (charitable receipt substantiation)",
            "HISTORICAL_RECORD (prior-year SALT refund)",
        ],
        depends_on_steps=[],
        typical_formats=["pdf", "jpg", "png", "xlsx", "csv"],
        skills_needed=[
            FormatSkill.PDF_TEXT_EXTRACT,
            FormatSkill.IMAGE_OCR,
            FormatSkill.EXCEL_PARSE,
            FormatSkill.CSV_PARSE,
            FormatSkill.CURRENCY_NORMALIZATION,
        ],
    ),
    WorkflowStepV2(
        step_number=5,
        name="Compute Credits",
        description="Child tax credit, EITC, education credits, APTC reconciliation.",
        dependencies=["Child tax credit eligibility", "EITC", "education credits", "APTC"],
        potential_gaps=[
            "DOCUMENT (1098-T)",
            "USER_ATTESTATION (dependent eligibility proof)",
            "DOCUMENT (1095-A)",
        ],
        depends_on_steps=[2],
        typical_formats=["pdf", "json"],
        skills_needed=[FormatSkill.PDF_FORM_FIELD_EXTRACT, FormatSkill.PDF_TABLE_EXTRACT],
    ),
    WorkflowStepV2(
        step_number=6,
        name="Handle Special Situations",
        description="Rental property, capital gains/losses, business income, QBI.",
        dependencies=["Rental property records", "capital gains/losses", "business income"],
        potential_gaps=[
            "HISTORICAL_RECORD (depreciation schedules)",
            "HISTORICAL_RECORD (cost basis records)",
            "CROSS_DOMAIN_LINK (QBI information)",
        ],
        depends_on_steps=[],
        typical_formats=["pdf", "csv", "xlsx"],
        skills_needed=[
            FormatSkill.PDF_TABLE_EXTRACT,
            FormatSkill.CSV_PARSE,
            FormatSkill.EXCEL_PARSE,
            FormatSkill.FINANCIAL_TABLE_INTERPRET,
        ],
    ),
    WorkflowStepV2(
        step_number=7,
        name="Compute Tax Liability",
        description="Apply tax tables, AMT check, net investment income tax.",
        dependencies=["All above steps completed"],
        potential_gaps=["HISTORICAL_RECORD (AMT carryforward)"],
        depends_on_steps=[2, 3, 4, 5, 6],
        typical_formats=["pdf", "json"],
        skills_needed=[FormatSkill.CROSS_REFERENCE],
    ),
    WorkflowStepV2(
        step_number=8,
        name="Apply Payments and Withholding",
        description="W-2 withholding, estimated payments, extension payments.",
        dependencies=["W-2 withholding", "estimated payments", "extension payments"],
        potential_gaps=[
            "THIRD_PARTY_RECORD (estimated payment ledger)",
            "THIRD_PARTY_RECORD (extension payment confirmation)",
        ],
        depends_on_steps=[],
        typical_formats=["pdf", "csv", "html"],
        skills_needed=[
            FormatSkill.PDF_TABLE_EXTRACT,
            FormatSkill.CSV_PARSE,
            FormatSkill.HTML_PARSE,
        ],
    ),
    WorkflowStepV2(
        step_number=9,
        name="Prepare State Returns",
        description="State-specific rules, state-federal coupling, multi-state allocation.",
        dependencies=["Federal return data", "state-specific rules"],
        potential_gaps=[
            "REGULATORY_REFERENCE (state nexus rules)",
            "DOCUMENT (state withholding statements)",
        ],
        depends_on_steps=[7],
        typical_formats=["pdf", "json"],
        skills_needed=[FormatSkill.PDF_TEXT_EXTRACT, FormatSkill.CROSS_REFERENCE],
    ),
    WorkflowStepV2(
        step_number=10,
        name="Authenticate for E-File",
        description="Prior-year AGI or IP PIN for IRS identity verification.",
        dependencies=["Prior-year AGI or IP PIN"],
        potential_gaps=["CREDENTIAL (prior-year AGI)", "CREDENTIAL (IP PIN)"],
        depends_on_steps=[],
        typical_formats=["pdf", "txt"],
        skills_needed=[FormatSkill.PDF_TEXT_EXTRACT],
    ),
    WorkflowStepV2(
        step_number=11,
        name="Submit Returns",
        description="E-file federal and state returns, set up direct deposit.",
        dependencies=["All above steps", "bank routing info"],
        potential_gaps=["DOCUMENT (bank account verification)"],
        depends_on_steps=[7, 9, 10],
        typical_formats=[],
        skills_needed=[],
    ),
]
