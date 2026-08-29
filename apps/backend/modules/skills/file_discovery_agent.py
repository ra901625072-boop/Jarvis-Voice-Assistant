import logging
from livekit.agents import llm
from modules.filesystem.file_manager import FileManager
from modules.filesystem.learning_engine import LearningEngine
from modules.filesystem.semantic_engine import SemanticEngine

logger = logging.getLogger("JARVIS.FileDiscoveryAgent")

class FileDiscoveryAgent:
    """
    The single tool the LLM calls for "find/open a file by description."
    It orchestrates alias checking, semantic search, fuzzy cache search, and live scanning.
    """
    def __init__(self, file_mgr: FileManager, learning_engine: LearningEngine, semantic_engine: SemanticEngine = None):
        self.file_mgr = file_mgr
        self.learning_engine = learning_engine
        self.semantic_engine = semantic_engine

    @llm.function_tool(description="Find and open a file by a natural language description (e.g., 'the marketing presentation from yesterday').")
    async def find_and_open_file(self, query: str, app_name: str = None) -> str:
        logger.info(f"FileDiscoveryAgent searching for: {query}")
        
        # 1. Check Learning Engine (Aliases)
        query_norm = query.strip().lower()
        alias_match = None
        try:
            with self.learning_engine.db._db_lock:
                cursor = self.learning_engine.db.db_conn.execute(
                    "SELECT path, confidence FROM file_aliases WHERE query_normalized = ? ORDER BY confidence DESC LIMIT 1",
                    (query_norm,)
                )
                row = cursor.fetchone()
                if row and row[1] > 80.0: # High confidence
                    alias_match = row[0]
        except Exception as e:
            logger.debug(f"Alias lookup failed: {e}")
            
        if alias_match:
            import os
            if os.path.exists(alias_match):
                success = self.file_mgr.open_item(alias_match, app_name)
                if success is True:
                    self.learning_engine.record(query, alias_match, "alias", 100.0, outcome="success")
                    return f"Successfully found and opened {alias_match} (via learned alias)."
                    
        # 2. Check Semantic Search
        if self.semantic_engine:
            semantic_matches = await self.semantic_engine.search(query, limit=1)
            if semantic_matches:
                best_match = semantic_matches[0]
                import os
                if os.path.exists(best_match):
                    success = self.file_mgr.open_item(best_match, app_name)
                    if success is True:
                        self.learning_engine.record(query, best_match, "semantic", 90.0, outcome="success")
                        return f"Successfully found and opened {best_match} (via semantic search)."

        
        # 3. Fallback to FileManager pipeline
        results = self.file_mgr.search_file(query, limit=1)
        if results:
            best_match = results[0]
            success = self.file_mgr.open_item(best_match, app_name)
            if success is True:
                self.learning_engine.record(query, best_match, "search_pipeline", 85.0, outcome="success")
                return f"Successfully found and opened {best_match}."
            
            self.learning_engine.record(query, best_match, "search_pipeline", 85.0, outcome="ambiguous")
            return f"Found {best_match}, but failed to open it: {success}"
            
        self.learning_engine.record(query, "", "all", 0.0, outcome="not_found")
        return f"Could not find any file matching '{query}'."
