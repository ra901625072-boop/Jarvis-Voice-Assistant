import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("JARVIS.LearningAgent.Curriculum")

AGENTS_CURRICULUM_TEMPLATES = {
    "coding_agent": {
        "curriculum_type": "code_discipline",
        "prompt": "Practice generating complete and syntax-correct JSON responses. Run python syntax checks on all generated code snippets before returning.",
        "expected_behavior": "Valid JSON output block matching target schema precisely.",
        "evaluation_rule": "JSON validation succeeds without parsing exceptions."
    },
    "research_agent": {
        "curriculum_type": "citation_ranking",
        "prompt": "Practice citation filtering and relevance ranking. Compare search results against academic or verified guidelines.",
        "expected_behavior": "Relevance ordered search output with complete domain metadata.",
        "evaluation_rule": "Top 3 links match key query terms."
    },
    "execution_agent": {
        "curriculum_type": "safe_retries",
        "prompt": "Practice robust exception handling and short recovery loops in tool usage. Avoid repeating exact failed commands.",
        "expected_behavior": "Alternative tool choices or options tried after first failure.",
        "evaluation_rule": "Retried command arguments do not duplicate the initial failing arguments."
    },
    "planning_agent": {
        "curriculum_type": "dependency_chains",
        "prompt": "Practice breaking down complex goals into smaller, independent sub-tasks. Define clear verification gates for each.",
        "expected_behavior": "Detailed checklist showing step dependencies and validation rules.",
        "evaluation_rule": "Plan has 3+ specific verification checkpoints."
    },
    "supervisor_agent": {
        "curriculum_type": "agent_routing",
        "prompt": "Practice optimizing sub-task handoffs between specialist agents. Minimize double hops or redundant routing.",
        "expected_behavior": "Direct routing to the most specific agent based on capability score.",
        "evaluation_rule": "No circular routing (A -> B -> A) and minimum total agent hops."
    }
}

def generate_curriculum_for_weakness(agent_id: str, task_type: str, failure_pattern: str) -> Dict[str, Any]:
    template = AGENTS_CURRICULUM_TEMPLATES.get(agent_id, {
        "curriculum_type": "general_refinement",
        "prompt": f"Practice execution of '{task_type}' focusing on avoiding standard pitfalls: {failure_pattern}.",
        "expected_behavior": "Successful task completion with zero error indicators.",
        "evaluation_rule": "Success status returned on next run."
    })
    return template
