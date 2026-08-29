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
import logging
import asyncio

from config.settings import load_config
load_config()

from livekit import agents
from livekit.agents import AgentServer, Agent
from livekit.agents.llm.mcp import MCPServerStdio, MCPToolset

from container import build_container
from modules.memory.manager import MemoryManager
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
    TranslationTools,
    LanguageTools,
    NotificationTools,
    SocialMediaTools,
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
_supervisor_agent = _container.get("supervisor_agent")

# Eagerly initialize task event bus, status board, and task announcer
_container.get("task_event_bus")
_container.get("status_board")
_container.get("task_announcer")

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
    TranslationTools(translation_service=_container.get("translation_service"), security=_security),
    LanguageTools(bus=_agent_bus, security=_security),
    NotificationTools(memory=_memory, security=_security),
    SocialMediaTools(security=_security),
] + _skills_list

# Cache services for session reuse
_cached_services = {"memory": _memory, "tools": _tools_base, "agent_bus": _agent_bus}

# Register tools in the container so TaskTools/VisionTools can look them up
_container._services["tools"] = _tools_base

# Eagerly boot all agents so they register on the bus:
_container.get("planning_agent")
_container.get("execution_agent")
_container.get("coordinator_agent")
_container.get("coding_agent")
_container.get("debugging_agent")
_container.get("browser_agent")
_container.get("vision_agent")
_container.get("verification_agent")
_container.get("recovery_agent")
_container.get("integration_agent")
_container.get("interaction_agent")
_container.get("language_agent")
_container.get("deep_research_agent")
_container.get("learning_agent")
_container.get("ui_ux_agent")
_container.get("social_media_agent")
_container.get("whatsapp_agent")
_container.get("gmail_agent")
_container.get("instagram_agent")
_container.get("social_watcher")
_init_log.info("All agents registered on AgentBus.")

# ── MCP server definitions ────────────────────────────────────────────────────
import sys
_mcp_cmd = "npx.cmd" if sys.platform == "win32" else "npx"

_search_mcp = MCPServerStdio(command=_mcp_cmd, args=["-y", "duckduckgo-mcp-server"], client_session_timeout_seconds=30)

_BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY")
_brave_mcp = (
    MCPServerStdio(command=_mcp_cmd, args=["-y", "@modelcontextprotocol/server-brave-search"], env={"BRAVE_API_KEY": _BRAVE_API_KEY}, client_session_timeout_seconds=30)
    if _BRAVE_API_KEY
    else None
)
_FS_MCP_ROOT = os.environ.get("JARVIS_MCP_FS_ROOT", os.path.expanduser("~/jarvis_workspace"))
os.makedirs(_FS_MCP_ROOT, exist_ok=True)

_GIT_MCP_REPO = os.environ.get("JARVIS_MCP_GIT_REPO", _FS_MCP_ROOT)
_git_mcp = (
    MCPServerStdio(command=_mcp_cmd, args=["-y", "mcp-server-git", "--repository", _GIT_MCP_REPO], client_session_timeout_seconds=30)
    if os.path.isdir(os.path.join(_GIT_MCP_REPO, ".git"))
    else None
)

_ENABLE_MCP = os.environ.get("JARVIS_ENABLE_MCP", "false").lower() == "true"

_mcp_toolsets = []
if _ENABLE_MCP:
    _mcp_toolsets.append(MCPToolset(id="ddg_search", mcp_server=_search_mcp))
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