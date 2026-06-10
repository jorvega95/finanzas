"""Modelos SQLAlchemy, un módulo por dominio (ver PLAN.md §3):

spaces.py, catalogs.py, transactions.py, cards.py, msi.py,
recurring.py, investments.py, budgets.py, reminders.py, imports.py
Importarlos aquí para que Alembic los detecte (autogenerate).
"""
from app.db.base import Base  # noqa: F401
