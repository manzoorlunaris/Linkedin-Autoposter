"""
OpenAI service: (1) trend-aware caption via the Responses API + web_search
tool, and (2) topic-relevant image generation via the Images API — both use
the same OPENAI_API_KEY, no separate image-provider key needed.
"""
import base64
import logging

from django.conf import settings
from openai import OpenAI

logger = logging.getLogger("poster")

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set in .env")
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


PROMPT_TEMPLATE = """You are writing a LinkedIn post for a professional account
focused on the topic: "{topic}".

First, search for what is currently trending or being actively discussed
related to "{topic}" in the last 2-3 days (news, reports, notable opinions,
product launches, industry data).

Then write ONE original LinkedIn post that:
- References that current trend/angle naturally (don't just restate a headline)
- Adds a genuine insight, opinion, or practical takeaway
- Stays under 200 words
- Ends with 2-3 relevant hashtags
- Uses a professional but human tone, no excessive emojis

Also produce a short (max 20 words) plain-text summary of the trend/angle you
based the post on.

Respond in EXACTLY this format, nothing else:
TREND: <short summary of the trend/angle>
POST: <the final LinkedIn post text>
"""


def generate_trend_aware_caption(topic: str) -> tuple[str, str]:
    """Returns (caption, trend_context)."""
    client = _get_client()
    response = client.responses.create(
        model=settings.OPENAI_TEXT_MODEL,
        tools=[{"type": "web_search"}],
        input=PROMPT_TEMPLATE.format(topic=topic),
    )
    text = response.output_text.strip()

    trend_context = ""
    caption = text
    if "TREND:" in text and "POST:" in text:
        try:
            trend_part = text.split("TREND:", 1)[1].split("POST:", 1)[0].strip()
            post_part = text.split("POST:", 1)[1].strip()
            trend_context = trend_part
            caption = post_part
        except IndexError:
            logger.warning("Could not parse TREND/POST format, using raw output")

    return caption, trend_context


IMAGE_PROMPT_TEMPLATE = """A clean, professional, modern illustration suitable
as a LinkedIn post banner image. Topic: {topic}. Visual angle: {trend_context}.
Style: minimal, corporate-friendly, no embedded text or logos, high contrast,
suitable for a business audience on social media."""


def generate_topic_image(topic: str, trend_context: str = "") -> bytes:
    """Returns raw PNG image bytes, ready to upload to LinkedIn."""
    client = _get_client()
    prompt = IMAGE_PROMPT_TEMPLATE.format(topic=topic, trend_context=trend_context or topic)

    response = client.images.generate(
        model=settings.OPENAI_IMAGE_MODEL,
        prompt=prompt,
        size="1536x1024",  # landscape — fits a LinkedIn feed image well
        quality="medium",
        n=1,
    )

    b64_data = response.data[0].b64_json
    if not b64_data:
        raise RuntimeError("OpenAI did not return image data for this prompt")
    return base64.b64decode(b64_data)