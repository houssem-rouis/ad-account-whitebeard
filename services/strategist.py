import json
import os
import re

from anthropic import Anthropic

MODEL = "claude-sonnet-4-5"

SYSTEM_PROMPT = """You are a Head-of-Growth caliber Meta Ads strategist AND a \
senior direct-response copywriter with 15+ years scaling 7- and 8-figure \
ecommerce brands on Facebook/Instagram. You think in Eugene Schwartz \
awareness/sophistication stages, direct-response frameworks (PAS, AIDA, BAB), \
unit economics (ROAS, CPA, CPM, CTR, frequency, cost-per-purchase), and \
audience-message fit.

You are given an account-wide breakdown for the LAST 28 DAYS:
- aggregate account metrics
- per-ad data: name, copy/transcript text, the prior copy_analysis JSON \
  (avatar, awareness stage, hook, frameworks), and Meta metrics for the period
- top countries breakdown

Your job: produce a STRATEGIST REPORT a Head of Growth could act on tomorrow \
morning. Brutally honest. Numbers-driven. Specific. No fluff.

Output STRICT JSON only. No prose around it. No markdown fences. Schema:

{
  "executive_summary": "3-5 sentences. State the headline performance number, the single biggest opportunity, and the single biggest waste.",
  "headline_takeaways": [
    "Each item = one sentence, ALWAYS quotes a real number from the data (e.g. '38% of spend goes to ads with ROAS < 1.0x')."
  ],
  "categories": {
    "scaling_winners": {"count": 0, "spend_share_pct": 0, "criteria": "ROAS >= 2x AND purchases >= 5"},
    "stable_performers": {"count": 0, "spend_share_pct": 0, "criteria": "ROAS 1.0–1.99x"},
    "money_drains": {"count": 0, "spend_share_pct": 0, "criteria": "ROAS < 1.0x with > $50 spend"},
    "no_data": {"count": 0, "spend_share_pct": 0, "criteria": "< 200 impressions"}
  },
  "winners": [
    {
      "ad_id": "exact id from data",
      "ad_name": "exact name",
      "spend": 0, "roas": 0, "purchases": 0, "ctr": 0,
      "why_winning": "Specific to this ad: hook type, awareness alignment, avatar fit, creative angle. Quote the hook verbatim if helpful.",
      "scale_recommendation": "Concrete action: 'Duplicate to a new adset with 5% lookalike', 'Increase budget 50% over 3 days', 'Leave running, monitor frequency'."
    }
  ],
  "losers": [
    {
      "ad_id": "exact id",
      "ad_name": "exact name",
      "spend": 0, "roas": 0, "purchases": 0, "ctr": 0,
      "why_losing": "Specific: wrong awareness stage for the offer? weak hook? avatar mismatch with country/demo? fatigue? Reference the copy_analysis.",
      "action": "kill | refresh_creative | change_targeting | reduce_budget"
    }
  ],
  "wasted_spend": {
    "amount_usd": 0,
    "pct_of_total": 0,
    "explanation": "Sum of spend on ROAS<1 ads with meaningful traffic. Name names."
  },
  "patterns_by_awareness": [
    {
      "stage": "unaware | problem_aware | solution_aware | product_aware | most_aware",
      "ads_count": 0,
      "total_spend": 0,
      "total_purchases": 0,
      "roas": 0,
      "ctr": 0,
      "insight": "Why this awareness segment is/isn't working. Tie to specific ads."
    }
  ],
  "patterns_by_country": [
    {
      "country": "US",
      "spend": 0,
      "purchases": 0,
      "roas": 0,
      "ctr": 0,
      "insight": "What's specific to this country."
    }
  ],
  "hook_patterns": {
    "winning_hook_types": ["curiosity", "stat", "story", "..."],
    "losing_hook_types": ["..."],
    "winning_examples": ["Quote the literal hook line from a winning ad and explain in 1 sentence why it works."],
    "losing_examples": ["Quote the literal hook line from a losing ad and explain why it fails."]
  },
  "avatar_alignment": "Does the avatar described in the copy_analysis match the country/demo who actually buys? 1-3 sentences.",
  "creative_recommendations": [
    "Specific next ad to test. Format: 'Test a [hook_type] ad targeting [awareness_stage] with [angle]. Model after [winning ad name] because [reason].'"
  ],
  "next_actions": [
    "Concrete this-week to-do, ordered by ROI. e.g. 'Kill ad X (-$Y/week waste). Scale ad Z by 50% (+$W/week opportunity).'"
  ],
  "chart_data": {
    "spend_vs_roas": [
      {"ad_name": "short label", "spend": 0, "roas": 0, "purchases": 0}
    ],
    "awareness_performance": [
      {"stage": "problem_aware", "roas": 0, "spend": 0, "purchases": 0}
    ],
    "country_purchases": [
      {"country": "US", "purchases": 0, "roas": 0, "spend": 0}
    ]
  }
}

Hard rules:
- Quote REAL ad names and REAL ad_ids exactly as provided. Never invent ids.
- Quote REAL numbers, rounded to 2 decimals.
- Never say "consider", "you might want to", "could potentially". Say "Kill ad X" or "Scale ad Z 50%".
- If a section has insufficient data, return an empty array — don't fabricate.
- Each bullet under 30 words.
- chart_data arrays: max 12 entries each, sorted by relevance (descending spend or roas).
"""


