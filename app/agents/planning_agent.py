# app/agents/planning_agent.py
"""
Planning Agent - Autonomous production planning decisions.
"""

from datetime import datetime
from typing import Dict, Any, List
from sqlmodel import Session, select

from .base_agent import BaseAgent
from .llm_client import AzureOpenAIClient


class PlanningAgent(BaseAgent):
    """
    Autonomous agent for production planning.
    
    Monitors:
    - Schedule Conformance
    - Material Availability  
    - OEE (Overall Equipment Effectiveness)
    - Machine Health
    
    Takes actions:
    - Trigger replanning
    - Expedite purchase orders
    - Adjust order priorities
    - Log alerts for human review
    """
    
    def __init__(self):
        super().__init__(
            name="PlanningAgent",
            config={
                "cycle_interval_seconds": 30,
                "thresholds": {
                    "schedule_conformance_min": 90.0,
                    "material_availability_min": 80.0,
                    "oee_min": 75.0,
                    "machine_health_min": 80.0
                }
            }
        )
        self.llm = AzureOpenAIClient()
        self.thresholds = self.config["thresholds"]
    
    def observe(self, session: Session) -> Dict[str, Any]:
        """
        Gather current plant state.
        
        Collects:
        - KPIs from compute_kpis()
        - Inventory status
        - Recent alerts
        - Active orders status
        """
        from ..services.kpis import compute_kpis
        from ..services.inventory import get_inventory_view
        from ..models.simulation import ProductionRealtime
        from ..models.planning import PlanRun
        
        # Get KPIs
        kpis = compute_kpis()
        kpi_data = {}
        for kpi in kpis:
            kpi_data[kpi.name] = {
                "value": kpi.value,
                "target": kpi.target,
                "status": kpi.alert_status
            }
        
        # Get inventory status
        inventory = get_inventory_view(session)
        critical_materials = [
            {
                "material_id": item["material_id"],
                "current_stock": item["current_stock"],
                "required": item["required_for_order"],
                "remaining_requirement": item["remaining_requirement"]
            }
            for item in inventory
            if item["remaining_requirement"] > item["current_stock"]
        ]
        
        # Get recent alerts from ProductionRealtime
        run = session.exec(
            select(PlanRun).order_by(PlanRun.created_at.desc())
        ).first()
        
        recent_alerts = []
        if run:
            realtime_rows = session.exec(
                select(ProductionRealtime)
                .where(ProductionRealtime.run_id == run.run_id)
                .order_by(ProductionRealtime.ts.desc())
                .limit(10)
            ).all()
            
            for rt in realtime_rows:
                if rt.alert_status and rt.alert_status != "Normal":
                    recent_alerts.append({
                        "line": rt.assembly_line,
                        "alert": rt.alert_status,
                        "timestamp": rt.ts.isoformat()
                    })
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "kpis": kpi_data,
            "critical_materials": critical_materials,
            "recent_alerts": recent_alerts[:5],  # Limit to 5 most recent
            "thresholds": self.thresholds
        }
    
    def think(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze observation and decide on action.
        
        1. Detect threshold breaches
        2. Use LLM for complex reasoning (or fallback rules)
        3. Return decision with explanation
        """
        # Step 1: Detect issues
        issues = self._detect_issues(observation)
        
        # Step 2: Get decision from LLM (or fallback)
        mcp_tools = self._get_mcp_tools()
        decision = self.llm.analyze_situation(observation, issues, mcp_tools)
        
        # Add issue context to decision
        decision["issues_detected"] = len(issues)
        decision["issues"] = issues
        
        return decision
    
    def act(self, decision: Dict[str, Any], session: Session) -> Dict[str, Any]:
        """
        Execute the decided action.
        """
        action = decision.get("action", "CONTINUE")
        result = {"status": "executed", "action": action}
        
        # Log the decision
        self._log_decision(session, decision)
        
        if action == "CONTINUE":
            result["message"] = "No action needed"
            
        elif action == "REPLAN":
            result.update(self._execute_replan(session, decision))
            
        elif action == "EXPEDITE_PO":
            result.update(self._execute_expedite_po(session, decision))
            
        elif action == "ADJUST_PRIORITY":
            result.update(self._execute_adjust_priority(session, decision))
            
        elif action == "ALERT":
            result.update(self._execute_alert(session, decision))
            
        elif action == "TOOL_CALL":
            # Execute MCP tool calls from LLM
            for tool_call in decision.get("tool_calls", []):
                tool_result = self._execute_tool_call(session, tool_call)
                result.setdefault("tool_results", []).append(tool_result)
        
        return result
    
    def _detect_issues(self, observation: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Detect threshold breaches and issues."""
        issues = []
        kpis = observation.get("kpis", {})
        thresholds = observation.get("thresholds", self.thresholds)
        
        # Check Schedule Conformance
        sched = kpis.get("Schedule Conformance %", {})
        if sched.get("value", 100) < thresholds.get("schedule_conformance_min", 90):
            issues.append({
                "type": "schedule_deviation",
                "kpi": "Schedule Conformance %",
                "value": sched.get("value"),
                "threshold": thresholds["schedule_conformance_min"],
                "severity": "critical" if sched.get("value", 100) < 80 else "warning"
            })
        
        # Check Material Availability
        mat = kpis.get("Material Availability %", {})
        if mat.get("value", 100) < thresholds.get("material_availability_min", 80):
            issues.append({
                "type": "material_shortage",
                "kpi": "Material Availability %",
                "value": mat.get("value"),
                "threshold": thresholds["material_availability_min"],
                "severity": "critical" if mat.get("value", 100) < 60 else "warning"
            })
        
        # Check OEE
        oee = kpis.get("Average Line OEE (approx)", {})
        if oee.get("value", 100) < thresholds.get("oee_min", 75):
            issues.append({
                "type": "oee_low",
                "kpi": "Average Line OEE",
                "value": oee.get("value"),
                "threshold": thresholds["oee_min"],
                "severity": "warning"
            })
        
        # Check Machine Health
        health = kpis.get("Average Machine Health Index", {})
        if health.get("value", 100) < thresholds.get("machine_health_min", 80):
            issues.append({
                "type": "machine_health",
                "kpi": "Average Machine Health Index",
                "value": health.get("value"),
                "threshold": thresholds["machine_health_min"],
                "severity": "critical" if health.get("value", 100) < 70 else "warning"
            })
        
        # Check critical materials
        for mat in observation.get("critical_materials", []):
            if mat["current_stock"] <= 0:
                issues.append({
                    "type": "material_shortage",
                    "material_id": mat["material_id"],
                    "current_stock": mat["current_stock"],
                    "required": mat["required"],
                    "severity": "critical"
                })
        
        return issues
    
    def _get_mcp_tools(self) -> List[Dict]:
        """Get available MCP tools for LLM function calling."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "trigger_replan",
                    "description": "Trigger replanning of production schedule",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "description": "Reason for replanning"
                            }
                        },
                        "required": ["reason"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "expedite_po",
                    "description": "Expedite a purchase order for critical materials",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "material_id": {
                                "type": "string",
                                "description": "Material ID to expedite"
                            },
                            "urgency": {
                                "type": "string",
                                "enum": ["high", "critical"],
                                "description": "Urgency level"
                            }
                        },
                        "required": ["material_id", "urgency"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "log_alert",
                    "description": "Log an alert for human review",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "alert_type": {
                                "type": "string",
                                "description": "Type of alert"
                            },
                            "message": {
                                "type": "string",
                                "description": "Alert message"
                            },
                            "severity": {
                                "type": "string",
                                "enum": ["low", "medium", "high", "critical"],
                                "description": "Alert severity"
                            }
                        },
                        "required": ["alert_type", "message", "severity"]
                    }
                }
            }
        ]
    
    def _log_decision(self, session: Session, decision: Dict[str, Any]):
        """Log decision to database."""
        from ..services.event_logger import log_event
        
        action = decision.get("action", "UNKNOWN")
        reason = decision.get("reason", "No reason provided")
        llm_used = decision.get("llm_used", False)
        
        log_event(
            session,
            f"AGENT_DECISION_{action}",
            f"[{'LLM' if llm_used else 'RULE'}] {reason}"
        )
    
    def _execute_replan(self, session: Session, decision: Dict) -> Dict:
        """Execute replanning action."""
        from ..services.planning import plan_all_open_orders
        
        try:
            result = plan_all_open_orders()
            return {"message": "Replanning triggered", "plan_result": str(result)}
        except Exception as e:
            return {"message": f"Replan failed: {e}", "error": True}
    
    def _execute_expedite_po(self, session: Session, decision: Dict) -> Dict:
        """Execute PO expedite action."""
        affected = decision.get("affected_items", [])
        # In a real system, this would update PO priorities
        return {"message": f"PO expedite requested for: {affected}"}
    
    def _execute_adjust_priority(self, session: Session, decision: Dict) -> Dict:
        """Execute priority adjustment."""
        affected = decision.get("affected_items", [])
        return {"message": f"Priority adjustment for: {affected}"}
    
    def _execute_alert(self, session: Session, decision: Dict) -> Dict:
        """Log alert for human review."""
        from ..services.event_logger import log_event
        
        reason = decision.get("reason", "Agent alert")
        log_event(session, "AGENT_ALERT", reason)
        return {"message": "Alert logged for human review"}
    
    def _execute_tool_call(self, session: Session, tool_call: Dict) -> Dict:
        """Execute an MCP tool call."""
        tool_name = tool_call.get("name")
        args = tool_call.get("arguments", {})
        
        # Map tool names to actions
        if tool_name == "trigger_replan":
            return self._execute_replan(session, {"reason": args.get("reason")})
        elif tool_name == "expedite_po":
            return self._execute_expedite_po(session, {"affected_items": [args.get("material_id")]})
        elif tool_name == "log_alert":
            from ..services.event_logger import log_event
            log_event(session, args.get("alert_type", "ALERT"), args.get("message", ""))
            return {"message": "Alert logged"}
        
        return {"message": f"Unknown tool: {tool_name}"}
    
    def _summarize_observation(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """Create compact summary for logging."""
        kpis = observation.get("kpis", {})
        return {
            "schedule_conformance": kpis.get("Schedule Conformance %", {}).get("value"),
            "material_availability": kpis.get("Material Availability %", {}).get("value"),
            "critical_materials_count": len(observation.get("critical_materials", [])),
            "alerts_count": len(observation.get("recent_alerts", []))
        }
