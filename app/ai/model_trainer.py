"""
Train two compact models from a CSV:

- Action classifier (RandomForest) -> recommended action label
- KPI regressor (RandomForest)     -> predicted KPI impact %

Artifacts are saved under backend/app/ai/models/:
  - action_classifier.pkl
  - kpi_regressor.pkl
  - label_encoders.pkl
  - model_metadata.json

Usage:
  python -m app.ai.model_trainer /absolute/or/relative/path/to/train_s1.csv
"""

from __future__ import annotations
import sys, json
from pathlib import Path
from typing import Dict, Any, List
import pandas as pd
from pandas.api.types import is_datetime64_any_dtype as is_dt
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, r2_score
import joblib
from dateutil import parser as dateparser

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "models"
OUT.mkdir(parents=True, exist_ok=True)

CAT_COLS = ["Scenario", "Assembly_Line", "Shift", "Semiconductor_Availability", "Alert_Status"]
NUM_COLS = ["Demand_SUVs", "Inventory_Status_%", "Machine_Uptime_%", "Worker_Availability_%",
            "Production_Output", "Defect_Rate_%", "Energy_Consumption_kWh"]
TARGET_ACTION = "AI_Recommendation"
TARGET_KPI = "Predicted_KPI_Impact_%"

def _parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    # Handle common date column names; if present, extract time parts to stabilize learning
    for col in ["Date", "EventDate", "Timestamp"]:
        if col in df.columns:
            try:
                # mixed tolerant parsing
                s = pd.to_datetime(df[col], errors="coerce", utc=False, format="mixed")
            except Exception:
                s = pd.to_datetime(df[col].apply(lambda x: dateparser.parse(str(x)) if pd.notna(x) else pd.NaT),
                                   errors="coerce", utc=False)
            df[col] = s
            if is_dt(df[col]):
                df["Hour"] = df[col].dt.hour.fillna(0).astype(int)
                df["DayOfWeek"] = df[col].dt.dayofweek.fillna(0).astype(int)
    return df

def _load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = _parse_dates(df)
    return df

def _build_encoders(df: pd.DataFrame) -> Dict[str, LabelEncoder]:
    enc: Dict[str, LabelEncoder] = {}
    for c in CAT_COLS:
        if c in df.columns:
            le = LabelEncoder()
            vals = df[c].astype(str).fillna("NA")
            enc[c] = le.fit(vals)
    return enc

def _encode_frame(df: pd.DataFrame, encoders: Dict[str, LabelEncoder]) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    for c in CAT_COLS:
        if c in df.columns and c in encoders:
            X[f"{c}_encoded"] = encoders[c].transform(df[c].astype(str).fillna("NA"))
        else:
            X[f"{c}_encoded"] = 0
    for n in NUM_COLS:
        X[n] = pd.to_numeric(df[n], errors="coerce").fillna(0.0)
    # Optional time features
    for t in ["Hour", "DayOfWeek"]:
        if t in df.columns:
            X[t] = pd.to_numeric(df[t], errors="coerce").fillna(0.0)
    return X

def train(csv_path: Path) -> Dict[str, Any]:
    df = _load_csv(csv_path)

    # Targets
    if TARGET_ACTION not in df.columns or TARGET_KPI not in df.columns:
        raise SystemExit(f"CSV must contain columns: {TARGET_ACTION}, {TARGET_KPI}")

    # Encoders for features + label for action target
    encoders = _build_encoders(df)
    X = _encode_frame(df, encoders)

    y_action_raw = df[TARGET_ACTION].astype(str).fillna("No_Change")
    le_action = LabelEncoder()
    y_action = le_action.fit_transform(y_action_raw)

    y_kpi = pd.to_numeric(df[TARGET_KPI], errors="coerce").fillna(0.0)

    # Train/test split
    X_train, X_test, ya_train, ya_test = train_test_split(X, y_action, test_size=0.2, random_state=42, stratify=y_action)
    _,      X_testK, yk_train, yk_test = train_test_split(X, y_kpi,    test_size=0.2, random_state=42)

    # Models
    clf = RandomForestClassifier(n_estimators=250, max_depth=None, random_state=42, class_weight="balanced")
    reg = RandomForestRegressor(n_estimators=300, max_depth=None, random_state=42)

    clf.fit(X_train, ya_train)
    reg.fit(X, y_kpi)

    # Metrics
    ya_pred = clf.predict(X_test)
    acc = accuracy_score(ya_test, ya_pred)
    f1 = f1_score(ya_test, ya_pred, average="weighted")

    yk_pred = reg.predict(X_testK)
    mae = mean_absolute_error(yk_test, yk_pred)
    r2 = r2_score(yk_test, yk_pred)

    # Save artifacts
    joblib.dump(clf, OUT / "action_classifier.pkl")
    joblib.dump(reg, OUT / "kpi_regressor.pkl")
    # Save encoders (features + action label encoder together)
    encoders_out = encoders.copy()
    encoders_out["__ACTION_LABEL__"] = le_action
    joblib.dump(encoders_out, OUT / "label_encoders.pkl")

    meta = {
        "source_csv": str(csv_path),
        "model_versions": {"action_classifier": "rf-1.0", "kpi_regressor": "rf-1.0"},
        "metrics": {"clf": {"accuracy": acc, "f1_weighted": f1}, "reg": {"mae": mae, "r2": r2}},
        "feature_columns": list(X.columns),
        "categoricals": CAT_COLS,
        "numericals": NUM_COLS,
    }
    (OUT / "model_metadata.json").write_text(json.dumps(meta, indent=2))

    return meta

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.ai.model_trainer <path/to/train_s1.csv>")
        sys.exit(2)
    meta = train(Path(sys.argv[1]).resolve())
    print(json.dumps(meta, indent=2))
