# app/services/kpi.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import mean
from typing import List, Dict

from sqlmodel import Session, select

from ..database import engine
from ..models.planning import PlanRun
from ..models.simulation import ProductionRealtime, MachineParameter
from ..models.master import Order
from ..services.inventory import get_inventory_view


@dataclass
class KPIValue:
    name: str
    value: float
    unit: str
    target: float | None
    alert_status: str  # "GREEN" | "AMBER" | "RED"


def _latest_run(session: Session) -> PlanRun | None:
    return session.exec(
        select(PlanRun).order_by(PlanRun.created_at.desc())
    ).first()


def _get_latest_realtime_by_line(session: Session, run_id: str) -> Dict[str, ProductionRealtime]:
    """
    Return the last ProductionRealtime row per line_id for a given run.
    Simple in-memory grouping; good enough for a small simulation DB.
    """
    rows = session.exec(
        select(ProductionRealtime).where(ProductionRealtime.run_id == run_id)
    ).all()

    latest_by_line: Dict[str, ProductionRealtime] = {}
    for r in rows:
        prev = latest_by_line.get(r.assembly_line)
        if prev is None or r.ts > prev.ts:
            latest_by_line[r.assembly_line] = r
    return latest_by_line


def compute_kpis() -> List[KPIValue]:
    """
    Compute a minimal KPI set from current DB & simulation state:

      - Schedule Conformance %
      - Average Material Availability %
      - Average Line OEE-like %
      - Average Machine Health Index %
    """
    with Session(engine) as session:
        run = _latest_run(session)
        if not run:
            return []

        # ---------- 1) Schedule Conformance % ----------
        orders = session.exec(select(Order)).all()
        planned_total = sum(o.quantity for o in orders)
        latest_rt_by_line = _get_latest_realtime_by_line(session, run.run_id)
        actual_total = sum(
            r.production_output_cum for r in latest_rt_by_line.values()
        )

        if planned_total > 0:
            schedule_conf = (actual_total / planned_total) * 100.0
        else:
            schedule_conf = 0.0

        # Thresholds (from doc: target ≈95%)
        if schedule_conf >= 95.0:
            sched_alert = "GREEN"
        elif schedule_conf >= 90.0:
            sched_alert = "AMBER"
        else:
            sched_alert = "RED"

        kpi_schedule = KPIValue(
            name="Schedule Conformance %",
            value=round(schedule_conf, 2),
            unit="%",
            target=95.0,
            alert_status=sched_alert,
        )

        # ---------- 2) Average Material Availability % ----------
        inv_rows = get_inventory_view(session)
        avail_values: List[float] = []
        for row in inv_rows:
            required = row["required_for_order"]
            current = row["current_stock"]
            if required > 0:
                avail = min(100.0, (current / float(required)) * 100.0)
                avail_values.append(avail)

        material_avail = mean(avail_values) if avail_values else 100.0

        if material_avail >= 95.0:
            mat_alert = "GREEN"
        elif material_avail >= 80.0:
            mat_alert = "AMBER"
        else:
            mat_alert = "RED"

        kpi_material = KPIValue(
            name="Material Availability %",
            value=round(material_avail, 2),
            unit="%",
            target=95.0,
            alert_status=mat_alert,
        )

        # ---------- 3) Average Line OEE-like % ----------
        oee_values: List[float] = []
        for r in latest_rt_by_line.values():
            # Approximate OEE = uptime × (1 - defects)
            oee = r.machine_uptime_pct * (1.0 - r.defect_rate_pct / 100.0)
            oee_values.append(oee)

        avg_oee = mean(oee_values) if oee_values else 0.0

        if avg_oee >= 85.0:
            oee_alert = "GREEN"
        elif avg_oee >= 75.0:
            oee_alert = "AMBER"
        else:
            oee_alert = "RED"

        kpi_oee = KPIValue(
            name="Average Line OEE (approx)",
            value=round(avg_oee, 2),
            unit="%",
            target=85.0,
            alert_status=oee_alert,
        )

        # ---------- 4) Average Machine Health Index % ----------
        mp_rows = session.exec(select(MachineParameter)).all()
        health_values: List[float] = []
        for mp in mp_rows:
            if mp.threshold == 0:
                continue
            deviation = abs(mp.current_value - mp.threshold) / float(mp.threshold)
            health = max(0.0, 1.0 - deviation)  # 0..1
            health_values.append(health * 100.0)

        avg_health = mean(health_values) if health_values else 100.0

        if avg_health >= 90.0:
            health_alert = "GREEN"
        elif avg_health >= 80.0:
            health_alert = "AMBER"
        else:
            health_alert = "RED"

        kpi_health = KPIValue(
            name="Average Machine Health Index",
            value=round(avg_health, 2),
            unit="%",
            target=90.0,
            alert_status=health_alert,
        )

        return [kpi_schedule, kpi_material, kpi_oee, kpi_health]
