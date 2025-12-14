# app/services/simulation.py

import asyncio
import random
from typing import Dict
from datetime import datetime, timedelta

from fastapi import BackgroundTasks
from sqlmodel import Session, select

from ..database import engine
from ..models.master import Order, Line
from ..models.planning import PlanRun, ProductPlan, OrderAllocation
from ..models.simulation import LineShiftProfile, ProductionRealtime, OrderProgress
from ..services import inventory
from ..services.purchase_order import (
    update_purchase_orders,
    check_and_place_purchase_orders,
)
from ..services.event_logger import log_event
from ..utils.helpers import get_current_shift_id


# Global simulation flags/state
simulation_running: bool = False

# Per-line state:
#   units_completed    : float (continuous, with fractional units)
#   units_completed_int: int (floor, used to trigger inventory consumption)
#   energy_kwh         : float (cumulative)
line_state: Dict[str, Dict[str, float]] = {}

# Which materials we treat as "semiconductors" for alerting
semiconductor_ids = {"M014", "M076", "M108"}


def init_line_state() -> None:
    """
    Initialize per-line production state from the master Line table.
    """
    global line_state
    with Session(engine) as session:
        lines = session.exec(select(Line)).all()
        line_state = {
            line.line_id: {
                "units_completed": 0.0,
                "units_completed_int": 0,
                "energy_kwh": 0.0,
            }
            for line in lines
        }


def update_order_progress(session: Session, run_id: str, line_id: str, units_produced: int, now: datetime) -> None:
    """
    Distribute produced units to orders based on allocations for this line.
    Updates OrderProgress table with cumulative completed quantities.
    """
    if units_produced <= 0:
        return
    
    # Get allocations for this line in this run
    allocations = session.exec(
        select(OrderAllocation).where(
            OrderAllocation.run_id == run_id,
            OrderAllocation.line_id == line_id
        )
    ).all()
    
    if not allocations:
        return
    
    # Distribute units proportionally to allocated quantities
    total_allocated = sum(a.allocated_qty for a in allocations)
    if total_allocated <= 0:
        return
    
    for alloc in allocations:
        # Calculate this order's share of the produced units
        share = alloc.allocated_qty / total_allocated
        units_for_order = int(units_produced * share)
        
        if units_for_order <= 0:
            continue
        
        # Get or create OrderProgress for this order
        progress = session.exec(
            select(OrderProgress).where(
                OrderProgress.order_id == alloc.order_id,
                OrderProgress.run_id == run_id
            ).order_by(OrderProgress.ts.desc())
        ).first()
        
        order = session.get(Order, alloc.order_id)
        if not order:
            continue
        
        if progress:
            # Update existing progress
            new_completed = min(progress.completed_qty + units_for_order, order.quantity)
            new_remaining = max(0, order.quantity - new_completed)
        else:
            # Create new progress entry
            new_completed = min(units_for_order, order.quantity)
            new_remaining = max(0, order.quantity - new_completed)
        
        # Estimate completion date based on current production rate
        estimated_completion = None
        if new_remaining > 0 and units_for_order > 0:
            # Simple estimation: remaining units / current rate
            # Assuming current rate continues (units per second)
            seconds_remaining = new_remaining / (units_for_order / 1.0)  # 1 second tick
            estimated_completion = (now + timedelta(seconds=seconds_remaining)).date()
        elif new_remaining == 0:
            estimated_completion = now.date()
        
        # Create new progress snapshot
        new_progress = OrderProgress(
            order_id=alloc.order_id,
            run_id=run_id,
            ts=now,
            completed_qty=new_completed,
            remaining_qty=new_remaining,
            estimated_completion_date=estimated_completion
        )
        session.add(new_progress)
        
        # Log if order is at risk
        if estimated_completion and estimated_completion > order.dispatch_date:
            delay_days = (estimated_completion - order.dispatch_date).days
            log_event(
                session,
                "ORDER_AT_RISK",
                f"Order {alloc.order_id} estimated to be {delay_days} days late (completion: {estimated_completion}, dispatch: {order.dispatch_date})"
            )


