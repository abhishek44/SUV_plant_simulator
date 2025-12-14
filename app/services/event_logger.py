import uuid
from datetime import datetime
from sqlmodel import Session
from ..models.planning import Event


def log_event(session: Session, event_type: str, description: str):
    eid = f"EVT-{uuid.uuid4().hex}"
    e = Event(
        event_id=eid,
        event_type=event_type,
        description=description,
        event_date=datetime.utcnow(),
        metadata_json=None,
    )
    session.add(e)
