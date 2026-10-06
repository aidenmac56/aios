"""Adapters that bring outside data in. Every adapter returns records; the core decides what to store.

Financial sources implement `FinancialSource.fetch()` and are imported through `import_from`, which
sends them down the same path as a CSV upload (`finance.ingest`): validation, de-duplication,
categorization, the audit log and events. An adapter never writes to the database itself, never
moves money, and never sees anything but read credentials.

Built: CSV files (`CsvSource`).
Not built (by design, until there is a need): Stripe payouts, bank feeds (e.g. Plaid), accounting
software (QuickBooks, Xero). Each would be a class with `name` and `fetch()` returning
`(records, rejected)`, reading its credentials from environment variables.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from sqlalchemy.orm import Session

from aios.core.actor import Actor
from aios.modules.finance import RawTransaction, ingest, parse_csv


class FinancialSource(Protocol):
    name: str

    def fetch(self) -> tuple[list[tuple[int, RawTransaction]], list[dict]]:
        """Return ([(position, record)], [rejected items with an 'error' and a 'line'/position])."""
        ...


class CsvSource:
    def __init__(self, path: str | Path | None = None, *, text: str | None = None, label: str | None = None,
                 amounts_negative_for_spend: bool = True):
        if (path is None) == (text is None):
            raise ValueError("give exactly one of path or text")
        self._text = Path(path).read_text() if path is not None else text
        self.name = label or (Path(path).name if path is not None else "csv")
        self._negative = amounts_negative_for_spend

    def fetch(self) -> tuple[list[tuple[int, RawTransaction]], list[dict]]:
        return parse_csv(self._text, amounts_negative_for_spend=self._negative)


def import_from(session: Session, actor: Actor, source: FinancialSource, *, account_name: str = "Primary") -> dict:
    records, rejected = source.fetch()
    return ingest(session, actor, records, source_label=source.name, account_name=account_name, errors=rejected)