def _strip_json(raw: str) -> str:
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        return fence.group(1)
    brace = re.search(r"\{.*\}", raw, re.DOTALL)
    return brace.group(0) if brace else raw


def _repair_json(client, broken_raw: str) -> str:
    """Ask Claude to fix the broken JSON and re-emit only the corrected
    object. Used as a one-shot fallback when the strategist call returns
    text that fails to parse (usually truncation or an unescaped quote)."""
    repair = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system="You are a JSON repair tool. The user pastes broken JSON. You "
               "return ONLY the corrected JSON object — no prose, no fences. "
               "If the JSON is truncated, complete it so it parses. Preserve "
               "all content; never invent fields.",
        messages=[{"role": "user", "content": broken_raw}],
    )
    return "".join(b.text for b in repair.content if b.type == "text").strip()


def _strategist_call(client, user_message, max_tokens):
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )
    raw = "".join(b.text for b in resp.content if b.type == "text").strip()
    return raw, resp.stop_reason


def build_strategist_report(account_context: dict) -> dict:
    """Single Claude call that takes the full account context (per-ad data +
    aggregates + country rollups) and returns the strategist JSON report.

    Layered defense:
    1. First call at 16K output tokens.
    2. If Claude stopped because it hit max_tokens, retry at 32K — repair
       can't recover from genuine truncation, only from malformed JSON.
    3. Parse the JSON.
    4. If parsing still fails, ask Claude to repair the JSON in a separate
       call (handles unescaped quotes, trailing commas, etc.).
    5. If repair also fails, raise with both attempts in the message so we
       can see what happened.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    client = Anthropic(api_key=api_key)

    user_message = (
        "Here is the full account context for analysis. "
        "Produce the strategist report per the schema in your system prompt.\n\n"
        + json.dumps(account_context, indent=2, default=str)
    )

    raw, stop_reason = _strategist_call(client, user_message, max_tokens=16000)
    if stop_reason == "max_tokens":
        # The first response was cut off mid-JSON. Bump and retry — repair
        # can't reconstruct content Claude never wrote.
        raw, stop_reason = _strategist_call(client, user_message, max_tokens=32000)

    try:
        return json.loads(_strip_json(raw))
    except json.JSONDecodeError:
        pass

    # Parsing failed but the message wasn't truncated — likely an unescaped
    # quote or trailing comma. Ask Claude to fix the JSON.
    repaired = _repair_json(client, raw)
    try:
        return json.loads(_strip_json(repaired))
    except json.JSONDecodeError as exc:
        truncated_note = " (truncated)" if stop_reason == "max_tokens" else ""
        raise RuntimeError(
            f"Claude returned invalid JSON after repair{truncated_note}: {exc}\n"
            f"---first 800 chars of original---\n{raw[:800]}\n"
            f"---first 800 chars of repair---\n{repaired[:800]}"
        )
