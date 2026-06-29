"""
agent.py — Thin orchestrator (~150 lines).

Responsibilities:
  1. Eagerly initialize services via ServiceContainer (moved from GlobalRegistry).
  2. Wire toolsets with their dependencies.
  3. Define @server.rtc_session handler.
  4. Configure MCP toolsets.

All toolset classes live in toolsets/*.py.
All singleton services live in container.py.
"""
import os
import asyncio
import logging

from config.settings import load_config
load_config()

from livekit import agents
from livekit.agents import AgentServer, AgentSession, Agent, llm
from livekit.agents.llm.mcp import MCPServerStdio, MCPToolset
from livekit.plugins import google

from container import build_container
from modules.core.memory_manager import MemoryManager
from modules.planning.behavior import JarvisBehavior
from modules.planning.task_planner import TaskPlannerTools
from modules.skills.registry import SkillRegistry

# ── Import all toolsets from the new package ──────────────────────────────────
from tools.builtin import (
    SystemTools,
    WindowTools,
    AppTools,
    BrowserTools,
    MediaTools,
    KeyboardTools,
    MouseTools,
    FileTools,
    TaskTools,
    MemoryTools,
    VisionTools,
    VerificationTools,
)

_init_log = logging.getLogger("JARVIS.Agent")

# ── Eager service initialization ──────────────────────────────────────────────
# Build all services at module-load time (during 'from agent import server')
# so that the user's first connection is not blocked by lengthy startup.
_init_log.info("Eagerly initializing services via ServiceContainer...")

_container = build_container()
_memory: MemoryManager = _container.get("memory")
_security = _container.get("security")
_world_state = _container.get("world_state")
_verification = _container.get("verification")
_agent_bus = _container.get("agent_bus")
_memory_agent = _container.get("memory_agent")

# Register memory to VisionManager
_container.get("vision_manager").set_memory_manager(_memory)

# Load all skills
_skill_registry = SkillRegistry(
    memory=_memory,
    security=_security,
    room=None,  # Room injected dynamically per-session
    verification=_verification,
)
_skills_list = _skill_registry.load_skills()

# Build the base tools list
_tools_base = [
    SystemTools(security=_security),
    WindowTools(security=_security),
    AppTools(security=_security),
    BrowserTools(security=_security),
    MediaTools(security=_security),
    KeyboardTools(security=_security),
    MouseTools(security=_security),
    FileTools(security=_security),
    TaskTools(security=_security),
    MemoryTools(memory=_memory, security=_security),
    TaskPlannerTools(memory=_memory),
    VerificationTools(verification=_verification, security=_security),
    VisionTools(security=_security),
] + _skills_list

# Cache services for session reuse
_cached_services = {"memory": _memory, "tools": _tools_base, "agent_bus": _agent_bus}

# Register tools in the container so TaskTools/VisionTools can look them up
_container._services["tools"] = _tools_base

# ── MCP server definitions ────────────────────────────────────────────────────
import sys
_mcp_cmd = "npx.cmd" if sys.platform == "win32" else "npx"

_search_mcp = MCPServerStdio(command=_mcp_cmd, args=["-y", "duckduckgo-mcp-server"])

_BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY")
_brave_mcp = (
    MCPServerStdio(command=_mcp_cmd, args=["-y", "@modelcontextprotocol/server-brave-search"], env={"BRAVE_API_KEY": _BRAVE_API_KEY})
    if _BRAVE_API_KEY
    else None
)
_FS_MCP_ROOT = os.environ.get("JARVIS_MCP_FS_ROOT", os.path.expanduser("~/jarvis_workspace"))
os.makedirs(_FS_MCP_ROOT, exist_ok=True)
_filesystem_mcp = MCPServerStdio(
    command=_mcp_cmd,
    args=["-y", "@modelcontextprotocol/server-filesystem", _FS_MCP_ROOT],
)

_GIT_MCP_REPO = os.environ.get("JARVIS_MCP_GIT_REPO", _FS_MCP_ROOT)
_git_mcp = (
    MCPServerStdio(command=_mcp_cmd, args=["-y", "mcp-server-git", "--repository", _GIT_MCP_REPO])
    if os.path.isdir(os.path.join(_GIT_MCP_REPO, ".git"))
    else None
)

_mcp_toolsets = [
    MCPToolset(id="ddg_search", mcp_server=_search_mcp),
    MCPToolset(id="filesystem", mcp_server=_filesystem_mcp),
]
if _git_mcp:
    _mcp_toolsets.append(MCPToolset(id="git", mcp_server=_git_mcp))
if _brave_mcp:
    _mcp_toolsets.append(MCPToolset(id="brave_search", mcp_server=_brave_mcp))

_init_log.info(
    f"Eager service init complete. {len(_tools_base)} tools + {len(_mcp_toolsets)} MCP toolsets ready."
)

# ── Agent definition ──────────────────────────────────────────────────────────

server = AgentServer()


class Assistant(Agent):
    def __init__(self, memory: MemoryManager) -> None:
        base_prompt = JarvisBehavior.get_full_system_prompt()
        super().__init__(instructions=base_prompt)


@server.rtc_session(agent_name=os.environ.get("AGENT_NAME", "jarvis"))
async def my_agent(ctx: agents.JobContext):
    # Delegate to the newly integrated SupervisorAgent (Phase 6)
    supervisor_agent = _container.get("supervisor_agent")
    
    # We pass the pre-warmed MCP tools and standard tools to the SupervisorAgent
    memory = _cached_services["memory"]
    tools = _cached_services["tools"]
    
    await supervisor_agent.run_session(ctx, _mcp_toolsets, tools, memory, _container)

if __name__ == "__main__":
    agents.cli.run_app(server)