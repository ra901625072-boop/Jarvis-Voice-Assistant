import logging
from typing import Dict, Any, List

logger = logging.getLogger("JARVIS.ToolRouter")

class ToolRouter:
    """
    ToolRouter routes generic capability requests to the most reliable tool based on historical tool memory scores.

    SYSTEM PROMPT:
    Query ToolRouter prior to dispatching actions for generic capabilities (e.g. web_search, ui_click) to get the most reliable tool candidate.

    SHORT DESCRIPTION:
    Intelligently routes generic execution capabilities to specific high-reliability tools.

    PROCESS:
    1. Holds mapping of generic capability keys (e.g., web_search, file_read) to list of candidate tool keys.
    2. Queries stats from ToolMemory for each candidate.
    3. Selects candidate with highest reliability score, defaulting missing tool stats to a score of 0.5.

    FLOW:
    Caller -> get_optimal_tool() -> ToolMemory stats lookup -> candidate comparison -> best tool name -> Caller
    """
    def __init__(self, tool_memory):
        self.tool_memory = tool_memory
        
        # Define semantic groups of tools that solve the same problem
        self.tool_groups = {
            "web_search": ["google_search", "duckduckgo_search", "brave_search", "selenium_search"],
            "browser_automation": ["playwright_action", "selenium_action"],
            "file_read": ["read_file", "cat_command"],
            "ui_click": ["pyautogui_click", "vision_click"]
        }
        
    def get_optimal_tool(self, capability: str) -> str:
        """
        Given a generic capability like 'web_search', returns the most reliable specific tool.
        If the requested capability isn't a known group, returns the capability itself.
        """
        capability_lower = capability.lower()
        if capability_lower not in self.tool_groups:
            return capability
            
        candidates = self.tool_groups[capability_lower]
        
        best_tool = candidates[0]
        best_score = -1.0
        
        for tool in candidates:
            stats = self.tool_memory.get_tool_stats(tool)
            # Default to 0.5 reliability for unknown tools to give them a chance
            if stats and (stats['success_count'] + stats['fail_count']) > 0:
                score = self.tool_memory.get_reliability(tool)
            else:
                score = 0.5
                
            if score > best_score:
                best_score = score
                best_tool = tool
                
        logger.info(f"ToolRouter routed '{capability}' -> '{best_tool}' (reliability: {best_score:.2f})")
        return best_tool

    async def route_async(self, capability: str) -> str:
        """Asynchronously routes a generic capability request to the most reliable tool."""
        import asyncio
        return await asyncio.to_thread(self.get_optimal_tool, capability)

    async def route_multiple_async(self, capabilities: List[str]) -> List[str]:
        """Asynchronously routes multiple generic capability requests simultaneously."""
        import asyncio
        tasks = [self.route_async(cap) for cap in capabilities]
        return await asyncio.gather(*tasks)
