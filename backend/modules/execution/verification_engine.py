import logging
import os
from .world_state import WorldStateManager

logger = logging.getLogger("JARVIS.VerificationEngine")

class VerificationEngine:
    """
    VerificationEngine programmatically evaluates execution outcomes against target conditions.

    SYSTEM PROMPT:
    Invoke VerificationEngine to verify tool outcomes programmatically. Provide specific condition types (e.g. process_running, window_exists, file_exists, clipboard_contains) to verify states.

    SHORT DESCRIPTION:
    Evaluates whether specific OS state conditions (processes, windows, files, clipboard) are met.

    PROCESS:
    1. Fetches a fresh system state snapshot from WorldStateManager.
    2. Runs comparison check based on target types:
       - process_running: checks running process list.
       - window_exists: checks open window titles.
       - file_exists: checks path presence on disk.
       - clipboard_contains: inspects system clipboard string values.
    3. Returns verification boolean outcomes.

    FLOW:
    Caller -> verify() -> WorldStateManager.get_state_snapshot() -> checks conditions -> returns boolean -> Caller
    """
    def __init__(self, world_state: WorldStateManager):
        self.world_state = world_state

    def is_port_open(self, host: str, port: int) -> bool:
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex((host, port)) == 0
        except Exception:
            return False
        
    def verify(self, condition_type: str, target: str) -> bool:
        """
        Programmatically verifies an outcome.
        
        Args:
            condition_type: One of 'process_running', 'window_exists', 'file_exists', 'clipboard_contains', 'port_open', 'url_reachable', 'ui_element_exists'
            target: The query target parameter.
            
        Returns:
            bool: True if the condition is met, False otherwise.
        """
        condition_type = condition_type.lower()
        logger.info(f"Verifying: {condition_type} -> {target}")
        
        if condition_type == "port_open":
            host = "127.0.0.1"
            port = 0
            try:
                if ":" in target:
                    parts = target.split(":")
                    host = parts[0]
                    port = int(parts[1])
                else:
                    port = int(target)
            except (ValueError, IndexError):
                logger.warning(f"Invalid port_open target format: '{target}'")
                return False
            return self.is_port_open(host, port)

        elif condition_type == "url_reachable":
            import urllib.request
            url = target
            if not url.startswith(("http://", "https://")):
                url = "http://" + url
            try:
                req = urllib.request.Request(url, method="HEAD")
                with urllib.request.urlopen(req, timeout=1.0) as response:
                    return response.status in (200, 201, 301, 302)
            except Exception:
                try:
                    with urllib.request.urlopen(url, timeout=1.5) as response:
                        return response.status in (200, 201, 301, 302)
                except Exception:
                    return False

        elif condition_type == "ui_element_exists":
            try:
                from container import ServiceContainer
                ui_mapper = ServiceContainer.instance().get_or_none("ui_mapper")
                if ui_mapper:
                    element = ui_mapper.get_element(target)
                    return element is not None
            except Exception as e:
                logger.error(f"UI Element verification failed: {e}")
            return False

        # State-based checks using snapshot
        state = self.world_state.get_state_snapshot()
        
        if condition_type == "process_running":
            target_lower = target.lower()
            return any(target_lower in p for p in state["processes"])
            
        elif condition_type == "window_exists":
            target_lower = target.lower()
            return any(target_lower in w["title"].lower() for w in state["windows"])
            
        elif condition_type == "file_exists":
            return os.path.exists(target)
            
        elif condition_type == "clipboard_contains":
            target_lower = target.lower()
            return target_lower in state["clipboard"].lower()
            
        else:
            logger.warning(f"Unknown verification condition: {condition_type}")
            return False
