# app/agents/mcp_executor.py
"""
MCP Tool Executor - Executes tools via HTTP calls to MCP-exposed endpoints.

This module enables agents to call FastAPI endpoints through the MCP protocol,
making the agent architecture truly tool-based.
"""

import httpx
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass 
class ToolResult:
    """Result of a tool execution."""
    tool_name: str
    success: bool
    result: Any
    error: Optional[str] = None


class MCPToolExecutor:
    """
    Executes MCP tools by calling the corresponding FastAPI endpoints.
    
    This provides the bridge between LLM tool calls and actual API execution.
    """
    
    # Map tool names to API endpoints
    TOOL_ENDPOINTS = {
        # Planning tools
        "trigger_replan": {
            "method": "POST",
            "path": "/api/agent/tools/trigger_replan",
            "description": "Trigger production replanning"
        },
        
        # Supply chain tools
        "expedite_purchase_order": {
            "method": "POST",
            "path": "/api/agent/tools/expedite_po",
            "description": "Expedite a purchase order"
        },
        "create_purchase_order": {
            "method": "POST",
            "path": "/api/agent/tools/create_po",
            "description": "Create a new purchase order"
        },
        
        # Priority tools
        "adjust_order_priority": {
            "method": "POST",
            "path": "/api/agent/tools/adjust_priority",
            "description": "Adjust order priority"
        },
        
        # Alert tools
        "log_alert": {
            "method": "POST",
            "path": "/api/agent/tools/log_alert",
            "description": "Log an alert for human review"
        },
        
        # Query tools (read-only)
        "get_kpis": {
            "method": "GET",
            "path": "/api/agent/tools/kpis",
            "description": "Get current KPIs"
        },
        "get_inventory_status": {
            "method": "GET",
            "path": "/api/agent/tools/inventory",
            "description": "Get inventory status"
        },
        
        # Maintenance tools
        "schedule_maintenance": {
            "method": "POST",
            "path": "/api/agent/tools/schedule_maintenance",
            "description": "Schedule maintenance window"
        },
        "alert_failure_risk": {
            "method": "POST",
            "path": "/api/agent/tools/alert_failure",
            "description": "Alert about failure risk"
        }
    }
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        """
        Initialize MCP executor.
        
        Args:
            base_url: Base URL of the FastAPI application
        """
        self.base_url = base_url
        self.client = httpx.Client(timeout=30.0)
    
    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> ToolResult:
        """
        Execute a single tool by name.
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            
        Returns:
            ToolResult with success status and result/error
        """
        tool_config = self.TOOL_ENDPOINTS.get(tool_name)
        
        if not tool_config:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                result=None,
                error=f"Unknown tool: {tool_name}"
            )
        
        url = f"{self.base_url}{tool_config['path']}"
        method = tool_config["method"]
        
        try:
            if method == "GET":
                response = self.client.get(url, params=arguments)
            elif method == "POST":
                response = self.client.post(url, json=arguments)
            else:
                return ToolResult(
                    tool_name=tool_name,
                    success=False,
                    result=None,
                    error=f"Unsupported method: {method}"
                )
            
            response.raise_for_status()
            
            return ToolResult(
                tool_name=tool_name,
                success=True,
                result=response.json()
            )
            
        except httpx.HTTPStatusError as e:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                result=None,
                error=f"HTTP {e.response.status_code}: {e.response.text}"
            )
        except Exception as e:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                result=None,
                error=str(e)
            )
    
    def execute_tools(self, tool_calls: List[Dict[str, Any]]) -> List[ToolResult]:
        """
        Execute multiple tool calls.
        
        Args:
            tool_calls: List of {"name": str, "arguments": dict}
            
        Returns:
            List of ToolResult for each call
        """
        results = []
        for call in tool_calls:
            result = self.execute_tool(
                tool_name=call.get("name", ""),
                arguments=call.get("arguments", {})
            )
            results.append(result)
        return results
    
    def get_available_tools(self) -> List[str]:
        """Get list of available tool names."""
        return list(self.TOOL_ENDPOINTS.keys())
    
    def close(self):
        """Close the HTTP client."""
        self.client.close()


# Global executor instance
_executor: Optional[MCPToolExecutor] = None


def get_executor(base_url: str = "http://localhost:8000") -> MCPToolExecutor:
    """Get or create global MCP executor."""
    global _executor
    if _executor is None:
        _executor = MCPToolExecutor(base_url)
    return _executor


def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> ToolResult:
    """Convenience function to execute a tool."""
    return get_executor().execute_tool(tool_name, arguments)


def execute_tools(tool_calls: List[Dict[str, Any]]) -> List[ToolResult]:
    """Convenience function to execute multiple tools."""
    return get_executor().execute_tools(tool_calls)
