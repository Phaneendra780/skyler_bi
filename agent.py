"""
Gemini-powered BI agent for Skylark Drones.
Uses the google-genai SDK with tool calling to query Monday.com dynamically.
"""

import json
import re
import google.genai as genai
from google.genai import types
from monday_client import fetch_deals, fetch_work_orders, fetch_cross_board
from config import GEMINI_API_KEY, MODEL_NAME, SYSTEM_INSTRUCTION

# ── Client ────────────────────────────────────────────────────────────────────
_client = genai.Client(api_key=GEMINI_API_KEY)

# ── Generation config ─────────────────────────────────────────────────────────
# NOTE: Do NOT set response_mime_type when using tool calling —
# it conflicts with function call responses in the new SDK.
_config = types.GenerateContentConfig(
    system_instruction=SYSTEM_INSTRUCTION,
    temperature=0,
    tools=[fetch_deals, fetch_work_orders, fetch_cross_board],
)


def create_chat():
    """Create a new stateful chat session."""
    return _client.chats.create(
        model=MODEL_NAME,
        config=_config,
    )


def _extract_json(text: str) -> dict | None:
    """Try to extract a JSON object from text, handling markdown fences."""
    if not text:
        return None

    # Strip markdown code fences
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[start:end]).strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in text
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


def ask(chat, message: str) -> dict:
    """
    Send a message to the agent and return a structured response dict.

    Returns:
        {
            "answer": str,        # markdown-formatted text answer
            "chart": dict | None  # chart spec for Plotly, or None
        }
    """
    try:
        response = chat.send_message(message)

        # Get text from response
        text = ""
        if hasattr(response, "text") and response.text:
            text = response.text
        elif hasattr(response, "candidates") and response.candidates:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    text += part.text

        if not text.strip():
            return {
                "answer": "I received the data from Monday.com but had trouble formatting the response. Please try asking again.",
                "chart": None,
            }

        # Try to parse as JSON
        parsed = _extract_json(text)
        if parsed and "answer" in parsed:
            return parsed

        # If it's valid text but not our JSON format, wrap it
        return {"answer": text, "chart": None}

    except Exception as e:
        err = str(e)
        # Rate limit — tell the user clearly
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            return {
                "answer": "⚠️ **Rate limit hit.** Please wait 30 seconds and try again.\n\nThe free tier allows 250,000 tokens per minute. Your query is working — just needs a brief pause.",
                "chart": None,
            }
        return {
            "answer": f"⚠️ Error while processing your request: {err[:200]}\n\nPlease try again.",
            "chart": None,
        }
