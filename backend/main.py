import os
import sys
import logging
import signal
import time
from collections import defaultdict

# Force UTF-8 on Windows so LiveKit emoji (e.g. 🚀) don't crash the cp1252 console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from rich.console import Console
from livekit.agents import cli
from livekit import api
import threading
import asyncio
import socket
from flask import Flask, jsonify, send_from_directory, request
import psutil
import uuid

# Setup rich console for terminal output
console = Console()

frontend_path = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend'))
app = Flask(__name__, static_folder=frontend_path, static_url_path='')

# Dedicated background event loop for LiveKit API dispatch
dispatch_loop = asyncio.new_event_loop()
def start_dispatch_loop():
    asyncio.set_event_loop(dispatch_loop)
    dispatch_loop.run_forever()
threading.Thread(target=start_dispatch_loop, daemon=True).start()

# Shared LiveKit API singleton
livekit_api = None

# Simple in-memory rate limiter: max 5 token requests per IP per 60 seconds
_token_rate: dict = defaultdict(list)

@app.route('/token', methods=['GET'])
def token_handler():
    # Rate limiting
    ip = request.remote_addr
    now = time.time()
    _token_rate[ip] = [t for t in _token_rate[ip] if now - t < 60]
    if len(_token_rate[ip]) >= 5:
        return jsonify({"error": "Rate limit exceeded. Maximum 5 token requests per minute."}), 429
    _token_rate[ip].append(now)

    # Security: basic API key check
    req_api_key = request.headers.get("Authorization") or request.args.get("api_key")
    expected_api_key = os.environ.get("JARVIS_API_KEY")
    if expected_api_key and req_api_key != expected_api_key:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        room_name = f"jarvis-room-{uuid.uuid4().hex[:8]}"
        
        # 1. Create token for frontend
        grant = api.VideoGrants(
            room_join=True,
            room=room_name,
        )
        token = api.AccessToken(os.environ.get("LIVEKIT_API_KEY"), os.environ.get("LIVEKIT_API_SECRET")) \
            .with_identity("User_Frontend") \
            .with_name("Web User") \
            .with_grants(grant)
            
        # 2. Trigger the agent to join the room
        async def dispatch():
            global livekit_api
            try:
                if not livekit_api:
                    livekit_api = api.LiveKitAPI(os.environ.get("LIVEKIT_URL"), os.environ.get("LIVEKIT_API_KEY"), os.environ.get("LIVEKIT_API_SECRET"))
                
                await livekit_api.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
                    agent_name=os.environ.get("AGENT_NAME", "jarvis"),
                    room=room_name
                ))
            except Exception as e:
                console.print(f"[red]Error dispatching agent:[/red] {e}")

        # Run dispatch safely in the dedicated background loop
        asyncio.run_coroutine_threadsafe(dispatch(), dispatch_loop)

        return jsonify({
            "token": token.to_jwt(),
            "url": os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/stats', methods=['GET'])
def stats_handler():
    # Real CPU usage over the last interval (0.5s is a good short interval, but 0 just gives since last call)
    cpu_percent = psutil.cpu_percent(interval=0)
    
    # Real temperature on Windows requires admin privileges via WMI which often fails.
    # We simulate a highly realistic temperature curve directly tied to the CPU load.
    # Base idle temp ~42C, spiking up to 85C under 100% load.
    simulated_temp = 42.0 + (cpu_percent * 0.43)
    
    return jsonify({
        "cpu": cpu_percent,
        "temp": round(simulated_temp, 1),
        "temp_source": "simulated"
    })

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

def run_web_server():
    from waitress import serve
    serve(app, host='0.0.0.0', port=8000)

def setup_logging():
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    # Define the standard format
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    formatter = logging.Formatter(log_format)
    
    # 1. Setup Root Logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Clear existing handlers to avoid duplicates (e.g. during test re-runs)
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    # Console Stream Handler (All logs propagate here)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    root_logger.addHandler(stdout_handler)
    
    # Root File Handler (logs/jarvis.log)
    jarvis_file_handler = logging.FileHandler("logs/jarvis.log", encoding='utf-8')
    jarvis_file_handler.setFormatter(formatter)
    
    # Filter to exclude FileManager and TaskManager logs from logs/jarvis.log
    class IsolatedLogFilter(logging.Filter):
        def filter(self, record):
            return not (record.name.startswith("JARVIS.FileManager") or record.name.startswith("JARVIS.TaskManager"))
            
    jarvis_file_handler.addFilter(IsolatedLogFilter())
    root_logger.addHandler(jarvis_file_handler)
    
    # 2. Setup FileManager Logger (logs/file_manager.log)
    file_mgr_logger = logging.getLogger("JARVIS.FileManager")
    file_mgr_logger.setLevel(logging.INFO)
    for handler in file_mgr_logger.handlers[:]:
        file_mgr_logger.removeHandler(handler)
    file_mgr_handler = logging.FileHandler("logs/file_manager.log", encoding='utf-8')
    file_mgr_handler.setFormatter(formatter)
    file_mgr_logger.addHandler(file_mgr_handler)
    file_mgr_logger.propagate = True
    
    # 3. Setup TaskManager Logger (logs/task_manager.log)
    task_mgr_logger = logging.getLogger("JARVIS.TaskManager")
    task_mgr_logger.setLevel(logging.INFO)
    for handler in task_mgr_logger.handlers[:]:
        task_mgr_logger.removeHandler(handler)
    task_mgr_handler = logging.FileHandler("logs/task_manager.log", encoding='utf-8')
    task_mgr_handler.setFormatter(formatter)
    task_mgr_logger.addHandler(task_mgr_handler)
    task_mgr_logger.propagate = True

def shutdown(signum=None, frame=None):
    console.print("\n[bold yellow]JARVIS is shutting down gracefully...[/bold yellow]")
    logging.getLogger("JARVIS.Main").info("JARVIS shut down by user.")
    sys.exit(0)

def main():
    import time
    startup_start = time.perf_counter()
    
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    load_dotenv(env_path, override=False) # Load environment variables from .env if present
    
    # Environment Validation
    required = ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"]
    for key in required:
        if not os.environ.get(key):
            raise RuntimeError(f"Missing required environment variable: {key}")
            
    setup_logging()
    logger = logging.getLogger("JARVIS.Main")
    
    # Register shutdown handlers
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    
    console.print("[bold cyan]Initializing JARVIS LiveKit Agent...[/bold cyan]")
    logger.info("Starting JARVIS LiveKit Agent")
    
    try:
        agent_import_start = time.perf_counter()
        from agent import server
        agent_import_duration = time.perf_counter() - agent_import_start
        logger.info(f"Agent modules and dependencies imported in {agent_import_duration:.3f}s")
        
        web_server_start = time.perf_counter()
        web_thread = threading.Thread(target=run_web_server, daemon=True)
        web_thread.start()
        web_server_duration = time.perf_counter() - web_server_start
        
        # Get local IP to display in logs
        local_ip = "127.0.0.1"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass
            
        logger.info(f"Frontend Web Server accessible locally at: http://localhost:8000 (Started in {web_server_duration:.3f}s)")
        logger.info(f"Frontend Web Server accessible on network at: http://{local_ip}:8000")
        
        startup_duration = time.perf_counter() - startup_start
        console.print(f"[bold green]JARVIS setup completed in {startup_duration:.3f}s[/bold green]")
        logger.info(f"JARVIS setup completed in {startup_duration:.3f}s")
        
        cli.run_app(server)
    except KeyboardInterrupt:
        shutdown()
    except Exception as e:
        logger.exception(f"Critical error during startup: {e}")
        console.print(f"[bold red]Critical Error:[/bold red] {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
