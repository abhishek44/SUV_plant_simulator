# app/services/order_analytics.py

from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from sqlmodel import Session, select

from ..models.master import Order, BOMItem
from ..models.planning import PlanItem, OrderAllocation, PlanRun
from ..models.supply import PurchaseOrder, InventoryItem
from ..models.simulation import OrderProgress
from . import inventory


def calculate_order_delays(session: Session) -> List[Dict]:
    """
    Analyze all orders and return delay information.
    
    Returns list of dicts with:
      - order_id, product_id, quantity, dispatch_date
      - planned_completion_date (max end_ts across all allocations)
      - delay_days (positive if late, negative if early, 0 if on-time)
      - status: "ON_TIME", "AT_RISK", "DELAYED"
      - root_causes: list of ["CAPACITY_SHORTFALL", "INVENTORY_SHORTAGE", "SUPPLIER_DELAY"]
      - allocated_qty, shortfall_qty
    """
    # Get latest run
    run = session.exec(
        select(PlanRun).order_by(PlanRun.created_at.desc())
    ).first()
    
    if not run:
        return []
    
    orders = session.exec(select(Order)).all()
    results = []
    
    for order in orders:
        # Get all allocations for this order in the latest run
        allocations = session.exec(
            select(OrderAllocation).where(
                OrderAllocation.order_id == order.order_id,
                OrderAllocation.run_id == run.run_id
            )
        ).all()
        
        if not allocations:
            # Order not allocated - severe capacity shortfall
            results.append({
                "order_id": order.order_id,
                "product_id": order.product_id,
                "quantity": order.quantity,
                "dispatch_date": order.dispatch_date.isoformat(),
                "planned_completion_date": None,
                "delay_days": None,
                "status": "NOT_PLANNED",
                "root_causes": ["CAPACITY_SHORTFALL"],
                "allocated_qty": 0,
                "shortfall_qty": order.quantity
            })
            continue
        
        # Get plan items for these allocations
        plan_item_ids = [a.plan_item_id for a in allocations]
        plan_items = session.exec(
            select(PlanItem).where(PlanItem.item_id.in_(plan_item_ids))
        ).all()
        
        # Calculate total allocated quantity
        allocated_qty = sum(a.allocated_qty for a in allocations)
        shortfall_qty = max(0, order.quantity - allocated_qty)
        
        # Find latest completion date across all plan items
        end_dates = [p.end_ts for p in plan_items if p.end_ts]
        if not end_dates:
            planned_completion_date = None
            delay_days = None
        else:
            latest_end_ts = max(end_dates)
            planned_completion_date = latest_end_ts.date()
            delay_days = (planned_completion_date - order.dispatch_date).days
        
        # Determine status
        if delay_days is None:
            status = "UNKNOWN"
        elif delay_days > 0:
            status = "DELAYED"
        elif delay_days == 0 or delay_days == -1:
            status = "AT_RISK"  # Due today or tomorrow
        else:
            status = "ON_TIME"
        
        # Identify root causes
        root_causes = []
        if shortfall_qty > 0:
            root_causes.append("CAPACITY_SHORTFALL")
        
        # Check inventory shortage for this product
        inv_limit = _check_inventory_availability(session, order.product_id)
        if inv_limit < order.quantity:
            root_causes.append("INVENTORY_SHORTAGE")
        
        # Check supplier delays
        if _has_supplier_delays(session, order.product_id):
            root_causes.append("SUPPLIER_DELAY")
        
        results.append({
            "order_id": order.order_id,
            "product_id": order.product_id,
            "quantity": order.quantity,
            "dispatch_date": order.dispatch_date.isoformat(),
            "planned_completion_date": planned_completion_date.isoformat() if planned_completion_date else None,
            "delay_days": delay_days,
            "status": status,
            "root_causes": root_causes,
            "allocated_qty": allocated_qty,
            "shortfall_qty": shortfall_qty
        })
    
    return results


