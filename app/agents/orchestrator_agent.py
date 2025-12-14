# app/agents/orchestrator_agent.py
"""
Orchestrator Agent - Multi-agent coordination and conflict resolution.
"""

from datetime import datetime
from typing import Dict, Any, List
from sqlmodel import Session

from .base_agent import BaseAgent
from .llm_client import AzureOpenAIClient


class OrchestratorAgent(BaseAgent):
    """
    Master agent that coordinates all specialized agents.
    
    Responsibilities:
    - Collect pending actions from all agents
    - Detect and resolve conflicts
    - Make plant-wide optimization decisions
    - Aggregate insights for human review
    """
    
    def __init__(self):
        super().__init__(
            name="OrchestratorAgent",
            config={
                "cycle_interval_seconds": 15,  # Fastest cycle
                "child_agents": ["planning", "supply_chain", "maintenance"]
            }
        )
        self.llm = AzureOpenAIClient()
        self.child_agents = self.config["child_agents"]
        self.pending_actions: List[Dict[str, Any]] = []
    
    def observe(self, session: Session) -> Dict[str, Any]:
        """
        Gather state from all child agents and overall plant.
        
        Now includes:
        - KPIs
        - Agent statuses
        - Recent decisions (in-memory log)
        - Pending actions (from DB table)
        """
        from ..services.kpis import compute_kpis
        from ..models.planning import AgentPendingAction
        from . import agent_runner
        
        # Get overall KPIs
        kpis = compute_kpis()
        kpi_summary = {k.name: {"value": k.value, "status": k.alert_status} for k in kpis}
        
        # Get status of all child agents
        agent_statuses = {}
        for agent_name in self.child_agents:
            status = agent_runner.get_status(agent_name)
            agent_statuses[agent_name] = status
        
        # Get recent decisions from in-memory log
        all_decisions = agent_runner.get_decisions(limit=50)
        
        # Separate by agent
        recent_decisions = {}
        for agent_name in self.child_agents:
            agent_decisions = [d for d in all_decisions if d.get("agent") == agent_name]
            recent_decisions[agent_name] = agent_decisions[:5]  # Last 5 per agent
        
        # Get PENDING actions from DB (the main input for orchestration)
        pending_actions = session.exec(
            select(AgentPendingAction)
            .where(AgentPendingAction.status == "PENDING")
            .order_by(AgentPendingAction.priority.desc(), AgentPendingAction.created_at)
        ).all()
        
        pending_list = [
            {
                "id": pa.id,
                "agent": pa.agent_name,
                "action_type": pa.action_type,
                "priority": pa.priority,
                "line_id": pa.line_id,
                "material_id": pa.material_id,
                "order_id": pa.order_id,
                "reason": pa.reason,
                "created_at": pa.created_at.isoformat() if pa.created_at else None
            }
            for pa in pending_actions
        ]
        
        # Detect conflicts from both pending actions and recent decisions
        conflicts = self._detect_conflicts(recent_decisions, pending_list)
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "kpis": kpi_summary,
            "agent_statuses": agent_statuses,
            "recent_decisions": recent_decisions,
            "pending_actions": pending_list,
            "pending_count": len(pending_list),
            "active_agents": len([s for s in agent_statuses.values() if s.get("is_running")]),
            "total_recent_actions": sum(len(d) for d in recent_decisions.values()),
            "conflicts": conflicts
        }
    
    def think(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze multi-agent state and decide on coordination actions.
        """
        conflicts = observation.get("conflicts", [])
        
        if not conflicts:
            # Check if any agents need attention
            inactive_agents = self._check_inactive_agents(observation)
            if inactive_agents:
                return {
                    "action": "START_AGENTS",
                    "reason": f"Agents not running: {', '.join(inactive_agents)}",
                    "affected_items": inactive_agents,
                    "llm_used": False
                }
            
            return {
                "action": "CONTINUE",
                "reason": "All agents operating normally, no conflicts",
                "llm_used": False
            }
        
        # Use LLM for conflict resolution
        if self.llm.is_available():
            decision = self._llm_resolve_conflicts(observation, conflicts)
            return decision
        
        # Fallback: prioritize by severity
        return self._fallback_resolution(conflicts)
    
    def act(self, decision: Dict[str, Any], session: Session) -> Dict[str, Any]:
        """Execute orchestration actions."""
        action = decision.get("action", "CONTINUE")
        result = {"status": "executed", "action": action}
        
        self._log_decision(session, decision)
        
        if action == "CONTINUE":
            result["message"] = "No coordination action needed"
            
        elif action == "START_AGENTS":
            result.update(self._start_inactive_agents(decision))
            
        elif action == "DEFER_ACTION":
            result.update(self._defer_action(session, decision))
            
        elif action == "PRIORITIZE":
            result.update(self._prioritize_action(session, decision))
            
        elif action == "ESCALATE":
            result.update(self._escalate_to_human(session, decision))
        
        return result
    
    def _detect_conflicts(self, recent_decisions: Dict[str, List], pending_actions: List[Dict] = None) -> List[Dict]:
        """
        Detect conflicts between agent actions.
        
        Conflict types:
        - Maintenance vs Production: Maintenance wants downtime, Planning wants to produce
        - Resource contention: Multiple agents want same resource (line/material)
        - Timing conflicts: Actions that can't happen simultaneously
        """
        conflicts = []
        pending_actions = pending_actions or []
        
        # Get latest decision from each agent (from in-memory log)
        latest = {}
        for agent_name, decisions in recent_decisions.items():
            if decisions:
                latest[agent_name] = decisions[0]
        
        # Check for maintenance vs planning conflict in recent decisions
        planning_decision = latest.get("planning", {}).get("decision", {})
        maintenance_decision = latest.get("maintenance", {}).get("decision", {})
        
        if (planning_decision.get("action") == "REPLAN" and 
            maintenance_decision.get("action") == "SCHEDULE_MAINTENANCE"):
            conflicts.append({
                "type": "maintenance_vs_production",
                "agents": ["planning", "maintenance"],
                "description": "Planning wants to replan while maintenance needs downtime",
                "planning_action": planning_decision,
                "maintenance_action": maintenance_decision,
                "severity": "high"
            })
        
        # Check for resource contention in pending actions
        # Group by resource (line_id or material_id)
        by_line = {}
        by_material = {}
        
        for pa in pending_actions:
            if pa.get("line_id"):
                lid = pa["line_id"]
                if lid not in by_line:
                    by_line[lid] = []
                by_line[lid].append(pa)
            
            if pa.get("material_id"):
                mid = pa["material_id"]
                if mid not in by_material:
                    by_material[mid] = []
                by_material[mid].append(pa)
        
        # Check for line contention (multiple agents want same line)
        for line_id, actions in by_line.items():
            if len(actions) > 1:
                agents_involved = list(set(a["agent"] for a in actions))
                if len(agents_involved) > 1:
                    conflicts.append({
                        "type": "resource_contention_line",
                        "resource": line_id,
                        "agents": agents_involved,
                        "actions": [a["action_type"] for a in actions],
                        "description": f"Multiple agents want line {line_id}",
                        "severity": "medium",
                        "pending_action_ids": [a["id"] for a in actions]
                    })
        
        # Check for supply chain vs planning coordination
        supply_decision = latest.get("supply_chain", {}).get("decision", {})
        
        if (planning_decision.get("action") == "REPLAN" and
            supply_decision.get("action") in ["CREATE_PO", "EXPEDITE_PO"]):
            conflicts.append({
                "type": "supply_and_planning",
                "agents": ["planning", "supply_chain"],
                "description": "Both planning and supply chain taking action - coordinate timing",
                "severity": "low"
            })
        
        return conflicts
    
    def _check_inactive_agents(self, observation: Dict) -> List[str]:
        """Check for agents that should be running but aren't."""
        inactive = []
        for agent_name in self.child_agents:
            status = observation.get("agent_statuses", {}).get(agent_name, {})
            if not status.get("is_running") and status.get("status") != "not_found":
                inactive.append(agent_name)
        return inactive
    
    def _llm_resolve_conflicts(self, observation: Dict, conflicts: List) -> Dict:
        """Use LLM to resolve conflicts."""
        prompt_data = {
            "kpis": observation.get("kpis"),
            "conflicts": conflicts
        }
        
        issues = [{"type": "conflict", **c} for c in conflicts]
        decision = self.llm.analyze_situation(prompt_data, issues, self._get_mcp_tools())
        
        return decision
    
    def _fallback_resolution(self, conflicts: List) -> Dict:
        """Rule-based conflict resolution."""
        if not conflicts:
            return {"action": "CONTINUE", "reason": "No conflicts", "llm_used": False}
        
        # Prioritize by severity
        high_severity = [c for c in conflicts if c.get("severity") == "high"]
        
        if high_severity:
            conflict = high_severity[0]
            
            # Default: prioritize maintenance over production for safety
            if conflict["type"] == "maintenance_vs_production":
                return {
                    "action": "PRIORITIZE",
                    "reason": "Prioritizing maintenance for equipment safety",
                    "prioritize_agent": "maintenance",
                    "defer_agent": "planning",
                    "llm_used": False
                }
        
        # Low severity: just note the coordination
        return {
            "action": "CONTINUE",
            "reason": f"Low severity coordination noted: {conflicts[0].get('type')}",
            "llm_used": False
        }
    
    def _get_mcp_tools(self) -> List[Dict]:
        """Get MCP tools for orchestration."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "prioritize_agent",
                    "description": "Prioritize one agent's action over another",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "prioritize": {"type": "string", "description": "Agent to prioritize"},
                            "defer": {"type": "string", "description": "Agent to defer"},
                            "reason": {"type": "string"}
                        },
                        "required": ["prioritize", "defer", "reason"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "escalate_to_human",
                    "description": "Escalate complex decision to human operator",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string"},
                            "options": {"type": "array", "items": {"type": "string"}},
                            "urgency": {"type": "string", "enum": ["low", "medium", "high"]}
                        },
                        "required": ["summary", "urgency"]
                    }
                }
            }
        ]
    
    def _log_decision(self, session: Session, decision: Dict[str, Any]):
        """Log orchestrator decision."""
        from ..services.event_logger import log_event
        
        action = decision.get("action", "UNKNOWN")
        reason = decision.get("reason", "No reason")
        llm_used = decision.get("llm_used", False)
        
        log_event(
            session,
            f"ORCHESTRATOR_{action}",
            f"[{'LLM' if llm_used else 'RULE'}] {reason}"
        )
    
    def _start_inactive_agents(self, decision: Dict) -> Dict:
        """Start agents that aren't running."""
        from . import agent_runner
        
        agents = decision.get("affected_items", [])
        started = []
        
        for agent_name in agents:
            result = agent_runner.start_agent(agent_name)
            if result.get("status") == "started":
                started.append(agent_name)
        
        return {"message": f"Started agents: {started}"}
    
    def _defer_action(self, session: Session, decision: Dict) -> Dict:
        """Defer an agent's action."""
        from ..services.event_logger import log_event
        
        defer_agent = decision.get("defer_agent", "unknown")
        log_event(session, "ACTION_DEFERRED", f"Deferred action from {defer_agent}")
        
        return {"message": f"Action deferred for {defer_agent}"}
    
    def _prioritize_action(self, session: Session, decision: Dict) -> Dict:
        """Prioritize one agent over another."""
        from ..services.event_logger import log_event
        
        prioritize = decision.get("prioritize_agent", "unknown")
        defer = decision.get("defer_agent", "unknown")
        
        log_event(session, "ACTION_PRIORITIZED", f"Prioritized {prioritize} over {defer}")
        
        return {"message": f"Prioritized {prioritize}, deferred {defer}"}
    
    def _escalate_to_human(self, session: Session, decision: Dict) -> Dict:
        """Escalate decision to human."""
        from ..services.event_logger import log_event
        
        reason = decision.get("reason", "Complex decision requires human input")
        log_event(session, "ESCALATED_TO_HUMAN", reason)
        
        return {"message": "Escalated to human operator"}
    
    def _summarize_observation(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """Compact summary for logging."""
        return {
            "active_agents": observation.get("active_agents"),
            "total_actions": observation.get("total_recent_actions"),
            "conflicts": len(observation.get("conflicts", []))
        }
