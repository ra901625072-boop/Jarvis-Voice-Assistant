import asyncio
import logging
from typing import Optional, Callable, Awaitable
from events.event_bus import EventBus, VoiceEvent
from core.orchestrator import MasterOrchestrator

logger = logging.getLogger("JARVIS.VoiceListener")

class VoiceListenerPipeline:
    """
    Dedicated Non-Blocking Continuous Voice Listener Pipeline.
    Runs independently on Priority 100 so voice commands, wake words,
    and speech inputs are never blocked by background coding or research tasks.
    """
    _instance: Optional["VoiceListenerPipeline"] = None

    def __init__(self):
        self.orchestrator = MasterOrchestrator.get_instance()
        self.event_bus = EventBus.get_instance()
        self._input_queue: asyncio.Queue = asyncio.Queue()
        self._is_listening = False
        self._listener_task: Optional[asyncio.Task] = None

    @classmethod
    def get_instance(cls) -> "VoiceListenerPipeline":
        if cls._instance is None:
            cls._instance = VoiceListenerPipeline()
        return cls._instance

    async def start(self) -> None:
        """Start non-blocking continuous voice listener loop."""
        if self._is_listening:
            return
        self._is_listening = True
        self._listener_task = asyncio.create_task(self._process_voice_queue())
        logger.info("VoiceListenerPipeline started (Priority 100 - Always Active).")

    async def stop(self) -> None:
        self._is_listening = False
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except (asyncio.CancelledError, Exception):
                pass
            self._listener_task = None

    async def push_transcript(self, transcript: str, is_final: bool = True) -> None:
        """
        Non-blocking entry point called by LiveKit STT, Whisper, or Microphone audio stream.
        Immediately queues user speech without waiting for background execution tasks.
        """
        if not transcript or not transcript.strip():
            return

        logger.info(f"VoiceListener received speech transcript: '{transcript}'")
        
        # Publish VoiceEvent immediately to EventBus
        await self.event_bus.publish(VoiceEvent(
            text=transcript,
            is_final=is_final,
            sender="voice_stt"
        ))

        if is_final:
            await self._input_queue.put(transcript)

    async def _process_voice_queue(self) -> None:
        """Processes queued user transcripts concurrently without blocking STT audio ingestion."""
        while self._is_listening:
            try:
                transcript = await self._input_queue.get()
                
                logger.info(f"VoiceListener dispatching transcript to MasterOrchestrator: '{transcript}'")
                
                # Non-blocking handoff to MasterOrchestrator
                asyncio.create_task(self.orchestrator.handle_user_intent(transcript, origin="voice"))
                
                self._input_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error in VoiceListener pipeline loop: {e}")
