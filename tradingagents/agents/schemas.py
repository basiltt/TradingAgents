"""Pydantic schemas used by agents that produce structured output.

The framework's primary artifact is still prose: each agent's natural-language
reasoning is what users read in the saved markdown reports and what the
downstream agents read as context.  Structured output is layered onto the
three decision-making agents (Research Manager, Trader, Portfolio Manager)
so that:

- Their outputs follow consistent section headers across runs and providers
- Each provider's native structured-output mode is used (json_schema for
  OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic)
- Schema field descriptions become the model's output instructions, freeing
  the prompt body to focus on context and the rating-scale guidance
- A render helper turns the parsed Pydantic instance back into the same
  markdown shape the rest of the system already consumes, so display,
  memory log, and saved reports keep working unchanged
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


def _coerce_enum(v: Any, enum_cls: type[Enum]) -> Any:
    """Extract an enum value from free-text LLM output.

    Prefers exact match, then longest-value substring match to avoid
    'Buy' matching inside 'Underweight/Buy-side' ambiguities.
    """
    if isinstance(v, str):
        stripped = v.strip()
        low = stripped.lower()
        # Exact match (case-insensitive)
        for member in enum_cls:
            if low == member.value.lower():
                return member.value
        # Longest-first substring match to avoid short values matching inside longer text
        members_by_length = sorted(enum_cls, key=lambda m: len(m.value), reverse=True)
        for member in members_by_length:
            if member.value.lower() in low:
                return member.value
    return v


# ---------------------------------------------------------------------------
# Shared rating types
# ---------------------------------------------------------------------------


class PortfolioRating(str, Enum):
    """5-tier rating used by the Research Manager and Portfolio Manager."""

    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class TraderAction(str, Enum):
    """3-tier transaction direction used by the Trader.

    The Trader's job is to translate the Research Manager's investment plan
    into a concrete transaction proposal: should the desk execute a Buy, a
    Sell, or sit on Hold this round.  Position sizing and the nuanced
    Overweight / Underweight calls happen later at the Portfolio Manager.
    """

    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


class OrderType(str, Enum):
    """Order type for the Trader's execution strategy."""

    MARKET = "Market"
    LIMIT = "Limit"
    STOP_LIMIT = "Stop-Limit"


# ---------------------------------------------------------------------------
# Trader — intermediate schema for Call 1 (directional decision)
# ---------------------------------------------------------------------------


class TraderDirection(BaseModel):
    """Directional decision produced by the Trader's first pass.

    Synthesizes the 4 analyst reports and the Research Manager's plan
    into a conviction call before any price-level calculation.
    """

    action: TraderAction = Field(
        description="The transaction direction. Exactly one of Buy / Hold / Sell.",
    )
    confidence: int = Field(
        description=(
            "Conviction level from 1 (lowest) to 10 (highest) reflecting how "
            "strongly the combined analyst evidence supports this action. "
            "1-3 = weak/conflicting signals, 4-6 = moderate, 7-10 = strong alignment."
        ),
    )
    reasoning: str = Field(
        description=(
            "The case for this action, synthesizing all four analyst reports "
            "and the research plan. Cite specific signals (e.g. RSI level, "
            "sentiment %, earnings surprise) that drove the decision. "
            "Three to five sentences."
        ),
    )

    @field_validator("action", mode="before")
    @classmethod
    def _coerce_action(cls, v: Any) -> Any:
        return _coerce_enum(v, TraderAction)


# ---------------------------------------------------------------------------
# Research Manager
# ---------------------------------------------------------------------------


class ResearchPlan(BaseModel):
    """Structured investment plan produced by the Research Manager.

    Hand-off to the Trader: the recommendation pins the directional view,
    the rationale captures which side of the bull/bear debate carried the
    argument, and the strategic actions translate that into concrete
    instructions the trader can execute against.
    """

    recommendation: PortfolioRating = Field(
        description=(
            "The investment recommendation. Exactly one of Buy / Overweight / "
            "Hold / Underweight / Sell. Choose the rating that best matches "
            "the weight of evidence from the debate."
        ),
    )
    rationale: str = Field(
        description=(
            "Conversational summary of the key points from both sides of the "
            "debate, ending with which arguments led to the recommendation. "
            "Speak naturally, as if to a teammate."
        ),
    )
    strategic_actions: str = Field(
        description=(
            "Concrete steps for the trader to implement the recommendation, "
            "including position sizing guidance consistent with the rating."
        ),
    )

    @field_validator("recommendation", mode="before")
    @classmethod
    def _coerce_recommendation(cls, v: Any) -> Any:
        return _coerce_enum(v, PortfolioRating)


