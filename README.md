# J.A.R.V.I.S - AI Assistant for Windows

A comprehensive, modular AI assistant powered by Python, LiveKit, and Google Gemini Realtime. JARVIS provides a low-latency, multimodal voice interface with deep integration into Windows system controls, file management, browser automation, and computer vision.

## Architecture

- **Backend (Python)**: Built with `livekit-agents`, `Flask`, and `asyncio`. It connects to a LiveKit room as an AI agent and exposes a vast suite of computer control tools to the LLM. It serves the frontend via a local web server.
- **Frontend (HTML/JS/CSS)**: A sleek, responsive Web Dashboard that connects to the LiveKit room using the `livekit-client` SDK. It transmits/receives audio and displays a dynamic neural wave visualization, along with real-time system stats (CPU, Temperature).
- **LLM Engine**: Powered by Google's Gemini Flash Native Audio for real-time voice-to-voice interaction, bypassing the need for separate STT or TTS latency layers.

## Features & Modules

JARVIS is organized into several core modules to encapsulate its vast capabilities:

### 1. System & Media Controls (`modules/controls`)
- **System Control**: Shutdown, restart, lock, sleep, and control the clipboard.
- **Window Management**: Minimize, maximize, restore, close, and switch active windows.
- **Media Control**: Adjust system volume, mute/unmute, and control display brightness.
- **Application Management**: Open and close installed Windows applications natively.
- **Browser Automation**: Open URLs, search Google/YouTube, close tabs, navigate history, and fetch live search results.
- **Keyboard & Mouse**: Full programmatic control of the keyboard (typing, shortcuts) and mouse (click, move, scroll).

### 2. Filesystem & Background Tasks (`modules/filesystem` & `modules/planning`)
- **File Management**: Fuzzy search, create, read, move, copy, rename, and delete files/folders. 
- **Background Task Manager**: Handles long-running filesystem operations (like cross-drive large file copies) in the background asynchronously without blocking the AI's conversation.
- **Task Tools**: Check background task progress, status, or cancel them dynamically.

### 3. Perception & Vision (`modules/perception`)
- **Computer Vision**: Take screenshots, analyze screen content visually using AI, and extract visible text.
- **UI Mapper**: Locate interactive UI elements (buttons, text boxes) by description and interact with them using AI vision, rather than relying on fixed coordinates.
- **Action Verifier**: Programmatically verify the outcome of actions by checking if the expected state is present on the screen.

### 4. Memory & Cognition (`modules/core` & `modules/database`)
- **Long-Term Memory**: Uses local SQLite databases (`memory.db`, `file_manager.db`, `tasks.db`, `vision_cache.db`) to store user preferences, semantic knowledge, and episodic memories.
- **Cognitive Coordinator**: Manages JARVIS's self-reflections, workflow patterns, and project-specific contexts.
- **Knowledge Graph**: Stores relationships between entities and facts to enhance JARVIS's understanding over time.
- **Security Layer**: Requires explicit user confirmation for destructive actions (e.g., deleting files, clearing history, system shutdown).

### 5. Execution & Planning (`modules/execution` & `modules/planning`)
- **Executive Controller & Verification Engine**: Validates the results of LLM actions (e.g., verifying a process started, window exists, file was created, or clipboard contains text).
- **Task Planner**: Enables JARVIS to break down complex user requests into step-by-step plans.

## Setup Instructions

1. **Install Python Dependencies**
   Run the setup script to create a virtual environment and install dependencies:
   ```cmd
   cd backend
   setup.bat
   ```

2. **Environment Variables**
   Ensure you have your environment variables configured (e.g., Google API Key, LiveKit credentials).

3. **Install Windows Startup (Optional)**
   Run `install_startup.bat` to add JARVIS to your Windows Startup folder, allowing it to boot automatically when you log in.

4. **Run JARVIS**
   Start the backend server and agent process:
   ```cmd
   jarvis_startup.bat
   ```
   *This will initialize the LiveKit agent and start the local web server on `http://localhost:8000`.*

5. **Access the Dashboard**
   Open your web browser and navigate to `http://localhost:8000` to access the JARVIS Web Dashboard. Connect to start interacting via voice!

## Security

JARVIS runs locally on your machine with significant control over your OS. For safety, destructive operations (e.g., deleting files, system shutdown) intercept the AI's intent and require explicit confirmation from the user before executing.