async def simulation_loop() -> None:
    """
    Background loop that advances the simulation once per second.
    """
    global simulation_running
    while simulation_running:
        await step_simulation_once()
        await asyncio.sleep(1.0)


async def step_simulation_once() -> None:
    """
    Single simulation tick (1 second).
    - Reads latest PlanRun / ProductPlan / LineShiftProfile
    - Produces output per line
    - Consumes inventory based on BOM per product
    - Updates purchase orders (deliveries + new POs)
    - Writes ProductionRealtime rows and events
    - Tracks per-order progress
    """
    global simulation_running, line_state

    now = datetime.utcnow()
    shift_id = get_current_shift_id(now)

    with Session(engine) as session:
        # 1) Orders & total plant demand
        orders = session.exec(select(Order)).all()
        if not orders:
            return

        total_planned = sum(o.quantity for o in orders)

        # 2) Apply PO deliveries (if ETA reached)
        update_purchase_orders(session)

        # 3) Get latest PlanRun & ProductPlan
        run = session.exec(
            select(PlanRun).order_by(PlanRun.created_at.desc())
        ).first()
        if not run:
            return

        plan = session.exec(
            select(ProductPlan).where(ProductPlan.run_id == run.run_id)
        ).first()

        # 4) Line shift profiles for this run
        profiles = session.exec(
            select(LineShiftProfile).where(LineShiftProfile.run_id == run.run_id)
        ).all()
        profile_by_line = {p.line_id: p for p in profiles}
        if not profile_by_line:
            return

        # 5) Line → product mapping
        lines = session.exec(select(Line)).all()
        product_by_line = {ln.line_id: ln.product_id for ln in lines}

        # 6) Check completion and compute global inventory %
        total_completed = sum(s["units_completed"] for s in line_state.values())

        if total_completed >= total_planned:
            simulation_running = False
            log_event(session, "PLAN_COMPLETED", "All orders completed in simulation")
            session.commit()
            return

        if inventory.initial_inventory_total > 0:
            inventory_pct = (
                sum(inventory.inventory_state.values())
                / float(inventory.initial_inventory_total)
            ) * 100.0
        else:
            inventory_pct = 0.0

        realtime_rows: list[ProductionRealtime] = []

        # 7) Per-line simulation
        for line_id, state in line_state.items():
            profile = profile_by_line.get(line_id)
            if not profile:
                # Line not in this run's shift profile; skip
                continue

            product_id = product_by_line.get(line_id)
            bom_list = inventory.bom_by_product.get(product_id, [])

            # Base rate per second
            base_rate_per_sec = profile.base_rate_units_per_hour / 3600.0
            # Random throughput factor
            factor = random.gauss(1.0, profile.throughput_sigma_pct / 100.0)
            produced_float = max(0.0, base_rate_per_sec * factor)

            # Cap at remaining plant-wide demand
            remaining = total_planned - total_completed
            if remaining <= 0:
                produced_float = 0.0
            elif produced_float > remaining:
                produced_float = float(remaining)

            # Update continuous units
            state["units_completed"] += produced_float
            total_completed += produced_float

            # Convert to integer completed units to drive inventory
            old_int = int(state.get("units_completed_int", 0))
            new_int = int(state["units_completed"])
            delta_units = max(0, new_int - old_int)
            state["units_completed_int"] = new_int

            # Consume inventory per BOM for this line's product
            for _ in range(delta_units):
                for bom in bom_list:
                    current_stock = inventory.inventory_state.get(bom.material_id, 0)
                    inventory.inventory_state[bom.material_id] = max(
                        0, current_stock - bom.quantity_per_unit
                    )

            # Update per-order progress
            update_order_progress(session, run.run_id, line_id, delta_units, now)

            # Recalculate global inventory % after consumption
            if inventory.initial_inventory_total > 0:
                inventory_pct = (
                    sum(inventory.inventory_state.values())
                    / float(inventory.initial_inventory_total)
                ) * 100.0
            else:
                inventory_pct = 0.0

            # Machine & worker performance (synthetic but realistic-ish)
            machine_uptime = max(
                0.0,
                min(
                    100.0,
                    random.gauss(profile.base_uptime_pct, profile.uptime_sigma_pct),
                ),
            )
            worker_avail = max(
                0.0,
                min(
                    100.0,
                    random.gauss(
                        profile.base_worker_availability_pct,
                        profile.worker_avail_sigma_pct,
                    ),
                ),
            )
            defect_rate = max(
                0.0,
                random.gauss(profile.base_defect_rate_pct, profile.defect_sigma_pct),
            )

            # Energy usage
            per_unit_energy = random.gauss(
                profile.base_energy_kwh_per_unit,
                profile.base_energy_kwh_per_unit * profile.energy_sigma_pct / 100.0,
            )
            energy_this_tick = per_unit_energy * delta_units
            state["energy_kwh"] += max(0.0, energy_this_tick)

            # Semiconductor availability classification
            semi_status = "Available"
            for mid in semiconductor_ids:
                if mid in inventory.inventory_state:
                    if inventory.inventory_state[mid] <= 0:
                        semi_status = "Shortage"
                        break
                    elif inventory.inventory_state[mid] < 10:
                        semi_status = "Delayed"

            # Alert logic
            alerts = []
            if machine_uptime < 80.0:
                alerts.append("Maintenance_Alert")
                log_event(
                    session,
                    "MAINTENANCE_RISK",
                    f"Low uptime on {line_id}",
                )
            if worker_avail < 80.0:
                alerts.append("ShiftAdjustment")
            if inventory_pct < 30.0 or semi_status != "Available":
                alerts.append("SupplyAlert")
                if semi_status != "Available":
                    log_event(
                        session,
                        "SUPPLY_ISSUE",
                        f"Semiconductor {semi_status} on {line_id}",
                    )
            if defect_rate > 5.0:
                alerts.append("Quality_Alert")

            alert_status = "Normal" if not alerts else "/".join(alerts)

            # Build realtime row
            rt = ProductionRealtime(
                run_id=run.run_id,
                plan_id=plan.plan_id if plan else None,
                plan_item_id=None,  # could be linked to closest PlanItem in a richer model
                ts=now,
                assembly_line=line_id,
                shift_id=shift_id,
                demand_suvs=total_planned,
                inventory_status_pct=round(inventory_pct, 2),
                machine_uptime_pct=round(machine_uptime, 2),
                worker_availability_pct=round(worker_avail, 2),
                production_output_cum=int(state["units_completed_int"]),
                defect_rate_pct=round(defect_rate, 2),
                energy_consumption_kwh_cum=round(state["energy_kwh"], 2),
                semiconductor_availability=semi_status,
                alert_status=alert_status,
            )
            realtime_rows.append(rt)

        # 8) Purchase orders based on updated stock and total order requirements
        check_and_place_purchase_orders(session)

        # 9) Persist realtime rows
        for r in realtime_rows:
            session.add(r)
        session.commit()


def start_simulation(background_tasks: BackgroundTasks | None = None) -> str:
    """
    Start the simulation loop.

    Called on startup (with background_tasks=None, using asyncio.create_task)
    or from the API (with BackgroundTasks, using FastAPI's background machinery).
    """
    global simulation_running
    if simulation_running:
        return "already_running"

    simulation_running = True
    inventory.init_simulation_state()
    init_line_state()

    if background_tasks is not None:
        background_tasks.add_task(simulation_loop)
    else:
        asyncio.create_task(simulation_loop())

    return "started"


def stop_simulation() -> str:
    global simulation_running
    simulation_running = False
    return "stopped"
