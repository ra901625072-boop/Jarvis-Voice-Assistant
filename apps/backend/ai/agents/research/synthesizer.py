"""
apps/backend/ai/agents/research/synthesizer.py
Evidence Graph Synthesizer & Domain Synthesis Engine:
Combines extracted evidence, claims, competitor matrices, and domain fallbacks into structured, traceable findings with citations.
"""
import logging
from typing import Dict, List, Any, Optional

from ai.agents.research.schemas.research import ResearchPlan, ResearchObjective, ResearchMode
from ai.agents.research.memory.evidence_store import EvidenceStore
from ai.agents.research.memory.source_store import SourceStore
from ai.agents.research.memory.claim_store import ClaimStore
from ai.agents.research.tools.file_search import ResearchDataAnalyzer
from ai.agents.research.tools.citation_tool import CitationTracker

logger = logging.getLogger("JARVIS.ResearchSynthesizer")


class ResearchSynthesizer:
    """
    Synthesizes the relational Evidence Graph, generating structured analytical sections,
    competitor comparison tables, and domain-informed technical insights.
    """

    def __init__(
        self,
        evidence_store: EvidenceStore,
        source_store: SourceStore,
        claim_store: ClaimStore,
        citation_tracker: CitationTracker
    ):
        self.evidence_store = evidence_store
        self.source_store = source_store
        self.claim_store = claim_store
        self.citation_tracker = citation_tracker

    def build_competitor_matrix_table(self, objective: ResearchObjective) -> str:
        """
        Builds a structured markdown competitor comparison matrix for market/business queries.
        """
        headers = ["Competitor / Architecture", "Target Segment / Paradigm", "Estimated Cost / Pricing", "Core Strengths & Moats", "Key Bottlenecks & Vulnerabilities"]
        
        q_lower = objective.core_question.lower()
        if "quantum" in q_lower or "physics" in q_lower:
            rows = [
                ["Superconducting Qubits (IBM, Google)", "Cloud Quantum Processors (NISQ / Transmons)", "$$$$ Multi-Million R&D / Cloud Tier", "Fast gate speeds (~10-100ns), planar lithography integration", "High sensitivity to thermal noise, requires dilution fridges at <15mK"],
                ["Trapped Ion Systems (Quantinuum, IonQ)", "High-Fidelity Quantum Computing", "$$$ Premium Cloud Compute", "Record two-qubit gate fidelities (>99.9%), long coherence times", "Slower gate operation speeds (~microseconds to ms), laser alignment scaling"],
                ["Neutral Atom Arrays (QuEra, Pasqal)", "Analog Simulation & 2D/3D Quantum Registers", "$$ Research Cloud Access", "Massive physical qubit counts (hundreds of atoms), reconfigurable geometries", "Optical dipole trap loading stochasticity, gate fidelity optimization"],
                ["Photonic Quantum Systems (PsiQuantum, Xanadu)", "Room-Temperature / Optical Quantum Computing", "$$$ Telecom Quantum R&D", "Standard telecom optical fiber compatibility, minimal cryo requirements", "Probabilistic photon generation and photon loss in waveguides"],
            ]
        elif "document" in q_lower or "ocr" in q_lower or "saas" in q_lower:
            rows = [
                ["Enterprise IDP (e.g. ABBYY / AWS Textract)", "Enterprise / Fortune 500", "$$$$ ($5k-$50k/mo)", "High compliance, multi-page batch OCR", "High complexity, slow setup, prohibitive pricing for SMBs"],
                ["Modern AI Extractors (e.g. Mindee / Base64.ai)", "Mid-Market / Developers", "$$ ($0.05 - $0.15/page)", "Clean REST APIs, pre-trained invoice/receipt models", "Lacks integrated end-to-end workflow UI for non-technical users"],
                ["Open-Source Local Stacks (e.g. DocumenSO / Paperless-ngx)", "Self-hosters / Privacy SMBs", "Free (Self-hosted)", "Zero recurring subscription, complete data privacy", "Requires technical maintenance, lacks native multimodal LLM reasoning"],
                ["AI Native Document Hubs (Proposed SaaS)", "Solo Developers & SMBs", "$ ($19 - $49/mo)", "Instant natural language Q&A, automated tagging, zero setup", "Initial brand awareness, API token cost management"],
            ]
        elif "agent" in q_lower or "mcp" in q_lower or "llm" in q_lower:
            rows = [
                ["Anthropic MCP Ecosystem", "AI Agent Developers", "Open Standard / Free", "Standardized tool definition, active industry adoption", "Requires client orchestration support"],
                ["Custom REST/gRPC Services", "Enterprise Microservices", "Custom Infra", "Fine-grained ACLs, existing APM tooling", "High boilerplates, manual schema sync across agents"],
                ["LangGraph / LangChain Multi-Agent", "Python Developers", "Open Source / Cloud", "Rich state graphs, checkpointing", "Steep learning curve, debugging complexity"],
            ]
        else:
            rows = [
                ["Category Leaders (Incumbents)", "Large Enterprises", "$$$ Premium Tier", "Established brand, compliance certifications", "High complexity, legacy technical debt"],
                ["Niche / Modern Challenger", "SMBs & Growth Teams", "$$ Mid-tier", "Modern UX, fast onboarding, AI integration", "Limited custom enterprise integration"],
                ["Self-Hosted / Open-Source", "Technical Builders", "Free / Self-managed", "Customizability, zero data lock-in", "Maintenance overhead, lack of managed support"],
            ]

        return ResearchDataAnalyzer.generate_markdown_comparison_table(
            headers=headers,
            rows=rows,
            caption=f"Architectural & Competitive Benchmark Matrix ({objective.timeframe})"
        )

    def synthesize_subquestion_evidence(self, sub_q_id: str) -> str:
        """
        Aggregates all atomic evidence facts for a sub-question with verified inline citations.
        """
        evidence_items = self.evidence_store.get_evidence_for_subquestion(sub_q_id)
        if not evidence_items:
            return "_No direct external evidence gathered for this specific sub-dimension._\n\n"

        text = ""
        seen_texts = set()
        for evd in evidence_items:
            clean_text = evd.excerpt.strip()
            # Normalize to avoid duplicate lines
            norm_key = clean_text.lower()[:60]
            if norm_key in seen_texts:
                continue
            seen_texts.add(norm_key)

            src = self.source_store.get_source(evd.source_id)
            if src:
                cite = self.citation_tracker.register_source(src)
                src_type = "Primary" if cite.is_primary else "Secondary"
                text += f"- **Evidence**: \"{clean_text}\" {cite.inline_tag}  \n  *(Source: `{cite.domain}` | Type: `{src_type}` | Confidence: `{cite.confidence}`)*\n\n"
            else:
                text += f"- **Evidence**: \"{clean_text}\"\n\n"
        return text
