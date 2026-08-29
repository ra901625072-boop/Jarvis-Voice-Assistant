from fastapi import APIRouter, Depends, HTTPException
from api.middleware.auth import get_current_user
from container import ServiceContainer

import logging

router = APIRouter(prefix="/api/agents", tags=["Agents"])
logger = logging.getLogger("JARVIS.API.Agents")

@router.get("")
async def list_agents(current_user: dict = Depends(get_current_user)):
    try:
        container = ServiceContainer.instance()
        if not container:
            return {"agents": []}
            
        agents_data = [
            {
                "name": "SupervisorAgent",
                "description": "Orchestrates commands, routes execution plans, and communicates with the user.",
                "capabilities": ["speak", "orchestrate"]
            },
            {
                "name": "PlanningAgent",
                "description": "Creates, updates, and decomposes complex execution plans and goals.",
                "capabilities": ["create_plan", "decompose_goal"]
            },
            {
                "name": "CodingAgent",
                "description": "Writes, refactors, reviews, and scaffolds software projects.",
                "capabilities": ["write_code", "refactor_code", "build_project"]
            },
            {
                "name": "DebuggingAgent",
                "description": "Diagnoses codebase errors, scans stack traces, and suggests code fixes.",
                "capabilities": ["diagnose_error", "suggest_fix"]
            },
            {
                "name": "BrowserAgent",
                "description": "Automates web navigation, completes web forms, and crawls sites.",
                "capabilities": ["automate_web_flow"]
            },
            {
                "name": "ExecutionAgent",
                "description": "Runs shell commands, compiles programs, and executes system actions.",
                "capabilities": ["execute_command", "run_script"]
            },
            {
                "name": "MemoryAgent",
                "description": "Maintains semantic search, retrieves context, and handles procedural memories.",
                "capabilities": ["retrieve_context", "store_memory"]
            },
            {
                "name": "VerificationAgent",
                "description": "Validates agent execution outcomes, runs tests, and double-checks correctness.",
                "capabilities": ["verify_result", "validate_output"]
            },
            {
                "name": "IntegrationAgent",
                "description": "Integrates modules, manages git repos, and handles branch merges.",
                "capabilities": ["merge_code", "resolve_conflict"]
            },
            {
                "name": "RecoveryAgent",
                "description": "Handles error recovery, handles rollback of failed steps, and repairs states.",
                "capabilities": ["recover_state", "rollback_change"]
            },
            {
                "name": "InteractionAgent",
                "description": "Coordinates human-in-the-loop actions and handles user confirmation triggers.",
                "capabilities": ["wait_for_user", "confirm_action"]
            },
            {
                "name": "LanguageAgent",
                "description": "Handles OCR (Indic OCR), translates languages, and processes text.",
                "capabilities": ["translate_text", "ocr_image"]
            },
            {
                "name": "VisionAgent",
                "description": "Observes screens, processes visual inputs, and maps UI coordinates.",
                "capabilities": ["describe_screen", "locate_element"]
            }
        ]
        
        bus = container.get_or_none("agent_bus")
        active_agents = list(bus._handlers.keys()) if bus and hasattr(bus, "_handlers") else []
        
        agents_list = []
        for agent in agents_data:
            agent_id = None
            for key in active_agents:
                if key.replace("_", "").lower() == agent["name"].lower():
                    agent_id = key
                    break
                    
            status = "idle" if agent_id else "offline"
                
            agents_list.append({
                "name": agent["name"],
                "description": agent["description"],
                "status": status,
                "capabilities": agent["capabilities"]
            })
            
        return {"agents": agents_list}
    except Exception as e:
        logger.exception("Failed to list agents")
        raise HTTPException(status_code=500, detail=str(e))