def render_research_plan(plan: ResearchPlan) -> str:
    """Render a ResearchPlan to markdown for storage and the trader's prompt context."""
    return "\n".join([
        f"**Recommendation**: {plan.recommendation.value}",
        "",
        f"**Rationale**: {plan.rationale}",
        "",
        f"**Strategic Actions**: {plan.strategic_actions}",
    ])


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------


class TraderProposal(BaseModel):
    """Structured transaction proposal produced by the Trader.

    The trader reads the Research Manager's investment plan and the analyst
    reports, then turns them into a concrete transaction: what action to
    take, the reasoning that justifies it, and the practical levels for
    entry, stop-loss, and sizing.
    """

    action: TraderAction = Field(
        description="The transaction direction. Exactly one of Buy / Hold / Sell.",
    )
    confidence: Optional[int] = Field(
        default=None,
        description=(
            "Conviction level from 1 (lowest) to 10 (highest) reflecting how "
            "strongly the evidence supports this action."
        ),
    )
    reasoning: str = Field(
        description=(
            "The case for this action, anchored in the analysts' reports and "
            "the research plan. Two to four sentences."
        ),
    )
    entry_price: Optional[float] = Field(
        default=None,
        description="Entry price target in the instrument's quote currency.",
    )
    stop_loss: Optional[float] = Field(
        default=None,
        description="Primary stop-loss price in the instrument's quote currency.",
    )
    stop_loss_2: Optional[float] = Field(
        default=None,
        description="Secondary (wider) stop-loss price, if a two-tier exit strategy is warranted.",
    )
    take_profit_1: Optional[float] = Field(
        default=None,
        description="First (nearest) take-profit target price.",
    )
    take_profit_2: Optional[float] = Field(
        default=None,
        description="Second take-profit target price.",
    )
    take_profit_3: Optional[float] = Field(
        default=None,
        description="Third (stretch) take-profit target price.",
    )
    risk_reward_ratio: Optional[float] = Field(
        default=None,
        description="Risk-to-reward ratio, e.g. 2.5 means 2.5R reward per 1R risk.",
    )
    position_sizing: Optional[str] = Field(
        default=None,
        description="Sizing guidance, e.g. '5% of portfolio'.",
    )
    time_horizon: Optional[str] = Field(
        default=None,
        description="Recommended holding period, e.g. '2-4 weeks' or '3-6 months'.",
    )
    order_type: Optional[OrderType] = Field(
        default=None,
        description=(
            "Preferred order type for execution. Market for immediate fills, "
            "Limit for price-sensitive entries, Stop-Limit for breakout entries."
        ),
    )
    scaling_plan: Optional[str] = Field(
        default=None,
        description=(
            "How to scale into or out of the position across the take-profit "
            "levels. E.g. '50% at TP1, 30% at TP2, 20% at TP3' or "
            "'DCA in 3 equal tranches over 48 hours'."
        ),
    )
    invalidation_thesis: Optional[str] = Field(
        default=None,
        description=(
            "What would make this trade wrong — the specific condition or "
            "price level that invalidates the thesis and warrants exiting "
            "regardless of stop-loss. One to two sentences."
        ),
    )
    catalyst_timing: Optional[str] = Field(
        default=None,
        description=(
            "Key upcoming event or catalyst that affects timing, e.g. "
            "'Earnings report on May 15 — enter before or wait for reaction'."
        ),
    )

    @field_validator("action", mode="before")
    @classmethod
    def _coerce_action(cls, v: Any) -> Any:
        return _coerce_enum(v, TraderAction)

    @field_validator("order_type", mode="before")
    @classmethod
    def _coerce_order_type(cls, v: Any) -> Any:
        if v is None:
            return v
        return _coerce_enum(v, OrderType)


