import os
import sys
import asyncio
import threading
import time
import unittest

# Add apps/backend to sys.path so we can import modules
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "apps", "backend"))

# Mock Environment Variables
os.environ["JARVIS_PROACTIVE_SPEECH_ENABLED"] = "true"
os.environ["JARVIS_ANNOUNCE_MILESTONES"] = "25,50,75,100"
os.environ["JARVIS_ANNOUNCE_BATCH_WINDOW_SEC"] = "0.5"

from modules.task.events import task_event_bus
from modules.task.status_board import StatusBoard
from modules.task.announcer import TaskAnnouncer
from container import ServiceContainer, build_container
from ai.agents.types import AgentTask, AgentResult

class MockAgentBus:
    def __init__(self):
        self.dispatched_tasks = []

    def register(self, agent_id: str, handler) -> None:
        pass

    async def dispatch(self, task: AgentTask, timeout=None) -> AgentResult:
        self.dispatched_tasks.append(task)
        return AgentResult(task_id=task.task_id, success=True, result={})

class TestParallelTaskAwareness(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Clear any stale subscribers from other test files
        task_event_bus._subscribers.clear()
        
        # Build a container and override agent_bus with mock
        self.container = build_container()
        self.mock_bus = MockAgentBus()
        self.container._services["agent_bus"] = self.mock_bus
        
        # Instantiate services
        self.status_board = self.container.get("status_board")
        self.announcer = self.container.get("task_announcer")
        
        # Ensure event bus has the running loop
        task_event_bus.set_loop(asyncio.get_running_loop())
        self.mock_bus.dispatched_tasks.clear()

    async def asyncTearDown(self):
        task_event_bus.unsubscribe(self.announcer.handle_event)
        task_event_bus.unsubscribe(self.status_board.handle_event)

    async def test_thread_event_propagation(self):
        """Verify task_event_bus handles thread-to-asyncio loop switching correctly."""
        event_received = asyncio.Event()
        received_event = {}

        def cb(event):
            received_event.update(event)
            event_received.set()

        task_event_bus.subscribe(cb)

        # Publish from a background thread
        def run_thread():
            task_event_bus.publish({
                "task_id": "thread_task_1",
                "task_type": "test",
                "status": "running",
                "progress": 0,
                "label": "Thread Task",
                "announce": True,
                "priority": "normal",
                "timestamp": time.time()
            })

        t = threading.Thread(target=run_thread)
        t.start()
        t.join()

        # Wait for callback to execute on the asyncio event loop
        await asyncio.wait_for(event_received.wait(), timeout=2.0)
        self.assertEqual(received_event["task_id"], "thread_task_1")
        self.assertEqual(received_event["status"], "running")
        task_event_bus.unsubscribe(cb)

    async def test_progress_milestone_filtering(self):
        """Verify progress events are filtered and only milestones announce."""
        # Clean progress states
        self.announcer._last_progress.clear()
        
        # Publish some non-milestone progress updates
        task_event_bus.publish({
            "task_id": "task_progress",
            "task_type": "download",
            "status": "progress",
            "progress": 10,
            "label": "File download",
            "announce": True,
            "priority": "normal",
            "timestamp": time.time()
        })
        
        # Sleep for a bit more than batch window (0.5s) to ensure no dispatch
        await asyncio.sleep(0.7)
        self.assertEqual(len(self.mock_bus.dispatched_tasks), 0)

        # Publish a milestone progress update (50%)
        task_event_bus.publish({
            "task_id": "task_progress",
            "task_type": "download",
            "status": "progress",
            "progress": 52,  # Should trigger the 50% milestone
            "label": "File download",
            "announce": True,
            "priority": "normal",
            "timestamp": time.time()
        })

        await asyncio.sleep(0.7)
        self.assertEqual(len(self.mock_bus.dispatched_tasks), 1)
        speak_task = self.mock_bus.dispatched_tasks[-1]
        self.assertEqual(speak_task.task_type, "speak")
        self.assertIn("50%", speak_task.payload["text"])

    async def test_announcer_batching(self):
        """Verify multiple events within the batch window are batched into a single speech."""
        task_event_bus.publish({
            "task_id": "batch_task_1",
            "task_type": "backup",
            "status": "completed",
            "progress": 100,
            "label": "Backup",
            "announce": True,
            "priority": "normal",
            "timestamp": time.time()
        })

        task_event_bus.publish({
            "task_id": "batch_task_2",
            "task_type": "download",
            "status": "completed",
            "progress": 100,
            "label": "Download",
            "announce": True,
            "priority": "normal",
            "timestamp": time.time()
        })

        # Wait for batch window to expire and dispatch
        await asyncio.sleep(0.7)
        self.assertEqual(len(self.mock_bus.dispatched_tasks), 1)
        speak_task = self.mock_bus.dispatched_tasks[0]
        self.assertEqual(speak_task.task_type, "speak")
        self.assertIn("Backup and Download completed successfully.", speak_task.payload["text"])

    async def test_status_board(self):
        """Verify status board maintains active tasks and ring buffer of finished tasks."""
        # 1. Start a task
        task_event_bus.publish({
            "task_id": "board_task_1",
            "task_type": "copy",
            "status": "running",
            "progress": 20,
            "label": "Copy Files",
            "announce": True,
            "priority": "normal",
            "timestamp": time.time()
        })
        
        await asyncio.sleep(0.1)
        snapshot = self.status_board.get_snapshot()
        self.assertEqual(len(snapshot["active"]), 1)
        self.assertEqual(snapshot["active"][0]["task_id"], "board_task_1")
        
        rendered = self.status_board.render_context()
        self.assertIn("Currently running: Copy Files (20%)", rendered)

        # 2. Complete it
        task_event_bus.publish({
            "task_id": "board_task_1",
            "task_type": "copy",
            "status": "completed",
            "progress": 100,
            "label": "Copy Files",
            "announce": True,
            "priority": "normal",
            "timestamp": time.time()
        })

        await asyncio.sleep(0.1)
        snapshot = self.status_board.get_snapshot()
        self.assertEqual(len(snapshot["active"]), 0)
        self.assertEqual(len(snapshot["finished"]), 1)
        self.assertEqual(snapshot["finished"][0]["task_id"], "board_task_1")
        
        rendered = self.status_board.render_context()
        self.assertIn("Recently finished: Copy Files completed", rendered)

    async def test_supervisor_speech_queue_preemption(self):
        """Verify SupervisorAgent speech queue prioritizes critical speech and drops superseded low-priority speech."""
        supervisor = self.container.get("supervisor_agent")
        
        # Clear queue and reply tasks
        supervisor._speech_queue = asyncio.PriorityQueue()
        supervisor._reply_tasks.clear()
        
        # 1. Push a low-priority task update
        supervisor._push_to_speech_queue("task 1 progress 25%", 1, ["task_1"])
        
        # 2. Push a critical task update for the same bg_task_id
        supervisor._push_to_speech_queue("task 1 failed!", 4, ["task_1"])
        
        # Verify both items are in the queue (preemption adds canceled ID to set, doesn't prune queue)
        self.assertEqual(supervisor._speech_queue.qsize(), 2)
        
        # Pop and verify it is the critical one
        item = await supervisor._speech_queue.get()
        self.assertEqual(item[0], -4)
        self.assertEqual(item[2], "task 1 failed!")
        
        # Pop the next item (the low-priority one) and verify its ID is in the canceled set
        item_canceled = await supervisor._speech_queue.get()
        self.assertEqual(item_canceled[0], -1)
        self.assertIn(item_canceled[4], supervisor._canceled_speech_items)
        
        # 3. Push a normal task update (priority 2) for task_2 and a high task update (priority 3) for task_3
        supervisor._push_to_speech_queue("task 2 running", 2, ["task_2"])
        supervisor._push_to_speech_queue("task 3 finished", 3, ["task_3"])
        
        self.assertEqual(supervisor._speech_queue.qsize(), 2)
        
        # Pop first (should be high priority task_3 finished)
        item1 = await supervisor._speech_queue.get()
        self.assertEqual(item1[0], -3)
        self.assertEqual(item1[2], "task 3 finished")
        
        # Pop second (should be normal priority task_2 running)
        item2 = await supervisor._speech_queue.get()
        self.assertEqual(item2[0], -2)
        self.assertEqual(item2[2], "task 2 running")

if __name__ == "__main__":
    unittest.main()
