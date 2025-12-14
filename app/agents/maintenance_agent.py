# app/agents/maintenance_agent.py
"""
Maintenance Agent - Machine health monitoring and predictive maintenance.
"""

from datetime import datetime
from typing import Dict, Any, List
from sqlmodel import Session, select

from .base_agent import BaseAgent
from .llm_client import AzureOpenAIClient


class MaintenanceAgent(BaseAgent):
    """
    Autonomous agent for predictive maintenance.
    
    Monitors:
    - Machine health parameters (temperature, vibration, wear)
    - Production line uptime
    - Historical failure patterns
    
    Takes actions:
    - Schedule preventive maintenance
    - Alert on failure risk
    - Recommend capacity reduction
    """
    
    def __init__(self):
        super().__init__(
            name="MaintenanceAgent",
            config={
                "cycle_interval_seconds": 60,
                "thresholds": {
                    "health_warning": 80,
                    "health_critical": 70,
                    "uptime_min": 85,
                    "temperature_max": 85,
                    "vibration_max": 5.0
                }
            }
        )
        self.llm = AzureOpenAIClient()
        self.thresholds = self.config["thresholds"]
    
    def observe(self, session: Session) -> Dict[str, Any]:
        """
        Gather machine health state.
        
        Collects:
        - Machine parameters (temp, vibration, wear)
        - Line uptime percentages
        - Recent maintenance alerts
        """
        from ..models.simulation import MachineParameter, ProductionRealtime
        from ..models.planning import PlanRun
        from ..models.master import Line
        
        # Get machine parameters
        machine_params = session.exec(select(MachineParameter)).all()
        
        # Analyze each machine
        machines_status = []
        at_risk_machines = []
        
        for mp in machine_params:
            # Calculate health score based on deviation from threshold
            if mp.threshold > 0:
                deviation = abs(mp.current_value - mp.threshold) / mp.threshold
                health_score = max(0, (1 - deviation)) * 100
            else:
                health_score = 100
            
            status = {
                "machine_id": mp.machine_id,
                "parameter": mp.parameter_name,
                "current_value": mp.current_value,
                "threshold": mp.threshold,
                "health_score": round(health_score, 1),
                "unit": mp.unit if hasattr(mp, 'unit') else ""
            }
            
            machines_status.append(status)
            
            # Flag at-risk machines
            if health_score < self.thresholds["health_critical"]:
                status["severity"] = "critical"
                at_risk_machines.append(status)
            elif health_score < self.thresholds["health_warning"]:
                status["severity"] = "warning"
                at_risk_machines.append(status)
        
        # Get line uptime from recent ProductionRealtime
        run = session.exec(
            select(PlanRun).order_by(PlanRun.created_at.desc())
        ).first()
        
        line_uptime = {}
        if run:
            realtime = session.exec(
                select(ProductionRealtime)
                .where(ProductionRealtime.run_id == run.run_id)
                .order_by(ProductionRealtime.ts.desc())
            ).all()
            
            # Get latest uptime per line
            for rt in realtime:
                if rt.assembly_line not in line_uptime:
                    line_uptime[rt.assembly_line] = {
                        "line_id": rt.assembly_line,
                        "uptime_pct": rt.machine_uptime_pct,
                        "alert_status": rt.alert_status
                    }
        
        # Count low uptime lines
        low_uptime_lines = [
            l for l in line_uptime.values()
            if l["uptime_pct"] < self.thresholds["uptime_min"]
        ]
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_machines": len(machines_status),
            "at_risk_count": len(at_risk_machines),
            "at_risk_machines": at_risk_machines,
            "line_uptime": list(line_uptime.values()),
            "low_uptime_count": len(low_uptime_lines),
            "thresholds": self.thresholds
        }
    
    def think(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze machine health and decide on maintenance actions.
        """
        issues = self._detect_issues(observation)
        
        if not issues:
            return {
                "action": "CONTINUE",
                "reason": "All machines within acceptable health parameters",
                "llm_used": False
            }
        
        # Use LLM for complex decisions
        if self.llm.is_available() and len(issues) > 1:
            mcp_tools = self._get_mcp_tools()
            decision = self.llm.analyze_situation(observation, issues, mcp_tools)
            return decision
        
        # Fallback decision
        return self._fallback_decision(issues)
    
    def act(self, decision: Dict[str, Any], session: Session) -> Dict[str, Any]:
        """Execute maintenance actions."""
        action = decision.get("action", "CONTINUE")
        result = {"status": "executed", "action": action}
        
        self._log_decision(session, decision)
        
        if action == "CONTINUE":
            result["message"] = "No action needed"
            
        elif action == "SCHEDULE_MAINTENANCE":
            result.update(self._schedule_maintenance(session, decision))
            
        elif action == "ALERT_FAILURE_RISK":
            result.update(self._alert_failure_risk(session, decision))
            
        elif action == "REDUCE_LOAD":
            result.update(self._reduce_load(session, decision))
        
        return result
    
    def _detect_issues(self, observation: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Detect maintenance issues."""
        issues = []
        
        # Check at-risk machines
        for machine in observation.get("at_risk_machines", []):
            issue = {
                "type": "machine_health",
                "machine_id": machine["machine_id"],
                "parameter": machine["parameter"],
                "health_score": machine["health_score"],
                "current_value": machine["current_value"],
                "threshold": machine["threshold"],
                "severity": machine.get("severity", "warning")
            }
            
            if machine["health_score"] < self.thresholds["health_critical"]:
                issue["recommended_action"] = "SCHEDULE_MAINTENANCE"
            else:
                issue["recommended_action"] = "ALERT_FAILURE_RISK"
            
            issues.append(issue)
        
        # Check low uptime lines
        for line in observation.get("line_uptime", []):
            if line["uptime_pct"] < self.thresholds["uptime_min"]:
                issues.append({
                    "type": "low_uptime",
                    "line_id": line["line_id"],
                    "uptime_pct": line["uptime_pct"],
                    "severity": "warning",
                    "recommended_action": "REDUCE_LOAD"
                })
        
        return issues
    
    def _fallback_decision(self, issues: List[Dict]) -> Dict[str, Any]:
        """Rule-based decision when LLM unavailable."""
        if not issues:
            return {"action": "CONTINUE", "reason": "No issues", "llm_used": False}
        
        # Handle most critical issue first
        critical = [i for i in issues if i["severity"] == "critical"]
        issue = critical[0] if critical else issues[0]
        
        action = issue.get("recommended_action", "ALERT_FAILURE_RISK")
        
        affected = issue.get("machine_id") or issue.get("line_id", "UNKNOWN")
        
        return {
            "action": action,
            "reason": f"{issue['type']} on {affected} (health: {issue.get('health_score', 'N/A')}%)",
            "affected_items": [affected],
            "priority": 5 if issue["severity"] == "critical" else 3,
            "llm_used": False
        }
    
    def _get_mcp_tools(self) -> List[Dict]:
        """Get MCP tools for maintenance actions."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "schedule_maintenance",
                    "description": "Schedule preventive maintenance for a machine",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "machine_id": {"type": "string"},
                            "urgency": {"type": "string", "enum": ["scheduled", "urgent", "emergency"]},
                            "estimated_downtime_hours": {"type": "integer"}
                        },
                        "required": ["machine_id", "urgency"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "alert_failure_risk",
                    "description": "Alert about potential machine failure",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "machine_id": {"type": "string"},
                            "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                            "description": {"type": "string"}
                        },
                        "required": ["machine_id", "risk_level"]
                    }
                }
            }
        ]
    
    def _log_decision(self, session: Session, decision: Dict[str, Any]):
        """Log decision to event log."""
        from ..services.event_logger import log_event
        
        action = decision.get("action", "UNKNOWN")
        reason = decision.get("reason", "No reason")
        llm_used = decision.get("llm_used", False)
        
        log_event(
            session,
            f"MAINTENANCE_{action}",
            f"[{'LLM' if llm_used else 'RULE'}] {reason}"
        )
    
    def _schedule_maintenance(self, session: Session, decision: Dict) -> Dict:
        """Schedule maintenance window."""
        from ..services.event_logger import log_event
        
        affected = decision.get("affected_items", [])
        machine_id = affected[0] if affected else "UNKNOWN"
        
        log_event(session, "MAINTENANCE_SCHEDULED", f"Maintenance scheduled for {machine_id}")
        
        return {"message": f"Maintenance scheduled for {machine_id}"}
    
    def _alert_failure_risk(self, session: Session, decision: Dict) -> Dict:
        """Alert about failure risk."""
        from ..services.event_logger import log_event
        
        reason = decision.get("reason", "Machine failure risk")
        log_event(session, "MAINTENANCE_ALERT", reason)
        
        return {"message": "Failure risk alert logged"}
    
    def _reduce_load(self, session: Session, decision: Dict) -> Dict:
        """Recommend load reduction."""
        from ..services.event_logger import log_event
        
        affected = decision.get("affected_items", [])
        line_id = affected[0] if affected else "UNKNOWN"
        
        log_event(session, "LOAD_REDUCTION", f"Load reduction recommended for {line_id}")
        
        return {"message": f"Load reduction recommended for {line_id}"}
    
    def _summarize_observation(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """Compact summary for logging."""
        return {
            "total_machines": observation.get("total_machines"),
            "at_risk_count": observation.get("at_risk_count"),
            "low_uptime_count": observation.get("low_uptime_count")
        }
