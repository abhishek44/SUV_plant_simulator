from typing import Optional
from datetime import datetime, date
from sqlmodel import SQLModel, Field


class MachineParameter(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    machine_id: str
    line_id: str
    parameter: str
    threshold: float
    current_value: float
    oee_pct: float


class LineShiftProfile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="planrun.run_id")
    line_id: str = Field(foreign_key="line.line_id")
    shift_id: str = Field(foreign_key="shift.shift_id")
    product_id: str = Field(foreign_key="product.product_id")

    base_rate_units_per_hour: float
    base_defect_rate_pct: float
    base_uptime_pct: float
    base_worker_availability_pct: float
    base_energy_kwh_per_unit: float

    throughput_sigma_pct: float = 5.0
    uptime_sigma_pct: float = 2.0
    worker_avail_sigma_pct: float = 3.0
    defect_sigma_pct: float = 0.5
    energy_sigma_pct: float = 3.0


class ProductionRealtime(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="planrun.run_id")
    plan_id: Optional[str] = Field(default=None, foreign_key="productplan.plan_id")
    plan_item_id: Optional[int] = Field(default=None, foreign_key="planitem.item_id")

    ts: datetime

    assembly_line: str
    shift_id: str
    demand_suvs: int

    inventory_status_pct: float
    machine_uptime_pct: float
    worker_availability_pct: float

    production_output_cum: int
    defect_rate_pct: float
    energy_consumption_kwh_cum: float

    semiconductor_availability: str
    alert_status: str


class OrderProgress(SQLModel, table=True):
    """Tracks per-order production progress during simulation."""
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: str = Field(foreign_key="order.order_id")
    run_id: str = Field(foreign_key="planrun.run_id")
    ts: datetime
    completed_qty: int  # cumulative units completed for this order
    remaining_qty: int
    estimated_completion_date: Optional[date] = None  # projected completion based on current rate
