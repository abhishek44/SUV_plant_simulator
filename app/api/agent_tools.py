# app/api/agent_tools.py
"""
Agent API endpoints - MCP-exposed tools and agent control.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from typing import Optional
from pydantic import BaseModel

from ..database import get_session


router = APIRouter(prefix="/api/agent", tags=["agent"])


# ============ Request Models ============

class ReplanRequest(BaseModel):
    reason: str


class ExpeditePORequest(BaseModel):
    material_id: str
    urgency: str = "high"


class PriorityRequest(BaseModel):
    order_id: str
    new_priority: int
    reason: str


class AlertRequest(BaseModel):
    alert_type: str
    message: str
    severity: str = "medium"


# ============ Agent Control Endpoints ============

@router.get("/list")
def list_agents():
    """List all available agents."""
    from ..agents.agent_runner import list_available_agents
    return {"agents": list_available_agents()}


@router.get("/config")
def get_agent_config():
    """Get current agent configuration."""
    from ..agents.config import get_config
    config = get_config()
    return {
        "write_enabled": config.WRITE_ENABLED,
        "dry_run": not config.WRITE_ENABLED,
        "llm_enabled": config.LLM_ENABLED
    }


@router.post("/config/dry-run")
def set_dry_run_mode(enabled: bool = True):
    """
    Enable or disable dry-run mode.
    
    When dry_run=True, agents log decisions but don't modify data.
    """
    from ..agents.config import set_dry_run
    return set_dry_run(enabled)


@router.get("/pending-actions")
def get_pending_actions(
    status: str = "PENDING",
    session: Session = Depends(get_session)
):
    """
    Get pending actions from the queue.
    
    Args:
        status: Filter by status (PENDING, APPROVED, EXECUTED, etc.)
    """
    from ..models.planning import AgentPendingAction
    from sqlmodel import select
    
    query = select(AgentPendingAction)
    if status:
        query = query.where(AgentPendingAction.status == status)
    query = query.order_by(AgentPendingAction.priority.desc(), AgentPendingAction.created_at.desc())
    
    actions = session.exec(query.limit(50)).all()
    return {
        "count": len(actions),
        "actions": [
            {
                "id": a.id,
                "agent": a.agent_name,
                "action_type": a.action_type,
                "priority": a.priority,
                "status": a.status,
                "line_id": a.line_id,
                "material_id": a.material_id,
                "reason": a.reason,
                "created_at": a.created_at.isoformat() if a.created_at else None
            }
            for a in actions
        ]
    }


@router.post("/start-all")
def start_all_agents():
    """
    Start all agents in the multi-agent system.
    
    Starts in order: supply_chain, maintenance, planning, orchestrator
    """
    from ..agents.agent_runner import start_all_agents as _start_all
    return _start_all()


@router.post("/stop-all")
def stop_all_agents():
    """Stop all running agents."""
    from ..agents.agent_runner import stop_all_agents as _stop_all
    return _stop_all()


@router.post("/start/{agent_name}")
def start_specific_agent(agent_name: str, interval: int = 30):
    """
    Start a specific agent.
    
    Args:
        agent_name: One of: planning, supply_chain, maintenance, orchestrator
        interval: Seconds between agent cycles
    """
    from ..agents.agent_runner import start_agent as _start
    return _start(agent_name, interval)


@router.post("/stop/{agent_name}")
def stop_specific_agent(agent_name: str):
    """Stop a specific agent."""
    from ..agents.agent_runner import stop_agent as _stop
    return _stop(agent_name)


@router.get("/status")
def get_all_agent_status():
    """Get status of all agents."""
    from ..agents.agent_runner import get_status
    return get_status()


@router.get("/status/{agent_name}")
def get_specific_agent_status(agent_name: str):
    """Get status of a specific agent."""
    from ..agents.agent_runner import get_status
    return get_status(agent_name)


@router.get("/decisions")
def get_all_decisions(limit: int = 50):
    """
    Get recent decisions from all agents.
    
    Args:
        limit: Maximum number of decisions to return
    """
    from ..agents.agent_runner import get_decisions
    return get_decisions(None, limit)


@router.get("/decisions/{agent_name}")
def get_agent_decisions(agent_name: str, limit: int = 20):
    """Get recent decisions from a specific agent."""
    from ..agents.agent_runner import get_decisions
    return get_decisions(agent_name, limit)


@router.post("/run-once")
def run_agent_once(session: Session = Depends(get_session)):
    """
    Run a single agent cycle (for testing/debugging).
    
    Returns the observation, decision, and result immediately.
    """
    from ..agents.planning_agent import PlanningAgent
    import asyncio
    
    agent = PlanningAgent()
    
    # Run synchronously for immediate response
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(agent.run_cycle(session))
        session.commit()
        return result
    finally:
        loop.close()


# ============ MCP Tool Endpoints ============
# These endpoints are exposed as tools via MCP

@router.post("/tools/trigger_replan")
def trigger_replan(request: ReplanRequest, session: Session = Depends(get_session)):
    """
    [MCP Tool] Trigger replanning of production schedule.
    
    Use when:
    - Schedule conformance drops below threshold
    - Demand spike occurs
    - Capacity issue detected
    """
    from ..services.planning import plan_all_open_orders
    from ..services.event_logger import log_event
    
    log_event(session, "AGENT_REPLAN", f"Replan triggered: {request.reason}")
    session.commit()
    
    result = plan_all_open_orders()
    
    return {
        "status": "replanned",
        "reason": request.reason,
        "result": str(result)
    }


@router.post("/tools/expedite_po")
def expedite_purchase_order(request: ExpeditePORequest, session: Session = Depends(get_session)):
    """
    [MCP Tool] Expedite a purchase order for critical materials.
    
    Use when:
    - Material availability is critically low
    - Production at risk due to material shortage
    """
    from ..services.event_logger import log_event
    
    log_event(
        session, 
        "AGENT_EXPEDITE_PO", 
        f"Expedite requested for {request.material_id} (urgency: {request.urgency})"
    )
    session.commit()
    
    # In a real system, this would:
    # 1. Find the PO for this material
    # 2. Update its priority/status
    # 3. Potentially notify supplier
    
    return {
        "status": "expedited",
        "material_id": request.material_id,
        "urgency": request.urgency
    }


@router.post("/tools/adjust_priority")
def adjust_order_priority(request: PriorityRequest, session: Session = Depends(get_session)):
    """
    [MCP Tool] Adjust production priority for an order.
    
    Use when:
    - Order is at risk of delay
    - Customer escalation
    - Resource reallocation needed
    """
    from ..models.master import Order
    from ..services.event_logger import log_event
    
    order = session.get(Order, request.order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {request.order_id} not found")
    
    log_event(
        session,
        "AGENT_PRIORITY_CHANGE",
        f"Order {request.order_id} priority changed to {request.new_priority}: {request.reason}"
    )
    session.commit()
    
    return {
        "status": "priority_adjusted",
        "order_id": request.order_id,
        "new_priority": request.new_priority,
        "reason": request.reason
    }


@router.post("/tools/log_alert")
def log_alert(request: AlertRequest, session: Session = Depends(get_session)):
    """
    [MCP Tool] Log an alert for human review.
    
    Use when:
    - Situation requires human decision
    - Complex trade-offs involved
    - Threshold breach detected
    """
    from ..services.event_logger import log_event
    
    log_event(
        session,
        f"AGENT_ALERT_{request.severity.upper()}",
        f"[{request.alert_type}] {request.message}"
    )
    session.commit()
    
    return {
        "status": "logged",
        "alert_type": request.alert_type,
        "severity": request.severity
    }


# ============ Data Access Endpoints ============
# These provide data for the agent and can be called via MCP

@router.get("/tools/kpis")
def get_kpis():
    """
    [MCP Tool] Get current KPI values.
    
    Returns:
    - Schedule Conformance %
    - Material Availability %
    - Average Line OEE
    - Average Machine Health Index
    """
    from ..services.kpis import compute_kpis
    
    kpis = compute_kpis()
    return {
        "kpis": [
            {
                "name": k.name,
                "value": k.value,
                "unit": k.unit,
                "target": k.target,
                "status": k.alert_status
            }
            for k in kpis
        ]
    }


@router.get("/tools/inventory")
def get_inventory_status(critical_only: bool = False, session: Session = Depends(get_session)):
    """
    [MCP Tool] Get current inventory status.
    
    Args:
        critical_only: If true, only return materials below threshold
    """
    from ..services.inventory import get_inventory_view
    
    inventory = get_inventory_view(session)
    
    if critical_only:
        inventory = [
            item for item in inventory
            if item["remaining_requirement"] > item["current_stock"]
        ]
    
    return {"inventory": inventory}


# ============ Additional MCP Tools ============

class CreatePORequest(BaseModel):
    material_id: str
    quantity: Optional[int] = None
    urgency: str = "normal"


class MaintenanceRequest(BaseModel):
    line_id: str
    urgency: str = "scheduled"
    estimated_downtime_hours: int = 4


class FailureAlertRequest(BaseModel):
    machine_id: str
    risk_level: str = "medium"
    description: str = ""


@router.post("/tools/create_po")
def create_purchase_order(request: CreatePORequest, session: Session = Depends(get_session)):
    """
    [MCP Tool] Create a new purchase order for a material.
    
    Use when:
    - Material is below safety stock
    - No existing PO for the material
    """
    from ..services.event_logger import log_event
    from ..services.purchase_order import check_and_place_purchase_orders
    from .config import is_write_enabled
    
    if not is_write_enabled():
        log_event(session, "PO_CREATE_DRYRUN", f"[Dry-run] Would create PO for {request.material_id}")
        session.commit()
        return {"status": "dry_run", "material_id": request.material_id}
    
    # Trigger PO creation logic
    check_and_place_purchase_orders(session)
    
    log_event(session, "MCP_PO_CREATED", f"PO created via MCP for {request.material_id} ({request.urgency})")
    session.commit()
    
    return {
        "status": "created",
        "material_id": request.material_id,
        "urgency": request.urgency
    }


@router.post("/tools/schedule_maintenance")
def schedule_maintenance(request: MaintenanceRequest, session: Session = Depends(get_session)):
    """
    [MCP Tool] Schedule a maintenance window for a production line.
    
    Use when:
    - Machine health is critical
    - Preventive maintenance is due
    """
    from ..services.event_logger import log_event
    from .config import is_write_enabled
    
    if not is_write_enabled():
        log_event(session, "MAINTENANCE_DRYRUN", f"[Dry-run] Would schedule maintenance for {request.line_id}")
        session.commit()
        return {"status": "dry_run", "line_id": request.line_id}
    
    log_event(
        session,
        "MCP_MAINTENANCE_SCHEDULED",
        f"Maintenance scheduled for {request.line_id} ({request.urgency}, {request.estimated_downtime_hours}h)"
    )
    session.commit()
    
    return {
        "status": "scheduled",
        "line_id": request.line_id,
        "urgency": request.urgency,
        "downtime_hours": request.estimated_downtime_hours
    }


@router.post("/tools/alert_failure")
def alert_failure_risk(request: FailureAlertRequest, session: Session = Depends(get_session)):
    """
    [MCP Tool] Alert about potential machine failure risk.
    
    Use when:
    - Machine parameters indicate degradation
    - Predictive maintenance flags an issue
    """
    from ..services.event_logger import log_event
    
    log_event(
        session,
        f"MCP_FAILURE_ALERT_{request.risk_level.upper()}",
        f"Failure risk for {request.machine_id}: {request.description}"
    )
    session.commit()
    
    return {
        "status": "alerted",
        "machine_id": request.machine_id,
        "risk_level": request.risk_level
    }

