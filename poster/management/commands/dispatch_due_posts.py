"""
Run this every ~5 minutes via cron (or in a loop) to auto-post for any
account whose scheduled slot has arrived and hasn't posted for that slot
yet today — respecting each account's posting frequency (every N days).

Cron example (runs every 5 minutes):
    */5 * * * * cd /path/to/project && /path/to/venv/bin/python manage.py dispatch_due_posts

No Celery/Redis needed — this is a plain synchronous management command.
Due posts across DIFFERENT accounts run in parallel threads (each account
has its own DB rows and its own LinkedIn credentials/token, so there is no
shared state between them) — if several channels share the same posting
time, none of them delays or blocks another.
"""
import random
import threading
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from poster.models import LinkedInAccount, GeneratedPost
from poster.services.post_pipeline import generate_and_post


class Command(BaseCommand):
    help = "Posts for every active LinkedIn account whose schedule (frequency + time slots) is due today."

    def handle(self, *args, **options):
        now = timezone.localtime()
        today = now.date()
        threads = []

        for account in LinkedInAccount.objects.filter(is_active=True):
            if not account.is_connected or not account.posting_times:
                continue

            # --- frequency gate: is TODAY an eligible posting day at all? ---
            last_date = account.most_recent_post_date()
            if last_date is not None:
                days_since = (today - last_date).days
                if days_since < account.frequency_days:
                    continue  # not due yet under this account's frequency

            # --- per time-slot check (multiple posts/day supported) ---
            for slot in account.posting_times:
                try:
                    slot_hour, slot_minute = map(int, slot.split(":"))
                except (ValueError, AttributeError):
                    continue

                already_posted_this_slot_today = account.posts.filter(
                    scheduled_for__date=today,
                    slot_time=slot,
                    status__in=[GeneratedPost.Status.POSTED, GeneratedPost.Status.GENERATING],
                ).exists()
                if already_posted_this_slot_today:
                    continue

                jitter = random.randint(0, account.posting_window_minutes)
                base_dt = datetime.combine(today, datetime.min.time().replace(hour=slot_hour, minute=slot_minute))
                target_dt = base_dt + timedelta(minutes=jitter)
                if timezone.is_naive(target_dt):
                    target_dt = timezone.make_aware(target_dt, now.tzinfo)

                if now >= target_dt:
                    self.stdout.write(f"Posting for '{account.display_name}' ({account.topic}) — slot {slot}…")
                    t = threading.Thread(target=self._run_one, args=(account.id, slot), daemon=False)
                    t.start()
                    threads.append(t)

        # Wait for every launched post to finish before the command exits —
        # otherwise cron would kill mid-flight threads when the process ends.
        for t in threads:
            t.join()

        if not threads:
            self.stdout.write("No accounts due right now.")

    def _run_one(self, account_id: int, slot: str):
        post = generate_and_post(account_id, slot_time=slot)
        self.stdout.write(self.style.SUCCESS(
            f"  -> account {account_id} slot {slot}: {post.status}"
            + (f" ({post.error_message})" if post.error_message else "")
        ))