"""
Pure-Python financial calculations. These exist for two reasons:

1. So the Excel formulas we write (built as strings in xlsx_generator.py)
   can be verified against a known-correct reference implementation in
   tests/test_financial_formulas.py, without needing an Excel engine.
2. So the QC engine (Phase 2C) can independently recompute expected
   values from raw data and flag a workbook whose formulas produce a
   different answer.

No I/O, no openpyxl here — keep it trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass


def remaining_balance(income: float, expenses: float) -> float:
    """Monthly Budget Tracker core formula: Remaining = Income - Expenses."""
    return round(income - expenses, 2)


def category_percentage(category_total: float, total_expenses: float) -> float:
    """Category % = Category Total / Total Expenses. Returns 0.0 (not an
    error) when total_expenses is 0, since an empty budget has no
    meaningful percentage but must not raise or divide by zero."""
    if total_expenses == 0:
        return 0.0
    return round(category_total / total_expenses, 4)


def net_income(gross_income: float, business_expenses: float) -> float:
    """Freelancer Finance Tracker: Net Income = Gross Income - Business Expenses."""
    return round(gross_income - business_expenses, 2)


def tax_set_aside(net_income_value: float, tax_rate: float) -> float:
    """Freelancer Finance Tracker: Tax Set-Aside = Net Income * Tax Rate."""
    return round(net_income_value * tax_rate, 2)


def outstanding_invoices(amounts: list[float], statuses: list[str]) -> float:
    """Sum of amounts whose status is not 'Paid' (i.e. 'Unpaid' or 'Overdue')."""
    if len(amounts) != len(statuses):
        raise ValueError("amounts and statuses must be the same length")
    return round(sum(a for a, s in zip(amounts, statuses) if s != "Paid"), 2)


def debt_remaining_balance(starting_balance: float, payments: list[float]) -> float:
    """Debt Payoff Tracker: Remaining Balance = Starting Balance - SUM(Payments)."""
    remaining = starting_balance - sum(payments)
    return round(max(remaining, 0.0), 2)


def debt_progress_percentage(starting_balance: float, remaining_balance_value: float) -> float:
    """Progress % = 1 - (Remaining / Starting). Returns 0.0 if starting
    balance is 0 to avoid division by zero (a debt that never existed
    has no payoff progress)."""
    if starting_balance == 0:
        return 0.0
    progress = 1 - (remaining_balance_value / starting_balance)
    return round(max(0.0, min(1.0, progress)), 4)


@dataclass
class FormulaSpec:
    """A named Excel formula template paired with the pure-Python function
    that computes the same result, so tests can assert they agree."""
    name: str
    excel_template: str          # human-readable template, e.g. "={income}-{expenses}"
    description: str


# Named formula catalog referenced by xlsx_generator.py and by
# tests/test_financial_formulas.py, so both sides describe the same
# formulas by name instead of duplicating magic strings.
FORMULA_CATALOG: dict[str, FormulaSpec] = {
    "remaining_balance": FormulaSpec(
        name="remaining_balance",
        excel_template="=Income_Total-Expenses_Total",
        description="Remaining = Income - Expenses",
    ),
    "category_percentage": FormulaSpec(
        name="category_percentage",
        excel_template="=IF(Expenses_Total=0,0,{category_cell}/Expenses_Total)",
        description="Category % = Category Total / Total Expenses (0 if no expenses)",
    ),
    "net_income": FormulaSpec(
        name="net_income",
        excel_template="=Gross_Income-Business_Expenses_Total",
        description="Net Income = Gross Income - Business Expenses",
    ),
    "tax_set_aside": FormulaSpec(
        name="tax_set_aside",
        excel_template="={net_income_cell}*{tax_rate_cell}",
        description="Tax Set-Aside = Net Income * Tax Rate",
    ),
    "outstanding_invoices": FormulaSpec(
        name="outstanding_invoices",
        excel_template='=SUMIF(Invoice_Status_Range,"<>Paid",Invoice_Amount_Range)',
        description="Outstanding = SUM of amounts where status <> Paid",
    ),
    "debt_remaining_balance": FormulaSpec(
        name="debt_remaining_balance",
        excel_template="=MAX({starting_balance_cell}-SUM({payments_range}),0)",
        description="Remaining Balance = MAX(Starting - SUM(Payments), 0)",
    ),
    "debt_progress_percentage": FormulaSpec(
        name="debt_progress_percentage",
        excel_template="=IF({starting_balance_cell}=0,0,1-({remaining_cell}/{starting_balance_cell}))",
        description="Progress % = 1 - (Remaining / Starting), 0 if Starting is 0",
    ),
}
