# app/agents/agent_runner.py
"""
Background task runner for agents.
"""

import asyncio
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any

from sqlmodel import Session

from ..database import engine
from .base_agent import BaseAgent


# Global agent registry
_agents: Dict[str, BaseAgent] = {}
_agent_threads: Dict[str, threading.Thread] = {}
_decision_log: List[Dict[str, Any]] = []  # In-memory log (limited size)
MAX_LOG_SIZE = 100


def agent_loop_sync(agent_name: str, interval_seconds: int = 30):
    """
    Synchronous agent loop running in a separate thread.
    
    Args:
        agent_name: Name of agent to run
        interval_seconds: Time between cycles
    """
    import time
    
    agent = _agents.get(agent_name)
    if not agent:
        return
    
    agent.is_running = True
    print(f"Agent {agent_name} started with {interval_seconds}s interval")
    
    while agent.is_running:
        try:
            with Session(engine) as session:
                # Run the async cycle in a new event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(agent.run_cycle(session))
                    _log_decision(agent_name, result)
                    session.commit()
                    print(f"Agent cycle {result.get('cycle')}: {result.get('decision', {}).get('action', 'UNKNOWN')}")
                finally:
                    loop.close()
                
        except Exception as e:
            print(f"Agent error: {e}")
            _log_error(agent_name, str(e))
        
        # Sleep between cycles
        time.sleep(interval_seconds)
    
    print(f"Agent {agent_name} stopped.")


def _log_decision(agent_name: str, result: Dict[str, Any]):
    """Log decision to in-memory store."""
    global _decision_log
    
    log_entry = {
        "agent": agent_name,
        "timestamp": datetime.utcnow().isoformat(),
        "cycle": result.get("cycle"),
        "decision": result.get("decision", {}),
        "result": result.get("result", {})
    }
    
    _decision_log.append(log_entry)
    
    # Keep log size bounded
    if len(_decision_log) > MAX_LOG_SIZE:
        _decision_log = _decision_log[-MAX_LOG_SIZE:]


def _log_error(agent_name: str, error: str):
    """Log error to in-memory store."""
    global _decision_log
    
    log_entry = {
        "agent": agent_name,
        "timestamp": datetime.utcnow().isoformat(),
        "error": error
    }
    
    _decision_log.append(log_entry)


def start_agent(agent_name: str, interval: int = 30) -> Dict[str, Any]:
    """
    Start an agent by name.
    
    Args:
        agent_name: "planning" or other registered agent
        interval: Cycle interval in seconds
        
    Returns:
        Status dict
    """
    global _agents, _agent_threads
    
    # Check if already running
    if agent_name in _agents and _agents[agent_name].is_running:
        return {"status": "already_running", "agent": agent_name}
    
    # Create agent instance
    if agent_name == "planning":
        from .planning_agent import PlanningAgent
        agent = PlanningAgent()
    elif agent_name == "supply_chain":
        from .supply_chain_agent import SupplyChainAgent
        agent = SupplyChainAgent()
    elif agent_name == "maintenance":
        from .maintenance_agent import MaintenanceAgent
        agent = MaintenanceAgent()
    elif agent_name == "orchestrator":
        from .orchestrator_agent import OrchestratorAgent
        agent = OrchestratorAgent()
    else:
        return {"status": "error", "message": f"Unknown agent: {agent_name}"}
    
    _agents[agent_name] = agent
    
    # Start background thread
    thread = threading.Thread(
        target=agent_loop_sync,
        args=(agent_name, interval),
        daemon=True,
        name=f"agent-{agent_name}"
    )
    thread.start()
    _agent_threads[agent_name] = thread
    
    return {
        "status": "started",
        "agent": agent_name,
        "interval_seconds": interval,
        "llm_available": agent.llm.is_available() if hasattr(agent, 'llm') else False
    }


def stop_agent(agent_name: str) -> Dict[str, Any]:
    """Stop a running agent."""
    global _agents, _agent_threads
    
    if agent_name not in _agents:
        return {"status": "not_found", "agent": agent_name}
    
    agent = _agents[agent_name]
    agent.is_running = False
    
    # Thread will stop on next loop iteration
    if agent_name in _agent_threads:
        del _agent_threads[agent_name]
    
    return {
        "status": "stopped",
        "agent": agent_name,
        "cycles_completed": agent.cycle_count
    }


def stop_all_agents() -> Dict[str, Any]:
    """Stop all running agents."""
    results = {}
    for agent_name in list(_agents.keys()):
        results[agent_name] = stop_agent(agent_name)
    return {"stopped": results}


def start_all_agents() -> Dict[str, Any]:
    """
    Start all agents in the multi-agent system.
    
    Order matters:
    1. Supply Chain (60s interval)
    2. Maintenance (60s interval)
    3. Planning (30s interval)
    4. Orchestrator (15s interval - fastest, coordinates others)
    """
    results = {}
    
    # Start specialized agents first
    results["supply_chain"] = start_agent("supply_chain", interval=60)
    results["maintenance"] = start_agent("maintenance", interval=60)
    results["planning"] = start_agent("planning", interval=30)
    
    # Start orchestrator last (it monitors others)
    results["orchestrator"] = start_agent("orchestrator", interval=15)
    
    return {"started": results}


def get_status(agent_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get status of agent(s).
    
    Args:
        agent_name: Specific agent or None for all
    """
    if agent_name:
        if agent_name not in _agents:
            return {"status": "not_found", "agent": agent_name}
        return _agents[agent_name].get_status()
    
    # Return all agents
    return {
        "agents": {
            name: agent.get_status()
            for name, agent in _agents.items()
        }
    }


def get_decisions(agent_name: Optional[str] = None, limit: int = 20) -> List[Dict]:
    """
    Get recent agent decisions.
    
    Args:
        agent_name: Filter by agent or None for all
        limit: Max number of decisions to return
    """
    global _decision_log
    
    if agent_name:
        filtered = [d for d in _decision_log if d.get("agent") == agent_name]
    else:
        filtered = _decision_log
    
    # Return most recent first
    return list(reversed(filtered[-limit:]))


def run_single_cycle_sync(agent_name: str) -> Dict[str, Any]:
    """
    Run a single agent cycle synchronously (for testing/debugging).
    
    Returns the cycle result immediately.
    """
    if agent_name == "planning":
        from .planning_agent import PlanningAgent
        agent = PlanningAgent()
    elif agent_name == "supply_chain":
        from .supply_chain_agent import SupplyChainAgent
        agent = SupplyChainAgent()
    elif agent_name == "maintenance":
        from .maintenance_agent import MaintenanceAgent
        agent = MaintenanceAgent()
    elif agent_name == "orchestrator":
        from .orchestrator_agent import OrchestratorAgent
        agent = OrchestratorAgent()
    else:
        return {"error": f"Unknown agent: {agent_name}"}
    
    with Session(engine) as session:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(agent.run_cycle(session))
            session.commit()
            return result
        finally:
            loop.close()


def list_available_agents() -> List[str]:
    """List all available agent types."""
    return ["planning", "supply_chain", "maintenance", "orchestrator"]