def get_order_timeline(session: Session, order_id: str) -> Dict:
    """
    Returns detailed timeline for a specific order.
    
    Includes:
      - Order details
      - All plan item allocations with start/end times
      - Material requirements and availability
      - Supplier PO status for required materials
    """
    order = session.get(Order, order_id)
    if not order:
        return {"error": "Order not found"}
    
    # Get latest run
    run = session.exec(
        select(PlanRun).order_by(PlanRun.created_at.desc())
    ).first()
    
    if not run:
        return {"error": "No plan run found"}
    
    # Get allocations
    allocations = session.exec(
        select(OrderAllocation).where(
            OrderAllocation.order_id == order_id,
            OrderAllocation.run_id == run.run_id
        )
    ).all()
    
    # Get plan items
    plan_items_data = []
    for alloc in allocations:
        plan_item = session.get(PlanItem, alloc.plan_item_id)
        if plan_item:
            plan_items_data.append({
                "line_id": alloc.line_id,
                "allocated_qty": alloc.allocated_qty,
                "start_ts": plan_item.start_ts.isoformat() if plan_item.start_ts else None,
                "end_ts": plan_item.end_ts.isoformat() if plan_item.end_ts else None,
                "status": plan_item.status
            })
    
    # Get material requirements
    bom_items = session.exec(
        select(BOMItem).where(BOMItem.product_id == order.product_id)
    ).all()
    
    materials_data = []
    for bom in bom_items:
        required_qty = bom.quantity_per_unit * order.quantity
        current_stock = inventory.inventory_state.get(bom.material_id, 0)
        
        # Get PO status
        po = session.exec(
            select(PurchaseOrder).where(
                PurchaseOrder.material_id == bom.material_id,
                PurchaseOrder.status != "DELIVERED"
            )
        ).first()
        
        materials_data.append({
            "material_id": bom.material_id,
            "required_qty": required_qty,
            "current_stock": current_stock,
            "po_quantity": po.quantity if po else None,
            "po_eta": po.eta_date.isoformat() if po else None,
            "po_status": po.status if po else None
        })
    
    # Get current progress if available
    progress = session.exec(
        select(OrderProgress).where(
            OrderProgress.order_id == order_id,
            OrderProgress.run_id == run.run_id
        ).order_by(OrderProgress.ts.desc())
    ).first()
    
    return {
        "order_id": order.order_id,
        "product_id": order.product_id,
        "quantity": order.quantity,
        "start_date": order.start_date.isoformat(),
        "dispatch_date": order.dispatch_date.isoformat(),
        "status": order.status,
        "plan_items": plan_items_data,
        "materials": materials_data,
        "current_progress": {
            "completed_qty": progress.completed_qty if progress else 0,
            "remaining_qty": progress.remaining_qty if progress else order.quantity,
            "estimated_completion": progress.estimated_completion_date.isoformat() if progress and progress.estimated_completion_date else None
        } if progress else None
    }


def get_delay_recommendations(session: Session, order_id: str) -> Dict:
    """
    Provides actionable recommendations to mitigate delays.
    
    Returns:
      - order_id
      - delay_days
      - recommendations: list of action items
    """
    # Get delay info
    delays = calculate_order_delays(session)
    order_delay = next((d for d in delays if d["order_id"] == order_id), None)
    
    if not order_delay:
        return {"error": "Order not found"}
    
    recommendations = []
    
    # Capacity-based recommendations
    if "CAPACITY_SHORTFALL" in order_delay["root_causes"]:
        recommendations.append({
            "priority": "HIGH",
            "category": "CAPACITY",
            "action": "Increase production capacity",
            "details": f"Shortfall of {order_delay['shortfall_qty']} units. Consider: (1) Add overtime shifts, (2) Reallocate lines from lower-priority orders, (3) Increase OEE through maintenance"
        })
    
    # Inventory-based recommendations
    if "INVENTORY_SHORTAGE" in order_delay["root_causes"]:
        order = session.get(Order, order_id)
        bom_items = session.exec(
            select(BOMItem).where(BOMItem.product_id == order.product_id)
        ).all()
        
        low_materials = []
        for bom in bom_items:
            required = bom.quantity_per_unit * order.quantity
            current = inventory.inventory_state.get(bom.material_id, 0)
            if current < required:
                low_materials.append(f"{bom.material_id} (need {required}, have {current})")
        
        recommendations.append({
            "priority": "HIGH",
            "category": "INVENTORY",
            "action": "Expedite material procurement",
            "details": f"Low stock for: {', '.join(low_materials)}. Consider: (1) Expedite existing POs, (2) Place emergency orders, (3) Use alternate suppliers"
        })
    
    # Supplier-based recommendations
    if "SUPPLIER_DELAY" in order_delay["root_causes"]:
        recommendations.append({
            "priority": "MEDIUM",
            "category": "SUPPLIER",
            "action": "Address supplier delays",
            "details": "Supplier deliveries are delayed. Consider: (1) Contact suppliers to expedite, (2) Use alternate suppliers, (3) Increase safety stock for critical materials"
        })
    
    # If on-time, provide preventive recommendations
    if order_delay["status"] == "ON_TIME" and not recommendations:
        recommendations.append({
            "priority": "LOW",
            "category": "PREVENTIVE",
            "action": "Monitor closely",
            "details": "Order is currently on track. Continue monitoring inventory levels and production rates."
        })
    
    return {
        "order_id": order_id,
        "delay_days": order_delay["delay_days"],
        "status": order_delay["status"],
        "recommendations": recommendations
    }


# Helper functions

def _check_inventory_availability(session: Session, product_id: str) -> int:
    """Check how many units of this product can be made with current inventory."""
    bom_items = session.exec(
        select(BOMItem).where(BOMItem.product_id == product_id)
    ).all()
    
    if not bom_items:
        return 10**9  # No BOM constraint
    
    max_units = 10**9
    for bom in bom_items:
        if bom.quantity_per_unit <= 0:
            continue
        current_stock = inventory.inventory_state.get(bom.material_id, 0)
        units_possible = current_stock // bom.quantity_per_unit
        max_units = min(max_units, units_possible)
    
    return max_units


def _has_supplier_delays(session: Session, product_id: str) -> bool:
    """Check if any materials for this product have delayed supplier deliveries."""
    bom_items = session.exec(
        select(BOMItem).where(BOMItem.product_id == product_id)
    ).all()
    
    today = date.today()
    
    for bom in bom_items:
        # Check if there are overdue POs
        pos = session.exec(
            select(PurchaseOrder).where(
                PurchaseOrder.material_id == bom.material_id,
                PurchaseOrder.status != "DELIVERED"
            )
        ).all()
        
        for po in pos:
            if po.eta_date < today:
                return True  # Overdue PO found
    
    return False
