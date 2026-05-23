import json
import os
import re

from anthropic import Anthropic

MODEL = "claude-sonnet-4-5"

SYSTEM_PROMPT = """You are a senior direct-response copywriting strategist with 20+ \
years auditing winning ads on Meta, TikTok, YouTube and email. You think in \
Eugene Schwartz's frameworks (5 awareness stages, 5 sophistication stages), \
classic structures (PAS, AIDA, BAB, FAB, 4 Ps, Star-Story-Solution), and \
modern direct-response heuristics (hook-curiosity gap, specificity, proof, \
emotional payoff, CTA strength).

You will be given the spoken or written text of a single ad creative. Your job \
is to deliver a tight, brutally honest copywriting audit a creative strategist \
would actually use to decide what to test next.

Output STRICT JSON only, matching this exact schema. No prose outside the JSON. \
No markdown fences.

{
  "avatar": {
    "demographic": "1 sentence",
    "pain_points": ["short bullet", "..."],
    "desires": ["short bullet", "..."],
    "objections": ["short bullet", "..."],
    "emotional_state": "1 sentence"
  },
  "awareness_level": {
    "stage": "unaware | problem_aware | solution_aware | product_aware | most_aware",
    "reasoning": "1-2 sentences explaining the call"
  },
  "sophistication_level": {
    "stage": "1 | 2 | 3 | 4 | 5",
    "reasoning": "1-2 sentences"
  },
  "hook": {
    "opening_line": "the literal first hook line, copied verbatim",
    "type": "curiosity | contrarian | story | question | stat | callout | promise | warning | other",
    "strength": "weak | average | strong | exceptional",
    "reasoning": "1 sentence"
  },
  "angle": "the single core promise the ad is making, in 1 sentence",
  "frameworks_detected": ["PAS", "AIDA", "BAB", "FAB", "4Ps", "..."],
  "tone": "1-2 words (e.g. urgent, friendly, authoritative, emotional, deadpan)",
  "style": "1-3 words (e.g. story-driven, direct-response, educational, testimonial)",
  "strengths": ["short bullet", "..."],
  "weaknesses": ["short bullet", "..."],
  "test_suggestions": [
    "specific A/B test idea, ready to run",
    "..."
  ],
  "overall_score": {
    "value": 0-10,
    "reasoning": "1-2 sentences justifying the score"
  }
}

Rules:
- Keep every bullet under 15 words. Be specific, not generic.
- Quote phrases from the actual ad when possible (e.g. "uses the phrase 'in just 7 days'").
- If the ad text is too short or empty, return null for ambiguous fields rather than guessing.
- Never invent product features the text doesn't mention.
- Awareness and sophistication must use the exact enum values shown.
"""


def _strip_json(raw: str) -> str:
    """Pull the first JSON object out of the model's response, tolerating any
    accidental prose or code fences around it."""
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        return fence.group(1)
    brace = re.search(r"\{.*\}", raw, re.DOTALL)
    return brace.group(0) if brace else raw


def analyze_copy(text: str, ad_context: dict | None = None) -> dict:
    """Run a copywriting audit on `text`. Returns the parsed JSON dict from
    Claude. Raises on API/parse failure so the caller can mark the job failed.

    `ad_context` may include `name`, `campaign_name`, `creative_type`,
    `roas` — used to give the model a tiny bit of framing without changing
    the audit logic.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    client = Anthropic(api_key=api_key)

    context_lines = []
    if ad_context:
        if ad_context.get("name"):
            context_lines.append(f"Ad name: {ad_context['name']}")
        if ad_context.get("campaign_name"):
            context_lines.append(f"Campaign: {ad_context['campaign_name']}")
        if ad_context.get("creative_type"):
            context_lines.append(f"Format: {ad_context['creative_type']}")
        if ad_context.get("roas") is not None:
            context_lines.append(f"Current ROAS: {ad_context['roas']}")
    context_block = ("\n".join(context_lines) + "\n\n") if context_lines else ""

    user_message = (
        f"{context_block}Ad text (transcript or copy):\n\"\"\"\n{text.strip()}\n\"\"\""
    )

    resp = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )

    raw = "".join(block.text for block in resp.content if block.type == "text").strip()
    try:
        return json.loads(_strip_json(raw))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Claude returned invalid JSON: {exc}\n---\n{raw[:500]}")
