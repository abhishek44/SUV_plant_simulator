# app/agents/supply_chain_agent.py
"""
Supply Chain Agent - Inventory monitoring and PO management.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List
from sqlmodel import Session, select

from .base_agent import BaseAgent
from .llm_client import AzureOpenAIClient


class SupplyChainAgent(BaseAgent):
    """
    Autonomous agent for supply chain management.
    
    Monitors:
    - Inventory levels and consumption rates
    - Purchase order status and ETAs
    - Material criticality
    
    Takes actions:
    - Create new purchase orders
    - Expedite existing POs
    - Alert on critical shortages
    """
    
    def __init__(self):
        super().__init__(
            name="SupplyChainAgent",
            config={
                "cycle_interval_seconds": 60,
                "thresholds": {
                    "safety_stock_days": 3,
                    "critical_stock_pct": 20,
                    "reorder_point_pct": 40
                }
            }
        )
        self.llm = AzureOpenAIClient()
        self.thresholds = self.config["thresholds"]
    
    def observe(self, session: Session) -> Dict[str, Any]:
        """
        Gather supply chain state.
        
        Collects:
        - Current inventory levels
        - Consumption rates (calculated from production output and BOM)
        - Open purchase orders
        - Days of stock remaining
        """
        from ..services.inventory import get_inventory_view, bom_by_product
        from ..models.supply import PurchaseOrder
        from ..models.simulation import ProductionRealtime
        from ..models.planning import PlanRun
        from sqlalchemy import func
        
        # Get inventory status
        inventory = get_inventory_view(session)
        
        # Calculate consumption rate from recent production
        # Get production output over last hour (3600 seconds of simulation)
        run = session.exec(
            select(PlanRun).order_by(PlanRun.created_at.desc())
        ).first()
        
        daily_consumption_by_material: Dict[str, float] = {}
        
        if run:
            # Get recent production grouped by product
            recent_production = session.exec(
                select(ProductionRealtime)
                .where(ProductionRealtime.run_id == run.run_id)
                .order_by(ProductionRealtime.ts.desc())
                .limit(100)
            ).all()
            
            if recent_production and len(recent_production) >= 2:
                # Calculate production rate (units per simulation second)
                first = recent_production[-1]
                last = recent_production[0]
                time_delta = (last.ts - first.ts).total_seconds()
                
                if time_delta > 0:
                    # Group by line to get total output
                    output_by_line = {}
                    for rt in recent_production:
                        if rt.assembly_line not in output_by_line:
                            output_by_line[rt.assembly_line] = {"first": rt.production_output_cum, "last": rt.production_output_cum}
                        output_by_line[rt.assembly_line]["last"] = rt.production_output_cum
                    
                    total_output = sum(v["last"] - v["first"] for v in output_by_line.values())
                    units_per_second = total_output / time_delta if time_delta > 0 else 0
                    units_per_day = units_per_second * 86400  # Scale to daily rate
                    
                    # Calculate material consumption from BOM
                    # Assume even distribution across products for simplicity
                    if bom_by_product:
                        products = list(bom_by_product.keys())
                        units_per_product = units_per_day / len(products) if products else 0
                        
                        for product_id, bom_items in bom_by_product.items():
                            for bom in bom_items:
                                mid = bom.material_id
                                consumption = units_per_product * bom.quantity_per_unit
                                daily_consumption_by_material[mid] = daily_consumption_by_material.get(mid, 0) + consumption
        
        # Analyze each material
        materials_status = []
        critical_materials = []
        
        for item in inventory:
            current = item["current_stock"]
            required = item["required_for_order"]
            remaining_req = item["remaining_requirement"]
            material_id = item["material_id"]
            
            # Calculate stock percentage
            if required > 0:
                stock_pct = (current / required) * 100
            else:
                stock_pct = 100
            
            # Use calculated consumption rate or estimate
            daily_consumption = daily_consumption_by_material.get(material_id, 0)
            if daily_consumption <= 0:
                # Fallback: estimate from remaining requirement over planning horizon (9 days)
                daily_consumption = remaining_req / 9 if remaining_req > 0 else 0
            
            days_of_stock = current / daily_consumption if daily_consumption > 0 else 999
            
            status = {
                "material_id": material_id,
                "description": item.get("description", ""),
                "current_stock": current,
                "required": required,
                "remaining_requirement": remaining_req,
                "stock_pct": round(stock_pct, 1),
                "daily_consumption": round(daily_consumption, 2),
                "days_of_stock": round(days_of_stock, 1),
                "has_open_po": item.get("po_status") is not None,
                "po_eta": item.get("po_eta"),
                "po_quantity": item.get("po_quantity")
            }
            
            materials_status.append(status)
            
            # Flag critical materials
            if stock_pct < self.thresholds["critical_stock_pct"]:
                status["severity"] = "critical"
                critical_materials.append(status)
            elif stock_pct < self.thresholds["reorder_point_pct"]:
                status["severity"] = "warning"
                critical_materials.append(status)
        
        # Get open POs
        open_pos = session.exec(
            select(PurchaseOrder).where(PurchaseOrder.status != "DELIVERED")
        ).all()
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_materials": len(materials_status),
            "critical_count": len([m for m in critical_materials if m.get("severity") == "critical"]),
            "warning_count": len([m for m in critical_materials if m.get("severity") == "warning"]),
            "critical_materials": critical_materials,
            "open_po_count": len(open_pos),
            "thresholds": self.thresholds
        }
    
    def think(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze supply chain and decide on actions.
        """
        issues = self._detect_issues(observation)
        
        if not issues:
            return {
                "action": "CONTINUE",
                "reason": "All materials within acceptable stock levels",
                "llm_used": False
            }
        
        # Use LLM for complex decisions
        if self.llm.is_available() and len(issues) > 1:
            mcp_tools = self._get_mcp_tools()
            decision = self.llm.analyze_situation(observation, issues, mcp_tools)
            return decision
        
        # Fallback: handle most critical issue
        return self._fallback_decision(issues)
    
    def act(self, decision: Dict[str, Any], session: Session) -> Dict[str, Any]:
        """Execute supply chain actions."""
        action = decision.get("action", "CONTINUE")
        result = {"status": "executed", "action": action}
        
        self._log_decision(session, decision)
        
        if action == "CONTINUE":
            result["message"] = "No action needed"
            
        elif action == "CREATE_PO":
            result.update(self._create_purchase_order(session, decision))
            
        elif action == "EXPEDITE_PO":
            result.update(self._expedite_po(session, decision))
            
        elif action == "ALERT_SHORTAGE":
            result.update(self._alert_shortage(session, decision))
        
        return result
    
    def _detect_issues(self, observation: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Detect supply chain issues."""
        issues = []
        
        for material in observation.get("critical_materials", []):
            severity = material.get("severity", "warning")
            
            issue = {
                "type": "material_shortage",
                "material_id": material["material_id"],
                "current_stock": material["current_stock"],
                "stock_pct": material["stock_pct"],
                "days_of_stock": material["days_of_stock"],
                "has_open_po": material["has_open_po"],
                "severity": severity
            }
            
            # Determine recommended action
            if not material["has_open_po"]:
                issue["recommended_action"] = "CREATE_PO"
            elif severity == "critical":
                issue["recommended_action"] = "EXPEDITE_PO"
            else:
                issue["recommended_action"] = "ALERT_SHORTAGE"
            
            issues.append(issue)
        
        return issues
    
    def _fallback_decision(self, issues: List[Dict]) -> Dict[str, Any]:
        """Rule-based decision when LLM unavailable."""
        if not issues:
            return {"action": "CONTINUE", "reason": "No issues", "llm_used": False}
        
        # Handle most critical issue first
        critical = [i for i in issues if i["severity"] == "critical"]
        issue = critical[0] if critical else issues[0]
        
        action = issue.get("recommended_action", "ALERT_SHORTAGE")
        
        return {
            "action": action,
            "reason": f"Material {issue['material_id']} at {issue['stock_pct']}% stock",
            "affected_items": [issue["material_id"]],
            "priority": 5 if issue["severity"] == "critical" else 3,
            "llm_used": False
        }
    
    def _get_mcp_tools(self) -> List[Dict]:
        """Get MCP tools for supply chain actions."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "create_purchase_order",
                    "description": "Create a new purchase order for a material",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "material_id": {"type": "string"},
                            "quantity": {"type": "integer"},
                            "urgency": {"type": "string", "enum": ["normal", "high", "critical"]}
                        },
                        "required": ["material_id", "quantity"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "expedite_po",
                    "description": "Expedite an existing purchase order",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "material_id": {"type": "string"},
                            "urgency": {"type": "string", "enum": ["high", "critical"]}
                        },
                        "required": ["material_id", "urgency"]
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
            f"SUPPLY_CHAIN_{action}",
            f"[{'LLM' if llm_used else 'RULE'}] {reason}"
        )
    
    def _create_purchase_order(self, session: Session, decision: Dict) -> Dict:
        """
        Create a new purchase order using actual PO logic.
        
        Calls check_and_place_purchase_orders scoped to specific material.
        """
        from ..services.event_logger import log_event
        from ..services.purchase_order import check_and_place_purchase_orders
        from .config import is_write_enabled
        
        affected = decision.get("affected_items", [])
        material_id = affected[0] if affected else None
        
        if not material_id:
            return {"message": "No material specified", "status": "skipped"}
        
        # Check dry-run mode
        if not is_write_enabled():
            log_event(session, "PO_CREATED_DRYRUN", f"[Dry-run] Would create PO for {material_id}")
            return {"message": f"[Dry-run] Would create PO for {material_id}", "dry_run": True}
        
        # Call real PO logic - this will create PO if material needs it
        check_and_place_purchase_orders(session)
        
        log_event(session, "AGENT_PO_CREATED", f"Agent triggered PO creation for {material_id}")
        
        return {"message": f"PO created for {material_id}", "material_id": material_id}
    
    def _expedite_po(self, session: Session, decision: Dict) -> Dict:
        """
        Expedite existing PO by reducing ETA.
        
        In a real system this would notify supplier. Here we log the request.
        """
        from ..services.event_logger import log_event
        from ..models.supply import PurchaseOrder
        from .config import is_write_enabled
        from datetime import timedelta
        
        affected = decision.get("affected_items", [])
        material_id = affected[0] if affected else None
        
        if not material_id:
            return {"message": "No material specified", "status": "skipped"}
        
        # Find open PO for this material
        po = session.exec(
            select(PurchaseOrder).where(
                PurchaseOrder.material_id == material_id,
                PurchaseOrder.status != "DELIVERED"
            )
        ).first()
        
        if not po:
            log_event(session, "EXPEDITE_FAILED", f"No open PO found for {material_id}")
            return {"message": f"No open PO for {material_id}", "status": "not_found"}
        
        if not is_write_enabled():
            log_event(session, "PO_EXPEDITED_DRYRUN", f"[Dry-run] Would expedite PO {po.po_id}")
            return {"message": f"[Dry-run] Would expedite PO {po.po_id}", "dry_run": True}
        
        # Reduce ETA by 2 days (simulation of expediting)
        original_eta = po.eta_date
        po.eta_date = po.eta_date - timedelta(days=2)
        po.status = "EXPEDITED"
        
        log_event(session, "AGENT_PO_EXPEDITED", f"Expedited PO {po.po_id}: ETA {original_eta} -> {po.eta_date}")
        
        return {
            "message": f"PO {po.po_id} expedited",
            "po_id": po.po_id,
            "original_eta": str(original_eta),
            "new_eta": str(po.eta_date)
        }
    
    def _alert_shortage(self, session: Session, decision: Dict) -> Dict:
        """Log shortage alert and propose to pending actions table."""
        from ..services.event_logger import log_event
        from ..models.planning import AgentPendingAction
        from .config import is_write_enabled
        import json
        
        reason = decision.get("reason", "Material shortage")
        affected = decision.get("affected_items", [])
        material_id = affected[0] if affected else None
        
        # Always log the alert
        log_event(session, "SUPPLY_ALERT", reason)
        
        # Create pending action for orchestrator to review
        if is_write_enabled() and material_id:
            pending = AgentPendingAction(
                agent_name="supply_chain",
                action_type="ALERT_SHORTAGE",
                priority=decision.get("priority", 3),
                material_id=material_id,
                payload_json=json.dumps({"reason": reason}),
                status="PENDING",
                reason=reason
            )
            session.add(pending)
        
        return {"message": "Shortage alert logged", "material_id": material_id}
    
    def _summarize_observation(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """Compact summary for logging."""
        return {
            "total_materials": observation.get("total_materials"),
            "critical_count": observation.get("critical_count"),
            "warning_count": observation.get("warning_count"),
            "open_pos": observation.get("open_po_count")
        }
