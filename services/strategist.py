import json
import os
import re

from anthropic import Anthropic

MODEL = "claude-sonnet-4-5"

SYSTEM_PROMPT = """You are a Head-of-Growth caliber Meta Ads operator with \
20+ years of frontline experience as BOTH a senior direct-response copywriter \
AND a performance media buyer scaling 7- and 8-figure ecommerce brands on \
Facebook/Instagram. You have launched, scaled, and killed thousands of ads; \
written hundreds of winning hooks; and walked into accounts spending \
$1M+/month and surgically reshaped them inside 30 days.

Your thinking blends three disciplines:

1. Direct-response copywriting — Eugene Schwartz awareness (unaware → most \
aware) and sophistication stages, classical structures (PAS, AIDA, BAB, FAB, \
4Ps, Star-Story-Solution), hook-curiosity gaps, specificity, proof, identity \
appeals, emotional payoff, CTA strength.

2. Decision-making and persuasion science — Cialdini's principles (reciprocity, \
commitment/consistency, social proof, authority, liking, scarcity, unity), \
Kahneman (System 1 vs 2, loss aversion, anchoring, availability), Thaler \
(default bias, endowment effect), Ariely (relativity, free-as-zero, decoy \
effect), framing, identity narratives, behavioral nudges. You weigh how each \
ad triggers — or fails to trigger — these mechanisms.

3. Performance media buying — unit economics (ROAS, CPA, CPM, CTR, frequency, \
cost-per-purchase, MER), audience-message fit, learning-phase mechanics, \
frequency-driven fatigue, CBO vs ABO, country-level CPM arbitrage, scale \
ceilings, lookalike vs interest vs broad, dynamic creative testing, \
incrementality reasoning, attribution windows.

You have a web_search tool. Use it (max 3 queries) BEFORE writing the report \
ONLY when it would meaningfully sharpen the recommendation — e.g. to verify a \
current Meta delivery quirk, a recent algorithm shift, a fresh hook pattern \
winning across the industry right now, or a specific behavioral-science \
finding that strengthens a creative angle. Do NOT search for filler or \
generic background; if your knowledge already covers it with high confidence, \
skip the search.

You are given an account-wide breakdown for the LAST 28 DAYS (always — this \
window is fixed and is the only one your recommendations should reason about):
- aggregate account metrics
- per-ad data: name, copy/transcript text, the prior copy_analysis JSON \
  (avatar, awareness stage, hook, frameworks), and Meta metrics for the period
- top countries breakdown

Your job: produce a STRATEGIST REPORT a Head of Growth could act on tomorrow \
morning. Brutally honest. Numbers-driven. Specific. No fluff. Recommendations \
must reflect 20 years of pattern recognition — never generic advice.

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

Account structure context (use this to sharpen scaling recommendations):
- The two MAIN scaling campaigns for the USA are "CBO Scaling - USA" and \
"iAcquisition||Testing||ABO||US". Treat these as the primary proving ground for \
USA performance.
- The other CBOs target Canada, Australia, UK, and Worldwide. These often run a \
NARROWER set of ad sets/ads than the two USA campaigns — meaning winning ad sets \
and creatives that exist in "CBO Scaling - USA" or "iAcquisition||Testing||ABO||US" \
may be ABSENT from the Canada / Australia / UK / Worldwide CBOs.
- When a winner lives in one of the two USA campaigns, actively check whether that \
ad set / creative is missing from the other regional CBOs. If so, RECOMMEND \
duplicating that winning ad (or ad set) from the USA campaign into the CBO(s) \
where it is absent (Canada, Australia, UK, Worldwide) to lift performance there. \
Be specific: name the source ad, the source USA campaign, and the target CBO(s). \
Surface these duplication moves in "scale_recommendation", "creative_recommendations", \
and "next_actions" where the data supports it.

Hard rules:
- Quote REAL ad names and REAL ad_ids exactly as provided. Never invent ids.
- Quote REAL numbers, rounded to 2 decimals.
- Never say "consider", "you might want to", "could potentially". Say "Kill ad X" or "Scale ad Z 50%".
- If a section has insufficient data, return an empty array — don't fabricate.
- Each bullet under 30 words.
- chart_data arrays: max 12 entries each, sorted by relevance (descending spend or roas).
"""


