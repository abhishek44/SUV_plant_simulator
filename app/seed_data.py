from datetime import date, timedelta
from typing import List
from sqlmodel import Session, select
from .database import engine
from .models.master import Product, Line, Shift, Order, BOMItem
from .models.supply import Supplier, InventoryItem
from .models.simulation import MachineParameter


def seed_master_data() -> None:
    """
    Seeds master, supply chain, BOM, and simulation data into the database.
    Skips seeding if Product table is non-empty.
    """
    today = date.today()
    dispatch = today + timedelta(days=9)

    with Session(engine) as session:
        # Skip if already seeded
        if session.exec(select(Product)).first():
            return

        # === Products ===
        products = [
            Product(product_id="P-HE", name="Premium Hybrid SUV"),
        ]
        session.add_all(products)

        # === Lines ===
        lines = [
            Line(line_id="L1", name="HighRange_Line1", product_id="P-HE", daily_capacity=100, oee_pct=0.88, mtbf_hours=150.0, mttr_hours=2.5),
            Line(line_id="L2", name="HighRange_Line2", product_id="P-HE", daily_capacity=90, oee_pct=0.85, mtbf_hours=140.0, mttr_hours=2),
            Line(line_id="L3", name="MidRange_Line1", product_id="P-ME", daily_capacity=80, oee_pct=0.87, mtbf_hours=160.0, mttr_hours=1.8),
            Line(line_id="L4", name="MidRange_Line2", product_id="P-ME", daily_capacity=75, oee_pct=0.86, mtbf_hours=155.0, mttr_hours=2.2),
            Line(line_id="L5", name="MidRange_Line3", product_id="P-ME", daily_capacity=70, oee_pct=0.84, mtbf_hours=145.0, mttr_hours=2),
        ]
        session.add_all(lines)

        # === Shifts ===
        shifts = [
            Shift(shift_id="S1", shift_timing="06:00-14:00", workers_assigned=120, skill_level="High", max_overtime_hrs=2, labor_cost_per_hr=550),
            Shift(shift_id="S2", shift_timing="14:00-22:00", workers_assigned=110, skill_level="Medium", max_overtime_hrs=2, labor_cost_per_hr=500),
            Shift(shift_id="S3", shift_timing="22:00-06:00", workers_assigned=90, skill_level="Medium", max_overtime_hrs=1, labor_cost_per_hr=480),
        ]
        session.add_all(shifts)

        # === Suppliers ===
        suppliers = [
            {"supplier_id": "SUP01", "supplier_name": "Tata Autocomp", "location": "Delhi", "lead_time_days": 2, "reliability_pct": 88, "alternate_supplier": "Yes"},
            {"supplier_id": "SUP02", "supplier_name": "Hella Electronics", "location": "Chennai", "lead_time_days": 2, "reliability_pct": 90, "alternate_supplier": "No"},
            {"supplier_id": "SUP03", "supplier_name": "Motherson Sumi", "location": "Pune", "lead_time_days": 8, "reliability_pct": 86, "alternate_supplier": "No"},
            {"supplier_id": "SUP04", "supplier_name": "Panasonic Energy", "location": "Bangalore", "lead_time_days": 8, "reliability_pct": 92, "alternate_supplier": "No"},
            {"supplier_id": "SUP05", "supplier_name": "Panasonic Energy", "location": "Germany", "lead_time_days": 7, "reliability_pct": 94, "alternate_supplier": "No"},
            {"supplier_id": "SUP06", "supplier_name": "Motherson Sumi", "location": "Delhi", "lead_time_days": 4, "reliability_pct": 95, "alternate_supplier": "Yes"},
            {"supplier_id": "SUP07", "supplier_name": "Panasonic Energy", "location": "Germany", "lead_time_days": 5, "reliability_pct": 86, "alternate_supplier": "Yes"},
            {"supplier_id": "SUP08", "supplier_name": "Continental Pune", "location": "Bangalore", "lead_time_days": 8, "reliability_pct": 94, "alternate_supplier": "No"},
            {"supplier_id": "SUP09", "supplier_name": "Motherson Sumi", "location": "Korea", "lead_time_days": 9, "reliability_pct": 98, "alternate_supplier": "No"},
            {"supplier_id": "SUP10", "supplier_name": "Panasonic Energy", "location": "Delhi", "lead_time_days": 9, "reliability_pct": 97, "alternate_supplier": "Yes"},
            {"supplier_id": "SUP11", "supplier_name": "Panasonic Energy", "location": "Chennai", "lead_time_days": 9, "reliability_pct": 98, "alternate_supplier": "No"},
            {"supplier_id": "SUP12", "supplier_name": "Bosch India", "location": "Pune", "lead_time_days": 6, "reliability_pct": 85, "alternate_supplier": "No"},
            {"supplier_id": "SUP13", "supplier_name": "Tata Autocomp", "location": "Germany", "lead_time_days": 2, "reliability_pct": 89, "alternate_supplier": "No"},
            {"supplier_id": "SUP14", "supplier_name": "Hitachi Automotive", "location": "Chennai", "lead_time_days": 4, "reliability_pct": 92, "alternate_supplier": "Yes"},
            {"supplier_id": "SUP15", "supplier_name": "Panasonic Energy", "location": "Pune", "lead_time_days": 8, "reliability_pct": 94, "alternate_supplier": "No"},
            {"supplier_id": "SUP16", "supplier_name": "Tata Autocomp", "location": "Germany", "lead_time_days": 8, "reliability_pct": 85, "alternate_supplier": "No"},
            {"supplier_id": "SUP17", "supplier_name": "Delphi India", "location": "Bangalore", "lead_time_days": 8, "reliability_pct": 94, "alternate_supplier": "Yes"},
            {"supplier_id": "SUP18", "supplier_name": "Panasonic Energy", "location": "Bangalore", "lead_time_days": 4, "reliability_pct": 91, "alternate_supplier": "Yes"},
            {"supplier_id": "SUP19", "supplier_name": "Tata Autocomp", "location": "Chennai", "lead_time_days": 4, "reliability_pct": 90, "alternate_supplier": "No"},
            {"supplier_id": "SUP20", "supplier_name": "Bosch India", "location": "Delhi", "lead_time_days": 9, "reliability_pct": 87, "alternate_supplier": "Yes"},
        ]
        session.add_all([Supplier(**s) for s in suppliers])

        # === Inventory Items ===
        inv_items = [
            {"material_id": "M001", "description": "Motor", "category": "Mechanical", "reorder_point": 85, "safety_stock": 46, "lead_time_days": 4, "supplier_id": "SUP14", "current_stock": 850, "unit_cost_inr": 1682},
            {"material_id": "M002", "description": "Motor", "category": "Interior", "reorder_point": 61, "safety_stock": 49, "lead_time_days": 6, "supplier_id": "SUP08", "current_stock": 870, "unit_cost_inr": 1317},
            {"material_id": "M003", "description": "Paint", "category": "Mechanical", "reorder_point": 92, "safety_stock": 47, "lead_time_days": 7, "supplier_id": "SUP17", "current_stock": 1960, "unit_cost_inr": 19255},
            {"material_id": "M004", "description": "Tyre", "category": "Interior", "reorder_point": 95, "safety_stock": 22, "lead_time_days": 3, "supplier_id": "SUP10", "current_stock": 420, "unit_cost_inr": 19209},
            {"material_id": "M005", "description": "Tyre", "category": "Mechanical", "reorder_point": 117, "safety_stock": 20, "lead_time_days": 5, "supplier_id": "SUP01", "current_stock": 3200, "unit_cost_inr": 13677},  # ← updated
            {"material_id": "M006", "description": "BodyFrame", "category": "Body", "reorder_point": 120, "safety_stock": 39, "lead_time_days": 6, "supplier_id": "SUP03", "current_stock": 500, "unit_cost_inr": 10604},  # ← updated
            {"material_id": "M007", "description": "Dashboard", "category": "Mechanical", "reorder_point": 122, "safety_stock": 23, "lead_time_days": 9, "supplier_id": "SUP14", "current_stock": 4000, "unit_cost_inr": 3817},  # ← updated
            {"material_id": "M008", "description": "Sensor", "category": "Interior", "reorder_point": 131, "safety_stock": 41, "lead_time_days": 2, "supplier_id": "SUP14", "current_stock": 1350, "unit_cost_inr": 14759},
            {"material_id": "M009", "description": "WiringHarness", "category": "Interior", "reorder_point": 72, "safety_stock": 31, "lead_time_days": 8, "supplier_id": "SUP20", "current_stock": 2500, "unit_cost_inr": 4481},  # ← updated
            {"material_id": "M010", "description": "WiringHarness", "category": "Interior", "reorder_point": 95, "safety_stock": 46, "lead_time_days": 9, "supplier_id": "SUP13", "current_stock": 1280, "unit_cost_inr": 18572},
            {"material_id": "M011", "description": "Dashboard", "category": "Electrical", "reorder_point": 146, "safety_stock": 34, "lead_time_days": 8, "supplier_id": "SUP18", "current_stock": 880, "unit_cost_inr": 10950},
            {"material_id": "M012", "description": "BodyFrame", "category": "Mechanical", "reorder_point": 87, "safety_stock": 30, "lead_time_days": 7, "supplier_id": "SUP19", "current_stock": 2500, "unit_cost_inr": 5291},  # ← updated
            {"material_id": "M013", "description": "Battery", "category": "Interior", "reorder_point": 68, "safety_stock": 36, "lead_time_days": 5, "supplier_id": "SUP05", "current_stock": 4000, "unit_cost_inr": 14302},  # ← updated
            {"material_id": "M014", "description": "Chip", "category": "Interior", "reorder_point": 98, "safety_stock": 25, "lead_time_days": 3, "supplier_id": "SUP06", "current_stock": 3000, "unit_cost_inr": 13922},  # ← updated
            {"material_id": "M015", "description": "BodyFrame", "category": "Mechanical", "reorder_point": 131, "safety_stock": 39, "lead_time_days": 2, "supplier_id": "SUP02", "current_stock": 1860, "unit_cost_inr": 10457},
            {"material_id": "M016", "description": "BodyFrame", "category": "Interior", "reorder_point": 94, "safety_stock": 29, "lead_time_days": 9, "supplier_id": "SUP02", "current_stock": 650, "unit_cost_inr": 19734},
            {"material_id": "M017", "description": "BodyFrame", "category": "Electrical", "reorder_point": 87, "safety_stock": 35, "lead_time_days": 5, "supplier_id": "SUP15", "current_stock": 1580, "unit_cost_inr": 14144},
            {"material_id": "M018", "description": "Battery", "category": "Electrical", "reorder_point": 62, "safety_stock": 33, "lead_time_days": 4, "supplier_id": "SUP02", "current_stock": 2400, "unit_cost_inr": 6453},  # ← updated
            {"material_id": "M019", "description": "Battery", "category": "Electrical", "reorder_point": 107, "safety_stock": 27, "lead_time_days": 9, "supplier_id": "SUP15", "current_stock": 1790, "unit_cost_inr": 3761},
            {"material_id": "M020", "description": "BodyFrame", "category": "Body", "reorder_point": 116, "safety_stock": 26, "lead_time_days": 8, "supplier_id": "SUP18", "current_stock": 4500, "unit_cost_inr": 11311},  # ← updated
            {"material_id": "M021", "description": "Chip", "category": "Body", "reorder_point": 71, "safety_stock": 44, "lead_time_days": 8, "supplier_id": "SUP12", "current_stock": 1040, "unit_cost_inr": 3035},
            {"material_id": "M022", "description": "Seat", "category": "Body", "reorder_point": 56, "safety_stock": 25, "lead_time_days": 5, "supplier_id": "SUP11", "current_stock": 400, "unit_cost_inr": 16796},  # ← updated (was 1820 → now 400 as per Required)
            {"material_id": "M023", "description": "WiringHarness", "category": "Electrical", "reorder_point": 103, "safety_stock": 38, "lead_time_days": 6, "supplier_id": "SUP07", "current_stock": 990, "unit_cost_inr": 8032},
            {"material_id": "M024", "description": "WiringHarness", "category": "Interior", "reorder_point": 56, "safety_stock": 32, "lead_time_days": 5, "supplier_id": "SUP20", "current_stock": 3500, "unit_cost_inr": 10516},  # ← updated
            {"material_id": "M025", "description": "Battery", "category": "Interior", "reorder_point": 116, "safety_stock": 28, "lead_time_days": 3, "supplier_id": "SUP16", "current_stock": 500, "unit_cost_inr": 11852},  # ← updated
            {"material_id": "M026", "description": "WiringHarness", "category": "Interior", "reorder_point": 142, "safety_stock": 23, "lead_time_days": 9, "supplier_id": "SUP16", "current_stock": 1000, "unit_cost_inr": 5965},  # ← updated
            {"material_id": "M027", "description": "BodyFrame", "category": "Mechanical", "reorder_point": 143, "safety_stock": 45, "lead_time_days": 3, "supplier_id": "SUP13", "current_stock": 710, "unit_cost_inr": 13182},
            {"material_id": "M028", "description": "BodyFrame", "category": "Interior", "reorder_point": 130, "safety_stock": 32, "lead_time_days": 4, "supplier_id": "SUP16", "current_stock": 1100, "unit_cost_inr": 19238},
            {"material_id": "M029", "description": "Seat", "category": "Body", "reorder_point": 87, "safety_stock": 24, "lead_time_days": 5, "supplier_id": "SUP10", "current_stock": 3000, "unit_cost_inr": 16346},  # ← updated
            {"material_id": "M030", "description": "Chip", "category": "Body", "reorder_point": 147, "safety_stock": 37, "lead_time_days": 5, "supplier_id": "SUP01", "current_stock": 1450, "unit_cost_inr": 8914},
            {"material_id": "M031", "description": "Motor", "category": "Electrical", "reorder_point": 103, "safety_stock": 40, "lead_time_days": 9, "supplier_id": "SUP07", "current_stock": 1060, "unit_cost_inr": 14800},
            {"material_id": "M032", "description": "Battery", "category": "Body", "reorder_point": 136, "safety_stock": 38, "lead_time_days": 9, "supplier_id": "SUP08", "current_stock": 1330, "unit_cost_inr": 17009},
            {"material_id": "M033", "description": "Tyre", "category": "Mechanical", "reorder_point": 114, "safety_stock": 21, "lead_time_days": 4, "supplier_id": "SUP04", "current_stock": 1920, "unit_cost_inr": 9216},
            {"material_id": "M034", "description": "Tyre", "category": "Interior", "reorder_point": 140, "safety_stock": 35, "lead_time_days": 8, "supplier_id": "SUP19", "current_stock": 1490, "unit_cost_inr": 11593},
            {"material_id": "M035", "description": "WiringHarness", "category": "Interior", "reorder_point": 86, "safety_stock": 32, "lead_time_days": 3, "supplier_id": "SUP03", "current_stock": 4800, "unit_cost_inr": 13113},  # ← updated
            {"material_id": "M036", "description": "Seat", "category": "Electrical", "reorder_point": 95, "safety_stock": 22, "lead_time_days": 8, "supplier_id": "SUP15", "current_stock": 1200, "unit_cost_inr": 3126},  # ← updated
            {"material_id": "M037", "description": "Sensor", "category": "Interior", "reorder_point": 84, "safety_stock": 33, "lead_time_days": 7, "supplier_id": "SUP15", "current_stock": 1250, "unit_cost_inr": 2928},
            {"material_id": "M038", "description": "Paint", "category": "Electrical", "reorder_point": 55, "safety_stock": 26, "lead_time_days": 9, "supplier_id": "SUP03", "current_stock": 410, "unit_cost_inr": 7600},
            {"material_id": "M039", "description": "BodyFrame", "category": "Interior", "reorder_point": 82, "safety_stock": 39, "lead_time_days": 3, "supplier_id": "SUP20", "current_stock": 880, "unit_cost_inr": 14645},
            {"material_id": "M040", "description": "Sensor", "category": "Body", "reorder_point": 100, "safety_stock": 26, "lead_time_days": 4, "supplier_id": "SUP07", "current_stock": 3800, "unit_cost_inr": 1533},  # ← updated
            {"material_id": "M041", "description": "Paint", "category": "Mechanical", "reorder_point": 119, "safety_stock": 47, "lead_time_days": 8, "supplier_id": "SUP01", "current_stock": 1960, "unit_cost_inr": 2719},
            {"material_id": "M042", "description": "Dashboard", "category": "Body", "reorder_point": 136, "safety_stock": 25, "lead_time_days": 7, "supplier_id": "SUP05", "current_stock": 560, "unit_cost_inr": 7163},
            {"material_id": "M043", "description": "Tyre", "category": "Electrical", "reorder_point": 108, "safety_stock": 33, "lead_time_days": 3, "supplier_id": "SUP18", "current_stock": 3500, "unit_cost_inr": 2041},  # ← updated
            {"material_id": "M044", "description": "Paint", "category": "Electrical", "reorder_point": 121, "safety_stock": 22, "lead_time_days": 2, "supplier_id": "SUP11", "current_stock": 3000, "unit_cost_inr": 5405},  # ← updated
            {"material_id": "M045", "description": "Tyre", "category": "Body", "reorder_point": 76, "safety_stock": 49, "lead_time_days": 9, "supplier_id": "SUP18", "current_stock": 1200, "unit_cost_inr": 18911},  # ← updated
            {"material_id": "M046", "description": "WiringHarness", "category": "Body", "reorder_point": 69, "safety_stock": 44, "lead_time_days": 2, "supplier_id": "SUP18", "current_stock": 1960, "unit_cost_inr": 17877},
            {"material_id": "M047", "description": "Battery", "category": "Mechanical", "reorder_point": 147, "safety_stock": 36, "lead_time_days": 6, "supplier_id": "SUP18", "current_stock": 970, "unit_cost_inr": 10579},
            {"material_id": "M048", "description": "Dashboard", "category": "Electrical", "reorder_point": 62, "safety_stock": 43, "lead_time_days": 6, "supplier_id": "SUP20", "current_stock": 530, "unit_cost_inr": 13079},
            {"material_id": "M049", "description": "Tyre", "category": "Electrical", "reorder_point": 141, "safety_stock": 23, "lead_time_days": 7, "supplier_id": "SUP01", "current_stock": 960, "unit_cost_inr": 10466},
            {"material_id": "M050", "description": "Dashboard", "category": "Mechanical", "reorder_point": 85, "safety_stock": 22, "lead_time_days": 7, "supplier_id": "SUP15", "current_stock": 790, "unit_cost_inr": 2130},
            {"material_id": "M051", "description": "BodyFrame", "category": "Interior", "reorder_point": 81, "safety_stock": 40, "lead_time_days": 6, "supplier_id": "SUP13", "current_stock": 1130, "unit_cost_inr": 14987},
            {"material_id": "M052", "description": "Seat", "category": "Electrical", "reorder_point": 106, "safety_stock": 23, "lead_time_days": 8, "supplier_id": "SUP17", "current_stock": 400, "unit_cost_inr": 7552},
            {"material_id": "M053", "description": "Sensor", "category": "Electrical", "reorder_point": 119, "safety_stock": 27, "lead_time_days": 9, "supplier_id": "SUP01", "current_stock": 1570, "unit_cost_inr": 5918},
            {"material_id": "M054", "description": "WiringHarness", "category": "Electrical", "reorder_point": 55, "safety_stock": 36, "lead_time_days": 4, "supplier_id": "SUP17", "current_stock": 3000, "unit_cost_inr": 19103},  # ← updated
            {"material_id": "M055", "description": "BodyFrame", "category": "Interior", "reorder_point": 116, "safety_stock": 45, "lead_time_days": 6, "supplier_id": "SUP19", "current_stock": 300, "unit_cost_inr": 4898},
            {"material_id": "M056", "description": "Battery", "category": "Mechanical", "reorder_point": 79, "safety_stock": 21, "lead_time_days": 7, "supplier_id": "SUP09", "current_stock": 1000, "unit_cost_inr": 3942},  # ← updated
            {"material_id": "M057", "description": "Paint", "category": "Electrical", "reorder_point": 62, "safety_stock": 25, "lead_time_days": 5, "supplier_id": "SUP04", "current_stock": 860, "unit_cost_inr": 16926},
            {"material_id": "M058", "description": "Dashboard", "category": "Mechanical", "reorder_point": 131, "safety_stock": 31, "lead_time_days": 9, "supplier_id": "SUP12", "current_stock": 1840, "unit_cost_inr": 18236},
            {"material_id": "M059", "description": "WiringHarness", "category": "Mechanical", "reorder_point": 66, "safety_stock": 40, "lead_time_days": 2, "supplier_id": "SUP20", "current_stock": 1150, "unit_cost_inr": 5955},
            {"material_id": "M060", "description": "Seat", "category": "Electrical", "reorder_point": 62, "safety_stock": 29, "lead_time_days": 7, "supplier_id": "SUP02", "current_stock": 1980, "unit_cost_inr": 13457},
            {"material_id": "M061", "description": "Seat", "category": "Body", "reorder_point": 50, "safety_stock": 46, "lead_time_days": 8, "supplier_id": "SUP03", "current_stock": 3500, "unit_cost_inr": 9120},  # ← updated
            {"material_id": "M062", "description": "Battery", "category": "Mechanical", "reorder_point": 80, "safety_stock": 24, "lead_time_days": 4, "supplier_id": "SUP14", "current_stock": 1860, "unit_cost_inr": 9758},
            {"material_id": "M063", "description": "Motor", "category": "Interior", "reorder_point": 80, "safety_stock": 21, "lead_time_days": 5, "supplier_id": "SUP18", "current_stock": 1090, "unit_cost_inr": 14902},
            {"material_id": "M064", "description": "Paint", "category": "Mechanical", "reorder_point": 135, "safety_stock": 27, "lead_time_days": 2, "supplier_id": "SUP20", "current_stock": 1950, "unit_cost_inr": 4412},
            {"material_id": "M065", "description": "Chip", "category": "Body", "reorder_point": 60, "safety_stock": 47, "lead_time_days": 9, "supplier_id": "SUP20", "current_stock": 1810, "unit_cost_inr": 19545},
            {"material_id": "M066", "description": "BodyFrame", "category": "Interior", "reorder_point": 126, "safety_stock": 48, "lead_time_days": 2, "supplier_id": "SUP18", "current_stock": 1390, "unit_cost_inr": 13497},
            {"material_id": "M067", "description": "Dashboard", "category": "Mechanical", "reorder_point": 126, "safety_stock": 41, "lead_time_days": 3, "supplier_id": "SUP08", "current_stock": 510, "unit_cost_inr": 1834},
            {"material_id": "M068", "description": "Sensor", "category": "Mechanical", "reorder_point": 54, "safety_stock": 37, "lead_time_days": 3, "supplier_id": "SUP13", "current_stock": 4000, "unit_cost_inr": 16464},  # ← updated
            {"material_id": "M069", "description": "Seat", "category": "Mechanical", "reorder_point": 113, "safety_stock": 43, "lead_time_days": 2, "supplier_id": "SUP17", "current_stock": 1560, "unit_cost_inr": 969},
            {"material_id": "M070", "description": "Motor", "category": "Mechanical", "reorder_point": 105, "safety_stock": 29, "lead_time_days": 7, "supplier_id": "SUP09", "current_stock": 1480, "unit_cost_inr": 2072},
            {"material_id": "M071", "description": "Paint", "category": "Interior", "reorder_point": 98, "safety_stock": 41, "lead_time_days": 6, "supplier_id": "SUP01", "current_stock": 1640, "unit_cost_inr": 18662},
            {"material_id": "M072", "description": "Seat", "category": "Body", "reorder_point": 143, "safety_stock": 47, "lead_time_days": 6, "supplier_id": "SUP12", "current_stock": 900, "unit_cost_inr": 9986},
            {"material_id": "M073", "description": "WiringHarness", "category": "Electrical", "reorder_point": 76, "safety_stock": 48, "lead_time_days": 4, "supplier_id": "SUP01", "current_stock": 1780, "unit_cost_inr": 17828},
            {"material_id": "M074", "description": "Dashboard", "category": "Body", "reorder_point": 51, "safety_stock": 32, "lead_time_days": 9, "supplier_id": "SUP04", "current_stock": 1320, "unit_cost_inr": 11772},
            {"material_id": "M075", "description": "Motor", "category": "Interior", "reorder_point": 99, "safety_stock": 37, "lead_time_days": 2, "supplier_id": "SUP14", "current_stock": 1850, "unit_cost_inr": 13746},
            {"material_id": "M076", "description": "Chip", "category": "Electrical", "reorder_point": 137, "safety_stock": 24, "lead_time_days": 3, "supplier_id": "SUP09", "current_stock": 2000, "unit_cost_inr": 7000},  # ← updated
            {"material_id": "M077", "description": "Motor", "category": "Mechanical", "reorder_point": 145, "safety_stock": 48, "lead_time_days": 9, "supplier_id": "SUP14", "current_stock": 970, "unit_cost_inr": 1454},
            {"material_id": "M078", "description": "BodyFrame", "category": "Interior", "reorder_point": 93, "safety_stock": 41, "lead_time_days": 8, "supplier_id": "SUP06", "current_stock": 1400, "unit_cost_inr": 14421},
            {"material_id": "M079", "description": "Paint", "category": "Mechanical", "reorder_point": 88, "safety_stock": 44, "lead_time_days": 8, "supplier_id": "SUP01", "current_stock": 4900, "unit_cost_inr": 13258},  # ← updated
            {"material_id": "M080", "description": "Paint", "category": "Electrical", "reorder_point": 94, "safety_stock": 46, "lead_time_days": 6, "supplier_id": "SUP09", "current_stock": 1560, "unit_cost_inr": 5383},
            {"material_id": "M081", "description": "Paint", "category": "Electrical", "reorder_point": 60, "safety_stock": 30, "lead_time_days": 9, "supplier_id": "SUP14", "current_stock": 1920, "unit_cost_inr": 12585},
            {"material_id": "M082", "description": "Seat", "category": "Body", "reorder_point": 148, "safety_stock": 21, "lead_time_days": 5, "supplier_id": "SUP08", "current_stock": 2000, "unit_cost_inr": 16219},  # ← updated
            {"material_id": "M083", "description": "Paint", "category": "Electrical", "reorder_point": 84, "safety_stock": 28, "lead_time_days": 5, "supplier_id": "SUP08", "current_stock": 400, "unit_cost_inr": 15037},  # ← updated (was 1450 → now 400)
            {"material_id": "M084", "description": "Seat", "category": "Electrical", "reorder_point": 69, "safety_stock": 20, "lead_time_days": 9, "supplier_id": "SUP10", "current_stock": 1800, "unit_cost_inr": 19965},
            {"material_id": "M085", "description": "Battery", "category": "Body", "reorder_point": 115, "safety_stock": 21, "lead_time_days": 2, "supplier_id": "SUP05", "current_stock": 530, "unit_cost_inr": 13555},
            {"material_id": "M086", "description": "Seat", "category": "Body", "reorder_point": 94, "safety_stock": 32, "lead_time_days": 7, "supplier_id": "SUP16", "current_stock": 380, "unit_cost_inr": 8579},
            {"material_id": "M087", "description": "Motor", "category": "Mechanical", "reorder_point": 53, "safety_stock": 37, "lead_time_days": 8, "supplier_id": "SUP01", "current_stock": 1500, "unit_cost_inr": 19632},  # ← updated
            {"material_id": "M088", "description": "Motor", "category": "Body", "reorder_point": 118, "safety_stock": 42, "lead_time_days": 2, "supplier_id": "SUP07", "current_stock": 800, "unit_cost_inr": 15205},  # ← updated
            {"material_id": "M089", "description": "Chip", "category": "Electrical", "reorder_point": 103, "safety_stock": 49, "lead_time_days": 8, "supplier_id": "SUP16", "current_stock": 1960, "unit_cost_inr": 17901},
            {"material_id": "M090", "description": "Dashboard", "category": "Mechanical", "reorder_point": 59, "safety_stock": 49, "lead_time_days": 6, "supplier_id": "SUP18", "current_stock": 370, "unit_cost_inr": 1925},
            {"material_id": "M091", "description": "Dashboard", "category": "Interior", "reorder_point": 91, "safety_stock": 21, "lead_time_days": 2, "supplier_id": "SUP04", "current_stock": 1200, "unit_cost_inr": 19514},
            {"material_id": "M092", "description": "Dashboard", "category": "Mechanical", "reorder_point": 99, "safety_stock": 27, "lead_time_days": 8, "supplier_id": "SUP18", "current_stock": 1880, "unit_cost_inr": 11530},
            {"material_id": "M093", "description": "Battery", "category": "Mechanical", "reorder_point": 128, "safety_stock": 32, "lead_time_days": 2, "supplier_id": "SUP01", "current_stock": 2000, "unit_cost_inr": 17442},  # ← updated
            {"material_id": "M094", "description": "Dashboard", "category": "Interior", "reorder_point": 143, "safety_stock": 38, "lead_time_days": 9, "supplier_id": "SUP01", "current_stock": 690, "unit_cost_inr": 18975},
            {"material_id": "M095", "description": "BodyFrame", "category": "Body", "reorder_point": 73, "safety_stock": 24, "lead_time_days": 3, "supplier_id": "SUP01", "current_stock": 1030, "unit_cost_inr": 7827},
            {"material_id": "M096", "description": "Paint", "category": "Mechanical", "reorder_point": 115, "safety_stock": 43, "lead_time_days": 3, "supplier_id": "SUP13", "current_stock": 920, "unit_cost_inr": 1351},
            {"material_id": "M097", "description": "Motor", "category": "Body", "reorder_point": 88, "safety_stock": 39, "lead_time_days": 8, "supplier_id": "SUP19", "current_stock": 870, "unit_cost_inr": 10058},
            {"material_id": "M098", "description": "Paint", "category": "Mechanical", "reorder_point": 64, "safety_stock": 41, "lead_time_days": 2, "supplier_id": "SUP04", "current_stock": 980, "unit_cost_inr": 4493},
            {"material_id": "M099", "description": "Dashboard", "category": "Mechanical", "reorder_point": 52, "safety_stock": 38, "lead_time_days": 8, "supplier_id": "SUP09", "current_stock": 360, "unit_cost_inr": 1408},
            {"material_id": "M100", "description": "Sensor", "category": "Interior", "reorder_point": 147, "safety_stock": 22, "lead_time_days": 5, "supplier_id": "SUP09", "current_stock": 1090, "unit_cost_inr": 11990},
            {"material_id": "M101", "description": "Tyre", "category": "Interior", "reorder_point": 70, "safety_stock": 22, "lead_time_days": 8, "supplier_id": "SUP15", "current_stock": 2400, "unit_cost_inr": 3790},  # ← updated
            {"material_id": "M102", "description": "Seat", "category": "Interior", "reorder_point": 137, "safety_stock": 27, "lead_time_days": 5, "supplier_id": "SUP14", "current_stock": 1180, "unit_cost_inr": 19233},
            {"material_id": "M103", "description": "Paint", "category": "Electrical", "reorder_point": 141, "safety_stock": 31, "lead_time_days": 7, "supplier_id": "SUP14", "current_stock": 3600, "unit_cost_inr": 9978},  # ← updated
            {"material_id": "M104", "description": "Sensor", "category": "Interior", "reorder_point": 68, "safety_stock": 33, "lead_time_days": 7, "supplier_id": "SUP03", "current_stock": 800, "unit_cost_inr": 4568},  # ← updated
            {"material_id": "M105", "description": "Tyre", "category": "Electrical", "reorder_point": 95, "safety_stock": 43, "lead_time_days": 7, "supplier_id": "SUP01", "current_stock": 1000, "unit_cost_inr": 2095},  # ← updated
            {"material_id": "M106", "description": "BodyFrame", "category": "Body", "reorder_point": 56, "safety_stock": 37, "lead_time_days": 3, "supplier_id": "SUP20", "current_stock": 560, "unit_cost_inr": 3436},
            {"material_id": "M107", "description": "Tyre", "category": "Electrical", "reorder_point": 94, "safety_stock": 27, "lead_time_days": 5, "supplier_id": "SUP03", "current_stock": 440, "unit_cost_inr": 6023},
            {"material_id": "M108", "description": "Chip", "category": "Interior", "reorder_point": 130, "safety_stock": 27, "lead_time_days": 2, "supplier_id": "SUP01", "current_stock": 2500, "unit_cost_inr": 17499},  # ← updated
            {"material_id": "M109", "description": "Seat", "category": "Interior", "reorder_point": 54, "safety_stock": 44, "lead_time_days": 5, "supplier_id": "SUP05", "current_stock": 1590, "unit_cost_inr": 5979},
            {"material_id": "M110", "description": "Sensor", "category": "Mechanical", "reorder_point": 98, "safety_stock": 25, "lead_time_days": 7, "supplier_id": "SUP07", "current_stock": 1500, "unit_cost_inr": 7020},  # ← updated
            {"material_id": "M111", "description": "WiringHarness", "category": "Interior", "reorder_point": 135, "safety_stock": 38, "lead_time_days": 2, "supplier_id": "SUP06", "current_stock": 680, "unit_cost_inr": 16528},
            {"material_id": "M112", "description": "BodyFrame", "category": "Electrical", "reorder_point": 81, "safety_stock": 32, "lead_time_days": 3, "supplier_id": "SUP14", "current_stock": 1760, "unit_cost_inr": 11489},
            {"material_id": "M113", "description": "BodyFrame", "category": "Electrical", "reorder_point": 93, "safety_stock": 47, "lead_time_days": 9, "supplier_id": "SUP08", "current_stock": 1500, "unit_cost_inr": 4226},  # ← updated
            {"material_id": "M114", "description": "Tyre", "category": "Mechanical", "reorder_point": 63, "safety_stock": 25, "lead_time_days": 4, "supplier_id": "SUP11", "current_stock": 1200, "unit_cost_inr": 18176},  # ← updated
            {"material_id": "M115", "description": "Battery", "category": "Body", "reorder_point": 79, "safety_stock": 42, "lead_time_days": 9, "supplier_id": "SUP15", "current_stock": 800, "unit_cost_inr": 10045},  # ← updated
            {"material_id": "M116", "description": "Tyre", "category": "Electrical", "reorder_point": 83, "safety_stock": 26, "lead_time_days": 2, "supplier_id": "SUP04", "current_stock": 650, "unit_cost_inr": 7007},
            {"material_id": "M117", "description": "Motor", "category": "Mechanical", "reorder_point": 50, "safety_stock": 40, "lead_time_days": 6, "supplier_id": "SUP05", "current_stock": 3500, "unit_cost_inr": 16987},  # ← updated
            {"material_id": "M118", "description": "Battery", "category": "Body", "reorder_point": 52, "safety_stock": 45, "lead_time_days": 5, "supplier_id": "SUP06", "current_stock": 5900, "unit_cost_inr": 19968},  # ← updated
            {"material_id": "M119", "description": "WiringHarness", "category": "Body", "reorder_point": 80, "safety_stock": 30, "lead_time_days": 8, "supplier_id": "SUP07", "current_stock": 820, "unit_cost_inr": 10355},
            {"material_id": "M120", "description": "Dashboard", "category": "Interior", "reorder_point": 112, "safety_stock": 33, "lead_time_days": 5, "supplier_id": "SUP08", "current_stock": 590, "unit_cost_inr": 2582},
        ]
        session.add_all([InventoryItem(**itm) for itm in inv_items])

        # === BOM Items ===
        bom_data = [
            ("P-ME", "M103", 9),
            ("P-HE", "M020", 9),
            ("P-ME", "M082", 5),
            ("P-HE", "M029", 6),
            ("P-ME", "M018", 6),
            ("P-ME", "M022", 1),
            ("P-HE", "M108", 5),
            ("P-ME", "M088", 2),
            ("P-HE", "M093", 4),
            ("P-HE", "M079", 9),
            ("P-ME", "M079", 1),  # duplicate in source — kept once
            ("P-ME", "M045", 3),
            ("P-HE", "M087", 3),
            ("P-ME", "M013", 10),  # duplicate in source — kept once
            ("P-ME", "M115", 2),
            ("P-ME", "M083", 1),
            ("P-HE", "M068", 8),
            ("P-HE", "M009", 5),
            ("P-ME", "M104", 2),
            ("P-HE", "M110", 3),
            ("P-HE", "M012", 5),
            ("P-HE", "M076", 4),
            ("P-HE", "M024", 7),
            ("P-ME", "M118", 6),  # duplicate in source — kept once
            ("P-HE", "M043", 7),
            ("P-HE", "M105", 2),
            ("P-HE", "M056", 2),
            ("P-ME", "M040", 2),
            ("P-ME", "M036", 3),
            ("P-HE", "M118", 7),  # duplicate in source — kept once
            ("P-HE", "M007", 8),
            ("P-HE", "M006", 1),
            ("P-HE", "M061", 7),
            ("P-ME", "M114", 3),
            ("P-HE", "M014", 6),
            ("P-HE", "M026", 2),
            ("P-HE", "M054", 6),
            ("P-HE", "M117", 7),
            ("P-HE", "M113", 3),
            ("P-ME", "M005", 8),
            ("P-HE", "M025", 1),
            ("P-ME", "M035", 12),
            ("P-HE", "M040", 6),
            ("P-HE", "M044", 6),
            ("P-ME", "M101", 6),
        ]

        # Deduplicate: last occurrence wins (or use first — adjust as needed)
        unique_bom = {}
        for pid, mid, qty in bom_data:
            unique_bom[(pid, mid)] = qty

        bom_rows = [
            BOMItem(product_id=pid, material_id=mid, quantity_per_unit=qty)
            for (pid, mid), qty in unique_bom.items()
        ]
        session.add_all(bom_rows)

        # === Machine Parameters ===
        machine_params = [
            {"machine_id": "MC008", "line_id": "L1", "parameter": "Vibration", "threshold": 138, "current_value": 101, "oee_pct": 93},
            {"machine_id": "MC012", "line_id": "L1", "parameter": "Pressure", "threshold": 141, "current_value": 75, "oee_pct": 76},
            {"machine_id": "MC002", "line_id": "L2", "parameter": "Speed", "threshold": 135, "current_value": 76, "oee_pct": 91},
            {"machine_id": "MC005", "line_id": "L2", "parameter": "Vibration", "threshold": 62, "current_value": 134, "oee_pct": 94},
        ]
        session.add_all([MachineParameter(**mp) for mp in machine_params])

        # === Orders ===
        orders = [
            Order(order_id="ORD-HE-001", product_id="P-HE", quantity=500, start_date=today, dispatch_date=dispatch, status="OPEN"),
            Order(order_id="ORD-ME-001", product_id="P-ME", quantity=400, start_date=today, dispatch_date=dispatch, status="OPEN"),
        ]
        session.add_all(orders)

        session.commit()