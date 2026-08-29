"""
apps/backend/ai/agents/research/planner.py
Research Planner: Intent Understanding, Depth Level Classifier, Sub-question Decomposition, and Scientific Query Generator.
"""
import re
import json
import logging
from typing import List, Dict, Any, Optional

from ai.agents.research.schemas.research import (
    ResearchObjective,
    ResearchPlan,
    ResearchSubQuestion,
    ResearchDepth,
    ResearchMode,
    ResearchBudget,
)

logger = logging.getLogger("JARVIS.ResearchPlanner")


class ResearchPlanner:
    """
    Analyzes research objectives, decomposes them into structured sub-questions, and generates multi-angle search queries.
    """

    def __init__(self, llm_generate_func=None):
        self._llm_generate = llm_generate_func

    def parse_objective(
        self,
        query: str,
        depth: Optional[ResearchDepth] = None,
        mode: Optional[ResearchMode] = None,
        language: str = "English",
        tone: str = "Professional"
    ) -> ResearchObjective:
        """
        Parses raw user query into a structured ResearchObjective with classified intent and depth.
        """
        q_lower = query.lower()

        # 1. Infer Research Mode if not specified
        if mode is None:
            if any(w in q_lower for w in [
                "quantum", "physics", "biology", "chemistry", "scientific", "theory",
                "mathematics", "phenomenon", "entanglement", "superposition", "particle",
                "optics", "cosmology", "astronomy", "nanotechnology", "paper", "academic"
            ]):
                inferred_mode = ResearchMode.ACADEMIC_SCIENTIFIC
            elif any(w in q_lower for w in [
                "saas", "startup", "market", "pricing", "business", "should build",
                "monetization", "unit economics", "cac", "b2b", "smb", "solo developer"
            ]):
                inferred_mode = ResearchMode.MARKET_BUSINESS
            elif any(w in q_lower for w in ["vs", "compare", "versus", "competitor", "alternative", "market share"]):
                inferred_mode = ResearchMode.COMPETITOR_ANALYSIS
            elif any(w in q_lower for w in ["architecture", "protocol", "code", "implementation", "tech stack", "api", "microservices"]):
                inferred_mode = ResearchMode.TECHNICAL_ARCHITECTURE
            else:
                inferred_mode = ResearchMode.GENERAL
        else:
            inferred_mode = mode

        # 2. Infer Research Depth if not specified
        if depth is None:
            if any(w in q_lower for w in ["quick", "brief", "short", "fast", "simple"]):
                inferred_depth = ResearchDepth.QUICK
            elif any(w in q_lower for w in ["exhaustive", "comprehensive", "deepest", "detailed investment", "complete teardown"]):
                inferred_depth = ResearchDepth.COMPREHENSIVE
            elif any(w in q_lower for w in ["deep", "in-depth", "thorough", "whether", "saas in 2026", "strategy"]):
                inferred_depth = ResearchDepth.DEEP
            else:
                inferred_depth = ResearchDepth.NORMAL
        else:
            inferred_depth = depth

        # 3. Infer Timeframe
        year_match = re.search(r"\b(202[4-9]|203[0-9])\b", query)
        timeframe = year_match.group(0) if year_match else "2026"

        # 4. Clean core question
        clean_q = re.sub(r"^(research|tell me about|analyze|detailed report on|give me a report on|research on)\s+", "", query, flags=re.I).strip()
        core_q = clean_q if clean_q else query

        # 5. Extract key entities
        entities = list(set(re.findall(r"\b[A-Z][a-zA-Z0-9_\-]{2,}\b", query)))

        return ResearchObjective(
            raw_query=query,
            core_question=core_q,
            intent_type=inferred_mode.value,
            depth=inferred_depth,
            mode=inferred_mode,
            timeframe=timeframe,
            geographic_scope="Global",
            target_audience="Founders, Engineers & Decision Makers" if inferred_mode == ResearchMode.MARKET_BUSINESS else "Researchers, Scientists & Technical Builders",
            key_entities=entities,
            language=language,
            tone=tone,
        )

    async def create_research_plan(self, objective: ResearchObjective) -> ResearchPlan:
        """
        Builds a comprehensive multi-dimensional research plan with sub-questions and multi-angle queries.
        """
        logger.info(f"Building research plan for: '{objective.core_question}' (Mode: {objective.mode.value}, Depth: {objective.depth.value})")
        budget = ResearchBudget.from_depth(objective.depth)

        # Try LLM decomposition if available
        if self._llm_generate:
            try:
                plan = await self._plan_with_llm(objective, budget)
                if plan and plan.sub_questions:
                    return plan
            except Exception as e:
                logger.warning(f"LLM plan generation failed: {e}. Falling back to deterministic planner.")

        return self._plan_deterministic(objective, budget)

    async def _plan_with_llm(self, objective: ResearchObjective, budget: ResearchBudget) -> Optional[ResearchPlan]:
        prompt = (
            f"You are a master scientific and strategic research planner. Decompose this research objective into 3-5 structured sub-questions with multi-angle search queries:\n"
            f"Objective: {objective.core_question}\n"
            f"Mode: {objective.mode.value}\n"
            f"Depth: {objective.depth.value}\n"
            f"Timeframe: {objective.timeframe}\n\n"
            "CRITICAL SEARCH QUERY RULE: Ensure search queries include authoritative domain keywords (e.g. 'arxiv', 'nature', 'nist', 'ieee', 'technical paper', 'benchmark', 'documentation') and avoid generic single-word terms.\n"
            "Return JSON matching format:\n"
            "{\n"
            '  "sub_questions": [\n'
            '    {"id": "SQ-1", "dimension": "Core Domain Dimension", "question": "...", "rationale": "...", "search_queries": ["query 1", "query 2"]}\n'
            "  ]\n"
            "}"
        )
        res_json = await self._llm_generate(prompt=prompt, response_mime_type="application/json")
        if res_json:
            data = json.loads(res_json)
            raw_sqs = data.get("sub_questions", [])
            sub_questions = []
            for i, item in enumerate(raw_sqs, 1):
                sq = ResearchSubQuestion(
                    id=item.get("id", f"SQ-{i}"),
                    dimension=item.get("dimension", "General"),
                    question=item.get("question", ""),
                    rationale=item.get("rationale", ""),
                    search_queries=item.get("search_queries", []),
                )
                if sq.question:
                    sub_questions.append(sq)
            if sub_questions:
                return ResearchPlan(objective=objective, sub_questions=sub_questions, budget=budget)
        return None

    def _plan_deterministic(self, objective: ResearchObjective, budget: ResearchBudget) -> ResearchPlan:
        """
        High-integrity deterministic plan decomposition based on research mode.
        """
        q = objective.core_question
        tf = objective.timeframe
        sub_questions: List[ResearchSubQuestion] = []

        if objective.mode == ResearchMode.ACADEMIC_SCIENTIFIC:
            # Topic-specific academic scientific breakdown
            if "quantum" in q.lower() or "physics" in q.lower():
                sub_questions.append(ResearchSubQuestion(
                    id="SQ-1",
                    dimension="Fundamental Principles & Mathematical Formulations",
                    question="What are the foundational principles of quantum physics (superposition, entanglement, uncertainty principle) and their rigorous non-hyperbolic mathematical definitions?",
                    rationale="Establishes peer-reviewed theoretical ground truth, distinguishing physical correlations from faster-than-light communication.",
                    search_queries=[
                        "quantum entanglement correlations Bell inequality Nature physics",
                        "quantum superposition mathematical principles review paper",
                        "quantum physics fundamental principles peer reviewed",
                    ]
                ))
                sub_questions.append(ResearchSubQuestion(
                    id="SQ-2",
                    dimension="Quantum Computing & Hardware Modalities",
                    question="What are the current hardware architectures (superconducting, trapped ion, neutral atom) and verified algorithmic advantage limits in quantum computing as of 2026?",
                    rationale="Evaluates experimental physical qubit roadmaps and algorithm-specific computational advantages.",
                    search_queries=[
                        "quantum computing hardware modalities superconducting trapped ion 2026",
                        "quantum computational advantage algorithm benchmarks Shor Grover",
                        "IBM Google Quantum AI hardware roadmap 2026",
                    ]
                ))
                sub_questions.append(ResearchSubQuestion(
                    id="SQ-3",
                    dimension="Quantum Error Correction & Fault Tolerance",
                    question="What are the latest empirical breakthroughs in quantum error correction (surface codes, cat qubits, LDPC) and logical qubit threshold demonstrations?",
                    rationale="Identifies the primary engineering bottleneck required for scalable fault-tolerant quantum computing.",
                    search_queries=[
                        "quantum error correction logical qubit threshold Nature 2025 2026",
                        "surface code quantum error correction physical qubit overhead",
                        "fault tolerant quantum computing experimental demonstration",
                    ]
                ))
                sub_questions.append(ResearchSubQuestion(
                    id="SQ-4",
                    dimension="Quantum Sensing & Metrology",
                    question="What are the commercial and experimental applications of quantum sensing (atomic clocks, NV centers, magnetometers, gravimeters) in 2026?",
                    rationale="Examines the most mature, commercially deployed production applications of quantum physics.",
                    search_queries=[
                        "quantum sensing metrology atomic clocks diamond NV center NIST",
                        "quantum gravimeter commercial applications defense navigation",
                        "quantum sensing applications production 2026",
                    ]
                ))
                sub_questions.append(ResearchSubQuestion(
                    id="SQ-5",
                    dimension="Quantum Networking & Cryptography",
                    question="What is the state of quantum key distribution (QKD), quantum memory repeaters, and NIST Post-Quantum Cryptography (PQC) standards?",
                    rationale="Analyzes enterprise security implications and physical quantum network infrastructure.",
                    search_queries=[
                        "NIST post quantum cryptography standards FIPS 203 204",
                        "quantum repeater entanglement swapping network testbed",
                        "quantum key distribution satellite commercial deployment",
                    ]
                ))
            else:
                sub_questions.append(ResearchSubQuestion(
                    id="SQ-1",
                    dimension="Theoretical Foundations & State of the Art",
                    question=f"What are the foundational principles and state-of-the-art peer-reviewed findings regarding {q} in {tf}?",
                    rationale="Establishes theoretical baseline.",
                    search_queries=[
                        f"{q} theoretical principles arxiv paper review",
                        f"{q} state of the art scientific methodology",
                    ]
                ))
                sub_questions.append(ResearchSubQuestion(
                    id="SQ-2",
                    dimension="Recent Empirical Breakthroughs",
                    question=f"What are the most significant recent experimental demonstrations and published breakthroughs in {q} as of {tf}?",
                    rationale="Identifies verified recent empirical research.",
                    search_queries=[
                        f"{q} breakthrough experimental demonstration Nature Science {tf}",
                        f"{q} empirical results benchmark validation",
                    ]
                ))
                sub_questions.append(ResearchSubQuestion(
                    id="SQ-3",
                    dimension="Limitations & Open Research Questions",
                    question=f"What are the major technical limitations, physical constraints, and unresolved open questions for {q}?",
                    rationale="Identifies what remains unknown and active research frontiers.",
                    search_queries=[
                        f"{q} technical limitations physical constraints open problems",
                        f"{q} research frontiers challenges future directions",
                    ]
                ))

        elif objective.mode == ResearchMode.MARKET_BUSINESS:
            sub_questions.append(ResearchSubQuestion(
                id="SQ-1",
                dimension="Market Sizing & Growth",
                question=f"What is the market size, growth rate (CAGR), and enterprise demand for {q} in {tf}?",
                rationale="Validates addressable market and macroeconomic tailwinds.",
                search_queries=[
                    f"{q} market size {tf} CAGR Gartner Statista",
                    f"{q} market growth industry report forecast",
                    f"{q} revenue valuation statistics",
                ]
            ))
            sub_questions.append(ResearchSubQuestion(
                id="SQ-2",
                dimension="Competitor Analysis & Pricing Matrix",
                question=f"Who are the leading competitors in {q}, and what are their features, pricing tiers, and vulnerabilities?",
                rationale="Identifies competitor saturation, pricing models, and market positioning.",
                search_queries=[
                    f"{q} top competitors pricing features teardown",
                    f"{q} alternatives comparison matrix review",
                ]
            ))
            sub_questions.append(ResearchSubQuestion(
                id="SQ-3",
                dimension="Technology & Architecture",
                question=f"What are the core technical architectures, AI models, and APIs required to build {q}?",
                rationale="Determines technical feasibility and infrastructure dependencies.",
                search_queries=[
                    f"{q} technical architecture stack GitHub documentation",
                    f"{q} open source implementation pipeline",
                ]
            ))
            sub_questions.append(ResearchSubQuestion(
                id="SQ-4",
                dimension="Customer Pain Points & Economics",
                question=f"What are user complaints, unit economics, gross margins, and customer acquisition channels for {q}?",
                rationale="Assesses CAC/LTV viability and underserved customer friction.",
                search_queries=[
                    f"{q} user complaints pain points Reddit",
                    f"{q} unit economics pricing margins distribution",
                ]
            ))
        elif objective.mode == ResearchMode.COMPETITOR_ANALYSIS:
            sub_questions.append(ResearchSubQuestion(
                id="SQ-1",
                dimension="Competitor Landscape & Market Share",
                question=f"What is the complete competitive landscape and market share breakdown for {q}?",
                rationale="Maps all major players and incumbent tools.",
                search_queries=[
                    f"{q} competitive landscape market share Gartner",
                    f"{q} top competitors comparison matrix",
                ]
            ))
            sub_questions.append(ResearchSubQuestion(
                id="SQ-2",
                dimension="Feature & Pricing Breakdown",
                question=f"How do competitors compare in pricing tiers, core feature sets, and target segments for {q}?",
                rationale="Identifies pricing benchmarks and feature parity requirements.",
                search_queries=[
                    f"{q} feature matrix comparison pricing",
                    f"{q} enterprise vs starter plans breakdown",
                ]
            ))
            sub_questions.append(ResearchSubQuestion(
                id="SQ-3",
                dimension="Weaknesses & Strategic Moats",
                question=f"What are the documented weaknesses of incumbents and potential strategic moats in {q}?",
                rationale="Finds differentiation angles and unexploited niches.",
                search_queries=[
                    f"{q} competitor weaknesses user complaints Reddit",
                    f"{q} competitive advantage differentiation moat",
                ]
            ))
        else:
            sub_questions.append(ResearchSubQuestion(
                id="SQ-1",
                dimension="Overview & Core Concepts",
                question=f"What is the foundational overview and latest state of {q} in {tf}?",
                rationale="Provides foundational factual baseline.",
                search_queries=[
                    f"{q} technical overview documentation",
                    f"{q} comprehensive guide {tf}",
                ]
            ))
            sub_questions.append(ResearchSubQuestion(
                id="SQ-2",
                dimension="Technical Specifications & Trade-offs",
                question=f"What are the technical specifications, architectural trade-offs, and best practices for {q}?",
                rationale="Gives deep actionable technical insight.",
                search_queries=[
                    f"{q} technical architecture specifications",
                    f"{q} benchmark performance trade-offs",
                ]
            ))

        # Adjust query count and sub-questions based on depth
        if objective.depth == ResearchDepth.QUICK:
            sub_questions = sub_questions[:2]
        elif objective.depth == ResearchDepth.NORMAL:
            sub_questions = sub_questions[:3]

        return ResearchPlan(
            objective=objective,
            sub_questions=sub_questions,
            budget=budget,
        )
