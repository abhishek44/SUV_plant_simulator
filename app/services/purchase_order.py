# app/services/purchase_order.py

from datetime import datetime, timedelta
from typing import Dict

from sqlmodel import Session, select

from ..models.master import Order, BOMItem
from ..models.supply import InventoryItem, Supplier, PurchaseOrder
from . import inventory
from .event_logger import log_event


def update_purchase_orders(session: Session) -> None:
    """
    Deliver POs whose ETA has passed and add stock into inventory_state.
    """
    today_d = datetime.utcnow().date()

    open_pos = session.exec(
        select(PurchaseOrder).where(PurchaseOrder.status != "DELIVERED")
    ).all()

    for po in open_pos:
        if today_d >= po.eta_date:
            current = inventory.inventory_state.get(po.material_id, 0)
            inventory.inventory_state[po.material_id] = current + po.quantity
            po.status = "DELIVERED"

            log_event(
                session,
                "PO_DELIVERED",
                f"{po.po_id} delivered for {po.material_id} (qty {po.quantity})",
            )


def check_and_place_purchase_orders(session: Session) -> None:
    """
    Check material requirements for ALL orders (all products) vs *current* stock,
    and place POs for any remaining requirement where there is no open PO.

    Remaining requirement per material:
        remaining = max(0, required_for_all_orders - current_stock)
    """
    # 1) All orders
    orders = session.exec(select(Order)).all()
    if not orders:
        return

    qty_by_product: Dict[str, int] = {}
    for o in orders:
        qty_by_product[o.product_id] = qty_by_product.get(o.product_id, 0) + o.quantity

    if not qty_by_product:
        return

    # 2) Total requirement from BOM (from the live inventory module)
    required_by_material: Dict[str, int] = {}
    all_bom: Dict[str, list[BOMItem]] = inventory.bom_by_product or {}

    for product_id, total_qty in qty_by_product.items():
        bom_list = all_bom.get(product_id, [])
        for b in bom_list:
            required_by_material[b.material_id] = required_by_material.get(
                b.material_id, 0
            ) + b.quantity_per_unit * total_qty

    if not required_by_material:
        return

    mat_ids = list(required_by_material.keys())

    # 3) Inventory rows for these materials
    inv_items = session.exec(
        select(InventoryItem).where(InventoryItem.material_id.in_(mat_ids))
    ).all()
    inv_by_id: Dict[str, InventoryItem] = {i.material_id: i for i in inv_items}

    today_d = datetime.utcnow().date()

    for mid, required in required_by_material.items():
        inv = inv_by_id.get(mid)
        if not inv:
            log_event(
                session,
                "SUPPLIER_MISSING",
                f"No inventory master row for material {mid}; cannot place PO.",
            )
            continue

        seed = inventory.initial_inventory_by_material.get(mid, inv.current_stock)
        current = inventory.inventory_state.get(mid, seed)

        # Remaining requirement is based on *current* stock
        remaining_requirement = max(0, required - current)

        if remaining_requirement <= 0:
            continue

        # 4) Skip if any PO already open for this material
        existing_po = session.exec(
            select(PurchaseOrder).where(
                PurchaseOrder.material_id == mid,
                PurchaseOrder.status != "DELIVERED",
            )
        ).first()
        if existing_po:
            continue

        # 5) Place a new PO
        supplier = session.get(Supplier, inv.supplier_id)
        if not supplier:
            log_event(
                session,
                "SUPPLIER_MISSING",
                f"No supplier found for material {mid}; cannot place PO.",
            )
            continue

        eta = today_d + timedelta(days=supplier.lead_time_days)
        po_id = f"PO-{mid}-{today_d.isoformat()}"

        po = PurchaseOrder(
            po_id=po_id,
            material_id=mid,
            supplier_id=supplier.supplier_id,
            quantity=remaining_requirement,
            order_date=today_d,
            eta_date=eta,
            status="PLACED",
        )
        session.add(po)

        log_event(
            session,
            "PO_CREATED",
            f"Placed PO {po_id} for {remaining_requirement} of {mid} from {supplier.supplier_name}",
        )
