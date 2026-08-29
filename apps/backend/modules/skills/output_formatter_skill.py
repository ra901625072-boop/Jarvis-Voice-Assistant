import json
from typing import Any
from livekit.agents import llm
from modules.skills.base_skill import BaseSkill

class OutputFormatterSkill(BaseSkill):
    """
    Skill to format raw/messy text, tabular data, JSON, and code into clean, structured Markdown output.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    def format_as_table(self, rows: list[dict]) -> str:
        if not rows:
            return ""
        # Get all unique keys as headers
        headers = []
        for r in rows:
            for k in r.keys():
                if k not in headers:
                    headers.append(k)
        
        # Build headers
        header_row = "| " + " | ".join(headers) + " |"
        separator_row = "| " + " | ".join(["---"] * len(headers)) + " |"
        
        # Build rows
        data_rows = []
        for r in rows:
            row_vals = [str(r.get(h, "")) for h in headers]
            data_rows.append("| " + " | ".join(row_vals) + " |")
            
        return "\n".join([header_row, separator_row] + data_rows)

    def format_as_code(self, code: str, language: str = "python") -> str:
        return f"```{language}\n{code}\n```"

    def format_json(self, data: dict | list) -> str:
        pretty = json.dumps(data, indent=2)
        return f"```json\n{pretty}\n```"

    @llm.function_tool(description="Automatically formats tabular data, JSON, code, or unstructured text into clean Markdown")
    async def auto_format(self, raw_content: str) -> str:
        """
        Inspects the raw_content and formats it as appropriate (tables, JSON, code block, or returns unchanged).
        """
        if not isinstance(raw_content, str):
            return str(raw_content)

        content = raw_content.strip()
        
        # 1. Look for and format any embedded JSON arrays or objects
        modified_content = content
        i = 0
        n = len(modified_content)
        
        while i < n:
            start_char = None
            if modified_content[i] == '[':
                start_char = '['
                end_char = ']'
            elif modified_content[i] == '{':
                start_char = '{'
                end_char = '}'
                
            if start_char:
                bracket_count = 0
                in_string = False
                escape = False
                found_json = None
                end_idx = -1
                
                for j in range(i, n):
                    char = modified_content[j]
                    if escape:
                        escape = False
                        continue
                    if char == '\\':
                        escape = True
                        continue
                    if char == '"':
                        in_string = not in_string
                        continue
                    if not in_string:
                        if char == start_char:
                            bracket_count += 1
                        elif char == end_char:
                            bracket_count -= 1
                            if bracket_count == 0:
                                candidate = modified_content[i:j+1]
                                try:
                                    parsed = json.loads(candidate)
                                    if isinstance(parsed, (list, dict)):
                                        found_json = parsed
                                        end_idx = j
                                        break
                                except Exception:
                                    pass
                                    
                if found_json is not None:
                    formatted = ""
                    if isinstance(found_json, list):
                        if all(isinstance(x, dict) for x in found_json):
                            formatted = self.format_as_table(found_json)
                        else:
                            formatted = self.format_json(found_json)
                    elif isinstance(found_json, dict):
                        formatted = self.format_json(found_json)
                    
                    raw_substring = modified_content[i:end_idx+1]
                    prefix = modified_content[:i]
                    suffix = modified_content[i:]
                    suffix = suffix.replace(raw_substring, formatted, 1)
                    modified_content = prefix + suffix
                    
                    i += len(formatted)
                    n = len(modified_content)
                    continue
            i += 1

        # If we successfully formatted some JSON, return the modified text
        if modified_content != content:
            return modified_content
            
        # 2. If it's a string looking like code:
        # heuristic: contains indicators like def/class/import or ends with semicolons
        code_indicators = [
            "def ", "import ", "class ", "const ", "let ", "function ", 
            "<html>", "body {", "import *", "from ", "package ", 
            "public static void main", "echo "
        ]
        
        lines = content.splitlines()
        has_semicolons = sum(1 for line in lines if line.strip().endswith(";"))
        has_indicator = any(ind in content for ind in code_indicators)
        
        if not content.startswith("```"):
            if has_indicator or (has_semicolons > 2 and len(lines) > 3):
                # Guess language
                lang = "python"
                if "const " in content or "let " in content or "function " in content:
                    lang = "javascript"
                elif "<html>" in content or "<div>" in content:
                    lang = "html"
                elif "body {" in content or ".class {" in content:
                    lang = "css"
                elif "echo " in content or "mkdir " in content:
                    lang = "bash"
                return self.format_as_code(content, lang)

        return raw_content
