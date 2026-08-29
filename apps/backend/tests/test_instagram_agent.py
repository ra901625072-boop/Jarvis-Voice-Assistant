"""
tests/test_instagram_agent.py — Comprehensive Unit & Integration Tests for Autonomous Instagram AI Agent.
"""
import os
import pytest
import asyncio
import sqlite3
from unittest.mock import AsyncMock, MagicMock

from ai.agents.types import AgentTask
from ai.agents.instagram.agent import InstagramAgent
from ai.agents.instagram.tools import (
    init_instagram_db,
    InstagramResearchEngine,
    InstagramStrategyPlanner,
    InstagramContentEngine,
    InstagramVisualValidator,
    InstagramCommentTriage,
    InstagramDMLeadFunnel,
    InstagramAnalyticsEngine,
    InstagramSelfLearningLoop,
    DB_PATH
)
from ai.agents.social_media.adapters.instagram_adapter import InstagramAdapter


@pytest.fixture(autouse=True)
def setup_db():
    init_instagram_db()
    yield


@pytest.mark.asyncio
async def test_instagram_research_engine():
    res = InstagramResearchEngine.research_trends(niche="UI/UX Design", topic="Portfolio Redesign")
    assert res["niche"] == "Ui/Ux Design"
    assert len(res["trending_hooks"]) > 0
    assert len(res["recommended_formats"]) > 0
    assert "core" in res["hashtag_clusters"]
    assert "competitor_insights" in res

    comp_res = InstagramResearchEngine.audit_competitor(
        username="@top_ux_creator",
        profile_data={"follower_count": "55K", "posts_count": "320"}
    )
    assert comp_res["competitor"] == "@top_ux_creator"
    assert comp_res["follower_baseline"] == "55K"
    assert "hook_strategy" in comp_res


@pytest.mark.asyncio
async def test_instagram_strategy_planner():
    strat = InstagramStrategyPlanner.generate_strategy(
        goal="Gain 1,000 followers and 20 client leads",
        niche="SaaS Design",
        days=14
    )
    assert strat["goal_type"] == "Lead Generation"
    assert len(strat["calendar_matrix"]) == 14
    first_day = strat["calendar_matrix"][0]
    assert "day_number" in first_day
    assert "content_theme" in first_day
    assert "format" in first_day

    # Verify retrieval of active strategy
    active = InstagramStrategyPlanner.get_active_strategy()
    assert active is not None
    assert active["strategy_id"] == strat["strategy_id"]


@pytest.mark.asyncio
async def test_instagram_content_engine_reel_and_carousel():
    # Test Reel Production Brief
    reel_brief = InstagramContentEngine.create_content_brief(
        topic="SaaS Landing Page Redesign",
        format_type="Reel",
        goal="reach",
        niche="UI/UX"
    )
    assert reel_brief["format"] == "Reel"
    assert len(reel_brief["script_breakdown"]) == 4
    assert "9:16" in reel_brief["visual_safe_zones"]["aspect_ratio"]
    assert "SYSTEM" in reel_brief["cta"]

    # Test 7-Slide Carousel Brief
    carousel_brief = InstagramContentEngine.create_carousel_brief(
        topic="Micro-Interactions",
        slide_count=7,
        niche="UI/UX",
        goal="saves"
    )
    assert carousel_brief["format"] == "Carousel"
    assert len(carousel_brief["slides"]) == 7
    assert carousel_brief["slides"][0]["type"] == "Hook / Cover Slide"
    assert "max_words" in carousel_brief["slides"][1]


@pytest.mark.asyncio
async def test_instagram_visual_validator():
    # Test safe zone detection
    elements = [
        {"name": "Header Title", "x": 500, "y": 100},   # Danger: < 220px
        {"name": "Center Hero Mockup", "x": 500, "y": 800}, # Safe
        {"name": "Bottom CTA", "x": 500, "y": 1650}    # Danger: > 1500px
    ]
    safe_check = InstagramVisualValidator.validate_safe_zones(aspect_ratio="9:16", element_positions=elements)
    assert safe_check["is_safe"] is False
    assert safe_check["violation_count"] == 2

    # Test WCAG contrast
    contrast = InstagramVisualValidator.evaluate_contrast(foreground_hex="#FFFFFF", background_hex="#000000")
    assert contrast["wcag_aa_compliant"] is True
    assert contrast["wcag_aaa_compliant"] is True


