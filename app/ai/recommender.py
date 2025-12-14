# app/ai/recommender.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List

import joblib
import pandas as pd
from sqlmodel import Session, select

from ..models.supply import InventoryItem
from ..models.master import Line

MODELS_DIR = Path(__file__).resolve().parent / "models"


def _try_load(path: Path):
    return joblib.load(path) if path.exists() else None


class Recommender:
    """
    Thin wrapper around the RF classifier + regressor.

    It is deliberately stateless w.r.t. the DB; everything needed for a
    recommendation is provided via the `row` feature dict built in
    `recommend()`, based on the current DB snapshot and scenario params.
    """

    def __init__(self) -> None:
        # Artifacts produced by app.ai.model_trainer
        self.action = _try_load(MODELS_DIR / "action_classifier.pkl")
        self.kpi = _try_load(MODELS_DIR / "kpi_regressor.pkl")
        self.enc: Dict[str, Any] = _try_load(MODELS_DIR / "label_encoders.pkl") or {}
        meta_path = MODELS_DIR / "model_metadata.json"
        self.meta: Dict[str, Any] = (
            json.loads(meta_path.read_text()) if meta_path.exists() else {}
        )

        # Cached config from metadata
        self._cat_cols: List[str] = self.meta.get(
            "categoricals",
            ["Scenario", "Assembly_Line", "Shift", "Semiconductor_Availability", "Alert_Status"],
        )
        self._num_cols: List[str] = self.meta.get(
            "numericals",
            [
                "Demand_SUVs",
                "Inventory_Status_%",
                "Machine_Uptime_%",
                "Worker_Availability_%",
                "Production_Output",
                "Defect_Rate_%",
                "Energy_Consumption_kWh",
            ],
        )

    def _encode_row(self, row: Dict[str, Any]) -> pd.DataFrame:
        """
        Encode one logical "situation" row using the same encoding as training.
        Unknown categories are mapped to 0.
        """
        encoded: Dict[str, Any] = {}

        for c in self._cat_cols:
            le = self.enc.get(c)
            val = str(row.get(c, "NA"))
            if le is not None:
                # If unseen, fall back to 0
                if val in le.classes_:
                    encoded[f"{c}_encoded"] = int(le.transform([val])[0])
                else:
                    encoded[f"{c}_encoded"] = 0
            else:
                encoded[f"{c}_encoded"] = 0

        for n in self._num_cols:
            encoded[n] = float(row.get(n, 0.0))

        # Optional time features if present in metadata
        for t in ["Hour", "DayOfWeek"]:
            if t in self.meta.get("feature_columns", []):
                encoded[t] = float(row.get(t, 0.0))

        return pd.DataFrame([encoded])

    def _fallback(self, event_type: str, row: Dict[str, Any]) -> Dict[str, Any]:
        """
        Simple rule-based fallback when models are not available.
        Keeps the demo usable even before training.
        """
        if event_type == "chip_delay":
            return {
                "source": "ai-fallback",
                "recommended_action": "Switch_Supplier",
                "confidence": 0.9,
                "predicted_kpi_impact_%": -3.0,
                "alternatives": [
                    {"action": "Reallocate_Line", "confidence": 0.07},
                    {"action": "Maintenance_Dispatch", "confidence": 0.03},
                ],
                "explanation": "Heuristic: chip delay → switch to alternate supplier.",
                "features_used": row,
                "model_version": "fallback-1",
            }

        # default: demand spike
        return {
            "source": "ai-fallback",
            "recommended_action": "Increase_Shift",
            "confidence": 0.85,
            "predicted_kpi_impact_%": 4.5,
            "alternatives": [
                {"action": "Reallocate_Line", "confidence": 0.1},
                {"action": "Expedite_Supplier", "confidence": 0.05},
            ],
            "explanation": "Heuristic: demand spike with capacity available → increase shift.",
            "features_used": row,
            "model_version": "fallback-1",
        }

    def recommend(
        self,
        session: Session,
        event_type: str,
        delta_qty: int,
        chip_status: str,
    ) -> Dict[str, Any]:
        """
        Build a compact feature vector representing the current plant + scenario,
        and run classifier + regressor to obtain an action and KPI impact.
        """
        # --- Derive features from DB ---
        # Inventory: use a semiconductor-like material if present, else aggregate.
        # Here we pick a representative chip material if available.
        chip_item = session.exec(
            select(InventoryItem).where(InventoryItem.material_id == "M014")
        ).first()

        if chip_item:
            denom = max(chip_item.safety_stock + chip_item.reorder_point, 1)
            inv_pct = min(100.0, (chip_item.current_stock / denom) * 100.0)
        else:
            # Fallback: average over all items
            all_inv = session.exec(select(InventoryItem)).all()
            if all_inv:
                total = sum(i.current_stock for i in all_inv)
                denom = sum(i.safety_stock + i.reorder_point for i in all_inv) or 1
                inv_pct = min(100.0, (total / denom) * 100.0)
            else:
                inv_pct = 75.0

        # Lines → average OEE-like uptime
        lines = session.exec(select(Line)).all()
        machine_uptime = (
            sum(l.oee_pct for l in lines) / len(lines) * 100.0 if lines else 90.0
        )

        assembly_line = "HighRange_1"  # logical line family; consistent with training CSV
        shift = "S1"  # in this simple demo we treat scenario as S1 / daytime

        semi_avail = (
            "Available"
            if chip_status == "Available"
            else ("Delayed" if chip_status == "Delayed" else "Shortage")
        )
        alert_status = (
            "Supply_Alert" if semi_avail != "Available" else "Demand_Spike_Alert"
        )

        # Construct feature row shaped like the training CSV
        row = {
            "Scenario": (
                "Morning_Sudden_Demand_Spike"
                if event_type == "demand_spike"
                else "Midday_Semiconductor_Shortage"
            ),
            "Assembly_Line": assembly_line,
            "Shift": shift,
            "Demand_SUVs": int(delta_qty),
            "Inventory_Status_%": float(inv_pct),
            "Machine_Uptime_%": float(machine_uptime),
            "Worker_Availability_%": 90.0,
            "Production_Output": 260.0,
            "Defect_Rate_%": 1.6,
            "Energy_Consumption_kWh": 6200.0,
            "Semiconductor_Availability": semi_avail,
            "Alert_Status": alert_status,
        }

        # --- Fall back if models not yet trained ---
        if not (self.action and self.kpi and self.enc):
            return self._fallback(event_type, row)

        # --- Encode + predict ---
        X = self._encode_row(row)
        probs = self.action.predict_proba(X)[0]
        pred = self.action.predict(X)[0]
        classes = list(self.action.classes_)

        conf = float(probs.max())
        top_idx = probs.argsort()[-3:][::-1]
        alternatives = [
            {"action": str(classes[i]), "confidence": float(probs[i])} for i in top_idx
        ]

        kpi_delta = float(self.kpi.predict(X)[0])

        return {
            "source": "ai-model",
            "recommended_action": str(pred),
            "confidence": conf,
            "predicted_kpi_impact_%": round(kpi_delta, 2),
            "alternatives": alternatives,
            "explanation": (
                "High confidence recommendation" if conf >= 0.7 else "Moderate confidence recommendation"
            ),
            "features_used": row,
            "model_version": self.meta.get("model_versions", {}).get(
                "action_classifier", "unknown"
            ),
        }


# Singleton accessor so models are loaded once per process
_reco: Recommender | None = None


def get_recommender() -> Recommender:
    global _reco
    if _reco is None:
        _reco = Recommender()
    return _reco
