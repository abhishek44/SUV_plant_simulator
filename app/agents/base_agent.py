# app/agents/base_agent.py
"""
Base agent class implementing the Observe → Think → Act pattern.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, Optional
from sqlmodel import Session


class BaseAgent(ABC):
    """
    Abstract base class for agentic AI components.
    
    Agents follow the OTA (Observe-Think-Act) pattern:
    - OBSERVE: Gather current state from database
    - THINK: Analyze and decide on action using LLM/rules
    - ACT: Execute the decision
    """
    
    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        """
        Initialize agent.
        
        Args:
            name: Agent identifier
            config: Optional configuration dict (thresholds, intervals, etc.)
        """
        self.name = name
        self.config = config or {}
        self.is_running = False
        self.cycle_count = 0
        self.last_cycle_at: Optional[datetime] = None
        self.last_decision: Optional[Dict[str, Any]] = None
    
    @abstractmethod
    def observe(self, session: Session) -> Dict[str, Any]:
        """
        Gather current state from database.
        
        Returns:
            Dict containing current observations (KPIs, alerts, inventory, etc.)
        """
        pass
    
    @abstractmethod
    def think(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze observation and decide on action.
        
        Uses LLM for complex reasoning or rule-based logic for simple cases.
        
        Returns:
            Dict containing:
                - action: The action to take (REPLAN, ALERT, CONTINUE, etc.)
                - reason: Explanation for the decision
                - tool_calls: Optional list of MCP tool calls
        """
        pass
    
    @abstractmethod
    def act(self, decision: Dict[str, Any], session: Session) -> Dict[str, Any]:
        """
        Execute the decided action.
        
        Returns:
            Dict containing execution result
        """
        pass
    
    async def run_cycle(self, session: Session) -> Dict[str, Any]:
        """
        Execute one complete observe → think → act cycle.
        
        Returns:
            Dict containing cycle results
        """
        cycle_start = datetime.utcnow()
        
        # Phase 1: OBSERVE
        observation = self.observe(session)
        
        # Phase 2: THINK
        decision = self.think(observation)
        
        # Phase 3: ACT
        result = self.act(decision, session)
        
        # Update state
        self.cycle_count += 1
        self.last_cycle_at = cycle_start
        self.last_decision = decision
        
        return {
            "agent": self.name,
            "cycle": self.cycle_count,
            "timestamp": cycle_start.isoformat(),
            "observation_summary": self._summarize_observation(observation),
            "decision": decision,
            "result": result
        }
    
    def _summarize_observation(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """Create a compact summary of observation for logging."""
        # Override in subclasses for custom summarization
        return {
            "keys": list(observation.keys()),
            "timestamp": observation.get("timestamp", datetime.utcnow().isoformat())
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Return current agent status."""
        return {
            "name": self.name,
            "is_running": self.is_running,
            "cycle_count": self.cycle_count,
            "last_cycle_at": self.last_cycle_at.isoformat() if self.last_cycle_at else None,
            "last_decision": self.last_decision
        }
