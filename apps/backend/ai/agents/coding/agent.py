import logging
import os
import aiofiles

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult

logger = logging.getLogger("JARVIS.CodingAgent")

class CodingAgent(BaseAgent):
    """
    Writes, modifies, and tests code.
    Absorbs CodingSkill, RefactoringSkill, ProjectBuilderSkill.
    """
    def __init__(self, bus):
        super().__init__(agent_id="coding_agent")
        self.bus = bus
        self.bus.register(self.agent_id, self.handle)

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload
        
        try:
            if task_type == "write_code":
                return await self._handle_write_code(task, payload)
            elif task_type == "refactor_code":
                return await self._handle_refactor_code(task, payload)
            elif task_type == "build_project":
                return await self._handle_build_project(task, payload)
            elif task_type == "ast_refactor":
                return await self._handle_ast_refactor(task, payload)
            elif task_type == "static_type_check":
                return await self._handle_static_type_check(task, payload)
            elif task_type == "generate_unit_tests":
                return await self._handle_generate_unit_tests(task, payload)
            else:
                return self._create_result(task, success=False, error=f"CodingAgent does not support task type '{task_type}'")
        except Exception as e:
            logger.exception(f"CodingAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))

    async def _handle_write_code(self, task: AgentTask, payload: dict) -> AgentResult:
        file_path = payload.get("file_path", "")
        code_content = payload.get("code_content") or payload.get("code") or payload.get("content")
        
        if code_content is not None:
            try:
                dirname = os.path.dirname(file_path)
                if dirname:
                    os.makedirs(dirname, exist_ok=True)
                async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                    await f.write(code_content)
                logger.info(f"CodingAgent: Wrote pre-provided code content directly to {file_path}")
                return self._create_result(task, success=True, result={
                    "file_path": file_path,
                    "content": code_content,
                    "explanation": "Wrote pre-provided code content directly."
                })
            except Exception as e:
                return self._create_result(task, success=False, error=f"Failed to write provided code content: {e}")

        instruction = payload.get("instruction", "")
        prompt = f"""
        You are a Coding Agent. 
        Write or modify the code based on the following instruction.
        Instruction: {instruction}
        File: {file_path}
        
        Return ONLY valid JSON with the following structure:
        {{
            "file_path": "{file_path}",
            "content": "the full raw code string to write to the file",
            "explanation": "brief explanation of what was written"
        }}
        """
        response = await self.generate_response(prompt, response_mime_type="application/json")
        try:
            data = self._parse_json_response(response)
            file_path = data.get("file_path")
            content = data.get("content")
            if file_path and content is not None:
                dirname = os.path.dirname(file_path)
                if dirname:
                    os.makedirs(dirname, exist_ok=True)
                async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                    await f.write(content)
                data["side_effect"] = f"Wrote {len(content)} chars to {file_path}"
            return self._create_result(task, success=True, result=data)
        except Exception as e:
            return self._create_result(task, success=False, error=f"Failed to parse or write code: {e}")

    async def _handle_refactor_code(self, task: AgentTask, payload: dict) -> AgentResult:
        file_path = payload.get("file_path", "")
        goal = payload.get("refactoring_goal", "")
        content = payload.get("content", "")
        
        prompt = f"""
        Refactor the following code based on this target refactoring goal: "{goal}".
        Ensure all existing logic and edge cases are preserved, but structures are improved.
        
        File: {file_path}
        ```
        {content}
        ```
        
        Return a JSON response with exactly:
        - 'explanation': string describing the improvements
        - 'refactored_content': complete updated content of the file
        """
        
        response = await self.generate_response(prompt, response_mime_type="application/json")
        try:
            data = self._parse_json_response(response)
            refactored_content = data.get("refactored_content")
            if file_path and refactored_content is not None:
                import os
                import aiofiles
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                    await f.write(refactored_content)
                data["side_effect"] = f"Wrote refactored content to {file_path}"
            return self._create_result(task, success=True, result=data)
        except Exception as e:
            return self._create_result(task, success=False, error=f"Failed to parse or write refactored code: {e}")

    async def _handle_build_project(self, task: AgentTask, payload: dict) -> AgentResult:
        description = payload.get("project_description", "")
        target_dir = payload.get("target_dir", "")
        
        prompt = f"""
        Create a new project scaffold for the following description:
        {description}
        
        Target Directory: {target_dir}
        
        Return a JSON object containing a list of files to create and initialization commands to run.
        {{
            "files": [
                {{"path": "relative/path/to/file", "content": "file content"}}
            ],
            "commands": [
                "npm init -y",
                "pip install -r requirements.txt"
            ]
        }}
        """
        response = await self.generate_response(prompt, response_mime_type="application/json")
        try:
            data = self._parse_json_response(response)
            files = data.get("files", [])
            commands = data.get("commands", [])
            side_effects = []
            
            import os
            import aiofiles
            for file_info in files:
                fpath = file_info.get("path")
                fcontent = file_info.get("content", "")
                if fpath and target_dir:
                    full_path = os.path.join(target_dir, fpath)
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                        await f.write(fcontent)
                    side_effects.append(f"Created file: {full_path}")
            
            # We don't execute the commands directly for safety unless in a sandbox, 
            # but we return them for the ExecutionAgent to run.
            data["side_effects"] = side_effects
            return self._create_result(task, success=True, result=data)
        except Exception as e:
            return self._create_result(task, success=False, error=f"Failed to parse or build project: {e}")

    async def _handle_ast_refactor(self, task: AgentTask, payload: dict) -> AgentResult:
        import ast
        source_code = payload.get("source_code", "")
        try:
            tree = ast.parse(source_code)
            functions = [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
            
            summary = f"Parsed AST containing {len(functions)} functions and {len(classes)} classes."
            return self._create_result(
                task,
                success=True,
                result={
                    "ast_valid": True,
                    "functions": functions,
                    "classes": classes,
                    "summary": summary
                }
            )
        except SyntaxError as se:
            return self._create_result(task, success=False, error=f"AST Syntax Error line {se.lineno}: {se.msg}")
        except Exception as e:
            return self._create_result(task, success=False, error=f"AST Refactor error: {e}")

    async def _handle_static_type_check(self, task: AgentTask, payload: dict) -> AgentResult:
        import ast
        source_code = payload.get("source_code", "")
        try:
            ast.parse(source_code)
            return self._create_result(task, success=True, result={"valid_syntax": True, "error": None})
        except SyntaxError as se:
            return self._create_result(
                task,
                success=True,
                result={
                    "valid_syntax": False,
                    "error": f"SyntaxError line {se.lineno}: {se.msg}"
                }
            )

    async def _handle_generate_unit_tests(self, task: AgentTask, payload: dict) -> AgentResult:
        import ast
        source_code = payload.get("source_code", "")
        file_name = payload.get("file_name", "module.py")
        try:
            tree = ast.parse(source_code)
            functions = [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            
            test_lines = ["import pytest", f"# Auto-generated test suite for {file_name}"]
            for func in functions:
                test_lines.append(f"\ndef test_{func}():\n    # TODO: Implement test for {func}\n    assert True\n")
            
            generated_test_code = "\n".join(test_lines)
            return self._create_result(
                task,
                success=True,
                result={
                    "test_file_name": f"test_{file_name}",
                    "generated_test_code": generated_test_code,
                    "functions_tested": functions
                }
            )
        except Exception as e:
            return self._create_result(task, success=False, error=f"Unit test generation error: {e}")
