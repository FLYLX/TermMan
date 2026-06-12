"""Compatibility entry point for plugin discovery.

New robot-agent integration code lives in app.plugins.robot.agent.integration.
"""

from __future__ import annotations

from app.plugins.robot.agent.integration import register_agent_integration

__all__ = ["register_agent_integration"]