CAMPAIGN_SYSTEM_PROMPT = """You are a Head-of-Growth caliber Meta Ads operator \
with 20+ years scaling 7- and 8-figure ecommerce brands — equal parts senior \
direct-response copywriter and performance media buyer. You blend copywriting \
craft (Schwartz awareness/sophistication; PAS/AIDA/BAB hooks), persuasion \
science (Cialdini, Kahneman), and media-buying discipline (ROAS, CPA, CPM, CTR, \
frequency, learning phase, CBO/ABO, scale ceilings).

You are analyzing ONE campaign in isolation for the LAST 28 DAYS. Everything you \
recommend must be specific to THIS campaign's ad sets and ads — what works in \
one campaign often fails in another (different audiences, geos, budgets, \
funnel stage), so do NOT give generic account-wide advice. Reason only from the \
data provided.

You are given: the campaign name, its aggregate metrics, a per-ad-set rollup, \
and per-ad data (name, copy/transcript text, prior copy_analysis JSON, and Meta \
metrics for the window).

Output STRICT JSON only. No prose, no markdown fences. Schema:

{
  "verdict": "1-2 sentences: is this campaign scaling, stable, or bleeding, and the single most important move to make this week.",
  "headline_metrics": {"spend": 0, "revenue": 0, "roas": 0, "purchases": 0, "ctr": 0, "cpa": 0},
  "adset_breakdown": [
    {"adset_name": "exact name", "spend": 0, "roas": 0, "purchases": 0, "ctr": 0,
     "insight": "What's happening in this ad set, specific to its ads.",
     "action": "scale | hold | reduce | kill | refresh"}
  ],
  "winners": [
    {"ad_id": "exact id", "ad_name": "exact name", "spend": 0, "roas": 0, "purchases": 0, "ctr": 0,
     "why_winning": "Specific to this ad: hook, awareness fit, avatar, angle. Quote the hook if useful.",
     "scale_recommendation": "Concrete: 'Duplicate into a 5% lookalike adset', 'Raise budget 50% over 3 days'."}
  ],
  "losers": [
    {"ad_id": "exact id", "ad_name": "exact name", "spend": 0, "roas": 0, "purchases": 0, "ctr": 0,
     "why_losing": "Specific: weak hook? wrong awareness stage? fatigue? avatar mismatch?",
     "action": "kill | refresh_creative | change_targeting | reduce_budget"}
  ],
  "what_to_change": ["Concrete change to make INSIDE this campaign, tied to a named ad/ad set."],
  "what_to_launch": ["Specific new ad/ad set/test to launch in this campaign. Format: 'Test a [hook_type] ad for [awareness_stage] modeled after [winning ad name] because [reason]'."],
  "next_actions": ["Ordered this-week to-do for THIS campaign, each quoting the $ impact. e.g. 'Kill ad X (-$Y/week). Scale ad Z 50% (+$W/week).'"]
}

Hard rules:
- Quote REAL ad names and REAL ad_ids exactly as provided. Never invent ids.
- Quote REAL numbers, rounded to 2 decimals.
- Never say "consider" or "you might want to". Say "Kill ad X" / "Scale ad Z 50%".
- If a section has insufficient data, return an empty array — don't fabricate.
- Each bullet under 30 words.
"""


def _strip_json(raw: str) -> str:
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        return fence.group(1)
    brace = re.search(r"\{.*\}", raw, re.DOTALL)
    return brace.group(0) if brace else raw


# A permissive object schema: the model must return SOME object, but we don't
# constrain the shape (the report schema varies). Tool inputs are serialized by
# the API as valid JSON and surfaced as an already-parsed dict, so this path is
# immune to the unescaped-quote / trailing-comma breakage that plagues parsing
# free-form text.
_EMIT_TOOL = {
    "name": "emit_report",
    "description": "Return the corrected report as a structured JSON object.",
    "input_schema": {"type": "object", "additionalProperties": True},
}