@pytest.mark.asyncio
async def test_instagram_comment_triage():
    # Lead comment
    c1 = InstagramCommentTriage.classify_comment(username="alice", comment_text="How much do you charge for a full SaaS redesign?")
    assert c1["category"] == "Lead"
    assert c1["recommended_action"] == "qualify_lead"

    # Question comment
    c2 = InstagramCommentTriage.classify_comment(username="bob", comment_text="What software did you use to build this prototype?")
    assert c2["category"] == "Question"
    assert "Figma" in c2["suggested_reply"]

    # Spam comment
    c3 = InstagramCommentTriage.classify_comment(username="spammer", comment_text="DM to promote on 500k page! Invest in crypto!")
    assert c3["category"] == "Spam"
    assert c3["recommended_action"] == "hide_or_delete"

    # Toxic comment
    c4 = InstagramCommentTriage.classify_comment(username="troll", comment_text="This is fake and terrible trash scam")
    assert c4["category"] == "Toxic"
    assert c4["recommended_action"] == "hide_or_flag"


@pytest.mark.asyncio
async def test_instagram_dm_lead_funnel_and_crm():
    lead_res = InstagramDMLeadFunnel.qualify_dm(
        username="john_founder",
        message_text="Hey! We need an urgent UI/UX redesign for our mobile app. Our budget is around $10k. Can we talk this week?"
    )
    assert lead_res["is_qualified"] is True
    assert "UI/UX" in lead_res["service_interest"]
    assert "Tier 1" in lead_res["budget"]
    assert "Urgent" in lead_res["timeline"]

    # Check persistence in CRM
    leads = InstagramDMLeadFunnel.list_leads(status_filter="Qualified Lead")
    assert len(leads) >= 1
    assert any(l["username"] == "john_founder" or l["username"] == "@john_founder" for l in leads)


@pytest.mark.asyncio
async def test_instagram_analytics_and_self_learning():
    # Log a high-performing post
    post_ana = InstagramAnalyticsEngine.analyze_post(
        views=45000,
        likes=3500,
        comments=180,
        shares=1200,
        saves=2100,
        post_type="Carousel",
        topic="3 UI Mistakes"
    )
    assert "Viral" in post_ana["performance_rating"] or "Strong" in post_ana["performance_rating"]
    assert len(post_ana["causal_factors"]) >= 1

    # Run self-learning loop
    learning_res = InstagramSelfLearningLoop.run_feedback_optimization()
    assert learning_res["status"] in ("optimized", "cold_start")
    if learning_res["status"] == "optimized":
        assert len(learning_res["core_discoveries"]) > 0


@pytest.mark.asyncio
async def test_instagram_agent_task_dispatch():
    agent = InstagramAgent(bus=None)

    # 1. Research task
    t_research = AgentTask(task_type="research_trends", payload={"niche": "Fintech UI"})
    res1 = await agent.handle(t_research)
    assert res1.success is True
    assert "trending_hooks" in res1.result

    # 2. Strategy task
    t_strat = AgentTask(task_type="generate_strategy", payload={"goal": "Grow brand authority", "days": 5})
    res2 = await agent.handle(t_strat)
    assert res2.success is True
    assert len(res2.result["calendar_matrix"]) == 5

    # 3. Content brief task
    t_brief = AgentTask(task_type="create_content_brief", payload={"topic": "Fintech Dashboard"})
    res3 = await agent.handle(t_brief)
    assert res3.success is True
    assert res3.result["format"] == "Reel"

    # 4. DM Lead Triage task
    t_lead = AgentTask(task_type="qualify_dm_lead", payload={"username": "founder_sarah", "message": "Looking for Figma UI design quote for our seed stage startup."})
    res4 = await agent.handle(t_lead)
    assert res4.success is True
    assert res4.result["is_qualified"] is True


@pytest.mark.asyncio
async def test_instagram_adapter_autonomous_routing():
    adapter = InstagramAdapter()

    res = await adapter.execute_task("research_trends", {"niche": "Mobile Apps"})
    assert res["success"] is True
    assert "trending_hooks" in res

    strat_res = await adapter.execute_task("generate_strategy", {"goal": "Follower Growth", "days": 7})
    assert strat_res["success"] is True
    assert len(strat_res["calendar_matrix"]) == 7
