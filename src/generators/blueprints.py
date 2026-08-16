"""
Product blueprints: one per supported niche (config/categories.yaml
subcategory ids). A blueprint defines *structural* differences between
products — which sheets exist, what each sheet computes, which features
are present — so that variation between products comes from Target
Customer -> Problem -> UX -> Layout, not from swapping colors.

XlsxGenerator and PdfGenerator consume blueprints; they never hardcode
niche-specific logic themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ColumnSpec:
    header: str
    width: float
    number_format: Optional[str] = None   # e.g. "#,##0.00", "mm/dd/yyyy", "0.0%"
    data_validation: Optional[dict] = None  # {"type": "list", "formula1": '"Rent,Groceries,..."'}


@dataclass
class SheetSpec:
    sheet_key: str            # e.g. "dashboard", "income", "expenses"
    title: str
    columns: list[ColumnSpec]
    starting_data_row: int = 2
    sample_rows: int = 6      # how many demo rows to seed (cleared/marked DEMO before packaging)
    freeze_panes: str = "A2"
    has_totals_row: bool = True
    conditional_formatting: list[str] = field(default_factory=list)  # rule ids, resolved by generator
    notes: str = ""


@dataclass
class ProductBlueprint:
    niche: str
    display_name: str
    sheets: list[SheetSpec]
    core_formulas: list[str]           # human-readable description, actual formulas built in generator
    default_target_customer: str
    default_features: list[str]


# --------------------------------------------------------------------------
# Blueprint registry
# --------------------------------------------------------------------------

def _monthly_budget_tracker() -> ProductBlueprint:
    return ProductBlueprint(
        niche="monthly_budget_tracker",
        display_name="Monthly Budget Tracker",
        default_target_customer="student_or_budget_beginner",
        default_features=[
            "monthly income vs expense summary",
            "category breakdown with percentages",
            "remaining balance calculation",
            "dropdown category selection",
        ],
        core_formulas=[
            "Remaining = Income - Expenses",
            "Category % = Category Total / Total Expenses",
        ],
        sheets=[
            SheetSpec(
                sheet_key="dashboard",
                title="Dashboard",
                columns=[
                    ColumnSpec("Metric", 28),
                    ColumnSpec("Value", 16, number_format="#,##0.00"),
                ],
                sample_rows=0,
                has_totals_row=False,
                notes="Summary pulled via formulas from Income/Expenses sheets.",
            ),
            SheetSpec(
                sheet_key="income",
                title="Income",
                columns=[
                    ColumnSpec("Date", 14, number_format="mm/dd/yyyy"),
                    ColumnSpec("Source", 22),
                    ColumnSpec("Amount", 14, number_format="#,##0.00"),
                ],
                sample_rows=4,
                conditional_formatting=["highlight_negative"],
            ),
            SheetSpec(
                sheet_key="expenses",
                title="Expenses",
                columns=[
                    ColumnSpec("Date", 14, number_format="mm/dd/yyyy"),
                    ColumnSpec(
                        "Category", 20,
                        data_validation={
                            "type": "list",
                            "formula1": '"Housing,Food,Transport,Utilities,Entertainment,Other"',
                        },
                    ),
                    ColumnSpec("Description", 26),
                    ColumnSpec("Amount", 14, number_format="#,##0.00"),
                ],
                sample_rows=8,
                conditional_formatting=["highlight_over_budget"],
            ),
            SheetSpec(
                sheet_key="instructions",
                title="Instructions",
                columns=[ColumnSpec("Instructions", 90)],
                sample_rows=0,
                has_totals_row=False,
                freeze_panes="A1",
            ),
        ],
    )


def _freelancer_finance_tracker() -> ProductBlueprint:
    return ProductBlueprint(
        niche="freelancer_finance_tracker",
        display_name="Freelancer Finance Tracker",
        default_target_customer="freelancer_or_independent_contractor",
        default_features=[
            "per-client income tracking",
            "quarterly estimated tax set-aside calculator",
            "business expense log with deductible flag",
            "invoice status tracker",
            "quarterly + annual summary dashboard",
        ],
        core_formulas=[
            "Net Income = Gross Income - Business Expenses",
            "Tax Set-Aside = Net Income * Tax Rate (editable)",
            "Outstanding = SUMIF(Invoice Status = 'Unpaid')",
        ],
        sheets=[
            SheetSpec(
                sheet_key="dashboard",
                title="Dashboard",
                columns=[
                    ColumnSpec("Metric", 30),
                    ColumnSpec("Q1", 14, number_format="#,##0.00"),
                    ColumnSpec("Q2", 14, number_format="#,##0.00"),
                    ColumnSpec("Q3", 14, number_format="#,##0.00"),
                    ColumnSpec("Q4", 14, number_format="#,##0.00"),
                    ColumnSpec("Annual", 14, number_format="#,##0.00"),
                ],
                sample_rows=0,
                has_totals_row=False,
            ),
            SheetSpec(
                sheet_key="client_income",
                title="Client Income",
                columns=[
                    ColumnSpec("Date", 14, number_format="mm/dd/yyyy"),
                    ColumnSpec("Client", 22),
                    ColumnSpec(
                        "Invoice Status", 16,
                        data_validation={"type": "list", "formula1": '"Paid,Unpaid,Overdue"'},
                    ),
                    ColumnSpec("Amount", 14, number_format="#,##0.00"),
                ],
                sample_rows=6,
                conditional_formatting=["highlight_overdue"],
            ),
            SheetSpec(
                sheet_key="business_expenses",
                title="Business Expenses",
                columns=[
                    ColumnSpec("Date", 14, number_format="mm/dd/yyyy"),
                    ColumnSpec(
                        "Category", 20,
                        data_validation={
                            "type": "list",
                            "formula1": '"Software,Equipment,Travel,Marketing,Office,Other"',
                        },
                    ),
                    ColumnSpec(
                        "Deductible", 12,
                        data_validation={"type": "list", "formula1": '"Yes,No"'},
                    ),
                    ColumnSpec("Amount", 14, number_format="#,##0.00"),
                ],
                sample_rows=6,
            ),
            SheetSpec(
                sheet_key="tax_setaside",
                title="Tax Set-Aside",
                columns=[
                    ColumnSpec("Quarter", 14),
                    ColumnSpec("Net Income", 16, number_format="#,##0.00"),
                    ColumnSpec("Tax Rate", 12, number_format="0.0%"),
                    ColumnSpec("Set-Aside Amount", 18, number_format="#,##0.00"),
                ],
                sample_rows=4,
                has_totals_row=True,
            ),
            SheetSpec(
                sheet_key="instructions",
                title="Instructions",
                columns=[ColumnSpec("Instructions", 90)],
                sample_rows=0,
                has_totals_row=False,
                freeze_panes="A1",
            ),
        ],
    )


def _debt_payoff_tracker() -> ProductBlueprint:
    return ProductBlueprint(
        niche="debt_payoff_tracker",
        display_name="Debt Payoff Tracker",
        default_target_customer="individual_paying_down_debt",
        default_features=[
            "multi-debt balance tracker",
            "snowball vs avalanche payoff order",
            "monthly payment log per debt",
            "payoff progress percentage",
        ],
        core_formulas=[
            "Remaining Balance = Starting Balance - SUM(Payments)",
            "Progress % = 1 - (Remaining Balance / Starting Balance)",
        ],
        sheets=[
            SheetSpec(
                sheet_key="dashboard",
                title="Dashboard",
                columns=[
                    ColumnSpec("Debt", 22),
                    ColumnSpec("Starting Balance", 16, number_format="#,##0.00"),
                    ColumnSpec("Remaining Balance", 16, number_format="#,##0.00"),
                    ColumnSpec("Progress %", 12, number_format="0.0%"),
                ],
                sample_rows=0,
                has_totals_row=False,
                conditional_formatting=["progress_bar"],
            ),
            SheetSpec(
                sheet_key="debts",
                title="Debts",
                columns=[
                    ColumnSpec("Debt Name", 22),
                    ColumnSpec(
                        "Type", 16,
                        data_validation={
                            "type": "list",
                            "formula1": '"Credit Card,Student Loan,Auto Loan,Personal Loan,Other"',
                        },
                    ),
                    ColumnSpec("Starting Balance", 16, number_format="#,##0.00"),
                    ColumnSpec("Interest Rate", 12, number_format="0.0%"),
                    ColumnSpec("Min Payment", 14, number_format="#,##0.00"),
                ],
                sample_rows=4,
                has_totals_row=False,
            ),
            SheetSpec(
                sheet_key="payment_log",
                title="Payment Log",
                columns=[
                    ColumnSpec("Date", 14, number_format="mm/dd/yyyy"),
                    ColumnSpec("Debt Name", 22),
                    ColumnSpec("Payment Amount", 16, number_format="#,##0.00"),
                ],
                sample_rows=6,
            ),
            SheetSpec(
                sheet_key="instructions",
                title="Instructions",
                columns=[ColumnSpec("Instructions", 90)],
                sample_rows=0,
                has_totals_row=False,
                freeze_panes="A1",
            ),
        ],
    )


_REGISTRY: dict[str, ProductBlueprint] = {
    "monthly_budget_tracker": _monthly_budget_tracker(),
    "freelancer_finance_tracker": _freelancer_finance_tracker(),
    "debt_payoff_tracker": _debt_payoff_tracker(),
}


def get_blueprint(niche: str) -> ProductBlueprint:
    if niche not in _REGISTRY:
        raise KeyError(
            f"No blueprint registered for niche '{niche}'. "
            f"Available: {sorted(_REGISTRY.keys())}. "
            f"Add a new _<niche>() function and register it to support more niches."
        )
    return _REGISTRY[niche]


def available_niches() -> list[str]:
    return sorted(_REGISTRY.keys())
