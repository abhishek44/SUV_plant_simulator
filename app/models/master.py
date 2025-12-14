from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import date

class Product(SQLModel, table=True):
    product_id: str = Field(primary_key=True)
    name: str


class Line(SQLModel, table=True):
    line_id: str = Field(primary_key=True)
    name: str
    product_id: str = Field(foreign_key="product.product_id")
    daily_capacity: int
    oee_pct: float = 0.9
    mtbf_hours: float = 100.0  # Mean Time Between Failures (hours)
    mttr_hours: float = 2.0     # Mean Time To Repair (hours)


class Shift(SQLModel, table=True):
    shift_id: str = Field(primary_key=True)
    shift_timing: str
    workers_assigned: int
    skill_level: str
    max_overtime_hrs: int
    labor_cost_per_hr: float


class Order(SQLModel, table=True):
    order_id: str = Field(primary_key=True)
    product_id: str = Field(foreign_key="product.product_id")
    quantity: int
    start_date: date
    dispatch_date: date
    status: str = "OPEN"  # OPEN, ON_HOLD, COMPLETED
    priority: int = 5  # 1=highest (spike), 5=default, 10=lowest
    is_spike: bool = False  # True for urgent spike orders


class BOMItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: str = Field(foreign_key="product.product_id")
    material_id: str = Field(foreign_key="inventoryitem.material_id")
    quantity_per_unit: int
