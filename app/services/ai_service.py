"""
SahyogSutra AI Description Service.
Provides lazy-loaded Google GenAI integration with bounded input validation
and response parsing. Lazy-loading saves ~17MB RSS at application startup.
"""

import json
import logging
from typing import Dict, Any, Optional
from app.config import GOOGLE_API_KEY

logger = logging.getLogger(__name__)

# Cached single instance of GenAI client (lazy-loaded on first call)
_genai_client = None

def get_ai_client():
    """Lazily imports google-genai and creates a single persistent client instance."""
    global _genai_client
    if _genai_client is None:
        if not GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY is not configured.")
        from google import genai
        _genai_client = genai.Client(api_key=GOOGLE_API_KEY)
        logger.info("Initialized Google GenAI client.")
    return _genai_client


async def generate_campaign_descriptions(event_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Validates input parameters and requests 4 campaign descriptions
    with distinct tones using Gemini.
    """
    fields = ["eventname", "starttime", "endtime", "eventstartdate", "enddate", "location", "category"]
    # Bounded input sanitization
    sanitized_values = []
    for f in fields:
        raw_val = str(event_data.get(f) or "").strip()
        if raw_val:
            # Enforce max 120 characters per individual field
            sanitized_values.append([f, raw_val[:120]])

    if not sanitized_values:
        raise ValueError("Insufficient event details provided for AI generation.")

    content = f"""Generate a description based on following details in pure english language.
Context:
Details of event: {sanitized_values}
Generate total 4x descriptions (max 250 words each). Include hashtags. Reply strictly in JSON format without markdown fences:
{{"desc1": "Formal tone", "desc2": "Informal tone", "desc3": "Promotional tone", "desc4": "Entertaining/Fun tone"}}"""

    client = get_ai_client()

    # Blocking SDK call run in thread pool
    import asyncio
    loop = asyncio.get_running_loop()

    def _call_gemini():
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=content
        )
        return response.text

    output_text = await loop.run_in_executor(None, _call_gemini)

    # Clean markdown fences if model included them
    cleaned = output_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
        # Ensure all 4 expected keys exist
        for k in ["desc1", "desc2", "desc3", "desc4"]:
            if k not in parsed:
                parsed[k] = ""
        return parsed
    except json.JSONDecodeError:
        logger.warning("Gemini output was not valid JSON: %s", cleaned[:100])
        return {
            "desc1": cleaned,
            "desc2": "",
            "desc3": "",
            "desc4": ""
        }

