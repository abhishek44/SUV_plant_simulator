# app/services/inventory.py

from typing import Dict, List

from sqlmodel import Session, select

from ..database import engine
from ..models.master import BOMItem, Order
from ..models.supply import InventoryItem, PurchaseOrder

# In-memory simulation state shared with the simulation loop
inventory_state: Dict[str, int] = {}                 # live stock used by the sim
initial_inventory_total: int = 0                     # sum of all BOM material stock at t0
initial_inventory_by_material: Dict[str, int] = {}   # seed stock per material
bom_by_product: Dict[str, List[BOMItem]] = {}        # BOM rows per product


def init_simulation_state() -> None:
    """
    Load BOM for all products and initial inventory into memory.

    Called once at startup (after seeding & planning) and can also be
    called to re-initialize the sim if needed.
    """
    global inventory_state, initial_inventory_total, initial_inventory_by_material, bom_by_product

    with Session(engine) as session:
        # Load all BOM items and group by product
        all_bom = session.exec(select(BOMItem)).all()
        bom_by_product = {}
        mat_ids = set()

        for b in all_bom:
            bom_by_product.setdefault(b.product_id, []).append(b)
            mat_ids.add(b.material_id)

        if not mat_ids:
            inventory_state = {}
            initial_inventory_by_material = {}
            initial_inventory_total = 0
            return

        # Load inventory only for materials used in any BOM
        inv_items = session.exec(
            select(InventoryItem).where(InventoryItem.material_id.in_(list(mat_ids)))
        ).all()

        inventory_state = {item.material_id: item.current_stock for item in inv_items}
        initial_inventory_by_material = dict(inventory_state)
        initial_inventory_total = sum(inventory_state.values())


def get_inventory_view(session: Session):
    """
    Returns a richer inventory status table for the dashboard.

    For each material used in ANY BOM (P-HE or P-ME), we compute:
      - total required quantity across *all* orders
      - seed stock (simulation start)
      - consumed so far (seed − current)
      - current stock (live from simulation)
      - remaining requirement: max(0, required - current)
      - per-unit cost (unit_cost_inr)
      - total procurement cost for remaining requirement (remaining × unit_cost_inr)
      - purchase order details (qty, ETA, status)

    All quantities are derived from a single consistent “required” value so that:
        remaining_requirement = max(0, required_for_order - current_stock)
    holds by construction.
    """
    global bom_by_product, inventory_state, initial_inventory_by_material

    # 1) Aggregate order quantities by product (all orders for this demo)
    orders = session.exec(select(Order)).all()
    if not orders:
        return []

    qty_by_product: Dict[str, int] = {}
    for o in orders:
        qty_by_product[o.product_id] = qty_by_product.get(o.product_id, 0) + o.quantity

    # 2) Compute required units per material across all products
    required_by_material: Dict[str, int] = {}

    for product_id, total_qty in qty_by_product.items():
        bom_list = bom_by_product.get(product_id, [])
        for b in bom_list:
            required_by_material[b.material_id] = required_by_material.get(
                b.material_id, 0
            ) + b.quantity_per_unit * total_qty

    if not required_by_material:
        return []

    mat_ids = list(required_by_material.keys())

    # 3) Fetch inventory rows for those materials
    inv_items = session.exec(
        select(InventoryItem).where(InventoryItem.material_id.in_(mat_ids))
    ).all()
    items_by_id = {i.material_id: i for i in inv_items}

    out = []

    for mid, required in required_by_material.items():
        itm = items_by_id.get(mid)
        if not itm:
            continue

        # Seed = starting stock at sim init; fall back to DB stock if missing
        seed = initial_inventory_by_material.get(mid, itm.current_stock)
        current = inventory_state.get(mid, seed)

        consumed = max(0, seed - current)
        remaining_requirement = max(0, required - current)

        unit_cost = getattr(itm, "unit_cost_inr", None)
        total_cost = (
            remaining_requirement * unit_cost if unit_cost is not None else None
        )

        # Open PO info (if any)
        po = session.exec(
            select(PurchaseOrder).where(
                PurchaseOrder.material_id == mid,
                PurchaseOrder.status != "DELIVERED",
            )
        ).first()

        po_qty = po.quantity if po else None
        po_eta = po.eta_date.isoformat() if po else None
        po_status = po.status if po else None

        out.append(
            {
                "material_id": mid,
                "description": itm.description,
                "required_for_order": required,
                "consumed_so_far": consumed,
                "current_stock": current,
                "seed_stock": seed,
                "remaining_requirement": remaining_requirement,
                "unit_cost_inr": unit_cost,
                "total_cost_remaining": total_cost,
                "po_quantity": po_qty,
                "po_eta": po_eta,
                "po_status": po_status,
            }
        )

    out.sort(key=lambda r: r["material_id"])
    return out
