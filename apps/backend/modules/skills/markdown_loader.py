import re
import json

def parse_markdown(raw_text: str) -> dict:
    """
    Parses YAML frontmatter and extracts body content from a markdown string.
    Returns:
        dict: {
            "metadata": dict of frontmatter key-values,
            "body": raw markdown body text
        }
    """
    metadata = {}
    body = ""
    
    if not raw_text:
        return {"metadata": {}, "body": ""}
        
    lines = raw_text.splitlines()
    
    if len(lines) > 1 and lines[0].strip() == "---":
        yaml_lines = []
        body_start_idx = 1
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                body_start_idx = idx + 1
                break
            yaml_lines.append(lines[idx])
        else:
            # Revert to treating the whole file as body if closing '---' is not found
            return {"metadata": {}, "body": raw_text}
        
        # Parse simple YAML lines
        for line in yaml_lines:
            if not line.strip() or line.strip().startswith("#"):
                continue
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                # Clean quotes if present
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                
                # Check if it looks like a JSON array/list, e.g. ["weekly report", "status summary"]
                if val.startswith("[") and val.endswith("]"):
                    try:
                        val = json.loads(val)
                    except Exception:
                        # Fallback simple split
                        val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",") if v.strip()]
                metadata[key] = val
        
        body = "\n".join(lines[body_start_idx:])
    else:
        body = raw_text
        
    return {"metadata": metadata, "body": body.strip()}


def validate_skill(parsed: dict) -> tuple[bool, list[str]]:
    errors = []
    metadata = parsed.get("metadata", {})
    body = parsed.get("body", "")
    
    if not metadata:
        errors.append("No frontmatter metadata found. File must start with '---' block.")
        return False, errors
        
    # Check required fields
    for field in ["name", "description", "trigger"]:
        if field not in metadata or not metadata[field]:
            errors.append(f"Missing required metadata field: '{field}'")
            
    # Validate triggers
    triggers = metadata.get("trigger", [])
    if isinstance(triggers, str):
        # normalize single string trigger to list
        metadata["trigger"] = [triggers]
    elif not isinstance(triggers, list):
        errors.append("Field 'trigger' must be a list of strings or a single string.")
        
    # Length validations
    if len(body) > 20000:
        errors.append("Body length exceeds 20,000 characters limit.")
        
    return len(errors) == 0, errors


def parse_workflow_steps(body: str) -> tuple[list[dict], list[str]]:
    """
    Parses workflow steps from the markdown body.
    Expects each step on a line starting with a number, e.g.:
    1. execution_agent :: execute_command :: {"command": "git pull"}
    """
    steps = []
    errors = []
    
    # Allowed agents list
    allowed_agents = {
        "supervisor_agent", "coordinator_agent", "planning_agent",
        "execution_agent", "verification_agent", "recovery_agent",
        "memory_agent", "browser_agent", "coding_agent",
        "debugging_agent", "integration_agent", "vision_agent"
    }
    
    lines = body.splitlines()
    steps_section_started = False
    
    for idx, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue
            
        # Look for ## Steps or similar heading
        if stripped.startswith("##") and "steps" in stripped.lower():
            steps_section_started = True
            continue
            
        # If we are parsing step lines
        if steps_section_started:
            # Check if this line starts with a list marker (e.g. 1., 2., etc.)
            match = re.match(r"^(\d+)\.\s*(.*)$", stripped)
            if match:
                step_num = match.group(1)
                content = match.group(2).strip()
                
                # regex: ^([\w_]+)\s*::\s*([\w_]+)\s*::\s*(\{.*\})$
                step_match = re.match(r"^([\w_]+)\s*::\s*([\w_]+)\s*::\s*(\{.*\})$", content)
                if not step_match:
                    errors.append(f"Line {idx}: Step format invalid. Expected format: 'agent :: action :: {{json payload}}'")
                    continue
                    
                agent_name = step_match.group(1).strip()
                action_name = step_match.group(2).strip()
                payload_str = step_match.group(3).strip()
                
                # Normalize agent name to end with _agent
                normalized_agent = agent_name.lower()
                if not normalized_agent.endswith("_agent"):
                    normalized_agent = f"{normalized_agent}_agent"
                    
                if normalized_agent not in allowed_agents:
                    errors.append(f"Line {idx}: Unrecognized agent name '{agent_name}'. Supported agents are: {', '.join(sorted(list(allowed_agents)))}")
                    continue
                    
                try:
                    payload = json.loads(payload_str)
                    if not isinstance(payload, dict):
                        errors.append(f"Line {idx}: Payload must be a JSON object (dict).")
                        continue
                except json.JSONDecodeError as je:
                    errors.append(f"Line {idx}: Invalid JSON payload: {je.msg}")
                    continue
                    
                steps.append({
                    "name": f"Step {step_num}: {action_name}",
                    "agent": normalized_agent,
                    "action": action_name,
                    "payload": payload
                })
            else:
                # If it doesn't match list marker, let's complain or skip if it's comment/header
                if stripped.startswith("##") or stripped.startswith("#") or stripped.startswith("-"):
                    continue
                else:
                    errors.append(f"Line {idx}: Step line must start with a number (e.g. '1. ...').")
                    
    if not steps and not errors:
        errors.append("No workflow steps found in the body. Make sure to define steps under a '## Steps' heading.")
        
    return steps, errors


def validate_workflow(parsed: dict) -> tuple[bool, list[str]]:
    errors = []
    metadata = parsed.get("metadata", {})
    body = parsed.get("body", "")
    
    if not metadata:
        errors.append("No frontmatter metadata found. File must start with '---' block.")
        return False, errors
        
    # Check required fields
    for field in ["name", "description"]:
        if field not in metadata or not metadata[field]:
            errors.append(f"Missing required metadata field: '{field}'")
            
    # Parse and validate steps
    steps, step_errors = parse_workflow_steps(body)
    errors.extend(step_errors)
    
    return len(errors) == 0, errors
