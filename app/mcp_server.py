# app/mcp_server.py
"""
MCP (Model Context Protocol) server setup.

Exposes FastAPI endpoints as tools for AI agents.
"""

from typing import Optional


def setup_mcp(app, include_tags: Optional[list] = None):
    """
    Initialize MCP server to expose FastAPI endpoints as AI tools.
    
    Args:
        app: FastAPI application instance
        include_tags: Optional list of route tags to include
    
    Usage:
        from .mcp_server import setup_mcp
        setup_mcp(app, include_tags=["planning", "agent"])
    """
    try:
        from fastapi_mcp import FastApiMCP
        
        mcp = FastApiMCP(
            app,
            name="Manufacturing Scheduler MCP",
            description="AI-callable tools for production planning, inventory, and KPI monitoring"
        )
        
        # Mount MCP server at /mcp
        mcp.mount()
        
        print("✓ MCP server mounted at /mcp")
        return mcp
        
    except ImportError:
        print("Warning: fastapi-mcp not installed. MCP server not available.")
        print("Install with: pip install fastapi-mcp")
        return None


def get_mcp_tool_definitions():
    """
    Get tool definitions for direct LLM function calling.
    
    These can be passed to Azure OpenAI's tool parameter.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "trigger_replan",
                "description": "Trigger replanning of production schedule when schedule conformance drops or demand changes",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "Reason for triggering the replan"
                        }
                    },
                    "required": ["reason"]
                }
            }
        },
        {
            "type": "function", 
            "function": {
                "name": "expedite_purchase_order",
                "description": "Expedite a purchase order for critical materials when inventory is low",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "material_id": {
                            "type": "string",
                            "description": "ID of the material to expedite (e.g., M014, M076)"
                        },
                        "urgency": {
                            "type": "string",
                            "enum": ["high", "critical"],
                            "description": "Urgency level for the expedite request"
                        }
                    },
                    "required": ["material_id", "urgency"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "adjust_order_priority",
                "description": "Adjust production priority for an order that is at risk of delay",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_id": {
                            "type": "string",
                            "description": "Order ID to adjust priority for"
                        },
                        "new_priority": {
                            "type": "integer",
                            "description": "New priority level (1-5, where 5 is highest)"
                        },
                        "reason": {
                            "type": "string",
                            "description": "Reason for priority adjustment"
                        }
                    },
                    "required": ["order_id", "new_priority", "reason"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "log_alert",
                "description": "Log an alert for human review when situation requires manual intervention",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "alert_type": {
                            "type": "string",
                            "description": "Type of alert (e.g., MAINTENANCE_REQUIRED, CAPACITY_ISSUE)"
                        },
                        "message": {
                            "type": "string",
                            "description": "Detailed alert message"
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["low", "medium", "high", "critical"],
                            "description": "Alert severity level"
                        }
                    },
                    "required": ["alert_type", "message", "severity"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_kpis",
                "description": "Get current KPI values (Schedule Conformance, Material Availability, OEE, Machine Health)",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_inventory_status",
                "description": "Get current inventory status including critical materials",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "critical_only": {
                            "type": "boolean",
                            "description": "If true, only return materials below threshold"
                        }
                    },
                    "required": []
                }
            }
        }
    ]
