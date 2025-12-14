# app/agents/models.py
"""
Agent data models - Typed action model and pending actions.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum


class ActionType(str, Enum):
    """Standardized action types across all agents."""
    # Planning actions
    REPLAN = "REPLAN"
    ADJUST_PRIORITY = "ADJUST_PRIORITY"
    
    # Supply chain actions
    CREATE_PO = "CREATE_PO"
    EXPEDITE_PO = "EXPEDITE_PO"
    ALERT_SHORTAGE = "ALERT_SHORTAGE"
    
    # Maintenance actions
    SCHEDULE_MAINTENANCE = "SCHEDULE_MAINTENANCE"
    ALERT_FAILURE_RISK = "ALERT_FAILURE_RISK"
    REDUCE_LOAD = "REDUCE_LOAD"
    
    # Orchestrator actions
    PRIORITIZE = "PRIORITIZE"
    DEFER = "DEFER"
    ESCALATE = "ESCALATE"
    START_AGENTS = "START_AGENTS"
    
    # Generic
    CONTINUE = "CONTINUE"
    ALERT = "ALERT"


class ActionStatus(str, Enum):
    """Status of pending actions."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DEFERRED = "DEFERRED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"


@dataclass
class AgentAction:
    """
    Standardized action model for all agents.
    
    This provides a common contract for agents to propose actions
    that can be reviewed by the Orchestrator before execution.
    """
    agent: str                          # Source agent name
    action_type: ActionType             # What action to take
    priority: int = 3                   # 1-5, where 5 is highest
    
    # Target resources (optional, depends on action type)
    line_id: Optional[str] = None
    material_id: Optional[str] = None
    order_id: Optional[str] = None
    
    # Additional parameters
    payload: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    reason: str = ""
    llm_used: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "agent": self.agent,
            "action_type": self.action_type.value,
            "priority": self.priority,
            "line_id": self.line_id,
            "material_id": self.material_id,
            "order_id": self.order_id,
            "payload": self.payload,
            "reason": self.reason,
            "llm_used": self.llm_used,
            "created_at": self.created_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentAction":
        """Create from dictionary."""
        return cls(
            agent=data["agent"],
            action_type=ActionType(data["action_type"]),
            priority=data.get("priority", 3),
            line_id=data.get("line_id"),
            material_id=data.get("material_id"),
            order_id=data.get("order_id"),
            payload=data.get("payload", {}),
            reason=data.get("reason", ""),
            llm_used=data.get("llm_used", False),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.utcnow()
        )


@dataclass
class AgentDecision:
    """
    Result of an agent's think() phase.
    
    Contains one or more proposed actions along with reasoning.
    """
    agent: str
    actions: List[AgentAction]
    summary: str = ""
    llm_used: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "actions": [a.to_dict() for a in self.actions],
            "summary": self.summary,
            "llm_used": self.llm_used
        }
