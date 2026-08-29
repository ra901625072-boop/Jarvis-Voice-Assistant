import os
import shutil
from livekit.agents import llm
from modules.skills.base_skill import BaseSkill

class SoftwareInstallSkill(BaseSkill):
    """
    Skill for installing packages and software via package managers.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    @llm.function_tool(description="Install a package using a package manager (winget, choco, pip, npm)")
    async def install_package(self, package_name: str, manager: str = "auto", confirmed: bool = False) -> str:
        """Install software via a package manager."""
        async def _do_install():
            selected_manager = manager.lower()
            
            # Auto-detect manager if not specified
            if selected_manager == "auto":
                if shutil.which("winget"):
                    selected_manager = "winget"
                elif shutil.which("choco"):
                    selected_manager = "choco"
                elif shutil.which("pip"):
                    selected_manager = "pip"
                elif shutil.which("npm"):
                    selected_manager = "npm"
                else:
                    return "Error: Could not automatically detect a suitable package manager."

            # Construct the installation command
            if selected_manager == "winget":
                cmd = f"winget install --id {package_name} -e --accept-package-agreements --accept-source-agreements"
            elif selected_manager == "choco":
                cmd = f"choco install {package_name} -y"
            elif selected_manager == "pip":
                cmd = f"pip install {package_name}"
            elif selected_manager == "npm":
                cmd = f"npm install -g {package_name}"
            else:
                return f"Error: Unsupported package manager '{selected_manager}'."

            result = await self.run_shell_command(cmd)
            
            if result.get("returncode") == 0:
                return f"Successfully installed {package_name} via {selected_manager}.\nOutput: {result.get('stdout')}"
            else:
                return f"Failed to install {package_name} via {selected_manager}.\nError: {result.get('stderr')}"

        return await self.safe_execute(
            _do_install,
            confirmation_category="install", # explicitly 'install' tier
            confirmation_action=f"install package {package_name} using {manager}",
            confirmed=confirmed,
            success_msg="Package installed successfully",
            error_msg="Failed to install package"
        )
