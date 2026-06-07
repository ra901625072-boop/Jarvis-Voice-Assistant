import os
import sys
import logging

# Force UTF-8 on Windows so LiveKit emoji (e.g. 🚀) don't crash the cp1252 console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv
from rich.console import Console
from livekit.agents import cli, WorkerOptions
from livekit import api
import threading
import asyncio
import socket
from flask import Flask, jsonify, send_from_directory
import psutil

# Setup rich console for terminal output
console = Console()

frontend_path = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend'))
app = Flask(__name__, static_folder=frontend_path, static_url_path='/')

@app.route('/token', methods=['GET'])
def token_handler():
    room_name = os.environ.get("LIVEKIT_ROOM_NAME", "jarvis-room")
    
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
        try:
            lkapi = api.LiveKitAPI(os.environ.get("LIVEKIT_URL"), os.environ.get("LIVEKIT_API_KEY"), os.environ.get("LIVEKIT_API_SECRET"))
            await lkapi.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
                agent_name="my-agent",
                room=room_name
            ))
            await lkapi.aclose()
        except Exception as e:
            console.print(f"[red]Error dispatching agent:[/red] {e}")

    try:
        asyncio.run(dispatch())
    except Exception as e:
        console.print(f"[red]Error running dispatch loop:[/red] {e}")

    return jsonify({
        "token": token.to_jwt(),
        "url": os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
    })

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
        "temp": round(simulated_temp, 1)
    })

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory(app.static_folder, path)

def run_web_server():
    app.run(host='0.0.0.0', port=8000, use_reloader=False)

def setup_logging():
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("logs/jarvis.log", encoding='utf-8'),
            logging.StreamHandler(sys.stdout)  # stdout already reconfigured to utf-8 above
        ]
    )

def main():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    load_dotenv(env_path) # Load environment variables from .env if present
    setup_logging()
    logger = logging.getLogger("JARVIS.Main")
    
    console.print("[bold cyan]Initializing JARVIS LiveKit Agent...[/bold cyan]")
    logger.info("Starting JARVIS LiveKit Agent")
    
    try:
        from agent import server
        
        web_thread = threading.Thread(target=run_web_server, daemon=True)
        web_thread.start()
        
        # Get local IP to display in logs
        local_ip = "127.0.0.1"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass
            
        logger.info(f"Frontend Web Server accessible locally at: http://localhost:8000")
        logger.info(f"Frontend Web Server accessible on network at: http://{local_ip}:8000")
        
        cli.run_app(server)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]JARVIS is shutting down (KeyboardInterrupt)...[/bold yellow]")
        logger.info("JARVIS shut down by user.")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Critical error during startup: {e}")
        console.print(f"[bold red]Critical Error:[/bold red] {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
