import logging
from typing import Dict, Any, List

logger = logging.getLogger("JARVIS.ToolRouter")

class ToolRouter:
    """
    Intelligently routes generic capability requests to the most reliable specific tool
    based on historical success rates tracked in ToolMemory.
    """
    def __init__(self, tool_memory):
        self.tool_memory = tool_memory
        
        # Define semantic groups of tools that solve the same problem
        self.tool_groups = {
            "web_search": ["google_search", "duckduckgo_search", "selenium_search"],
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
