# app/agents/llm_client.py
"""
Azure OpenAI client for agent decision making.
"""

import os
import json
from typing import Dict, Any, List, Optional


class AzureOpenAIClient:
    """
    Azure OpenAI client wrapper for agent LLM calls.
    
    Handles:
    - Chat completions with tool/function calling
    - Structured output parsing
    - Fallback to rule-based decisions when LLM unavailable
    """
    
    def __init__(self):
        """Initialize Azure OpenAI client from environment variables."""
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4")
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
        
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """Initialize the Azure OpenAI client if credentials are available."""
        if self.api_key and self.endpoint:
            try:
                from openai import AzureOpenAI
                self.client = AzureOpenAI(
                    api_key=self.api_key,
                    api_version=self.api_version,
                    azure_endpoint=self.endpoint
                )
            except ImportError:
                print("Warning: openai package not installed. Using fallback mode.")
                self.client = None
        else:
            print("Warning: Azure OpenAI credentials not configured. Using fallback mode.")
    
    def analyze_situation(
        self, 
        observation: Dict[str, Any], 
        issues: List[Dict[str, Any]],
        available_tools: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Analyze plant situation and recommend actions.
        
        Args:
            observation: Current plant state (KPIs, inventory, alerts)
            issues: Detected issues/threshold breaches
            available_tools: MCP tools available for the agent
            
        Returns:
            Decision dict with action, reason, and executed tool results
        """
        if not self.client:
            return self._fallback_decision(issues)
        
        try:
            messages = [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": self._build_user_prompt(observation, issues)}
            ]
            
            kwargs = {
                "model": self.deployment,
                "messages": messages,
                "temperature": 0.3,  # Lower temperature for more deterministic decisions
                "max_tokens": 500
            }
            
            # Add tools if available
            if available_tools:
                kwargs["tools"] = available_tools
                kwargs["tool_choice"] = "auto"
            
            response = self.client.chat.completions.create(**kwargs)
            
            # Parse response and potentially execute tools
            result = self._parse_response(response)
            
            # If LLM requested tool calls, execute them via MCP
            if result.get("action") == "TOOL_CALL" and result.get("tool_calls"):
                tool_results = self._execute_tool_calls(result["tool_calls"])
                result["tool_results"] = tool_results
                result["mcp_executed"] = True
                
                # Update action based on executed tools
                if tool_results:
                    first_tool = result["tool_calls"][0]["name"]
                    result["action"] = self._tool_to_action(first_tool)
            
            return result
            
        except Exception as e:
            print(f"LLM call failed: {e}. Falling back to rules.")
            return self._fallback_decision(issues)
    
    def _execute_tool_calls(self, tool_calls: List[Dict]) -> List[Dict]:
        """
        Execute tool calls via MCP HTTP endpoints.
        
        Args:
            tool_calls: List of {"name": str, "arguments": dict}
            
        Returns:
            List of tool execution results
        """
        try:
            from .mcp_executor import execute_tools
            
            results = execute_tools(tool_calls)
            return [
                {
                    "tool": r.tool_name,
                    "success": r.success,
                    "result": r.result,
                    "error": r.error
                }
                for r in results
            ]
        except Exception as e:
            print(f"MCP tool execution failed: {e}")
            return [{"error": str(e)}]
    
    def _tool_to_action(self, tool_name: str) -> str:
        """Map tool name to action type."""
        mapping = {
            "trigger_replan": "REPLAN",
            "expedite_purchase_order": "EXPEDITE_PO",
            "create_purchase_order": "CREATE_PO",
            "adjust_order_priority": "ADJUST_PRIORITY",
            "log_alert": "ALERT",
            "schedule_maintenance": "SCHEDULE_MAINTENANCE",
            "alert_failure_risk": "ALERT_FAILURE_RISK",
            "get_kpis": "CONTINUE",
            "get_inventory_status": "CONTINUE"
        }
        return mapping.get(tool_name, "TOOL_CALL")
    
    def _system_prompt(self) -> str:
        """System prompt for the planning agent."""

        return """You are an AI planning agent for a manufacturing plant (P-HE Simulation Plant).

                Your responsibilities:
                1. Monitor KPIs: Schedule Conformance, Material Availability, OEE, Machine Health
                2. Detect issues requiring intervention
                3. Decide on corrective actions

                Available actions:
                - REPLAN: Trigger replanning when schedule is at risk
                - EXPEDITE_PO: Expedite purchase orders for critical materials
                - ADJUST_PRIORITY: Change order priorities
                - ALERT: Log alert for human review
                - CONTINUE: No action needed

                Decision guidelines:
                - Schedule Conformance < 90%: Consider REPLAN
                - Material Availability < 80%: Consider EXPEDITE_PO
                - OEE < 75%: Consider ALERT for maintenance
                - Machine Health < 80%: Consider ALERT

                Always provide clear reasoning for your decisions.

                Respond in JSON format:
                {
                    "action": "ACTION_NAME",
                    "reason": "Clear explanation",
                    "priority": 1-5,
                    "affected_items": ["order_id or material_id if applicable"]
                }"""

    def _build_user_prompt(self, observation: Dict, issues: List) -> str:
        """Build user prompt with current situation."""
        return f"""Current Plant Status:
                    {json.dumps(observation, indent=2, default=str)}

                    Detected Issues:
                    {json.dumps(issues, indent=2, default=str)}

                    Based on this situation, what action should be taken?"""

    def _parse_response(self, response) -> Dict[str, Any]:
        """Parse LLM response into structured decision."""
        message = response.choices[0].message
        
        result = {
            "action": "CONTINUE",
            "reason": "No issues detected",
            "llm_used": True
        }
        
        # Check for tool calls
        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments)
                }
                for tc in message.tool_calls
            ]
            result["action"] = "TOOL_CALL"
            result["reason"] = f"Executing {len(message.tool_calls)} tool(s)"
        
        # Parse content if present
        elif message.content:
            try:
                parsed = json.loads(message.content)
                result.update(parsed)
            except json.JSONDecodeError:
                result["reason"] = message.content
        
        return result
    
    def _fallback_decision(self, issues: List[Dict]) -> Dict[str, Any]:
        """
        Rule-based fallback when LLM is unavailable.
        
        Simple rules:
        - Multiple issues → REPLAN
        - Single critical issue → specific action
        - No issues → CONTINUE
        """
        if not issues:
            return {
                "action": "CONTINUE",
                "reason": "All KPIs within acceptable range",
                "llm_used": False
            }
        
        # Find most critical issue
        critical_issues = [i for i in issues if i.get("severity") == "critical"]
        
        if len(issues) >= 3 or len(critical_issues) >= 2:
            return {
                "action": "REPLAN",
                "reason": f"Multiple issues detected ({len(issues)} total). Triggering replan.",
                "priority": 5,
                "llm_used": False
            }
        
        # Handle specific issue types
        first_issue = issues[0]
        issue_type = first_issue.get("type", "unknown")
        
        if issue_type == "material_shortage":
            return {
                "action": "EXPEDITE_PO",
                "reason": f"Material shortage detected: {first_issue.get('material_id', 'unknown')}",
                "priority": 4,
                "affected_items": [first_issue.get("material_id")],
                "llm_used": False
            }
        
        if issue_type == "schedule_deviation":
            return {
                "action": "REPLAN",
                "reason": f"Schedule conformance low: {first_issue.get('value', 0)}%",
                "priority": 4,
                "llm_used": False
            }
        
        if issue_type in ("machine_health", "oee_low"):
            return {
                "action": "ALERT",
                "reason": f"Equipment issue: {issue_type}",
                "priority": 3,
                "llm_used": False
            }
        
        return {
            "action": "ALERT",
            "reason": f"Issue detected: {issue_type}",
            "priority": 2,
            "llm_used": False
        }
    
    def is_available(self) -> bool:
        """Check if LLM client is available."""
        return self.client is not None
