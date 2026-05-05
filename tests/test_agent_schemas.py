"""Tests for tradingagents.agents.schemas — render functions with optional fields."""

from tradingagents.agents.schemas import (
    PortfolioRating,
    TraderAction,
    ResearchPlan,
    TraderProposal,
    PortfolioDecision,
    render_research_plan,
    render_trader_proposal,
    render_pm_decision,
)


class TestRenderResearchPlan:
    def test_basic(self):
        plan = ResearchPlan(
            recommendation=PortfolioRating.BUY,
            rationale="Strong earnings",
            strategic_actions="Buy 100 shares",
        )
        md = render_research_plan(plan)
        assert "**Recommendation**: Buy" in md
        assert "**Rationale**: Strong earnings" in md
        assert "**Strategic Actions**: Buy 100 shares" in md


class TestRenderTraderProposal:
    def test_minimal(self):
        p = TraderProposal(action=TraderAction.HOLD, reasoning="Uncertain")
        md = render_trader_proposal(p)
        assert "**Action**: Hold" in md
        assert "Confidence" not in md
        assert "Entry Price" not in md
        assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in md

    def test_all_optional_fields(self):
        p = TraderProposal(
            action=TraderAction.BUY,
            confidence=8,
            reasoning="Strong momentum",
            entry_price=150.0,
            stop_loss=140.0,
            stop_loss_2=135.0,
            take_profit_1=160.0,
            take_profit_2=170.0,
            take_profit_3=180.0,
            risk_reward_ratio=2.5,
            position_sizing="5% of portfolio",
            time_horizon="2-4 weeks",
        )
        md = render_trader_proposal(p)
        assert "**Confidence**: 8/10" in md
        assert "**Entry Price**: 150.0" in md
        assert "**Stop Loss**: 140.0" in md
        assert "**Stop Loss 2**: 135.0" in md
        assert "**Take Profit 1**: 160.0" in md
        assert "**Take Profit 2**: 170.0" in md
        assert "**Take Profit 3**: 180.0" in md
        assert "**Risk/Reward Ratio**: 2.5" in md
        assert "**Position Sizing**: 5% of portfolio" in md
        assert "**Time Horizon**: 2-4 weeks" in md
        assert "FINAL TRANSACTION PROPOSAL: **BUY**" in md

    def test_sell_action(self):
        p = TraderProposal(action=TraderAction.SELL, reasoning="Bearish")
        md = render_trader_proposal(p)
        assert "FINAL TRANSACTION PROPOSAL: **SELL**" in md


class TestRenderPmDecision:
    def test_minimal(self):
        d = PortfolioDecision(
            rating=PortfolioRating.HOLD,
            executive_summary="Wait and see",
            investment_thesis="Mixed signals",
        )
        md = render_pm_decision(d)
        assert "**Rating**: Hold" in md
        assert "Confidence" not in md
        assert "Price Target" not in md
        assert "Time Horizon" not in md

    def test_all_optional_fields(self):
        d = PortfolioDecision(
            rating=PortfolioRating.BUY,
            confidence=9,
            executive_summary="Strong buy",
            investment_thesis="Solid fundamentals",
            price_target=200.0,
            time_horizon="6-12 months",
        )
        md = render_pm_decision(d)
        assert "**Confidence**: 9/10" in md
        assert "**Price Target**: 200.0" in md
        assert "**Time Horizon**: 6-12 months" in md

    def test_all_ratings(self):
        for rating in PortfolioRating:
            d = PortfolioDecision(
                rating=rating,
                executive_summary="s",
                investment_thesis="t",
            )
            md = render_pm_decision(d)
            assert f"**Rating**: {rating.value}" in md
