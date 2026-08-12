from django.conf import settings
from django.db import models
from django.utils import timezone

from .services.encryption import encrypt_value, decrypt_value


class LinkedInAccount(models.Model):
    """
    One connected LinkedIn profile. Each account has ONE fixed topic
    (client-defined) — the AI only varies the angle/content within that
    topic day to day, it never changes the topic itself.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="linkedin_accounts",
        help_text="Only this user can see/manage this channel",
    )

    display_name = models.CharField(
        max_length=150, help_text="Internal label, e.g. 'Client A – Personal Profile'"
    )
    linkedin_urn = models.CharField(max_length=255, unique=True, null=True, blank=True, default=None)

    # Each account uses its OWN LinkedIn Developer App credentials
    # (client can enter these from the dashboard — no code/.env access needed).
    linkedin_client_id = models.CharField(max_length=255, blank=True)
    linkedin_client_secret_encrypted = models.TextField(blank=True)

    # Tokens are stored encrypted (Fernet). Never read/write the *_encrypted
    # fields directly — use the access_token / refresh_token properties.
    access_token_encrypted = models.TextField(blank=True)
    refresh_token_encrypted = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)

    topic = models.CharField(
        max_length=255,
        help_text="Fixed subject for this account, e.g. 'Digital Marketing'",
    )
    posting_times = models.JSONField(
        default=list,
        help_text="List of local times this account posts on an eligible day, e.g. ['09:00', '14:30']",
    )
    frequency_days = models.PositiveIntegerField(
        default=1,
        help_text="Post every N days: 1=every day, 2/3/4=every N days, 7=every week",
    )
    posting_window_minutes = models.PositiveIntegerField(
        default=30,
        help_text="Random jitter window added to each posting time to avoid a robotic fixed-second pattern",
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_name"]

    def __str__(self):
        return f"{self.display_name} ({self.topic})"

    # --- LinkedIn app credential helpers (per-account, encrypted secret) ---
    @property
    def linkedin_client_secret(self) -> str:
        return decrypt_value(self.linkedin_client_secret_encrypted)

    @linkedin_client_secret.setter
    def linkedin_client_secret(self, raw: str):
        self.linkedin_client_secret_encrypted = encrypt_value(raw)

    @property
    def has_linkedin_credentials(self) -> bool:
        return bool(self.linkedin_client_id and self.linkedin_client_secret_encrypted)

    # --- token helpers (encrypt on write, decrypt on read) ---
    @property
    def access_token(self) -> str:
        return decrypt_value(self.access_token_encrypted)

    @access_token.setter
    def access_token(self, raw: str):
        self.access_token_encrypted = encrypt_value(raw)

    @property
    def refresh_token(self) -> str:
        return decrypt_value(self.refresh_token_encrypted)

    @refresh_token.setter
    def refresh_token(self, raw: str):
        self.refresh_token_encrypted = encrypt_value(raw)

    @property
    def is_connected(self) -> bool:
        return bool(self.access_token_encrypted)

    @property
    def token_expired(self) -> bool:
        if not self.token_expires_at:
            return False
        return timezone.now() >= self.token_expires_at

    def most_recent_post_date(self):
        """Date of the most recent posted/in-progress post, or None if never posted."""
        last = self.posts.filter(
            status__in=[GeneratedPost.Status.POSTED, GeneratedPost.Status.GENERATING]
        ).order_by("-scheduled_for").first()
        return last.scheduled_for.date() if last else None


class GeneratedPost(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        GENERATING = "generating", "Generating"
        POSTED = "posted", "Posted"
        FAILED = "failed", "Failed"

    account = models.ForeignKey(
        LinkedInAccount, on_delete=models.CASCADE, related_name="posts"
    )
    slot_time = models.CharField(
        max_length=10, blank=True,
        help_text="Which configured posting_times slot ('HH:MM') triggered this, or 'manual' for Post now",
    )
    caption = models.TextField(blank=True)
    trend_context = models.TextField(
        blank=True, help_text="The trending angle the caption was based on"
    )
    image = models.ImageField(upload_to="generated_posts/%Y/%m/", null=True, blank=True)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    error_message = models.TextField(blank=True)

    linkedin_post_urn = models.CharField(max_length=255, blank=True)

    scheduled_for = models.DateTimeField()
    posted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-scheduled_for"]

    def __str__(self):
        return f"{self.account.display_name} — {self.scheduled_for:%Y-%m-%d} — {self.status}"