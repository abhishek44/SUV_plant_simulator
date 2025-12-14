from typing import Optional
from datetime import date
from sqlmodel import SQLModel, Field


class Supplier(SQLModel, table=True):
    supplier_id: str = Field(primary_key=True)
    supplier_name: str
    location: str
    lead_time_days: int
    reliability_pct: float
    alternate_supplier: str  # "Yes"/"No"


class InventoryItem(SQLModel, table=True):
    material_id: str = Field(primary_key=True)
    description: str
    category: str
    reorder_point: int
    safety_stock: int
    lead_time_days: int
    supplier_id: str = Field(foreign_key="supplier.supplier_id")
    current_stock: int
    unit_cost_inr: float


class PurchaseOrder(SQLModel, table=True):
    po_id: str = Field(primary_key=True)
    material_id: str = Field(foreign_key="inventoryitem.material_id")
    supplier_id: str = Field(foreign_key="supplier.supplier_id")
    quantity: int
    order_date: date
    eta_date: date
    status: str = "PLACED"  # PLACED -> DELIVERED
