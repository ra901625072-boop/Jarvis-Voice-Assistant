from fastapi import APIRouter, Depends, HTTPException, Body
from api.middleware.auth import get_current_user
import uuid
import os
import json
import logging
import re
from datetime import datetime
from modules.skills.markdown_loader import parse_markdown, validate_skill

router = APIRouter(prefix="/api/skills", tags=["Skills"])
logger = logging.getLogger("JARVIS.API.Skills")

# Helper to find backend directory dynamically
def _get_db_paths():
    curr_dir = os.path.abspath(os.path.dirname(__file__))
    while curr_dir and os.path.basename(curr_dir) != "backend":
        parent = os.path.dirname(curr_dir)
        if parent == curr_dir:
            break
        curr_dir = parent
    skills_file = os.path.join(curr_dir, "database", "skills.json")
    custom_skills_dir = os.path.join(curr_dir, "database", "custom_skills")
    return skills_file, custom_skills_dir

SKILLS_FILE, CUSTOM_SKILLS_DIR = _get_db_paths()

def load_skills():
    if not os.path.exists(SKILLS_FILE):
        return {}
    try:
        with open(SKILLS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("Failed to load skills")
        return {}

def save_skills(skills):
    try:
        os.makedirs(os.path.dirname(SKILLS_FILE), exist_ok=True)
        with open(SKILLS_FILE, "w", encoding="utf-8") as f:
            json.dump(skills, f, indent=4)
        return True
    except Exception:
        logger.exception("Failed to save skills")
        return False

_builtin_skills_cache = None

@router.get("")
async def list_skills(current_user: dict = Depends(get_current_user)):
    global _builtin_skills_cache
    skills_list = []
    
    # 1. Load built-in skills from Registry (cached)
    try:
        if _builtin_skills_cache is None:
            from container import ServiceContainer
            container = ServiceContainer.instance()
            tools = container.get_or_none("tools") if container else None
            if tools:
                builtin_skills = [t for t in tools if hasattr(t, "__class__") and "Skill" in t.__class__.__name__]
            else:
                from modules.skills.registry import SkillRegistry
                registry = SkillRegistry()
                builtin_skills = registry.load_skills()

            cached = []
            for skill in builtin_skills:
                class_name = skill.__class__.__name__
                if class_name == "CustomSkillSkill":
                    continue
                cached.append({
                    "id": class_name,
                    "name": re.sub(r'(?<!^)(?=[A-Z])', ' ', class_name),
                    "description": skill.__class__.__doc__.strip() if skill.__class__.__doc__ else "Built-in system capability.",
                    "trigger": [],
                    "category": "system",
                    "source": "built-in",
                    "enabled": True
                })
            _builtin_skills_cache = cached
        skills_list.extend(_builtin_skills_cache)
    except Exception as e:
        logger.error(f"Failed to load built-in skills: {e}")


    # 2. Load custom skills from skills.json
    custom_skills = load_skills()
    username = current_user.get("username")
    for skill_id, skill_data in custom_skills.items():
        if not skill_data.get("owner") or skill_data.get("owner") == username:
            skills_list.append({
                "id": skill_id,
                "name": skill_data.get("name", "Unnamed Custom Skill"),
                "description": skill_data.get("description", "No description provided."),
                "trigger": skill_data.get("trigger", []),
                "category": skill_data.get("category", "custom"),
                "source": "custom",
                "enabled": skill_data.get("enabled", True),
                "created_at": skill_data.get("created_at")
            })

    return {"skills": skills_list}

@router.post("/validate-md")
async def validate_markdown_skill(body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    raw_markdown = body.get("raw_markdown", "")
    if not raw_markdown:
        raise HTTPException(status_code=400, detail="Missing 'raw_markdown'")
        
    parsed = parse_markdown(raw_markdown)
    ok, errors = validate_skill(parsed)
    return {
        "valid": ok,
        "errors": errors,
        "metadata": parsed.get("metadata", {})
    }

@router.post("")
async def create_custom_skill(body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    raw_markdown = body.get("raw_markdown", "")
    if not raw_markdown:
        raise HTTPException(status_code=400, detail="Missing 'raw_markdown'")
        
    parsed = parse_markdown(raw_markdown)
    ok, errors = validate_skill(parsed)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Validation failed: {', '.join(errors)}")
        
    metadata = parsed.get("metadata", {})
    name = metadata.get("name")
    
    # Check if there is an existing skill with the same name to overwrite or prevent duplicates
    skills = load_skills()
    skill_id = None
    for s_id, s_data in skills.items():
        if s_data.get("name", "").strip().lower() == name.strip().lower():
            skill_id = s_id
            break
            
    if not skill_id:
        skill_id = f"skill_{uuid.uuid4().hex[:8]}"
        
    # Ensure folder exists
    os.makedirs(CUSTOM_SKILLS_DIR, exist_ok=True)
    md_file_path = os.path.join(CUSTOM_SKILLS_DIR, f"{skill_id}.md")
    
    try:
        with open(md_file_path, "w", encoding="utf-8") as f:
            f.write(raw_markdown)
    except Exception as e:
        logger.exception("Failed to save markdown file")
        raise HTTPException(status_code=500, detail=f"Failed to write markdown file: {e}")
        
    skills[skill_id] = {
        "id": skill_id,
        "name": name,
        "description": metadata.get("description"),
        "trigger": metadata.get("trigger", []),
        "category": metadata.get("category", "custom"),
        "file": md_file_path,
        "created_at": datetime.now().isoformat(),
        "enabled": True,
        "owner": current_user.get("username")
    }
    
    if save_skills(skills):
        return {"status": "success", "skill": skills[skill_id]}
    raise HTTPException(status_code=500, detail="Failed to write skills index database")

@router.delete("/{skill_id}")
async def delete_custom_skill(skill_id: str, current_user: dict = Depends(get_current_user)):
    skills = load_skills()
    if skill_id not in skills:
        raise HTTPException(status_code=404, detail="Skill not found")
        
    skill_data = skills[skill_id]
    if skill_data.get("owner") and skill_data.get("owner") != current_user.get("username"):
        raise HTTPException(status_code=403, detail="You do not own this custom skill")
        
    md_file_path = skill_data.get("file")
    if md_file_path and os.path.exists(md_file_path):
        try:
            os.remove(md_file_path)
        except Exception as e:
            logger.warning(f"Failed to delete custom skill file: {e}")
            
    del skills[skill_id]
    if save_skills(skills):
        return {"status": "success", "message": f"Deleted custom skill {skill_id}"}
    raise HTTPException(status_code=500, detail="Failed to write skills index database")

@router.patch("/{skill_id}")
async def toggle_custom_skill(skill_id: str, body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    skills = load_skills()
    if skill_id not in skills:
        raise HTTPException(status_code=404, detail="Skill not found")
        
    skill_data = skills[skill_id]
    if skill_data.get("owner") and skill_data.get("owner") != current_user.get("username"):
        raise HTTPException(status_code=403, detail="You do not own this custom skill")
        
    enabled = body.get("enabled")
    if enabled is None:
        raise HTTPException(status_code=400, detail="Missing 'enabled' parameter")
        
    skills[skill_id]["enabled"] = bool(enabled)
    if save_skills(skills):
        return {"status": "success", "skill": skills[skill_id]}
    raise HTTPException(status_code=500, detail="Failed to write skills index database")
