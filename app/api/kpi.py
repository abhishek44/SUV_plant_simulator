# app/api/kpi.py

from fastapi import APIRouter
from typing import List

from ..services.kpis import compute_kpis, KPIValue

router = APIRouter(prefix="/api/kpi", tags=["kpi"])


@router.get("/latest", response_model=List[dict])
def get_latest_kpis():
    """
    Compute KPIs on the fly from current simulation state.

    Returns a list like:
    [
      {"name": "...", "value": 93.4, "unit": "%", "target": 95.0, "alert_status": "AMBER"},
      ...
    ]
    """
    kpis = compute_kpis()
    # Convert dataclasses to simple dicts for JSON
    return [k.__dict__ for k in kpis]
