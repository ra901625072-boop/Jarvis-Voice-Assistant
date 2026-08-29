# JARVIS — Phase 3 & 4 E2E Swarm Integration Test Results

| Test Name | Goal | Status | Latency (s) | Tokens | Cost ($) | Outcome / Details |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| Goal A (Deterministic Plan) | open settings app | PASS | 0.86s | 0 | $0.00000 | {'status': 'completed', 'goal': 'open settings app', 'evaluation': '', 'plan': [{'id': 1, 'description': 'Open system settings', 'tool_name': 'open_se |
| Goal B (Grounded/Visual routing) | find the biggest icon on screen | PASS | 1.84s | 0 | $0.00000 | {'status': 'completed', 'goal': 'find the biggest icon on screen', 'evaluation': '', 'plan': [{'id': 1, 'description': 'Find the biggest icon on the s |
| Goal C (Filesystem Search) | find my check_learning_status.py | PASS | 3.15s | 0 | $0.00000 | {'status': 'completed', 'goal': 'find my check_learning_status.py', 'evaluation': '', 'plan': [{'id': 1, 'description': 'Search for the file', 'tool_n |
| Goal D (Failure and Recovery Loop) | open_application 'nonexistent_app_abc' | PASS (Expected Failure) | 2.14s | 0 | $0.00000 | Execution failed: 1 critical tasks failed. Replanning/Recovery failed or exhausted. |
| Goal E (Concurrent dispatch) | Concurrent A & C | PASS | 1.36s | 0 | $0.00000 | Goal A Success: True, Goal C Success: True |


All tests completed successfully. Model telemetry verified.