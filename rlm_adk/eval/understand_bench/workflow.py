"""Tax-preparation workflow decomposition (N2).

Provides TAX_WORKFLOW — the ordered list of WorkflowStep objects
representing the end-to-end tax-preparation-and-filing pipeline.
"""

from __future__ import annotations

from rlm_adk.eval.understand_bench.types import WorkflowStep

TAX_WORKFLOW: list[WorkflowStep] = [
    WorkflowStep(
        step_number=1,
        name="Gather Taxpayer Identity Information",
        description="Collect SSNs, DOBs, filing status, address for all household members.",
        dependencies=["SSNs", "DOBs", "filing status", "address"],
        potential_gaps=["CREDENTIAL (IP PIN)", "DOCUMENT (dependent SSNs)"],
        depends_on_steps=[],
    ),
    WorkflowStep(
        step_number=2,
        name="Inventory Income Sources",
        description="Catalog all W-2s, 1099s, K-1s, rental income records.",
        dependencies=["All W-2s", "1099s", "K-1s", "rental income records"],
        potential_gaps=["DOCUMENT (missing W-2)", "CROSS_DOMAIN_LINK (missing K-1)"],
        depends_on_steps=[],
    ),
    WorkflowStep(
        step_number=3,
        name="Identify Adjustments to Income",
        description="Student loan interest, IRA contributions, SE health insurance.",
        dependencies=["Student loan interest", "IRA contributions", "SE health insurance"],
        potential_gaps=["HISTORICAL_RECORD (prior-year IRA basis)"],
        depends_on_steps=[],
    ),
    WorkflowStep(
        step_number=4,
        name="Determine Deduction Strategy",
        description="Evaluate standard vs. itemized; mortgage interest, SALT, charitable.",
        dependencies=["Mortgage interest", "SALT", "charitable contributions"],
        potential_gaps=[
            "DOCUMENT (charitable receipt substantiation)",
            "HISTORICAL_RECORD (prior-year SALT refund)",
        ],
        depends_on_steps=[],
    ),
    WorkflowStep(
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
    ),
    WorkflowStep(
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
    ),
    WorkflowStep(
        step_number=7,
        name="Compute Tax Liability",
        description="Apply tax tables, AMT check, net investment income tax.",
        dependencies=["All above steps completed"],
        potential_gaps=["HISTORICAL_RECORD (AMT carryforward)"],
        depends_on_steps=[2, 3, 4, 5, 6],
    ),
    WorkflowStep(
        step_number=8,
        name="Apply Payments and Withholding",
        description="W-2 withholding, estimated payments, extension payments.",
        dependencies=["W-2 withholding", "estimated payments", "extension payments"],
        potential_gaps=[
            "THIRD_PARTY_RECORD (estimated payment ledger)",
            "THIRD_PARTY_RECORD (extension payment confirmation)",
        ],
        depends_on_steps=[],
    ),
    WorkflowStep(
        step_number=9,
        name="Prepare State Returns",
        description="State-specific rules, state-federal coupling, multi-state allocation.",
        dependencies=["Federal return data", "state-specific rules"],
        potential_gaps=[
            "REGULATORY_REFERENCE (state nexus rules)",
            "DOCUMENT (state withholding statements)",
        ],
        depends_on_steps=[7],
    ),
    WorkflowStep(
        step_number=10,
        name="Authenticate for E-File",
        description="Prior-year AGI or IP PIN for IRS identity verification.",
        dependencies=["Prior-year AGI or IP PIN"],
        potential_gaps=["CREDENTIAL (prior-year AGI)", "CREDENTIAL (IP PIN)"],
        depends_on_steps=[],
    ),
    WorkflowStep(
        step_number=11,
        name="Submit Returns",
        description="E-file federal and state returns, set up direct deposit.",
        dependencies=["All above steps", "bank routing info"],
        potential_gaps=["DOCUMENT (bank account verification)"],
        depends_on_steps=[7, 9, 10],
    ),
]
