from livekit.agents import llm
from modules.skills.base_skill import BaseSkill
from container import ServiceContainer

class ResearchSkill(BaseSkill):
    """
    Skill for multi-source web research summarization.
    Uses existing MCP search tools if available.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    def _get_mcp_tool(self, tool_name: str):
        container = ServiceContainer.instance()
        if not container:
            return None
        tools_list = container.get_or_none("tools")
        if not tools_list:
            ee = container.get_or_none("execution_engine")
            if ee and hasattr(ee, "tools"):
                tools_list = list(ee.tools.values())
        if not tools_list:
            return None
            
        for t in tools_list:
            if hasattr(t, "name") and t.name == tool_name:
                return t
            elif t.__class__.__name__.lower() == tool_name.lower():
                return t
        return None

    @llm.function_tool(description="Research a topic across multiple web sources and summarize findings")
    async def research_topic(self, query: str, max_sources: int = 5) -> str:
        """Perform web research on a topic."""
        container = ServiceContainer.instance()
        scheduler = container.get_or_none("scheduler") if container else None

        async def _do_research(task_record=None):
            deep_agent = container.get_or_none("deep_research_agent") if container else None
            if scheduler and task_record:
                await scheduler.update_progress(task_record.id, 15, "Starting deep research stages")

            if deep_agent and hasattr(deep_agent, "execute_deep_research"):
                try:
                    res = await deep_agent.execute_deep_research(query)
                    if scheduler and task_record:
                        await scheduler.update_progress(task_record.id, 100, "Deep research complete")
                    return res
                except Exception as e:
                    self.logger.warning(f"DeepResearchAgent failed: {e}. Falling back to default search flow.")

            # Try to find a search tool (ddg_search or brave_search)
            search_tool = self._get_mcp_tool("ddg_search") or self._get_mcp_tool("brave_search")
            
            search_results = ""
            if search_tool and hasattr(search_tool, "search"):
                try:
                    search_results = await search_tool.search(query=query, limit=max_sources)
                except Exception as e:
                    self.logger.warning(f"MCP Search failed: {e}")
            
            if not search_results:
                # Try to use BrowserTools search_google_live directly
                browser_tools = self._get_mcp_tool("browsertools")
                if browser_tools and hasattr(browser_tools, "search_google_live"):
                    try:
                        search_results = await browser_tools.search_google_live(query=query)
                    except Exception as e:
                        self.logger.warning(f"BrowserTools Search failed: {e}")

            if not search_results:
                search_results = f"Search tools unavailable. Using LLM baseline knowledge for query: {query}"

            prompt = (
                f"You are an expert researcher. Compile a comprehensive summary on the following topic:\n"
                f"Topic: {query}\n\n"
                f"Based on the following search results:\n{search_results}\n\n"
                f"Provide a structured report with citations."
            )
            report = await self.generate_response(prompt=prompt)
            if scheduler and task_record:
                await scheduler.update_progress(task_record.id, 100, "Research report generated")
            return report

        if scheduler:
            from core.scheduler import TaskPriority
            task_rec = await scheduler.submit_task(
                name=f"Research: {query[:30]}",
                agent="research",
                coro_func=_do_research,
                priority=TaskPriority.RESEARCH,
                payload={"query": query}
            )
            return f"Research task #{task_rec.id} submitted to Multi-Agent OS queue and running in background. Task status can be tracked anytime."

        return await self.safe_execute(
            _do_research,
            confirmation_category="search", # search tier
            confirmation_action=f"research topic: {query}",
            confirmed=True,
            success_msg="Completed research successfully",
            error_msg="Failed to complete research"
        )
