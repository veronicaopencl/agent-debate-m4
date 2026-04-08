"""Federation SDK for external agent integration.

This module provides:
- API key generation and validation for external agents
- Agent registration and approval workflow
- Federation token management for cross-agent authentication
- Sample SDK client for external agents

Usage:
    from src.federation import FederationAuth, AgentRegistry
    
    # Generate API key for external agent
    auth = FederationAuth()
    api_key = auth.create_api_key(agent_id="agent_xyz", org="acme_corp")
    
    # Validate incoming request
    agent_info = auth.validate_api_key(request_api_key)
"""

from src.federation.auth import FederationAuth, FederationTokenError
from src.federation.agent_registry import AgentRegistry, AgentRegistryError

__all__ = [
    "FederationAuth",
    "FederationTokenError", 
    "AgentRegistry",
    "AgentRegistryError",
]
