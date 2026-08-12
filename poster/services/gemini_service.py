"""
Generates a topic + trend relevant image using Gemini's image model.
"""
import logging

from django.conf import settings
from google import genai
from google.genai import types

logger = logging.getLogger("poster")

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set in .env")
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


IMAGE_PROMPT_TEMPLATE = """A clean, professional, modern illustration suitable
as a LinkedIn post banner image. Topic: {topic}. Visual angle: {trend_context}.
Style: minimal, corporate-friendly, no text or logos embedded in the image,
16:9 aspect ratio, high contrast, suitable for a business audience."""


def generate_topic_image(topic: str, trend_context: str = "") -> bytes:
    """Returns raw image bytes (PNG/JPEG) ready to upload to LinkedIn."""
    client = _get_client()
    prompt = IMAGE_PROMPT_TEMPLATE.format(topic=topic, trend_context=trend_context or topic)

    response = client.models.generate_content(
        model=settings.GEMINI_IMAGE_MODEL,
        contents=[prompt],
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )

    for part in response.candidates[0].content.parts:
        if getattr(part, "inline_data", None) is not None:
            return part.inline_data.data

    raise RuntimeError("Gemini did not return image data for this prompt")
