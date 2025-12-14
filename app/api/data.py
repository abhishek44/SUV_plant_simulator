# app/api/data.py

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..database import get_session
from ..models.master import Order, Product, Line, Shift
from ..models.planning import PlanRun, ProductPlan, PlanItem, OrderAllocation, Event
from ..models.supply import PurchaseOrder
from ..models.simulation import ProductionRealtime
from ..services.inventory import get_inventory_view

router = APIRouter(prefix="/api/data", tags=["data"])


# ---------- helpers ----------

def _latest_run(session: Session) -> PlanRun | None:
    return session.exec(
        select(PlanRun).order_by(PlanRun.created_at.desc())
    ).first()


# ---------- realtime ----------

@router.get("/realtime")
def get_realtime(session: Session = Depends(get_session)):
    """
    Return the *latest* realtime snapshot per line for the latest plan run.
    This keeps the dashboard from showing multiple entries per line.
    """
    run = _latest_run(session)
    if not run:
        return []

    rows = session.exec(
        select(ProductionRealtime)
        .where(ProductionRealtime.run_id == run.run_id)
        .order_by(ProductionRealtime.ts.desc())
    ).all()

    latest_by_line: dict[str, ProductionRealtime] = {}
    for r in rows:
        # rows are ordered newest → oldest; first seen per line is the latest
        if r.assembly_line not in latest_by_line:
            latest_by_line[r.assembly_line] = r

    return list(latest_by_line.values())


# ---------- master lookups ----------

@router.get("/orders")
def get_orders(session: Session = Depends(get_session)):
    orders = session.exec(select(Order)).all()
    return orders


@router.get("/products")
def get_products(session: Session = Depends(get_session)):
    products = session.exec(select(Product)).all()
    return products


@router.get("/lines")
def get_lines(session: Session = Depends(get_session)):
    lines = session.exec(select(Line)).all()
    return lines


@router.get("/shifts")
def get_shifts(session: Session = Depends(get_session)):
    shifts = session.exec(select(Shift)).all()
    return shifts


@router.get("/plans")
def get_plans(session: Session = Depends(get_session)):
    plans = session.exec(select(ProductPlan)).all()
    return plans


@router.get("/purchase_orders")
def get_purchase_orders(session: Session = Depends(get_session)):
    pos = session.exec(select(PurchaseOrder)).all()
    return pos


# ---------- inventory view ----------

@router.get("/inventory")
def api_inventory(session: Session = Depends(get_session)):
    """
    Rich inventory status for dashboard.

    Returns list of dicts with:
      material_id, description, products, required_for_order,
      consumed_so_far, current_stock, seed_stock,
      remaining_requirement, total_cost_remaining,
      po_quantity, po_eta, po_status
    """
    return get_inventory_view(session)


# ---------- orders + plan items for latest run ----------

@router.get("/orders_plan")
def get_orders_and_plan(session: Session = Depends(get_session)):
    """
    Returns:
      - all orders with statuses
      - plan items (for *latest* run only), joined with allocations

    This ensures that after a demand spike / re-plan, the dashboard
    shows the refreshed plan instead of accumulating historical items.
    """
    run = _latest_run(session)
    if not run:
        return {"orders": [], "plan_items": []}

    orders = session.exec(select(Order)).all()

    # Get all allocations for this run
    allocations = session.exec(
        select(OrderAllocation).where(OrderAllocation.run_id == run.run_id)
    ).all()

    plan_items: list[dict] = []

    # To avoid N+1, cache PlanItems in a dict
    plan_item_ids = {oa.plan_item_id for oa in allocations}
    if plan_item_ids:
        plan_rows = session.exec(
            select(PlanItem).where(PlanItem.item_id.in_(list(plan_item_ids)))
        ).all()
        plan_by_id = {p.item_id: p for p in plan_rows}
    else:
        plan_by_id = {}

    for oa in allocations:
        p = plan_by_id.get(oa.plan_item_id)
        if not p:
            continue

        plan_items.append(
            {
                "order_id": oa.order_id,
                "product_id": oa.product_id,
                "line_id": oa.line_id,
                "planned_qty": oa.allocated_qty,
                "start_ts": p.start_ts.isoformat() if p.start_ts else None,
                "end_ts": p.end_ts.isoformat() if p.end_ts else None,
            }
        )

    return {"orders": orders, "plan_items": plan_items}


# ---------- events (event log) ----------

@router.get("/events")
def get_events(session: Session = Depends(get_session), limit: int = 100):
    """
    Recent events from the Event table (used as event log).
    """
    events = session.exec(
        select(Event).order_by(Event.event_date.desc()).limit(limit)
    ).all()
    return events


# ---------- order delay analysis ----------

@router.get("/order_delays")
def get_order_delays(session: Session = Depends(get_session)):
    """
    Returns delay analysis for all orders.
    
    Response includes:
      - order_id, product_id, quantity, dispatch_date
      - planned_completion_date, delay_days
      - status: ON_TIME, AT_RISK, DELAYED, NOT_PLANNED
      - root_causes: CAPACITY_SHORTFALL, INVENTORY_SHORTAGE, SUPPLIER_DELAY
      - allocated_qty, shortfall_qty
    """
    from ..services.order_analytics import calculate_order_delays
    return calculate_order_delays(session)


@router.get("/order_timeline/{order_id}")
def get_order_timeline_endpoint(order_id: str, session: Session = Depends(get_session)):
    """
    Returns detailed timeline for a specific order.
    
    Includes:
      - Order details
      - Plan item allocations with start/end times
      - Material requirements and availability
      - Supplier PO status
      - Current progress
    """
    from ..services.order_analytics import get_order_timeline
    return get_order_timeline(session, order_id)


@router.get("/order_recommendations/{order_id}")
def get_order_recommendations_endpoint(order_id: str, session: Session = Depends(get_session)):
    """
    Returns actionable recommendations to mitigate order delays.
    
    Includes:
      - Delay information
      - Prioritized recommendations by category
      - Specific action items
    """
    from ..services.order_analytics import get_delay_recommendations
    return get_delay_recommendations(session, order_id)
