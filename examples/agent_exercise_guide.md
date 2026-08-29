# Phase 2: Agent Exercise Guide (Closing the Coverage Gap)

The learning pipeline is fully wired, verified, and running. The only remaining step is the actual "training" — giving the system real task outcomes so the 10 silent agents can build their capability scores and self-models.

Currently, only `memory_agent` and `coding_agent` have real data. The goal is to deliberately trigger the other 10 agents over the next week or two.

## How to train each agent

Here are practical prompts and actions you can use in your normal JARVIS sessions to force each agent to fire and record an outcome.

### 1. `browser_agent` & `vision_agent`
*Goal: Automate web flows, analyze screen, find UI elements.*
- **Prompt:** "Open a browser, go to weather.com, and tell me the forecast for tomorrow."
- **Prompt:** "Look at my screen and tell me if I have any unread notifications."
- **Prompt:** "Find the 'Submit' button on this page and click it."
*(Failure is fine! If the vision model hallucinates or the browser hits a timeout, that's exactly the kind of negative signal the RealtimeLearner needs to build a failure streak and learn a lesson.)*

### 2. `planning_agent` & `execution_agent`
*Goal: Create multi-step plans and execute them.*
- **Prompt:** "Create a detailed plan to back up my documents folder, compress it, and move it to my external drive, then execute the plan."
- **Prompt:** "I need to research the top 3 electric SUVs of 2026. Make a plan to search for them, extract their specs into a table, and save it as a markdown file, then do it."

### 3. `verification_agent` & `debugging_agent`
*Goal: Verify results, diagnose errors, self-heal.*
- **Prompt (force a bug):** Write a python script that intentionally throws an `IndexError`, run it, and tell JARVIS: "Run this script and if it fails, debug and fix it."
- **Prompt:** "Check if the markdown file you just created actually contains the table of SUVs."

### 4. `integration_agent`
*Goal: Call external APIs, sync data.*
- **Prompt:** "Check my Google Calendar for my next meeting." (Assuming calendar integration is set up).
- **Prompt:** "Fetch the current Bitcoin price using a public API."

### 5. `supervisor_agent` & `coordinator_agent`
*Goal: Routing, context generation, evaluating plans.*
- These will naturally trigger as you do the complex tasks above. The Supervisor handles the initial routing, and the Coordinator manages the hand-offs between specialists (like Planning -> Execution -> Verification).
- **To specifically test Supervisor reconnects:** Interrupt a long-running task and ask it to resume.

### 6. `recovery_agent`
*Goal: Recover from failure.*
- **Action:** While the `execution_agent` or `browser_agent` is running a task, manually turn off your Wi-Fi or close the target application. When it fails, ask JARVIS to recover and try an alternative approach.

## Monitoring Progress

Run the monitoring dashboard periodically to check your coverage:

```bash
cd d:\Jarvis
python check_learning_status.py
```

Look at **Q8 (Coverage Gap)**. Your goal is to see:
`All 12 agents have outcome data!`

## Don't fear failure

The learning loop is designed to handle failure. A 100% success rate means the system isn't attempting hard enough tasks. Let it fail, let it build a `failure_streak`, and watch it generate `lessons_learned` that it will use to avoid the same mistake next time.
