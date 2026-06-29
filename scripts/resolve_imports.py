import os
import glob
import libcst as cst
from libcst import matchers as m

# Mappings of old module prefixes to new module prefixes
MAPPINGS = {
    "agents.browser_agent": "ai.agents.browser.agent",
    "agents.coding_agent": "ai.agents.coding.agent",
    "agents.execution_agent": "ai.agents.execution.agent",
    "agents.integration_agent": "ai.agents.integration.agent",
    "agents.memory_agent": "ai.agents.memory.agent",
    "agents.planning_agent": "ai.agents.planning.agent",
    "agents.recovery_agent": "ai.agents.recovery.agent",
    "agents.supervisor_agent": "ai.agents.supervisor.agent",
    "agents.verification_agent": "ai.agents.verification.agent",
    "agents.vision_agent": "ai.agents.vision.agent",
    "agents.debugging_agent": "ai.agents.debugging.agent",
    "agents.coordinator_agent": "ai.agents.coordinator.agent",
    "agents.base_agent": "ai.agents.base_agent",
    "agents.types": "ai.agents.types",
    "agents.bus": "events.bus",
    "agents": "ai.agents",
    
    "toolsets.app_tools": "tools.builtin.app.tool",
    "toolsets.browser_tools": "tools.builtin.browser.tool",
    "toolsets.file_tools": "tools.builtin.filesystem.tool",
    "toolsets.keyboard_tools": "tools.builtin.keyboard.tool",
    "toolsets.media_tools": "tools.builtin.media.tool",
    "toolsets.memory_tools": "tools.builtin.memory.tool",
    "toolsets.mouse_tools": "tools.builtin.mouse.tool",
    "toolsets.system_tools": "tools.builtin.system.tool",
    "toolsets.task_tools": "tools.builtin.task.tool",
    "toolsets.verification_tools": "tools.builtin.verification.tool",
    "toolsets.vision_tools": "tools.builtin.vision.tool",
    "toolsets.window_tools": "tools.builtin.window.tool",
    "toolsets.base": "tools.builtin.base",
    "toolsets": "tools.builtin",
    
    "db.models": "domain.entities.models",
    "db.database": "domain.repositories.database",
    "db": "domain.entities",
    
    "services.notification_service": "integrations.communication.notification_service",
    "services": "integrations",
    
    "config": "config.settings",
}

class ImportTransformer(cst.CSTTransformer):
    def _replace_name(self, name_str):
        for old, new in MAPPINGS.items():
            if name_str == old:
                return new
            if name_str.startswith(old + "."):
                return name_str.replace(old + ".", new + ".", 1)
        return name_str

    def _create_name_node(self, new_name: str):
        parts = new_name.split('.')
        node = cst.Name(parts[0])
        for part in parts[1:]:
            node = cst.Attribute(value=node, attr=cst.Name(part))
        return node

    def leave_ImportAlias(self, original_node: cst.ImportAlias, updated_node: cst.ImportAlias) -> cst.ImportAlias:
        old_name = cst.helpers.get_full_name_for_node(original_node.name)
        if old_name:
            new_name = self._replace_name(old_name)
            if new_name != old_name:
                return updated_node.with_changes(name=self._create_name_node(new_name))
        return updated_node

    def leave_ImportFrom(self, original_node: cst.ImportFrom, updated_node: cst.ImportFrom) -> cst.ImportFrom:
        if original_node.module:
            old_module = cst.helpers.get_full_name_for_node(original_node.module)
            if old_module:
                new_module = self._replace_name(old_module)
                if new_module != old_module:
                    return updated_node.with_changes(module=self._create_name_node(new_module))
        return updated_node


def process_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source_code = f.read()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return

    try:
        tree = cst.parse_module(source_code)
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")
        return

    transformer = ImportTransformer()
    modified_tree = tree.visit(transformer)
    modified_code = modified_tree.code

    if source_code != modified_code:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(modified_code)
        print(f"Updated imports in {filepath}")

def main():
    backend_dir = os.path.join(os.path.dirname(__file__), "..", "apps", "backend")
    backend_dir = os.path.abspath(backend_dir)
    
    pattern = os.path.join(backend_dir, "**", "*.py")
    files = glob.glob(pattern, recursive=True)
    
    for filepath in files:
        process_file(filepath)

if __name__ == "__main__":
    main()