def render_trader_proposal(proposal: TraderProposal) -> str:
    """Render a TraderProposal to markdown.

    The trailing ``FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`` line is
    preserved for backward compatibility with the analyst stop-signal text
    and any external code that greps for it.
    """
    parts = [
        f"**Action**: {proposal.action.value}",
    ]
    if proposal.confidence is not None:
        parts.extend(["", f"**Confidence**: {proposal.confidence}/10"])
    parts.extend(["", f"**Reasoning**: {proposal.reasoning}"])
    if proposal.entry_price is not None:
        parts.extend(["", f"**Entry Price**: {proposal.entry_price}"])
    if proposal.stop_loss is not None:
        parts.extend(["", f"**Stop Loss**: {proposal.stop_loss}"])
    if proposal.stop_loss_2 is not None:
        parts.extend(["", f"**Stop Loss 2**: {proposal.stop_loss_2}"])
    if proposal.take_profit_1 is not None:
        parts.extend(["", f"**Take Profit 1**: {proposal.take_profit_1}"])
    if proposal.take_profit_2 is not None:
        parts.extend(["", f"**Take Profit 2**: {proposal.take_profit_2}"])
    if proposal.take_profit_3 is not None:
        parts.extend(["", f"**Take Profit 3**: {proposal.take_profit_3}"])
    if proposal.risk_reward_ratio is not None:
        parts.extend(["", f"**Risk/Reward Ratio**: {proposal.risk_reward_ratio}"])
    if proposal.position_sizing:
        parts.extend(["", f"**Position Sizing**: {proposal.position_sizing}"])
    if proposal.time_horizon:
        parts.extend(["", f"**Time Horizon**: {proposal.time_horizon}"])
    if proposal.order_type is not None:
        parts.extend(["", f"**Order Type**: {proposal.order_type.value}"])
    if proposal.scaling_plan:
        parts.extend(["", f"**Scaling Plan**: {proposal.scaling_plan}"])
    if proposal.invalidation_thesis:
        parts.extend(["", f"**Invalidation Thesis**: {proposal.invalidation_thesis}"])
    if proposal.catalyst_timing:
        parts.extend(["", f"**Catalyst/Timing**: {proposal.catalyst_timing}"])
    parts.extend([
        "",
        f"FINAL TRANSACTION PROPOSAL: **{proposal.action.value.upper()}**",
    ])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Portfolio Manager
# ---------------------------------------------------------------------------


class PortfolioDecision(BaseModel):
    """Structured output produced by the Portfolio Manager.

    The model fills every field as part of its primary LLM call; no separate
    extraction pass is required. Field descriptions double as the model's
    output instructions, so the prompt body only needs to convey context and
    the rating-scale guidance.
    """

    rating: PortfolioRating = Field(
        description=(
            "The final position rating. Exactly one of Buy / Overweight / Hold / "
            "Underweight / Sell, picked based on the analysts' debate."
        ),
    )
    confidence: Optional[int] = Field(
        default=None,
        description=(
            "Conviction level from 1 (lowest) to 10 (highest) reflecting how "
            "strongly the overall evidence supports this rating."
        ),
    )
    executive_summary: str = Field(
        description=(
            "A concise action plan covering entry strategy, position sizing, "
            "key risk levels, and time horizon. Two to four sentences."
        ),
    )
    investment_thesis: str = Field(
        description=(
            "Detailed reasoning anchored in specific evidence from the analysts' "
            "debate. If prior lessons are referenced in the prompt context, "
            "incorporate them; otherwise rely solely on the current analysis."
        ),
    )
    price_target: Optional[float] = Field(
        default=None,
        description="Optional target price in the instrument's quote currency.",
    )
    time_horizon: Optional[str] = Field(
        default=None,
        description="Optional recommended holding period, e.g. '3-6 months'.",
    )

    @field_validator("rating", mode="before")
    @classmethod
    def _coerce_rating(cls, v: Any) -> Any:
        return _coerce_enum(v, PortfolioRating)


def render_pm_decision(decision: PortfolioDecision) -> str:
    """Render a PortfolioDecision back to the markdown shape the rest of the system expects.

    Memory log, CLI display, and saved report files all read this markdown,
    so the rendered output preserves the exact section headers (``**Rating**``,
    ``**Executive Summary**``, ``**Investment Thesis**``) that downstream
    parsers and the report writers already handle.
    """
    parts = [
        f"**Rating**: {decision.rating.value}",
    ]
    if decision.confidence is not None:
        parts.extend(["", f"**Confidence**: {decision.confidence}/10"])
    parts.extend([
        "",
        f"**Executive Summary**: {decision.executive_summary}",
        "",
        f"**Investment Thesis**: {decision.investment_thesis}",
    ])
    if decision.price_target is not None:
        parts.extend(["", f"**Price Target**: {decision.price_target}"])
    if decision.time_horizon:
        parts.extend(["", f"**Time Horizon**: {decision.time_horizon}"])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Compliance Officer
