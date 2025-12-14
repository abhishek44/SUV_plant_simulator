# app/services/planning.py

from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple, Optional

from sqlmodel import Session, select, delete

from ..database import engine
from ..models.master import Order, Line, BOMItem
from ..models.planning import PlanRun, ProductPlan, PlanItem, OrderAllocation
from ..models.supply import InventoryItem
from ..models.simulation import LineShiftProfile
from ..services.event_logger import log_event


def get_or_create_plan_run(session: Session) -> Tuple[PlanRun, bool]:
    """
    Get the latest BASELINE plan run, or create a new one if none exists.
    Returns (plan_run, is_new).
    """
    existing_run = session.exec(
        select(PlanRun)
        .where(PlanRun.scenario == "BASELINE")
        .order_by(PlanRun.created_at.desc())
    ).first()
    
    if existing_run:
        return existing_run, False
    
    run_id = f"RUN-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    new_run = PlanRun(run_id=run_id, scenario="BASELINE")
    session.add(new_run)
    session.flush()
    return new_run, True


def get_line_occupancy(session: Session, run_id: str) -> Dict[str, List[Tuple[datetime, datetime, int]]]:
    """
    Build a map of line occupancy from existing PlanItems.
    Returns: {line_id: [(start_ts, end_ts, plan_item_id), ...]}
    """
    plan_items = session.exec(
        select(PlanItem)
        .join(ProductPlan, PlanItem.plan_id == ProductPlan.plan_id)
        .where(ProductPlan.run_id == run_id)
    ).all()
    
    occupancy: Dict[str, List[Tuple[datetime, datetime, int]]] = {}
    for item in plan_items:
        if item.line_id not in occupancy:
            occupancy[item.line_id] = []
        occupancy[item.line_id].append((item.start_ts, item.end_ts, item.item_id))
    
    # Sort by start time for each line
    for line_id in occupancy:
        occupancy[line_id].sort(key=lambda x: x[0])
    
    return occupancy


def get_line_available_start(line_occupancy: List[Tuple[datetime, datetime, int]], 
                             desired_start: datetime) -> datetime:
    """
    Find the earliest available start time for a line, after desired_start.
    """
    if not line_occupancy:
        return desired_start
    
    # Find the latest end time among existing allocations
    latest_end = max(occ[1] for occ in line_occupancy)
    
    # If desired start is after all existing allocations, use it
    if desired_start >= latest_end:
        return desired_start
    
    # Otherwise, start after the latest allocation ends
    return latest_end


def get_already_allocated_orders(session: Session, run_id: str) -> set:
    """
    Get set of order_ids that are already fully allocated in this run.
    """
    allocations = session.exec(
        select(OrderAllocation).where(OrderAllocation.run_id == run_id)
    ).all()
    
    allocated_by_order: Dict[str, int] = {}
    for alloc in allocations:
        allocated_by_order[alloc.order_id] = allocated_by_order.get(alloc.order_id, 0) + alloc.allocated_qty
    
    # Get orders to check quantities
    fully_allocated = set()
    for order_id, allocated_qty in allocated_by_order.items():
        order = session.get(Order, order_id)
        if order and allocated_qty >= order.quantity:
            fully_allocated.add(order_id)
    
    return fully_allocated


