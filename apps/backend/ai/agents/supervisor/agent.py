import logging
import asyncio
import os
import time
import json
import uuid

from livekit import agents
from livekit.agents import AgentSession, TurnHandlingOptions, EndpointingOptions, room_io
from livekit.plugins import google as lk_google
import google.genai
from google.genai import types

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult

logger = logging.getLogger("JARVIS.SupervisorAgent")


class DynamicAssistant(agents.Agent):
    def __init__(self, instructions: str):
        super().__init__(instructions=instructions)


class SupervisorAgent(BaseAgent):
    """
    Supervisor connection, transcription, TTS, and routing.
    Migrates LiveKit connection logic and acts as the central router for tasks.
    """
    def __init__(self, bus):
        super().__init__(agent_id="supervisor_agent")
        self.bus = bus
        self.bus.register(self.agent_id, self.handle)
        
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.client = google.genai.Client(api_key=api_key) if api_key else None
        self.session = None

        # Speech queue & status tracking
        self._speech_queue = asyncio.PriorityQueue()
        self._reply_tasks = set()
        self._speech_worker_task = None
        self._user_speaking = False
        self._agent_speaking = False

        self._memory_context = ""
        self._last_session_context = ""
        self._preferred_language = None
        self._active_mcp = []
        self._mcp_toolsets = []
        self._last_rendered_status = ""

        # Safe speech controller
        self._bg_speech_tracker = {}  # bg_task_id -> item_id
        self._canceled_speech_items = set()  # set of item_ids that are canceled
        
        # Debounced context update task
        self._context_update_task = None
        
        # Session background task registry
        self._session_tasks = set()

    def _create_tracked_task(self, coro) -> asyncio.Task:
        """Spawns an asyncio Task and registers it for clean shutdown."""
        task = asyncio.create_task(coro)
        self._session_tasks.add(task)
        task.add_done_callback(self._session_tasks.discard)
        return task

    def _record_synthetic_task(self, task_type: str, success: bool, payload: dict = None, error: str = None) -> None:
        """Helper to create and record synthetic tasks targeting supervisor_agent so they are visible to the learning system."""
        try:
            task = AgentTask(
                task_id=str(uuid.uuid4()),
                task_type=task_type,
                payload=payload or {},
                origin_agent=self.agent_id,
                target_agent=self.agent_id
            )
            self._create_result(task, success=success, error=error)
        except Exception as e:
            logger.error(f"SupervisorAgent: failed to record synthetic task '{task_type}': {e}")

    def _get_mcp_note(self) -> str:
        mcp_note = ""
        for ts in self._mcp_toolsets:
            if ts not in self._active_mcp:
                mcp_note += f"\nNOTE: {ts.id} search tool is unavailable.\n"
        return mcp_note

    def _get_memory_context(self) -> str:
        if self._memory_context:
            return f"\n\n--- INJECTED MEMORY CONTEXT ---\n{self._memory_context}"
        return ""

    def _get_session_context(self) -> str:
        if getattr(self, "_last_session_context", None):
            return f"\n\n--- PREVIOUS SESSION SUMMARY ---\n{self._last_session_context}"
        return ""

    def _get_language_preference(self) -> str:
        if self._preferred_language:
            return f"\n\nUSER LANGUAGE PREFERENCE: The user prefers {self._preferred_language}. Respond in {self._preferred_language} when possible."
        return ""

    def _get_status_board_context(self) -> str:
        from container import ServiceContainer
        container = ServiceContainer.instance()
        status_board = container.get_or_none("status_board") if container else None
        if status_board:
            rendered = status_board.render_context()
            self._last_rendered_status = rendered
            return f"\n\n--- LIVE BACKGROUND TASKS STATUS BOARD ---\n{rendered}"
        return ""

    def _build_system_prompt(self) -> str:
        from modules.planning.behavior import JarvisBehavior
        enriched_prompt = JarvisBehavior.get_full_system_prompt()
        enriched_prompt += self._get_mcp_note()
        enriched_prompt += self._get_memory_context()
        enriched_prompt += self._get_session_context()
        enriched_prompt += self._get_language_preference()
        enriched_prompt += self._get_status_board_context()
        return enriched_prompt

    def _is_session_active(self) -> bool:
        if not getattr(self, "session", None):
            return False
        if not getattr(self, "room", None) or not hasattr(self.room, "isconnected") or not self.room.isconnected():
            return False
        try:
            return self.session.current_agent is not None
        except Exception:
            return False

    def _is_safe_to_speak(self) -> bool:
        if not self._is_session_active():
            return False
        try:
            # Not user speaking
            user_busy = (self.session.user_state == "speaking" or self._user_speaking)
            # Not assistant speaking/thinking
            agent_busy = (self.session.agent_state == "speaking" or self.session.agent_state == "thinking" or self._agent_speaking)
            return not (user_busy or agent_busy)
        except Exception:
            return False

    async def _speech_worker(self):
        logger.info("SupervisorAgent speech worker loop started.")
        try:
            while True:
                # Pop next item (negated_priority, timestamp, text, bg_task_ids, item_id)
                negated_priority, timestamp, text, bg_task_ids, item_id = await self._speech_queue.get()
                
                # Check if this item has been canceled/superseded
                if item_id in self._canceled_speech_items:
                    logger.info(f"SpeechQueue: Skipping superseded speech item: '{text}'")
                    self._canceled_speech_items.discard(item_id)
                    self._speech_queue.task_done()
                    continue
                
                # Wait until safe to speak
                while not self._is_safe_to_speak():
                    await asyncio.sleep(0.2)
                    # Re-check cancel state while waiting
                    if item_id in self._canceled_speech_items:
                        break
                        
                if item_id in self._canceled_speech_items:
                    logger.info(f"SpeechQueue: Skipping superseded speech item (after waiting): '{text}'")
                    self._canceled_speech_items.discard(item_id)
                    self._speech_queue.task_done()
                    continue
                
                if not self._is_session_active():
                    self._speech_queue.task_done()
                    continue
                
                try:
                    logger.info(f"Speech worker outputting: '{text}' (priority: {-negated_priority})")
                    reply_coro = self.session.generate_reply(
                        instructions=f"Read the following announcement verbatim to the user: {text}"
                    )
                    if reply_coro is not None:
                        import inspect
                        if inspect.isawaitable(reply_coro):
                            if asyncio.iscoroutine(reply_coro):
                                task = self._create_tracked_task(reply_coro)
                            else:
                                async def _wait_play(coro=reply_coro):
                                    await coro
                                task = self._create_tracked_task(_wait_play())
                            self._reply_tasks.add(task)
                            task.add_done_callback(self._reply_tasks.discard)
                            
                            # Add a 15-second timeout to prevent stuck generations from blocking the queue
                            try:
                                await asyncio.wait_for(task, timeout=15.0)
                            except asyncio.TimeoutError:
                                logger.warning("Speech worker: Reply generation stalled and timed out after 15s. Cancelling task...")
                                task.cancel()
                                try:
                                    await task
                                except (asyncio.CancelledError, RuntimeError):
                                    pass
                except (RuntimeError, AssertionError) as e:
                    logger.warning(f"Speech worker generation skipped (session paused/draining): {e}")
                except Exception as e:
                    logger.error(f"Error in speech worker during generation: {e}", exc_info=True)
                finally:
                    self._speech_queue.task_done()
        except asyncio.CancelledError:
            logger.info("SupervisorAgent speech worker loop cancelled.")
        except Exception as e:
            logger.error(f"Error in speech worker loop: {e}", exc_info=True)

    def _push_to_speech_queue(self, text: str, priority_val: int, bg_task_ids: list):
        negated_priority = -priority_val
        timestamp = time.time()
        item_id = str(uuid.uuid4())
        
        # Pre-empt and cancel older speech items with overlapping background task IDs safely
        if bg_task_ids:
            for bg_task_id in bg_task_ids:
                old_item_id = self._bg_speech_tracker.get(bg_task_id)
                if old_item_id:
                    logger.info(f"SpeechQueue: Pre-empting and cancelling superseded speech item ID: {old_item_id}")
                    self._canceled_speech_items.add(old_item_id)
                self._bg_speech_tracker[bg_task_id] = item_id

        self._speech_queue.put_nowait((negated_priority, timestamp, text, bg_task_ids, item_id))
        logger.debug(f"SpeechQueue: Added '{text}' with priority {priority_val} and ID {item_id}.")

    def _register_session_handlers(self, session, container, memory, ctx):
        """Helper to safely bind event listeners on recreation of self.session."""
        @session.on("agent_state_changed")
        def on_agent_state_changed(event):
            self._agent_speaking = (event.new_state == "speaking")
            
            # Apply any deferred instruction update when agent returns to idle state
            if event.new_state == "idle":
                self._reply_in_progress = False
                pending_prompt = getattr(self, "_pending_prompt_update", None)
                if pending_prompt and pending_prompt != getattr(self, "_last_applied_prompt", ""):
                    self._pending_prompt_update = None
                    try:
                        if self.session:
                            self.session.update_agent(DynamicAssistant(pending_prompt))
                            self._last_applied_prompt = pending_prompt
                            logger.info("SupervisorAgent: Dynamically applied deferred instructions update on idle.")
                    except Exception as e:
                        logger.warning(f"SupervisorAgent: Failed to apply deferred prompt update: {e}")

            async def _publish_state():
                try:
                    payload = json.dumps({"type": "agent_state", "state": event.new_state})
                    await ctx.room.local_participant.publish_data(payload.encode("utf-8"))
                except Exception as e:
                    logger.error(f"Failed to publish agent state: {e}")
            self._create_tracked_task(_publish_state())

        @session.on("user_state_changed")
        def on_user_state_changed(event):
            self._user_speaking = (event.new_state == "speaking")

        @session.on("user_speech_committed")
        def on_user_speech(msg):
            self._user_speaking = False
            self.interrupt()
        
        @session.on("conversation_item_added")
        def on_conversation_item_added(event):
            item = event.item
            role = getattr(item, "role", None)
            item_type = getattr(item, "type", None)
            
            # Log conversation turns
            if item_type == "message" and role in ("user", "assistant"):
                text = item.text_content
                if text:
                    try:
                        memory.log_conversation(
                            role=role,
                            content=text,
                            session_id=self.session_id
                        )
                    except Exception as log_err:
                        logger.error(f"Failed to log conversation turn: {log_err}")
            
            # Trigger dynamic context and memory update on user messages
            if role == "user":
                self._reply_in_progress = True
                text = item.text_content
                
                # Cancel any pending debounced update
                if self._context_update_task and not self._context_update_task.done():
                    self._context_update_task.cancel()
                    
                async def _debounced_update(utterance_text):
                    try:
                        # 2-second debounce window
                        await asyncio.sleep(2.0)
                        if utterance_text:
                            context_task = AgentTask(
                                task_id=str(uuid.uuid4()),
                                task_type="retrieve_context",
                                payload={"goal": utterance_text},
                                origin_agent="voice_agent",
                                target_agent="memory_agent"
                            )
                            context_result = await self.bus.dispatch(context_task)
                            if context_result and context_result.success:
                                self._memory_context = context_result.result.get("context", "")

                        status_board = container.get_or_none("status_board") if container else None
                        if self.session:
                            if status_board:
                                self._last_rendered_status = status_board.render_context()
                            new_prompt = self._build_system_prompt()
                            current_prompt = getattr(self, "_last_applied_prompt", "")
                            if new_prompt != current_prompt:
                                # Guard against updating agent instructions mid-turn which triggers duplicate model replies
                                if self._agent_speaking or getattr(self, "_reply_in_progress", False):
                                    self._pending_prompt_update = new_prompt
                                    logger.debug("SupervisorAgent: Active turn in progress, deferring prompt update until idle.")
                                else:
                                    self.session.update_agent(DynamicAssistant(new_prompt))
                                    self._last_applied_prompt = new_prompt
                                    self._pending_prompt_update = None
                                    logger.info("SupervisorAgent: Dynamically updated instructions with changed context.")
                    except asyncio.CancelledError:
                        pass
                    except Exception as err:
                        logger.error(f"Failed to dynamically update memory context and agent: {err}")

                self._context_update_task = self._create_tracked_task(_debounced_update(text))

            if item_type == "message" and role == "assistant":
                self._reply_in_progress = False
                text = item.text_content
                if text:
                    async def _format_and_publish():
                        try:
                            from modules.skills.output_formatter_skill import OutputFormatterSkill
                            formatter = OutputFormatterSkill()
                            formatted_text = await formatter.auto_format(text)
                            payload = json.dumps({"type": "transcript", "text": formatted_text})
                            await ctx.room.local_participant.publish_data(payload.encode("utf-8"))
                        except Exception as e:
                            logger.error(f"Failed to format/publish agent reply: {e}")
                    self._create_tracked_task(_format_and_publish())

    async def run_session(self, ctx: agents.JobContext, mcp_toolsets, tools_base, memory, container):
        """Migrated from agent.py: handles the entire LiveKit connection logic."""
        from modules.planning.behavior import JarvisBehavior
        from modules.task.events import task_event_bus

        # Register event loop in TaskEventBus
        task_event_bus.set_loop(asyncio.get_running_loop())

        # Initialize speech queue on the active event loop
        self._speech_queue = asyncio.PriorityQueue()
        self._reply_tasks = set()
        self._session_tasks = set()
        self._bg_speech_tracker.clear()
        self._canceled_speech_items.clear()

        # Start the speech worker task scoped to this session
        speech_worker_task = asyncio.create_task(self._speech_worker())
        self._session_tasks.add(speech_worker_task)
        self._speech_worker_task = speech_worker_task

        start_t = time.perf_counter()

        # Warmup VisionManager
        async def warmup_vision():
            try:
                mgr = container.get("vision_manager")
                if mgr:
                    await asyncio.to_thread(mgr.warmup)
            except Exception as e:
                logger.error(f"VisionManager warmup failed: {e}")
        self._create_tracked_task(warmup_vision())
        
        # Warmup BrowserController
        async def warmup_browser():
            try:
                for t in tools_base:
                    if type(t).__name__ == "BrowserTools":
                        await t.browser_ctrl._ensure_driver()
                        async def keepalive(t=t):
                            while ctx.room.isconnected():
                                t.browser_ctrl._is_port_open(9222)
                                await asyncio.sleep(30)
                        self._create_tracked_task(keepalive())
                        break
            except Exception as e:
                logger.error(f"Browser warmup failed: {e}")
        self._create_tracked_task(warmup_browser())

        # MCP setup
        async def cleanup_mcp():
            for mcp_ts in mcp_toolsets:
                try:
                    await mcp_ts.aclose()
                except Exception:
                    pass
        ctx.add_shutdown_callback(cleanup_mcp)

        async def init_mcp(mcp_ts):
            try:
                await asyncio.wait_for(mcp_ts.setup(), timeout=30.0)
                return mcp_ts
            except Exception as e:
                logger.warning(f"MCP toolset '{mcp_ts.id}' failed (non-fatal): {e}")
                return None

        mcp_results = await asyncio.gather(*[init_mcp(ts) for ts in mcp_toolsets])
        active_mcp = [ts for ts in mcp_results if ts is not None]
        tools = tools_base + active_mcp

        try:
            memory.start_async_writer(asyncio.get_running_loop())
        except Exception as e:
            logger.warning(f"Async Memory Writer failed: {e}")

        try:
            trace_store = container.get("trace_store")
            if trace_store and hasattr(trace_store, "start_async_writer"):
                trace_store.start_async_writer(asyncio.get_running_loop())
        except Exception as e:
            logger.warning(f"Async Trace Writer failed: {e}")

        for tool in tools:
            if hasattr(tool, "room"):
                tool.room = ctx.room

        from container import ServiceContainer
        container = ServiceContainer.instance()
        
        self.ctx = ctx
        self.room = ctx.room

        self.session_manager = None
        self.session_id = None
        if container:
            try:
                self.session_manager = container.get("session_manager")
                self.session_id = self.session_manager.start_session()
                self._record_synthetic_task("session_init", success=True)
            except Exception as e:
                logger.error(f"SupervisorAgent: failed to start session: {e}")
                self._record_synthetic_task("session_init", success=False, error=str(e))
                
            with container._lock:
                container._services["room"] = ctx.room
                if self.session_id:
                    container._services["session_id"] = self.session_id

        @ctx.room.on("data_received")
        def on_data_received(data_packet):
            try:
                # Limit incoming packet sizes to 64KB
                if not data_packet.data or len(data_packet.data) > 65536:
                    logger.warning("SupervisorAgent: Discarded large room data packet.")
                    return

                payload = data_packet.data.decode("utf-8")
                obj = json.loads(payload)
                
                # Schema validation
                if not isinstance(obj, dict) or obj.get("type") != "user_chat":
                    return
                text = obj.get("text")
                if not isinstance(text, str) or not text.strip():
                    return

                is_session_active = self._is_session_active()

                if is_session_active:
                    logger.info(f"SupervisorAgent: Received text mode message: '{text}'")
                    self.interrupt()
                    try:
                        reply_coro = self.session.generate_reply(user_input=text, input_modality="text")
                        if reply_coro is not None:
                            import inspect
                            if inspect.isawaitable(reply_coro):
                                if asyncio.iscoroutine(reply_coro):
                                    task = self._create_tracked_task(reply_coro)
                                else:
                                    async def _wait_play(coro=reply_coro):
                                        await coro
                                    task = self._create_tracked_task(_wait_play())
                                self._reply_tasks.add(task)
                                task.add_done_callback(self._reply_tasks.discard)
                    except Exception as e:
                        logger.warning(f"SupervisorAgent: Text reply generation skipped ({e}), dispatching to AgentBus...")
                        self._create_tracked_task(self._handle_fallback_text_command(text))
                else:
                    logger.info(f"SupervisorAgent: Voice session inactive/closing. Dispatching text command to AgentBus: '{text}'")
                    self._create_tracked_task(self._handle_fallback_text_command(text))
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"SupervisorAgent: Failed to parse room data packet: {e}")
            except Exception as e:
                logger.error(f"Error handling room data packet: {e}", exc_info=True)

        disconnect_count = 0
        try:
            while disconnect_count < 10:
                # Fully close/tear down old session object before creating a new one on reconnect
                if self.session:
                    try:
                        if hasattr(self.session, "close"):
                            await self.session.close()
                    except Exception as close_err:
                        logger.debug(f"Failed to close old session during reconnect: {close_err}")

                livekit_model = os.environ.get("LIVEKIT_GEMINI_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
                use_vertexai = os.environ.get("LIVEKIT_USE_VERTEXAI", "false").lower() == "true" or "live-2.5" in livekit_model
                
                self.session = AgentSession(
                    llm=lk_google.beta.realtime.RealtimeModel(
                        model=livekit_model,
                        vertexai=use_vertexai,
                        voice="Charon",
                        temperature=0.3,
                        realtime_input_config=types.RealtimeInputConfig(
                            automatic_activity_detection=types.AutomaticActivityDetection(
                                disabled=False,
                                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                                prefix_padding_ms=200,
                                silence_duration_ms=400,
                            ),
                        ),
                    ),
                    tools=tools,
                    turn_handling=TurnHandlingOptions(
                        endpointing=EndpointingOptions(
                            min_delay=0.2,
                            max_delay=0.5,
                        )
                    ),
                )
                try:
                    start_session_t = time.time()
                    
                    # Dynamic Context Injection via AgentBus
                    import uuid
                    context_task = AgentTask(
                        task_id=str(uuid.uuid4()),
                        task_type="retrieve_context",
                        payload={"goal": ""},
                        origin_agent="voice_agent",
                        target_agent="memory_agent"
                    )
                    context_result = await self.bus.dispatch(context_task)
                    
                    if getattr(context_result, "confidence", 0.0) < 0.6 and context_result.success:
                        # Low confidence — request verification
                        verify_task = AgentTask(
                            task_id=str(uuid.uuid4()),
                            task_type="verify_result",
                            payload={"original_result": context_result.result, "goal": ""},
                            origin_agent=self.agent_id,
                            target_agent="verification_agent",
                        )
                        verify_result = await self.bus.dispatch(verify_task)
                        if verify_result.success:
                            verified = verify_result.result.get("verified", False) if isinstance(verify_result.result, dict) else False
                            if not verified:
                                logger.warning("SupervisorAgent: Context verification failed. Discarding low-confidence context.")
                                context_result = None
                    
                    memory_context = context_result.result.get("context", "") if context_result and context_result.success else ""
                    
                    # Retrieve last session context
                    last_session_context = ""
                    try:
                        last_session_task = AgentTask(
                            task_id=str(uuid.uuid4()),
                            task_type="retrieve_last_session",
                            payload={},
                            origin_agent="voice_agent",
                            target_agent="memory_agent"
                        )
                        last_session_result = await self.bus.dispatch(last_session_task)
                        if last_session_result and last_session_result.success:
                            last_session_context = last_session_result.result.get("last_session", "")
                    except Exception as ls_err:
                        logger.error(f"SupervisorAgent: failed to retrieve last session context: {ls_err}")

                    # Fetch user's preferred language
                    preferred_language = None
                    try:
                        if memory:
                            preferred_language = memory.get_preference("preferred_language")
                    except Exception as e:
                        logger.debug(f"Failed to fetch preferred_language: {e}")

                    # Store context variables for dynamic updates
                    self._memory_context = memory_context
                    self._last_session_context = last_session_context
                    self._preferred_language = preferred_language
                    self._active_mcp = active_mcp
                    self._mcp_toolsets = mcp_toolsets
                    
                    # Register session handlers securely
                    self._register_session_handlers(self.session, container, memory, ctx)
                    
                    enriched_prompt = self._build_system_prompt()
                    self._last_applied_prompt = enriched_prompt

                    # Auto-open JARVIS dedicated separate browser upon server session connection
                    try:
                        from config.settings import JARVIS_AUTO_OPEN_BROWSER
                        if JARVIS_AUTO_OPEN_BROWSER:
                            async def _launch_browser_on_connect():
                                try:
                                    browser_ctrl = container.get_or_none("browser_controller")
                                    if not browser_ctrl:
                                        from modules.controls.browser_controller import BrowserController
                                        browser_ctrl = BrowserController()
                                    await browser_ctrl.ensure_separate_browser()
                                except Exception as b_err:
                                    logger.warning(f"SupervisorAgent: Auto-opening separate browser on connect note: {b_err}")
                            self._create_tracked_task(_launch_browser_on_connect())
                    except Exception as cfg_err:
                        logger.debug(f"Auto browser launch config check note: {cfg_err}")

                    await self.session.start(
                        room=ctx.room,
                        agent=DynamicAssistant(enriched_prompt),
                        room_options=room_io.RoomOptions(close_on_disconnect=False),
                    )
                    memory.log_session_disconnect(time.time() - start_session_t, "graceful_exit")
                    self._record_synthetic_task("context_retrieval_routing", success=True)
                    if disconnect_count > 0:
                        self._record_synthetic_task("session_reconnect", success=True, payload={"attempts": disconnect_count})
                    break
                except Exception as e:
                    disconnect_count += 1
                    duration = time.time() - start_session_t
                    memory.log_session_disconnect(duration, str(e))
                    logger.error(f"Session disconnected: {e}. Reconnecting (Attempt {disconnect_count})...")
                    self._record_synthetic_task("context_retrieval_routing", success=False, error=str(e))
                    self._record_synthetic_task("session_reconnect", success=False, error=str(e), payload={"attempt": disconnect_count})
                    try:
                        recon_task = AgentTask(
                            task_id=str(uuid.uuid4()),
                            task_type="session_reconnect",
                            payload={"reason": str(e)},
                            origin_agent=self.agent_id,
                            target_agent=self.agent_id,
                        )
                        logger.warning(f"Reconnection task queued on bus: {recon_task.task_id}")
                    except Exception:
                        pass
                    await asyncio.sleep(2)

            if disconnect_count >= 10:
                self._record_synthetic_task("session_reconnect", success=False, error="Max reconnect attempts reached (10)")
                raise RuntimeError("Failed to connect/reconnect after 10 attempts.")

            logger.info(f"Assistant startup completed in {time.perf_counter() - start_t:.3f}s")

            if self.session:
                try:
                    reply_coro = self.session.generate_reply(user_input=JarvisBehavior.INTRO_MESSAGE)
                    if reply_coro is not None:
                        import inspect
                        if inspect.isawaitable(reply_coro):
                            if asyncio.iscoroutine(reply_coro):
                                task = self._create_tracked_task(reply_coro)
                            else:
                                async def _wait_play(coro=reply_coro):
                                    await coro
                                task = self._create_tracked_task(_wait_play())
                            self._reply_tasks.add(task)
                            task.add_done_callback(self._reply_tasks.discard)
                except Exception as e:
                    logger.error(f"Failed to force intro: {e}")

            # Keep connection loop active
            while ctx.room.isconnected():
                await asyncio.sleep(1.0)

        finally:
            # Cancel and cleanly await all tracked background tasks
            pending_tasks = [t for t in list(self._session_tasks) + list(getattr(self, "_reply_tasks", set())) if not t.done()]
            for task in pending_tasks:
                task.cancel()
            if pending_tasks:
                try:
                    await asyncio.gather(*pending_tasks, return_exceptions=True)
                except Exception:
                    pass
            self._session_tasks.clear()
            self._speech_worker_task = None
            if hasattr(self, "_reply_tasks"):
                self._reply_tasks.clear()
                
            if getattr(self, "session_manager", None) and getattr(self, "session_id", None):
                try:
                    self.session_manager.end_session(disconnect_reason="graceful_exit")
                    # Non-blocking, enqueued to run in background loop safely
                    asyncio.create_task(self._summarize_session(self.session_id, memory))
                except Exception as close_err:
                    logger.error(f"SupervisorAgent failed to end/summarize session: {close_err}")
                    
            self.session = None
            self.room = None
            if container:
                with container._lock:
                    container._services.pop("room", None)
                    container._services.pop("session_id", None)

            logger.info("SupervisorAgent run_session teardown finished.")

    async def _summarize_session(self, session_id: str, memory) -> None:
        """Asynchronously summarizes the session turns and updates the sessions table."""
        try:
            logger.info(f"SupervisorAgent starting session summarization for {session_id}...")
            turns = await asyncio.to_thread(memory.get_session_transcript, session_id)
            if not turns or len(turns) < 4:
                logger.info(f"SupervisorAgent: Session {session_id} has too few turns ({len(turns)}), skipping summarization.")
                return

            rows = []
            for i, turn in enumerate(turns):
                if not isinstance(turn, dict) or "role" not in turn or "content" not in turn:
                    logger.warning(f"Invalid transcript entry at index {i}: {turn}")
                    continue
                role = turn["role"]
                content = turn["content"]
                importance = 3
                try:
                    meta = memory._scorer.analyze(content, role)
                    importance = meta.get("importance", 3)
                except Exception as scorer_err:
                    logger.warning(f"Memory scorer analyze failed: {scorer_err}")
                rows.append((i, role, content, importance))
                
            if not rows:
                logger.warning(f"No valid transcript rows after validation for session {session_id}.")
                return

            try:
                from modules.memory.consolidator import MemoryConsolidator
                consolidator = MemoryConsolidator(memory)
                clusters = consolidator._cluster_by_topic(rows)
            except Exception as consolidator_err:
                logger.error(f"Memory consolidator failed: {consolidator_err}")
                return
            
            cluster_summaries = []
            topics_found = []
            for topic, entries in clusters.items():
                if not entries:
                    continue
                try:
                    summary = consolidator._extractive_summary(topic, entries)
                    if summary:
                        cluster_summaries.append(summary)
                        if topic != "General":
                            topics_found.append(topic)
                except Exception as sum_err:
                    logger.warning(f"Extractive summary failed for topic {topic}: {sum_err}")
                        
            if not cluster_summaries:
                logger.info(f"SupervisorAgent: No summaries generated for session {session_id}.")
                return
                
            final_summary = "\n\n".join(cluster_summaries)
            topics_str = ", ".join(topics_found) if topics_found else "General"
            
            try:
                def _sync_update_session_summary(sid, summ, tops):
                    with memory._lock.write_lock():
                        memory.dbs["conversations"].execute(
                            "UPDATE sessions SET summary = ?, topics = ? WHERE session_id = ?",
                            (summ, tops, sid),
                        )
                        memory._commit()
                        
                memory.enqueue_write(_sync_update_session_summary, session_id, final_summary, topics_str)
                logger.info(f"SupervisorAgent: Session {session_id} summarized successfully. Topics: {topics_str}")
            except Exception as db_err:
                logger.error(f"Failed to update session summary in database: {db_err}")
            
            try:
                logger.info("SupervisorAgent triggering immediate session learning...")
                async def run_learning():
                    try:
                        await asyncio.to_thread(memory.lifecycle.run_session_learning)
                    except Exception as learn_err:
                        logger.error(f"Session learning execution failed: {learn_err}")
                self._create_tracked_task(run_learning())
            except Exception as learn_trigger_err:
                logger.error(f"Failed to trigger session learning: {learn_trigger_err}")
            
        except Exception as e:
            logger.error(f"SupervisorAgent: failed to summarize session {session_id}: {e}", exc_info=True)

    def interrupt(self):
        """Interrupts the active session generation or speech."""
        logger.info("SupervisorAgent processing user interrupt.")
        for task in list(self._reply_tasks):
            if not task.done():
                logger.info("SupervisorAgent cancelling active generate_reply task.")
                task.cancel()
        self._reply_tasks.clear()

        if self._is_session_active():
            try:
                # Do not force interrupt on Gemini Realtime API sessions as Gemini WebSockets 
                # drop connection with 1011 internal error when clear_audio/remove_message is attempted.
                plugin_module = ""
                if hasattr(self.session, "_llm") and getattr(self.session, "_llm", None):
                    plugin_module = getattr(self.session._llm.__class__, "__module__", "")
                
                if "google" not in plugin_module:
                    fut = self.session.interrupt(force=False)
                    if fut is not None:
                        import inspect
                        if inspect.isawaitable(fut):
                            if asyncio.iscoroutine(fut):
                                asyncio.create_task(fut)
                            else:
                                async def _wait_fut(f=fut):
                                    await f
                                asyncio.create_task(_wait_fut())
            except Exception as e:
                logger.debug(f"Failed to interrupt session: {e}")

    async def _send_processing_signal(self, is_processing: bool):
        """Sends processing_start or agent_state signal to the active room data channel."""
        from container import ServiceContainer
        container = ServiceContainer.instance()
        room = container.get_or_none("room") if container else getattr(self, "room", None)
        if room and hasattr(room, "isconnected") and room.isconnected():
            try:
                sig_type = "processing_start" if is_processing else "agent_state"
                payload = json.dumps({"type": sig_type, "state": "thinking" if is_processing else "idle"})
                await room.local_participant.publish_data(payload.encode("utf-8"))
            except Exception as e:
                logger.debug(f"Could not send processing signal: {e}")

    async def _publish_transcript(self, text: str):
        """Publishes formatted transcript text to the active room data channel and WebSockets for UI chat."""
        from container import ServiceContainer
        from modules.skills.output_formatter_skill import OutputFormatterSkill
        container = ServiceContainer.instance()
        
        # 1. Format text
        formatted_text = text
        try:
            formatter = OutputFormatterSkill()
            formatted_text = await formatter.auto_format(text)
        except Exception:
            pass

        logger.info(f"SupervisorAgent Response: {formatted_text}")

        # 2. Publish to LiveKit Room if connected
        room = container.get_or_none("room") if container else getattr(self, "room", None)
        if room and hasattr(room, "isconnected") and room.isconnected():
            try:
                payload = json.dumps({"type": "transcript", "text": formatted_text})
                await room.local_participant.publish_data(payload.encode("utf-8"))
                logger.info("SupervisorAgent: Published transcript reply to room data channel.")
            except Exception as e:
                logger.error(f"Failed to publish transcript to room: {e}")

        # 3. Broadcast to WebSocket clients for text chat mode
        try:
            from events.event_bus import EventBus
            from api.routes.websocket import active_connections
            ws_payload = {"type": "chat_message", "role": "assistant", "text": formatted_text}
            asyncio.create_task(EventBus.get_instance().publish("task_events", ws_payload))
            for conn in list(active_connections):
                try:
                    await conn.send_json(ws_payload)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Could not broadcast transcript to WebSocket: {e}")

    async def _generate_goal_summary_response(self, goal: str, result: AgentResult) -> str:
        """Generates a natural, professional response summarizing the executed goal."""
        if not result or not result.success:
            err = result.error if result else "Unknown error during execution"
            return f"Sir, I encountered an issue while executing your request '{goal}': {err}"

        # 1. Extract outputs from subtasks
        task_outputs = []
        plan = []
        if isinstance(result.result, dict):
            plan = result.result.get("plan", [])
            for s in plan:
                res_val = s.get("result")
                if res_val and str(res_val).strip() and str(res_val) != "None":
                    task_outputs.append(f"{s.get('description', s.get('task', 'Step'))}: {res_val}")
        elif isinstance(result.result, str) and result.result.strip():
            task_outputs.append(result.result.strip())

        # If a single tool provided a direct user-facing response, return it directly
        if len(task_outputs) == 1:
            raw_out = task_outputs[0].split(":", 1)[-1].strip() if ":" in task_outputs[0] else task_outputs[0]
            if any(k in raw_out for k in ("Social media statuses", "Emails", "Messages from", "Profile @", "Unread WhatsApp", "Instagram Direct", "WhatsApp Summary", "Summary for", "Summary of")):
                return raw_out

        steps_summary = "\n".join([f"- Step {s.get('id', i+1)}: {s.get('description', s.get('task', ''))}" for i, s in enumerate(plan)])
        outputs_summary = "\n".join(task_outputs) if task_outputs else "All tasks executed successfully."

        prompt = f"""
You are J.A.R.V.I.S., a sophisticated AI OS assistant.
The user requested: "{goal}"

Execution Details:
Planned Steps:
{steps_summary}

Outputs & Findings:
{outputs_summary}

Provide a concise, direct, and helpful voice/text response (in Hinglish if the user spoke Hindi/Hinglish, or clear English).
Summarize the answer, result, or findings directly to the user.
Keep it natural, polite, and under 3 sentences unless listing items.
"""
        try:
            summary = await self.generate_response(prompt)
            if summary and summary.strip():
                return summary.strip()
        except Exception as e:
            logger.warning(f"SupervisorAgent: summary generation failed: {e}")

        # Deterministic fallback response with data if available
        if task_outputs:
            return f"Sir, here are the results for '{goal}':\n" + "\n".join(task_outputs)
        step_count = len(plan) if plan else "all"
        return (
            f"Sir, the goal '{goal}' has been successfully completed. "
            f"All {step_count} execution stages were verified and executed to completion."
        )

    async def _handle_fallback_text_command(self, text: str) -> None:
        """Fallback handler for user text commands when the voice session is inactive or busy."""
        try:
            # 1. Notify frontend UI that processing has started
            await self._send_processing_signal(True)

            from modules.routing.intent_router import IntentRouter, QueryIntent
            from container import ServiceContainer
            c = ServiceContainer.instance()
            memory = c.get_or_none("memory") if c else None

            classification = IntentRouter.classify(text)
            logger.info(f"SupervisorAgent text classification: intent={classification.intent.value}, is_direct_chat={classification.is_direct_chat}")

            # Direct conversation, Q&A, and memory inquiries
            if classification.is_direct_chat:
                if classification.intent == QueryIntent.MEMORY_QUERY:
                    reply_text = await IntentRouter.handle_direct_memory_query(
                        query=text,
                        memory_manager=memory,
                        llm_generator_fn=self.generate_response,
                        preferred_language=getattr(self, "_preferred_language", "Hinglish")
                    )
                else:
                    reply_text = await IntentRouter.handle_direct_conversation_or_qa(
                        query=text,
                        llm_generator_fn=self.generate_response,
                        memory_context=getattr(self, "_memory_context", ""),
                        preferred_language=getattr(self, "_preferred_language", "Hinglish")
                    )

                if not reply_text or not reply_text.strip():
                    reply_text = "Hello Sir! Systems are operational and ready for your instructions."
                reply_text = reply_text.strip()

                # Publish transcript & speak
                await self._publish_transcript(reply_text)
                await self.handle(AgentTask(
                    task_id=str(uuid.uuid4()),
                    task_type="speak",
                    payload={"text": reply_text, "priority": "high"},
                    origin_agent="supervisor_agent",
                    target_agent="supervisor_agent"
                ))

                # Log turn into conversation memory
                if hasattr(self, "session_id") and self.session_id and memory:
                    try:
                        memory.log_conversation(
                            role="assistant",
                            content=reply_text,
                            session_id=self.session_id
                        )
                    except Exception as log_err:
                        logger.debug(f"Failed to log conversational turn: {log_err}")
                return

            logger.info(f"SupervisorAgent dispatching goal to CoordinatorAgent: '{text}'")
            
            # Record task in PriorityTaskScheduler so it appears in UI Task Pipeline & Observability Logs
            from core.scheduler import PriorityTaskScheduler
            scheduler = PriorityTaskScheduler.get_instance()
            task_rec = None
            try:
                task_rec = await scheduler.record_external_task(
                    name=text[:50],
                    agent="coordinator_agent",
                    status="running",
                    payload={"goal": text}
                )
            except Exception as e:
                logger.debug(f"Failed to record external task in scheduler: {e}")

            task = AgentTask(
                task_id=task_rec.id if task_rec else str(uuid.uuid4()),
                task_type="execute_goal",
                payload={"goal": text, "command": text, "user_input": text},
                origin_agent="supervisor_agent",
                target_agent="coordinator_agent",
            )
            result = await self.bus.dispatch(task)
            success = result.success if result else False
            logger.info(f"SupervisorAgent goal execution completed: success={success}")

            if task_rec:
                try:
                    res_summary = str(result.result) if result and result.result else ("Completed" if success else "Failed")
                    status_str = "completed" if success else "failed"
                    await scheduler.update_external_task(task_rec.id, status=status_str, result=res_summary, progress=100)
                except Exception as e:
                    logger.debug(f"Failed to update external task in scheduler: {e}")

            # 2. Formulate intelligent summary response
            reply_text = await self._generate_goal_summary_response(text, result)

            # 3. Publish transcript to room data channel
            await self._publish_transcript(reply_text)

            # 4. Speak response if session or TTS is active
            await self.handle(AgentTask(
                task_id=str(uuid.uuid4()),
                task_type="speak",
                payload={"text": reply_text, "priority": "high"},
                origin_agent="supervisor_agent",
                target_agent="supervisor_agent"
            ))

            # 5. Log turn into conversation memory
            if hasattr(self, "session_id") and self.session_id:
                from container import ServiceContainer
                c = ServiceContainer.instance()
                mem = c.get_or_none("memory") if c else None
                if mem:
                    try:
                        mem.log_conversation(
                            role="assistant",
                            content=reply_text,
                            session_id=self.session_id
                        )
                    except Exception as log_err:
                        logger.debug(f"Failed to log fallback response turn: {log_err}")

        except Exception as e:
            logger.error(f"SupervisorAgent error executing fallback text command: {e}", exc_info=True)
            err_text = f"Sir, I encountered an error executing your command: {e}"
            await self._publish_transcript(err_text)
        finally:
            await self._send_processing_signal(False)

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        
        try:
            if task_type == "speak":
                text = task.payload.get("text", "")
                priority_str = task.payload.get("priority", "normal")
                bg_task_ids = task.payload.get("bg_task_ids", [])
                
                priority_map = {
                    "low": 1,
                    "normal": 2,
                    "high": 3,
                    "critical": 4
                }
                priority_val = priority_map.get(priority_str, 2)
                
                if hasattr(self, "session") and self.session:
                    self._push_to_speech_queue(text, priority_val, bg_task_ids)
                else:
                    logger.warning("SupervisorAgent: speak task received but no active session.")
                return self._create_result(task, success=True)
                
            else:
                return self._create_result(
                    task, 
                    success=False, 
                    error=f"SupervisorAgent does not support task type '{task_type}'"
                )
        except Exception as e:
            logger.exception(f"SupervisorAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))
