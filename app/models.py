"""Pydantic request models for HSFOODS."""
from __future__ import annotations

from pydantic import BaseModel


class ProductCreate(BaseModel):
    name: str
    price: float
    unit: str = "kg"
    stock: float = 0
    emoji: str = "🍎"
    category: str = "Daily"
    cost: float | None = None


class ProductUpdate(BaseModel):
    name: str | None = None
    price: float | None = None
    unit: str | None = None
    stock: float | None = None
    emoji: str | None = None
    category: str | None = None
    active: bool | None = None
    # item-wise referral rule
    cost: float | None = None
    ref_bonus_type: str | None = None      # 'percent' | 'flat'
    ref_bonus_value: float | None = None
    ref_cap: float | None = None
    # item-wise loyalty cashback rule
    loyalty_bonus_type: str | None = None  # 'percent' | 'flat'
    loyalty_bonus_value: float | None = None


class OrderItemIn(BaseModel):
    productId: str
    qty: float = 1


class OrderCreate(BaseModel):
    phone: str = "walk-in"
    name: str = "Walk-in"
    items: list[OrderItemIn] = []


class OrderUpdate(BaseModel):
    status: str | None = None
    payment_status: str | None = None   # pending | paid


class SimulateIn(BaseModel):
    phone: str
    message: str


class LedgerAction(BaseModel):
    status: str   # approved | reversed | provisional | review


class AssistantIn(BaseModel):
    question: str