def handle_spike_preemption(session: Session, run_id: str, spike_order: Order, 
                            lines_by_product: Dict[str, List[Line]]) -> Dict[str, List[Tuple[datetime, datetime, int]]]:
    """
    Handle spike order preemption:
    1. Find all non-spike orders of same product type
    2. Set their status to ON_HOLD
    3. Remove their PlanItems and OrderAllocations (free capacity)
    4. Return updated line occupancy
    
    Returns the updated line_occupancy after freeing capacity.
    """
    product_id = spike_order.product_id
    
    # Find competing orders (same product, not spike, not completed)
    competing_orders = session.exec(
        select(Order)
        .where(
            Order.product_id == product_id,
            Order.is_spike == False,
            Order.status.in_(["OPEN", "ON_HOLD"])
        )
    ).all()
    
    orders_to_hold = []
    for order in competing_orders:
        if order.order_id != spike_order.order_id:
            orders_to_hold.append(order)
    
    if not orders_to_hold:
        # No competing orders to preempt
        return get_line_occupancy(session, run_id)
    
    # Get their allocations to remove
    for order in orders_to_hold:
        # Get allocations for this order
        allocations = session.exec(
            select(OrderAllocation).where(
                OrderAllocation.run_id == run_id,
                OrderAllocation.order_id == order.order_id
            )
        ).all()
        
        # Remove PlanItems and OrderAllocations
        for alloc in allocations:
            plan_item = session.get(PlanItem, alloc.plan_item_id)
            if plan_item:
                session.delete(plan_item)
            session.delete(alloc)
        
        # Delete ProductPlan for this order if exists
        plan_id = f"PLAN-{run_id}-{order.order_id}"
        product_plan = session.get(ProductPlan, plan_id)
        if product_plan:
            session.delete(product_plan)
        
        # Set order status to ON_HOLD
        order.status = "ON_HOLD"
        
        log_event(
            session,
            "ORDER_PREEMPTED",
            f"Order {order.order_id} for {product_id} put ON_HOLD due to spike order {spike_order.order_id}.",
        )
    
    session.flush()
    
    # Return updated line occupancy
    return get_line_occupancy(session, run_id)


def resume_held_orders_for_product(session: Session, product_id: str):
    """
    Resume orders that were put ON_HOLD for a specific product type.
    Called when spike order completes (or could be used by simulation).
    """
    held_orders = session.exec(
        select(Order)
        .where(
            Order.product_id == product_id,
            Order.status == "ON_HOLD",
            Order.is_spike == False
        )
    ).all()
    
    for order in held_orders:
        order.status = "OPEN"
        log_event(
            session,
            "ORDER_RESUMED",
            f"Order {order.order_id} for {product_id} resumed from ON_HOLD.",
        )
    
    session.flush()


