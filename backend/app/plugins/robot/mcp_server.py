"""Compatibility shim for the old robot MCP server import path."""

from __future__ import annotations

from app.plugins.robot.mcp.server import RobotMCPServer, robot_mcp_server

__all__ = ["RobotMCPServer", "robot_mcp_server"]
