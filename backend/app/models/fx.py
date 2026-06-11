"""Exchange rates. Implements FX-02 (daily Banxico FIX, carry-forward)."""

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExchangeRate(Base):
    """Rate to convert 1 unit of `base` into `quote` on `date`.

    Example: base=USD, quote=MXN, rate=18.50 (Banxico FIX, FX-02).
    """

    __tablename__ = "exchange_rates"

    base: Mapped[str] = mapped_column(String(3), primary_key=True)
    quote: Mapped[str] = mapped_column(String(3), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    # FX-02: non-business days persist the last published rate, flagged.
    is_carry_forward: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="banxico")