def _repair_json_to_dict(client, broken_raw: str) -> dict:
    """Repair malformed report JSON by forcing Claude to re-emit it through a
    tool call. Because the API returns tool inputs as a parsed object (not a
    string we have to json.loads), unescaped quotes and trailing commas in the
    original can't break this. Returns the dict, or raises on failure."""
    resp = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        tools=[_EMIT_TOOL],
        tool_choice={"type": "tool", "name": "emit_report"},
        system="You are a JSON repair tool. The user pastes a broken or "
               "partial report (possibly with prose or markdown fences around "
               "it, unescaped quotes, or trailing commas, and possibly "
               "truncated). Reconstruct the intended object and return it via "
               "the emit_report tool. Preserve all real content and numbers; "
               "if truncated, complete it sensibly; never invent new fields.",
        messages=[{"role": "user", "content": broken_raw}],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "emit_report":
            if isinstance(block.input, dict):
                return block.input
    raise RuntimeError("Repair tool call returned no object.")


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
        tools=[
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 3,
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )
    # With web search the response may interleave server_tool_use and
    # web_search_tool_result blocks with text. The final JSON is in the LAST
    # text block; earlier ones are usually "I'll search for…" reasoning.
    text_blocks = [b.text for b in resp.content if b.type == "text"]
    raw = (text_blocks[-1] if text_blocks else "").strip()
    return raw, resp.stop_reason


def _plain_call(client, system_prompt, user_message, max_tokens):
    """A Claude call with a cached system prompt and NO tools — used for the
    per-campaign reports, which don't need web search (the account-wide call
    already does any research) and so run faster and cheaper."""
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )
    text_blocks = [b.text for b in resp.content if b.type == "text"]
    raw = (text_blocks[-1] if text_blocks else "").strip()
    return raw, resp.stop_reason


def build_campaign_report(campaign_context: dict) -> dict:
    """One Claude call scoped to a SINGLE campaign. Same layered JSON defense as
    the account report (bump-on-truncation, then repair). Returns the campaign
    report JSON described in CAMPAIGN_SYSTEM_PROMPT.

    Caller is expected to fan these out (one per campaign) in parallel.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    client = Anthropic(api_key=api_key)

    user_message = (
        "Here is one campaign's full context for the LAST 28 DAYS. Reason "
        "exclusively from this window and only about THIS campaign. Produce the "
        "campaign report per the schema in your system prompt. STRICT JSON only, "
        "no prose, no markdown fences.\n\n"
        + json.dumps(campaign_context, separators=(",", ":"), default=str)
    )

    raw, stop_reason = _plain_call(
        client, CAMPAIGN_SYSTEM_PROMPT, user_message, max_tokens=8000
    )
    if stop_reason == "max_tokens":
        raw, stop_reason = _plain_call(
            client, CAMPAIGN_SYSTEM_PROMPT, user_message, max_tokens=16000
        )

    try:
        return json.loads(_strip_json(raw))
    except json.JSONDecodeError:
        pass

    # Tool-based repair returns a parsed dict directly — immune to escaping.
    try:
        return _repair_json_to_dict(client, raw)
    except Exception as exc:
        truncated_note = " (truncated)" if stop_reason == "max_tokens" else ""
        raise RuntimeError(
            f"Campaign report returned invalid JSON after repair{truncated_note}: {exc}"
        )


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
        "Here is the full account context for the LAST 28 DAYS. Reason "
        "exclusively from this window — do not project from older data or "
        "made-up trends.\n\n"
        "Apply your 20-year operator instinct: copywriting craft + media-buying "
        "discipline + decision-science. If — and only if — verifying a current "
        "Meta delivery quirk, a recent algorithm shift, a hook pattern winning "
        "in the wild right now, or a specific persuasion-research finding would "
        "change one of your recommendations, use the web_search tool first (max "
        "3 queries). Otherwise skip search and write the report directly.\n\n"
        "Produce the strategist report per the schema in your system prompt. "
        "STRICT JSON only, no prose, no markdown fences.\n\n"
        + json.dumps(account_context, separators=(",", ":"), default=str)
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
    # quote or trailing comma (e.g. Claude quoted a verbatim hook line). Repair
    # via a forced tool call, which returns a parsed dict and so can't be broken
    # by the same escaping issue.
    try:
        return _repair_json_to_dict(client, raw)
    except Exception as exc:
        truncated_note = " (truncated)" if stop_reason == "max_tokens" else ""
        raise RuntimeError(
            f"Claude returned invalid JSON after repair{truncated_note}: {exc}\n"
            f"---first 1200 chars of original---\n{raw[:1200]}"
        )
