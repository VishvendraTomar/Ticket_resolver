"""Defaults every new workspace starts with (PLAN §4.4). Editable per workspace."""

from __future__ import annotations

DEFAULT_TOPICS: list[tuple[str, str]] = [
    ("leave", "Annual leave"),
    ("sick_pay", "Sick leave and sick pay"),
    ("parental_leave", "Parental leave"),
    ("notice_period", "Notice periods"),
    ("payroll", "Payroll and pay dates"),
    ("expenses", "Expenses and reimbursements"),
    ("working_time", "Working time and overtime"),
    ("public_holidays", "Public holidays"),
    ("benefits", "Benefits"),
    ("remote_work", "Remote work"),
]
