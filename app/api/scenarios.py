# app/api/scenarios.py
import numpy as np
from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks
from sqlmodel import Session, select

from ..database import engine
from ..models.master import Order
from ..models.supply import PurchaseOrder
from ..models.planning import AIDecisionLog, PlanRun
from ..services.simulation import start_simulation, stop_simulation
from ..services.planning import plan_all_open_orders
from ..services.event_logger import log_event
from ..ai.recommender import get_recommender


router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])

def _to_native(obj):
    """
    Recursively convert numpy scalars / containers into plain Python types,
    so FastAPI's jsonable_encoder can serialize the response.
    """
    # numpy scalar → Python int/float
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)

    # containers
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_native(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_to_native(v) for v in obj)

    return obj

def _log_ai_decision(
    session: Session,
    *,
    scenario_name: str,
    run_id: str,
    ai_payload: dict,
    rule_ids: str,
    line_id: str = "GLOBAL",
) -> AIDecisionLog:
    """
    Persist AI recommendation into AIDecisionLog and return the row.
    """
    features = ai_payload.get("features_used", {}) or {}
    alert_status = features.get("Alert_Status", "None")

    row = AIDecisionLog(
        scenario_name=scenario_name,
        run_id=run_id,
        line_id=line_id,
        alert_status=str(alert_status),
        ai_recommendation=str(ai_payload.get("recommended_action", "")),
        predicted_kpi_impact_pct=float(
            ai_payload.get("predicted_kpi_impact_%", 0.0)
        ),
        rule_ids_fired=rule_ids,
        explanation=str(ai_payload.get("explanation", "")),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row

@router.post("/demand_spike")
def trigger_demand_spike(background_tasks: BackgroundTasks):
    """
    Scenario 1: Morning demand spike.
    - Create a new high-priority order for 500 P-HE (Europe dealer).
    - Re-plan all orders so this gets capacity first on P-HE lines.
    - Restart the simulation with the new plan.
    - Ask the AI recommender for an action + KPI impact and log it.
    """
    today = date.today()
    dispatch = today + timedelta(days=2)

    order_id = "ORD-HE-EUROPE-" + datetime.utcnow().strftime("%Y%m%d%H%M%S")

    # 1) Create order + scenario event
    with Session(engine) as session:
        new_order = Order(
            order_id=order_id,
            product_id="P-HE",
            quantity=500,
            start_date=today,
            dispatch_date=dispatch,
            status="OPEN",
            priority=1,  # Highest priority for spike orders
            is_spike=True,  # Mark as spike for preemption logic
        )
        session.add(new_order)

        log_event(
            session,
            "SCENARIO_DEMAND_SPIKE",
            f"Created high-priority Europe order {order_id} for 500 units of P-HE "
            f"(dispatch by {dispatch.isoformat()}).",
        )

        session.commit()

    # 2) Stop current simulation, re-plan, restart using latest plan
    stop_simulation()
    new_run_id = plan_all_open_orders(horizon_days_default=2)
    start_simulation(background_tasks)

    # 3) AI recommendation + logging for this scenario
    reco = get_recommender()
    with Session(engine) as session:
        ai_payload = reco.recommend(
            session=session,
            event_type="demand_spike",
            delta_qty=500,
            chip_status="Available",
        )
        ai_payload = _to_native(ai_payload)

        log_row = _log_ai_decision(
            session,
            scenario_name="demand_spike",
            run_id=new_run_id,
            ai_payload=ai_payload,
            rule_ids="R_DEMAND_SPIKE",
            line_id="GLOBAL",
        )

    # 4) Shape response for frontend: include latest AI decision
    return {
        "status": "ok",
        "order_id": order_id,
        "ai_decision": {
            "scenario_name": log_row.scenario_name,
            "run_id": log_row.run_id,
            "line_id": log_row.line_id,
            "ts": log_row.ts.isoformat(),
            "alert_status": log_row.alert_status,
            "ai_recommendation": log_row.ai_recommendation,
            "predicted_kpi_impact_pct": log_row.predicted_kpi_impact_pct,
            "rule_ids_fired": log_row.rule_ids_fired,
            "explanation": log_row.explanation,
            "model_version": ai_payload.get("model_version"),
            "alternatives": ai_payload.get("alternatives", []),
        },
    }



@router.post("/chip_delay")
def trigger_chip_delay():
    """
    Scenario 2: Mid-day semiconductor shipment delay.
    - Take the earliest open PO for a semiconductor material (M014/M076/M108).
    - Delay ETA by 48 hours and mark status as DELAYED.
    - Simulation continues, so the impact shows up naturally.
    - Ask the AI recommender for a mitigation suggestion and log it.
    """
    semiconductor_ids = ["M014", "M076", "M108"]

    with Session(engine) as session:
        po = session.exec(
            select(PurchaseOrder)
            .where(
                PurchaseOrder.material_id.in_(semiconductor_ids),
                PurchaseOrder.status != "DELIVERED",
            )
            .order_by(PurchaseOrder.eta_date)
        ).first()

        if not po:
            # No PO → still return a consistent payload
            # Use latest run_id (if any) for AI logging
            run_row = session.exec(
                select(PlanRun).order_by(PlanRun.created_at.desc())
            ).first()
            run_id = run_row.run_id if run_row else "NO_RUN"

            reco = get_recommender()
            ai_payload = reco.recommend(
                session=session,
                event_type="chip_delay",
                delta_qty=0,
                chip_status="Delayed",
            )
            log_row = _log_ai_decision(
                session,
                scenario_name="chip_delay",
                run_id=run_id,
                ai_payload=ai_payload,
                rule_ids="R_CHIP_DELAY",
                line_id="GLOBAL",
            )

            return {
                "status": "no_open_po_for_semiconductors",
                "ai_decision": {
                    "scenario_name": log_row.scenario_name,
                    "run_id": log_row.run_id,
                    "line_id": log_row.line_id,
                    "ts": log_row.ts.isoformat(),
                    "alert_status": log_row.alert_status,
                    "ai_recommendation": log_row.ai_recommendation,
                    "predicted_kpi_impact_pct": log_row.predicted_kpi_impact_pct,
                    "rule_ids_fired": log_row.rule_ids_fired,
                    "explanation": log_row.explanation,
                    "model_version": ai_payload.get("model_version"),
                    "alternatives": ai_payload.get("alternatives", []),
                },
            }

        old_eta = po.eta_date
        po.eta_date = po.eta_date + timedelta(days=2)
        po.status = "DELAYED"

        log_event(
            session,
            "SCENARIO_CHIP_DELAY",
            f"Delayed PO {po.po_id} for material {po.material_id} by 2 days "
            f"(from {old_eta.isoformat()} to {po.eta_date.isoformat()}).",
        )

        # Latest run_id for logging AI decision
        run_row = session.exec(
            select(PlanRun).order_by(PlanRun.created_at.desc())
        ).first()
        run_id = run_row.run_id if run_row else "NO_RUN"

        # AI recommendation
        reco = get_recommender()
        ai_payload = reco.recommend(
            session=session,
            event_type="chip_delay",
            delta_qty=0,
            chip_status="Delayed",
        )
        ai_payload = _to_native(ai_payload)

        log_row = _log_ai_decision(
            session,
            scenario_name="chip_delay",
            run_id=run_id,
            ai_payload=ai_payload,
            rule_ids="R_CHIP_DELAY",
            line_id="GLOBAL",
        )

        session.commit()

        return {
            "status": "ok",
            "po_id": po.po_id,
            "material_id": po.material_id,
            "new_eta": po.eta_date.isoformat(),
            "ai_decision": {
                "scenario_name": log_row.scenario_name,
                "run_id": log_row.run_id,
                "line_id": log_row.line_id,
                "ts": log_row.ts.isoformat(),
                "alert_status": log_row.alert_status,
                "ai_recommendation": log_row.ai_recommendation,
                "predicted_kpi_impact_pct": log_row.predicted_kpi_impact_pct,
                "rule_ids_fired": log_row.rule_ids_fired,
                "explanation": log_row.explanation,
                "model_version": ai_payload.get("model_version"),
                "alternatives": ai_payload.get("alternatives", []),
            },
        }
