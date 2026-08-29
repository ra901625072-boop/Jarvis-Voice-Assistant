import os
import sys
import logging
import logging.handlers
import signal
import socket
import threading

# Force UTF-8 on Windows so LiveKit emoji (e.g. 🚀) don't crash the cp1252 console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from rich.console import Console
from livekit.agents import cli

console = Console()


def setup_logging() -> None:
    """Configure rotating file handlers (10 MB × 5 backups) for all log streams."""
    if not os.path.exists("logs"):
        os.makedirs("logs")

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)

    # ── Root logger ──────────────────────────────────────────────────────────
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Clear existing handlers to avoid duplicates (e.g. during test re-runs).
    # NOTE: We intentionally leave livekit-agents' own handlers untouched;
    #       removing the root handlers that propagate to livekit is fine because
    #       we re-add a stdout handler below.
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Console stream handler — all logs propagate here
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    root_logger.addHandler(stdout_handler)

    # Root rotating file handler — logs/jarvis.log (excludes FileManager/TaskManager)
    class IsolatedLogFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return not (
                record.name.startswith("JARVIS.FileManager")
                or record.name.startswith("JARVIS.TaskManager")
            )

    jarvis_file_handler = logging.handlers.RotatingFileHandler(
        "logs/jarvis.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    jarvis_file_handler.setFormatter(formatter)
    jarvis_file_handler.addFilter(IsolatedLogFilter())
    root_logger.addHandler(jarvis_file_handler)

    # ── FileManager logger — logs/file_manager.log ───────────────────────────
    file_mgr_logger = logging.getLogger("JARVIS.FileManager")
    file_mgr_logger.setLevel(logging.INFO)
    for handler in file_mgr_logger.handlers[:]:
        file_mgr_logger.removeHandler(handler)
    file_mgr_handler = logging.handlers.RotatingFileHandler(
        "logs/file_manager.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_mgr_handler.setFormatter(formatter)
    file_mgr_logger.addHandler(file_mgr_handler)
    file_mgr_logger.propagate = True

    # ── TaskManager logger — logs/task_manager.log ───────────────────────────
    task_mgr_logger = logging.getLogger("JARVIS.TaskManager")
    task_mgr_logger.setLevel(logging.INFO)
    for handler in task_mgr_logger.handlers[:]:
        task_mgr_logger.removeHandler(handler)
    task_mgr_handler = logging.handlers.RotatingFileHandler(
        "logs/task_manager.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    task_mgr_handler.setFormatter(formatter)
    task_mgr_logger.addHandler(task_mgr_handler)
    task_mgr_logger.propagate = True

    # Silence extremely noisy third-party loggers
    noisy_loggers = [
        "h2",
        "hickory_net",
        "hickory_resolver",
        "rustls",
        "hyper_util",
        "reqwest",
        "primp",
        "cookie_store",
        "duckduckgo_search",
        "livekit.plugins.google",
        "urllib3",
        "google",
        "google_genai",
        "httpcore",
        "httpx",
        "comtypes",
        "comtypes._post_coinit.unknwn",
    ]
    for n_logger in noisy_loggers:
        if n_logger in ("google_genai", "google", "h2", "primp", "cookie_store", "comtypes", "comtypes._post_coinit.unknwn"):
            logging.getLogger(n_logger).setLevel(logging.ERROR)
        else:
            logging.getLogger(n_logger).setLevel(logging.WARNING)


def shutdown(signum=None, frame=None) -> None:
    console.print("\n[bold yellow]JARVIS is shutting down gracefully...[/bold yellow]")
    logging.getLogger("JARVIS.Main").info("JARVIS shut down by user.")
    sys.exit(0)


def main() -> None:
    import time

    startup_start = time.perf_counter()

    from config.settings import load_config
    load_config()

    # Environment validation
    required = ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "JARVIS_API_KEY"]
    for key in required:
        val = os.environ.get(key, "").strip()
        if not val:
            raise RuntimeError(f"Missing required environment variable: {key}")

    setup_logging()
    logger = logging.getLogger("JARVIS.Main")

    # Register shutdown handlers
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    console.print("[bold cyan]Initializing JARVIS LiveKit Agent...[/bold cyan]")
    logger.info("Starting JARVIS LiveKit Agent")

    try:
        # ── Import agent (triggers eager service init) ────────────────────────
        agent_import_start = time.perf_counter()
        from agent import server  # noqa: F401  — side-effects load all toolsets
        agent_import_duration = time.perf_counter() - agent_import_start
        logger.info(f"Agent modules imported in {agent_import_duration:.3f}s")

        # ── Start Unified FastAPI server in background thread ──────────────────
        import uvicorn
        from api.app import app as fastapi_app

        def run_fastapi_server() -> None:
            expose_lan = os.environ.get("JARVIS_EXPOSE_LAN", "false").lower() == "true"
            host = "0.0.0.0" if expose_lan else "127.0.0.1"
            uvicorn.run(fastapi_app, host=host, port=8000, log_level="warning")

        fastapi_thread = threading.Thread(target=run_fastapi_server, daemon=True, name="JarvisFastAPIServer")
        fastapi_thread.start()

        # Get local IP for log output
        local_ip = "127.0.0.1"
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
        except Exception:
            pass

        logger.info("JARVIS Unified Web Server accessible locally at: http://localhost:8000")
        logger.info(f"JARVIS Unified Web Server accessible on network at: http://{local_ip}:8000")

        # ── Pre-warm dedicated separate browser in background if enabled ─────
        from config.settings import JARVIS_AUTO_OPEN_BROWSER
        if JARVIS_AUTO_OPEN_BROWSER:
            def _prewarm_browser():
                try:
                    time.sleep(1.0)
                    from config.settings import (
                        JARVIS_BROWSER_PROFILE_DIR,
                        JARVIS_BROWSER_TYPE,
                        JARVIS_BROWSER_STARTUP_URL
                    )
                    import subprocess
                    from modules.controls.app_controller import AppController

                    user_data_dir = JARVIS_BROWSER_PROFILE_DIR
                    channel_name = JARVIS_BROWSER_TYPE if JARVIS_BROWSER_TYPE in ("chrome", "msedge") else "msedge"
                    cmd_app = "chrome" if channel_name == "chrome" else "msedge"
                    target_url = JARVIS_BROWSER_STARTUP_URL or "http://localhost:8000"

                    os.makedirs(user_data_dir, exist_ok=True)
                    app_ctrl = AppController()
                    exe_path = app_ctrl._find_app_path(cmd_app) or cmd_app

                    subprocess.run(
                        [
                            "cmd", "/c", "start", "", exe_path,
                            "--remote-debugging-port=9222",
                            f"--user-data-dir={user_data_dir}",
                            "--no-first-run",
                            "--no-default-browser-check",
                            target_url
                        ],
                        check=False
                    )
                    logger.info(f"Dedicated browser auto-launched: {cmd_app} on CDP port 9222")
                except Exception as b_err:
                    logger.debug(f"Browser startup launch note: {b_err}")

            browser_thread = threading.Thread(target=_prewarm_browser, daemon=True, name="JarvisBrowserStartup")
            browser_thread.start()

        startup_duration = time.perf_counter() - startup_start
        console.print(f"[bold green]JARVIS setup completed in {startup_duration:.3f}s[/bold green]")
        logger.info(f"JARVIS setup completed in {startup_duration:.3f}s")

        from livekit.agents import cli as agents_cli
        agents_cli.run_app(server)
    except KeyboardInterrupt:
        shutdown()
    except Exception as e:
        logger.exception(f"Critical error during startup: {e}")
        console.print(f"[bold red]Critical Error:[/bold red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
