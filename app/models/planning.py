from typing import Optional
from datetime import datetime, date
from sqlmodel import SQLModel, Field


class PlanRun(SQLModel, table=True):
    run_id: str = Field(primary_key=True)
    scenario: str
    base_run_id: Optional[str] = Field(default=None, foreign_key="planrun.run_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProductPlan(SQLModel, table=True):
    plan_id: str = Field(primary_key=True)
    run_id: str = Field(foreign_key="planrun.run_id")
    plan_date: date
    status: str = "PLANNED"


class PlanItem(SQLModel, table=True):
    item_id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: str = Field(foreign_key="productplan.plan_id")
    line_id: str = Field(foreign_key="line.line_id")
    product_id: str = Field(foreign_key="product.product_id")
    planned_qty: int
    start_ts: datetime
    end_ts: datetime
    status: str = "PLANNED"
    changeover_loss_min: int = 0


class Event(SQLModel, table=True):
    event_id: str = Field(primary_key=True)
    event_type: str
    description: str
    event_date: datetime
    metadata_json: Optional[str] = None


class OrderAllocation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="planrun.run_id")
    plan_id: str = Field(foreign_key="productplan.plan_id")
    order_id: str = Field(foreign_key="order.order_id")
    line_id: str = Field(foreign_key="line.line_id")
    product_id: str = Field(foreign_key="product.product_id")
    allocated_qty: int
    plan_item_id: int = Field(foreign_key="planitem.item_id")


class MaterialSubstitution(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    material_id: str
    alt_material_id: str
    max_percent_substitution: float = 100.0
    priority: int = 1

class AIDecisionLog(SQLModel, table=True):
    """
    Stores AI recommendations produced for scenario / alert events.

    Fields:
        scenario_name:     logical name like "demand_spike", "chip_delay"
        run_id:            plan run to which this decision relates
        line_id:           scope of decision ("GLOBAL", line id, etc.)
        ts:                decision timestamp (UTC)
        alert_status:      compact label ("DemandSpike", "SupplyAlert", ...)
        ai_recommendation: top suggested action label from classifier
        predicted_kpi_impact_pct: expected delta in KPI, e.g. +4.2
        rule_ids_fired:    rule identifiers, e.g. "R1,R3" or "R_DEMAND_SPIKE"
        explanation:       human-readable justification string
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    scenario_name: str
    run_id: str = Field(foreign_key="planrun.run_id")
    line_id: str
    ts: datetime = Field(default_factory=datetime.utcnow)

    alert_status: str
    ai_recommendation: str
    predicted_kpi_impact_pct: float
    rule_ids_fired: str
    explanation: str


class AgentPendingAction(SQLModel, table=True):
    """
    DB-backed pending actions queue for multi-agent coordination.
    
    Agents propose actions by inserting rows with status=PENDING.
    Orchestrator reviews and marks as APPROVED/DEFERRED/ESCALATED.
    Approved actions are then executed and marked EXECUTED.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Source agent
    agent_name: str
    
    # Action details
    action_type: str          # CREATE_PO, SCHEDULE_MAINTENANCE, REPLAN, etc.
    priority: int = 3         # 1-5, where 5 is highest
    
    # Target resources (optional)
    line_id: Optional[str] = None
    material_id: Optional[str] = None
    order_id: Optional[str] = None
    
    # Additional parameters as JSON
    payload_json: Optional[str] = None
    
    # Status tracking
    status: str = "PENDING"   # PENDING, APPROVED, DEFERRED, EXECUTED, REJECTED, ESCALATED
    
    # Reasoning
    reason: str = ""
    llm_used: bool = False
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None  # "orchestrator" or "human"