def plan_all_open_orders(horizon_days_default: int = 9) -> str:
    """Plan all open orders incrementally without wiping existing plans.

    Design:

    * Finds existing PlanRun or creates new one.
    * Tracks line occupancy from existing PlanItems.
    * Spike orders (is_spike=True) preempt other same-product orders.
    * Only plans orders that aren't already fully allocated.
    * Line scheduling respects existing occupancy (starts after previous ends).

    Example:
      - Orders: ORD-HE-001 (P-HE), ORD-ME-001 (P-ME)
      - We create:
          RUN-20251203...
          PLAN-RUN-20251203...-ORD-HE-001
          PLAN-RUN-20251203...-ORD-ME-001
    """
    today = date.today()

    with Session(engine) as session:
        # --- 1) Get or create PlanRun (DON'T wipe existing data) ---
        run, is_new = get_or_create_plan_run(session)
        run_id = run.run_id

        # --- 2) Lines grouped by product ---
        lines = session.exec(select(Line)).all()
        lines_by_product: Dict[str, List[Line]] = {}
        for line in lines:
            lines_by_product.setdefault(line.product_id, []).append(line)

        # --- 3) BOM grouped by product ---
        bom_items = session.exec(select(BOMItem)).all()
        bom_by_product: Dict[str, List[BOMItem]] = {}
        for b in bom_items:
            bom_by_product.setdefault(b.product_id, []).append(b)

        # --- 4) Inventory snapshot (planning-time view) ---
        inv_items = session.exec(select(InventoryItem)).all()
        stock_by_material: Dict[str, int] = {
            i.material_id: i.current_stock for i in inv_items
        }

        # This is an in-memory "shadow" of how much material we've already
        # reserved for earlier orders in THIS planning run.
        planned_usage: Dict[str, int] = {}

        def max_units_from_inventory(product_id: str) -> int:
            """How many units of this product can be planned given stock − planned_usage."""
            bom_list = bom_by_product.get(product_id, [])
            if not bom_list:
                # No BOM ⇒ no inventory constraint
                return 10**9

            max_units = 10**9
            for b in bom_list:
                if b.quantity_per_unit <= 0:
                    continue
                available = stock_by_material.get(b.material_id, 0) - planned_usage.get(
                    b.material_id, 0
                )
                units_for_material = available // b.quantity_per_unit
                max_units = min(max_units, max(0, units_for_material))
            return max_units

        def consume_inventory(product_id: str, units: int) -> None:
            """Reserve material for planning (only updates planned_usage)."""
            bom_list = bom_by_product.get(product_id, [])
            for b in bom_list:
                planned_usage[b.material_id] = planned_usage.get(b.material_id, 0) + (
                    units * b.quantity_per_unit
                )

        # --- 5) LineShiftProfile for this run (only for new runs) ---
        if is_new:
            for line in lines:
                base_rate = line.daily_capacity / 8.0  # assume 8h "effective" per day
                lsp = LineShiftProfile(
                    run_id=run_id,
                    line_id=line.line_id,
                    shift_id="S1",
                    product_id=line.product_id,
                    base_rate_units_per_hour=base_rate,
                    base_defect_rate_pct=2.5 if line.product_id == "P-HE" else 3.0,
                    base_uptime_pct=line.oee_pct * 100.0,
                    base_worker_availability_pct=90.0,
                    base_energy_kwh_per_unit=0.4 if line.product_id == "P-HE" else 0.35,
                    throughput_sigma_pct=10.0,
                    uptime_sigma_pct=5.0,
                    worker_avail_sigma_pct=5.0,
                    defect_sigma_pct=1.0,
                    energy_sigma_pct=5.0,
                )
                session.add(lsp)

        # --- 6) Get already allocated orders (skip them) ---
        already_allocated = get_already_allocated_orders(session, run_id)

        # --- 7) Get current line occupancy ---
        line_occupancy = get_line_occupancy(session, run_id)

        # --- 8) All open orders (not ON_HOLD or already allocated) ---
        orders = session.exec(
            select(Order).where(Order.status == "OPEN")
        ).all()
        
        if not orders:
            session.commit()
            return run_id

        # Filter out already allocated orders
        orders = [o for o in orders if o.order_id not in already_allocated]
        
        if not orders:
            session.commit()
            return run_id

        # --- 9) Handle spike orders first (preemption) ---
        spike_orders = [o for o in orders if o.is_spike]
        regular_orders = [o for o in orders if not o.is_spike]
        
        for spike_order in spike_orders:
            line_occupancy = handle_spike_preemption(
                session, run_id, spike_order, lines_by_product
            )

        # Sort orders: spike first (by priority), then regular (by dispatch, start)
        orders_to_plan = spike_orders + regular_orders
        orders_to_plan.sort(key=lambda o: (o.priority, o.dispatch_date, o.start_date))

        # --- 10) Per-order planning (one ProductPlan per order) ---
        for order in orders_to_plan:
            product_id = order.product_id
            order_lines = lines_by_product.get(product_id, [])

            if not order_lines:
                log_event(
                    session,
                    "NO_LINE_FOR_PRODUCT",
                    f"No lines found for product {product_id}; cannot plan order {order.order_id}.",
                )
                continue

            # 10.1 Create a ProductPlan for THIS order
            plan_id = f"PLAN-{run_id}-{order.order_id}"
            
            # Check if plan already exists (in case of re-planning)
            existing_plan = session.get(ProductPlan, plan_id)
            if existing_plan:
                continue  # Already planned
            
            plan = ProductPlan(
                plan_id=plan_id,
                run_id=run_id,
                plan_date=today,
                status="PLANNED",
            )
            session.add(plan)

            # 10.2 Order-specific planning horizon
            horizon_start = order.start_date or today
            horizon_end = order.dispatch_date or (
                today + timedelta(days=horizon_days_default)
            )
            horizon_days = max(1, (horizon_end - horizon_start).days)

            # 10.3 Capacity for lines that can build this product in the horizon
            line_capacity: Dict[str, float] = {}
            total_capacity_units = 0.0
            for ln in order_lines:
                eff_daily_cap = ln.daily_capacity * ln.oee_pct
                cap_units = eff_daily_cap * horizon_days
                if cap_units <= 0:
                    continue
                line_capacity[ln.line_id] = cap_units
                total_capacity_units += cap_units

            if total_capacity_units <= 0:
                log_event(
                    session,
                    "CAPACITY_SHORTFALL",
                    f"Order {order.order_id} for {product_id} has no line capacity in horizon.",
                )
                continue

            # 10.4 Inventory constraint for this product
            inv_limit = max_units_from_inventory(product_id)
            if inv_limit <= 0:
                log_event(
                    session,
                    "INVENTORY_SHORTFALL",
                    f"No inventory to plan product {product_id} for order {order.order_id}.",
                )
                continue

            # 10.5 Demand ∩ (capacity, inventory) ⇒ target_qty
            target_qty = min(order.quantity, int(total_capacity_units), inv_limit)
            if target_qty <= 0:
                log_event(
                    session,
                    "CAPACITY_SHORTFALL",
                    f"Order {order.order_id} requested {order.quantity}, "
                    f"but capacity+inventory only allow 0 units.",
                )
                continue

            # Log shortfalls vs requested
            if int(total_capacity_units) < order.quantity:
                short = order.quantity - int(total_capacity_units)
                log_event(
                    session,
                    "CAPACITY_SHORTFALL",
                    f"Order {order.order_id} requested {order.quantity}, "
                    f"capacity-limited to {int(total_capacity_units)}, shortfall {short}.",
                )
            if inv_limit < order.quantity:
                inv_short = order.quantity - inv_limit
                log_event(
                    session,
                    "INVENTORY_SHORTFALL",
                    f"Order {order.order_id} requested {order.quantity}, "
                    f"inventory-limited to {inv_limit}, shortfall {inv_short}.",
                )

            # 10.6 Distribute target_qty across lines proportional to capacity
            remaining_to_allocate = target_qty
            allocations: Dict[str, int] = {}

            for ln in order_lines:
                cap_units = line_capacity.get(ln.line_id, 0.0)
                if cap_units <= 0 or remaining_to_allocate <= 0:
                    continue

                share = cap_units / total_capacity_units
                qty_for_line = int(round(target_qty * share))

                # Keep numbers sane
                qty_for_line = max(0, min(qty_for_line, remaining_to_allocate))
                allocations[ln.line_id] = allocations.get(ln.line_id, 0) + qty_for_line
                remaining_to_allocate -= qty_for_line

            # Fix up rounding leftovers by giving extra units to the "big" lines
            if remaining_to_allocate > 0:
                for ln in sorted(
                    order_lines,
                    key=lambda l: line_capacity.get(l.line_id, 0.0),
                    reverse=True,
                ):
                    if remaining_to_allocate <= 0:
                        break
                    allocations[ln.line_id] = allocations.get(ln.line_id, 0) + 1
                    remaining_to_allocate -= 1

            # 10.7 Create PlanItems + OrderAllocations for THIS order's plan
            allocated_total = 0

            for ln in order_lines:
                alloc = allocations.get(ln.line_id, 0)
                if alloc <= 0:
                    continue

                consume_inventory(product_id, alloc)

                eff_daily_cap = ln.daily_capacity * ln.oee_pct
                duration_days = alloc / eff_daily_cap if eff_daily_cap > 0 else 0.0

                # Calculate start time based on line occupancy
                base_start = datetime.combine(horizon_start, datetime.min.time())
                line_occ = line_occupancy.get(ln.line_id, [])
                start_ts = get_line_available_start(line_occ, base_start)
                end_ts = start_ts + timedelta(days=duration_days)

                plan_item = PlanItem(
                    plan_id=plan_id,
                    line_id=ln.line_id,
                    product_id=product_id,
                    planned_qty=alloc,
                    start_ts=start_ts,
                    end_ts=end_ts,
                )
                session.add(plan_item)
                session.flush()

                # Update line occupancy for next orders
                if ln.line_id not in line_occupancy:
                    line_occupancy[ln.line_id] = []
                line_occupancy[ln.line_id].append((start_ts, end_ts, plan_item.item_id))

                oa = OrderAllocation(
                    run_id=run_id,
                    plan_id=plan_id,
                    order_id=order.order_id,
                    line_id=ln.line_id,
                    product_id=product_id,
                    allocated_qty=alloc,
                    plan_item_id=plan_item.item_id,
                )
                session.add(oa)

                allocated_total += alloc

            # 10.8 Final per-order capacity shortfall
            if allocated_total < order.quantity:
                short = order.quantity - allocated_total
                log_event(
                    session,
                    "CAPACITY_SHORTFALL",
                    f"Order {order.order_id} requested {order.quantity}, "
                    f"planned {allocated_total}, shortfall {short}.",
                )

        session.commit()
        return run_id
