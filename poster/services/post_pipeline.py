"""
The full daily pipeline for one account:
trend-aware caption (OpenAI) -> image (OpenAI) -> publish (LinkedIn).
Plain function, no task queue — called directly by the management
command (for the daily cron) and by the "Post now" API endpoint.
"""
import logging

from django.core.files.base import ContentFile
from django.utils import timezone

from ..models import LinkedInAccount, GeneratedPost
from . import openai_service, linkedin_client

logger = logging.getLogger("poster")


def generate_and_post(account_id: int, slot_time: str = "manual") -> GeneratedPost:
    account = LinkedInAccount.objects.get(id=account_id, is_active=True)

    post = GeneratedPost.objects.create(
        account=account,
        slot_time=slot_time,
        status=GeneratedPost.Status.GENERATING,
        scheduled_for=timezone.now(),
    )

    try:
        # 1. Trend-aware caption (OpenAI web_search + writing, one call)
        caption, trend_context = openai_service.generate_trend_aware_caption(account.topic)
        post.caption = caption
        post.trend_context = trend_context
        post.save(update_fields=["caption", "trend_context"])

        # 2. Image (OpenAI — same API key as the caption, no separate image
        # provider key needed). If generation fails for any reason, the
        # post still goes out as text-only rather than being lost entirely.
        image_bytes = None
        try:
            image_bytes = openai_service.generate_topic_image(account.topic, trend_context)
            post.image.save(
                f"account_{account.id}_{post.id}.png",
                ContentFile(image_bytes),
                save=True,
            )
        except Exception:
            logger.exception(
                "Image generation failed for account %s — posting text-only", account_id
            )
            image_bytes = None

        # 3. Publish to LinkedIn
        access_token = linkedin_client.ensure_fresh_token(account)
        client = linkedin_client.LinkedInClient(access_token)
        success, result = client.publish_post(caption, image_bytes)

        if success:
            post.status = GeneratedPost.Status.POSTED
            post.linkedin_post_urn = result
            post.posted_at = timezone.now()
        else:
            post.status = GeneratedPost.Status.FAILED
            post.error_message = result

        post.save()

    except Exception as exc:
        logger.exception("Post generation failed for account %s", account_id)
        post.status = GeneratedPost.Status.FAILED
        post.error_message = str(exc)[:2000]
        post.save(update_fields=["status", "error_message"])

    return post