# ---------------------------------------------------------------------------


class ComplianceVerdict(str, Enum):
    """Outcome of a compliance check."""

    PASS = "Pass"
    FLAG = "Flag"
    BLOCK = "Block"


class ComplianceFinding(BaseModel):
    """A single compliance finding."""

    check: str = Field(description="Name of the check (e.g. 'Position Size', 'Leverage Cap').")
    verdict: ComplianceVerdict = Field(description="Pass, Flag, or Block.")
    detail: str = Field(default="", description="Explanation of the finding.")

    @field_validator("verdict", mode="before")
    @classmethod
    def _coerce_verdict(cls, v: Any) -> Any:
        return _coerce_enum(v, ComplianceVerdict)


class ComplianceCheck(BaseModel):
    """Structured output from the Compliance Officer."""

    overall_verdict: ComplianceVerdict = Field(
        description=(
            "Overall compliance verdict. Block if ANY finding is Block. "
            "Flag if any finding is Flag but none are Block. Pass otherwise."
        ),
    )
    findings: list[ComplianceFinding] = Field(
        description="List of individual compliance check results.",
    )
    summary: str = Field(
        description="One-paragraph summary of the compliance review.",
    )

    @field_validator("overall_verdict", mode="before")
    @classmethod
    def _coerce_overall_verdict(cls, v: Any) -> Any:
        return _coerce_enum(v, ComplianceVerdict)


def render_compliance_check(check: ComplianceCheck) -> str:
    """Render a ComplianceCheck to markdown."""
    parts = [f"**Overall Verdict**: {check.overall_verdict.value}", ""]
    for f in check.findings:
        parts.append(f"- **{f.check}** [{f.verdict.value}]: {f.detail}")
    parts.extend(["", f"**Summary**: {check.summary}"])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Risk Manager schemas
# ---------------------------------------------------------------------------

class RiskVerdict(str, Enum):
    APPROVE = "Approve"
    MODIFY = "Modify"
    REJECT = "Reject"


class RiskFinding(BaseModel):
    check: str = Field(description="Name of the risk check performed.")
    verdict: RiskVerdict = Field(description="One of: Approve, Modify, Reject")
    detail: str = Field(default="", description="Explanation of the finding.")

    @field_validator("verdict", mode="before")
    @classmethod
    def _coerce_verdict(cls, v: Any) -> Any:
        return _coerce_enum(v, RiskVerdict)


class RiskAssessment(BaseModel):
    overall_verdict: RiskVerdict = Field(
        description="Overall risk verdict. Reject if ANY finding is Reject.",
    )
    risk_score: int = Field(
        description="Risk score 0-100 (0 = no risk, 100 = maximum risk).",
        ge=0, le=100,
    )
    findings: list[RiskFinding] = Field(
        description="Individual risk check results.",
    )
    adjusted_position_size: Optional[str] = Field(
        default=None,
        description="Recommended position size adjustment, if any.",
    )
    adjusted_leverage: Optional[int] = Field(
        default=None,
        description="Recommended leverage adjustment (clamped to max_leverage).",
        ge=1,
    )

    @field_validator("overall_verdict", mode="before")
    @classmethod
    def _coerce_overall_verdict(cls, v: Any) -> Any:
        return _coerce_enum(v, RiskVerdict)
    summary: str = Field(
        description="One-paragraph risk assessment summary.",
    )


def render_risk_assessment(assessment: RiskAssessment) -> str:
    parts = [
        f"**Overall Risk Verdict**: {assessment.overall_verdict.value}",
        f"**Risk Score**: {assessment.risk_score}/100",
        "",
    ]
    for f in assessment.findings:
        parts.append(f"- **{f.check}** [{f.verdict.value}]: {f.detail}")
    if assessment.adjusted_position_size:
        parts.append(f"\n**Adjusted Position Size**: {assessment.adjusted_position_size}")
    if assessment.adjusted_leverage is not None:
        parts.append(f"**Adjusted Leverage**: {assessment.adjusted_leverage}x")
    parts.extend(["", f"**Summary**: {assessment.summary}"])
    return "\n".join(parts)
