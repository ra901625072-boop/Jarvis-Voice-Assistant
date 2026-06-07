# JARVIS AI Assistant for Windows

A comprehensive, modular AI assistant powered by Python, LiveKit, and Google Gemini Realtime. JARVIS provides a low-latency, multimodal voice interface with deep integration into Windows system controls, file management, and browser automation.

## Architecture
- **Backend (Python)**: Uses `livekit-agents` and `aiohttp`. It connects to a LiveKit room as an AI agent and exposes a suite of computer control tools to the LLM. It also runs a local web server to serve the frontend.
- **Frontend (HTML/JS/CSS)**: A sleek Web Dashboard that connects to the LiveKit room using the `livekit-client` SDK to transmit and receive audio, displaying a dynamic AI orb visualization and system stats.
- **LLM Engine**: Powered by Google's Gemini 2.5 Flash Native Audio for real-time voice-to-voice interaction without the need for separate STT or TTS layers.

## Features
- **Real-Time Voice Interaction**: Native audio voice conversations via LiveKit and Gemini.
- **System Control**: Adjust volume, mute/unmute, and control display brightness.
- **App Management**: Open and close installed Windows applications natively.
- **Browser Automation**: Open URLs, search Google/YouTube, and close tabs.
- **File Management**: Fuzzy search, create, move, copy, rename, and delete files/folders. 
- **Keyboard & Mouse Control**: Full programmatic control of the keyboard and mouse (type, click, move, scroll).
- **Long-Term Memory**: Remembers user preferences and conversation history using a local SQLite database.
- **Security Layer**: Requires explicit user confirmation for destructive actions (e.g., deleting files, clearing history).

## Setup Instructions

1. **Install Python Dependencies**
   Run the setup script to create a virtual environment and install dependencies:
   ```cmd
   cd backend
   setup.bat
   ```

2. **Environment Variables**
   Ensure you have your `.env` configured in the `backend` directory. You will need LiveKit credentials and a Google API key for Gemini:
   ```env
   GOOGLE_API_KEY=your_google_api_key_here
   
   LIVEKIT_URL=wss://your-project.livekit.cloud
   LIVEKIT_API_KEY=your_livekit_api_key
   LIVEKIT_API_SECRET=your_livekit_api_secret
   ```

3. **Run JARVIS**
   Start the backend server and agent process:
   ```cmd
   cd backend
   call venv\Scripts\activate.bat
   python main.py
   ```
   *This will initialize the LiveKit agent and start a local web server on `http://localhost:8000`.*

4. **Access the Dashboard**
   Open your web browser and navigate to `http://localhost:8000` to access the JARVIS Web Dashboard. Click **Initialize Connection** to start interacting via voice!
