# app/agents/config.py
"""
Agent configuration settings.
"""

import os
from dataclasses import dataclass


@dataclass
class AgentConfig:
    """Global configuration for the agent system."""
    
    # Dry-run mode: when True, agents log but don't modify data
    WRITE_ENABLED: bool = True
    
    # LLM settings
    LLM_ENABLED: bool = True
    LLM_CONFLICT_THRESHOLD: float = 0.05  # Only use LLM when predicted KPI loss > 5%
    
    # Cycle intervals (seconds)
    PLANNING_INTERVAL: int = 30
    SUPPLY_CHAIN_INTERVAL: int = 60
    MAINTENANCE_INTERVAL: int = 60
    ORCHESTRATOR_INTERVAL: int = 15
    
    # Thresholds
    SCHEDULE_CONFORMANCE_WARNING: float = 85.0
    SCHEDULE_CONFORMANCE_CRITICAL: float = 75.0
    MATERIAL_AVAILABILITY_WARNING: float = 80.0
    MATERIAL_AVAILABILITY_CRITICAL: float = 60.0
    MACHINE_HEALTH_WARNING: float = 80.0
    MACHINE_HEALTH_CRITICAL: float = 70.0
    
    @classmethod
    def from_env(cls) -> "AgentConfig":
        """Load config from environment variables."""
        return cls(
            WRITE_ENABLED=os.getenv("AGENT_WRITE_ENABLED", "true").lower() == "true",
            LLM_ENABLED=os.getenv("AGENT_LLM_ENABLED", "true").lower() == "true",
        )


# Global config instance
_config: AgentConfig = None


def get_config() -> AgentConfig:
    """Get or create global config."""
    global _config
    if _config is None:
        _config = AgentConfig.from_env()
    return _config


def set_dry_run(enabled: bool = True):
    """Enable or disable dry-run (advisory) mode."""
    global _config
    if _config is None:
        _config = AgentConfig()
    _config.WRITE_ENABLED = not enabled
    return {"dry_run": enabled, "write_enabled": not enabled}


def is_write_enabled() -> bool:
    """Check if agents are allowed to modify data."""
    return get_config().WRITE_ENABLED
