"""Pydantic schemas for catalogs (CAT-01..CAT-08)."""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.catalogs import AccountBehavior, CategoryKind, ExpenseNature


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: CategoryKind
    expense_nature: ExpenseNature | None
    parent_id: uuid.UUID | None
    icon: str | None
    color: str | None
    is_active: bool


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: CategoryKind = CategoryKind.expense
    expense_nature: ExpenseNature | None = None
    parent_id: uuid.UUID | None = None
    icon: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=20)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    expense_nature: ExpenseNature | None = None
    icon: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=20)
    is_active: bool | None = None


# --- Account types (CAT-08) -----------------------------------------------------


class AccountTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    behavior: AccountBehavior
    icon: str | None
    color: str | None
    is_system: bool
    is_active: bool


class AccountTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    behavior: AccountBehavior
    icon: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=20)


class AccountTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    icon: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=20)
    is_active: bool | None = None
