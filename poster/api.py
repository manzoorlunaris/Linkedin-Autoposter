import logging
import re
import threading
import urllib.parse
import uuid
from datetime import timedelta
from typing import List, Optional

import requests as http_requests
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError
from ninja.security import django_auth

from .models import LinkedInAccount, GeneratedPost
from .services import linkedin_client
from .services.post_pipeline import generate_and_post

logger = logging.getLogger("poster")

# csrf=True because this API is authenticated via the Django session cookie
# (django_auth below) — CSRF protection is required for cookie-based auth.
api = NinjaAPI(title="LinkedIn Auto-Poster API", urls_namespace="poster_api", csrf=True)

# In-memory OAuth state store: state -> (account_id, user_id)
_oauth_state_map: dict[str, tuple[int, int]] = {}

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
VALID_FREQUENCIES = {1, 2, 3, 4, 5, 6, 7}


def _owned_account_or_404(request: HttpRequest, account_id: int) -> LinkedInAccount:
    """Only ever returns an account belonging to the logged-in user."""
    return get_object_or_404(LinkedInAccount, id=account_id, owner=request.auth)


def _validate_posting_times(times: List[str]) -> List[str]:
    if not times:
        raise HttpError(400, "Add at least one posting time")
    cleaned = []
    for t in times:
        if not TIME_RE.match(t):
            raise HttpError(400, f"'{t}' isn't a valid time (expected HH:MM)")
        cleaned.append(t)
    if len(set(cleaned)) != len(cleaned):
        raise HttpError(400, "Posting times must be unique — remove the duplicate")
    return sorted(cleaned)


def _validate_frequency(days: int) -> int:
    if days not in VALID_FREQUENCIES:
        raise HttpError(400, "Frequency must be every 1–7 days")
    return days


# ---------- Schemas ----------

class AccountIn(Schema):
    display_name: str
    topic: str
    posting_times: List[str]  # ["HH:MM", ...]
    frequency_days: int = 1
    posting_window_minutes: int = 30


class AccountUpdateIn(Schema):
    display_name: Optional[str] = None
    topic: Optional[str] = None
    posting_times: Optional[List[str]] = None
    frequency_days: Optional[int] = None
    posting_window_minutes: Optional[int] = None
    is_active: Optional[bool] = None


class LinkedInCredentialsIn(Schema):
    client_id: str
    client_secret: str


class AccountOut(Schema):
    id: int
    display_name: str
    topic: str
    posting_times: List[str]
    frequency_days: int
    posting_window_minutes: int
    is_active: bool
    is_connected: bool
    has_linkedin_credentials: bool
    linkedin_urn: str


class PostOut(Schema):
    id: int
    account_id: int
    slot_time: str
    caption: str
    trend_context: str
    status: str
    error_message: str
    image_url: Optional[str] = None
    scheduled_for: str
    posted_at: Optional[str] = None


def _account_to_out(a: LinkedInAccount) -> dict:
    return {
        "id": a.id,
        "display_name": a.display_name,
        "topic": a.topic,
        "posting_times": a.posting_times or [],
        "frequency_days": a.frequency_days,
        "posting_window_minutes": a.posting_window_minutes,
        "is_active": a.is_active,
        "is_connected": a.is_connected,
        "has_linkedin_credentials": a.has_linkedin_credentials,
        "linkedin_urn": a.linkedin_urn or "",
    }


def _post_to_out(p: GeneratedPost) -> dict:
    return {
        "id": p.id,
        "account_id": p.account_id,
        "slot_time": p.slot_time,
        "caption": p.caption,
        "trend_context": p.trend_context,
        "status": p.status,
        "error_message": p.error_message,
        "image_url": p.image.url if p.image else None,
        "scheduled_for": p.scheduled_for.isoformat(),
        "posted_at": p.posted_at.isoformat() if p.posted_at else None,
    }


# ---------- Accounts (every endpoint below requires login, and only ever
# touches accounts owned by the logged-in user) ----------

@api.get("/accounts", response=list[AccountOut], auth=django_auth)
def list_accounts(request: HttpRequest):
    return [_account_to_out(a) for a in LinkedInAccount.objects.filter(owner=request.auth)]


@api.post("/accounts", response=AccountOut, auth=django_auth)
def create_account(request: HttpRequest, payload: AccountIn):
    posting_times = _validate_posting_times(payload.posting_times)
    frequency_days = _validate_frequency(payload.frequency_days)
    account = LinkedInAccount.objects.create(
        owner=request.auth,
        display_name=payload.display_name,
        topic=payload.topic,
        posting_times=posting_times,
        frequency_days=frequency_days,
        posting_window_minutes=payload.posting_window_minutes,
    )
    account.refresh_from_db()
    return _account_to_out(account)


@api.patch("/accounts/{account_id}", response=AccountOut, auth=django_auth)
def update_account(request: HttpRequest, account_id: int, payload: AccountUpdateIn):
    account = _owned_account_or_404(request, account_id)
    data = payload.dict(exclude_unset=True)
    if "posting_times" in data:
        data["posting_times"] = _validate_posting_times(data["posting_times"])
    if "frequency_days" in data:
        data["frequency_days"] = _validate_frequency(data["frequency_days"])
    for field, value in data.items():
        setattr(account, field, value)
    account.save()
    account.refresh_from_db()
    return _account_to_out(account)


@api.delete("/accounts/{account_id}", auth=django_auth)
def delete_account(request: HttpRequest, account_id: int):
    account = _owned_account_or_404(request, account_id)
    account.delete()
    return {"deleted": True}


# ---------- LinkedIn OAuth connect flow ----------

@api.post("/accounts/{account_id}/linkedin-credentials", auth=django_auth)
def save_linkedin_credentials(request: HttpRequest, account_id: int, payload: LinkedInCredentialsIn):
    """
    Saves this account's own LinkedIn Developer App Client ID/Secret
    (entered from the dashboard). Called right before redirecting to
    LinkedIn's authorization page.
    """
    account = _owned_account_or_404(request, account_id)
    client_id = payload.client_id.strip()
    client_secret = payload.client_secret.strip()

    if not client_id or not client_secret:
        raise HttpError(400, "Client ID and Client Secret are both required")

    account.linkedin_client_id = client_id
    account.linkedin_client_secret = client_secret
    account.save(update_fields=["linkedin_client_id", "linkedin_client_secret_encrypted"])
    return {"saved": True}


@api.get("/linkedin/connect/{account_id}", auth=django_auth)
def linkedin_connect(request: HttpRequest, account_id: int):
    account = _owned_account_or_404(request, account_id)

    if not account.has_linkedin_credentials:
        raise HttpError(400, "Save this account's LinkedIn Client ID/Secret first")

    state = uuid.uuid4().hex
    _oauth_state_map[state] = (account_id, request.auth.id)
    auth_url = linkedin_client.build_authorization_url(state, account.linkedin_client_id)
    return HttpResponseRedirect(auth_url)


def _redirect_with_status(account_id: int, connected: bool, message: str = "") -> HttpResponseRedirect:
    params = {"channel": account_id}
    if connected:
        params["connected"] = 1
    else:
        params["linkedin_error"] = 1
        params["msg"] = message[:200]
    return HttpResponseRedirect(f"/?{urllib.parse.urlencode(params)}")


@api.get("/linkedin/callback", auth=None)
def linkedin_callback(request: HttpRequest, code: str = None, state: str = None, error: str = None):
    # No login check here on purpose: LinkedIn's redirect back to this URL
    # is a fresh top-level browser navigation, and its session cookie isn't
    # guaranteed to be sent (e.g. if the dashboard was opened on a slightly
    # different host/port than LINKEDIN_REDIRECT_URI, like 127.0.0.1 vs
    # localhost — those are different cookie domains to the browser).
    # Security instead comes entirely from `state`: it's a random token WE
    # generated in linkedin_connect (which IS login-protected) and mapped
    # to exactly one account + owner — nobody can forge a valid one.
    entry = _oauth_state_map.pop(state, None) if state else None

    if error:
        return _redirect_with_status(0, False, f"LinkedIn authorization failed: {error}")

    if not entry:
        return _redirect_with_status(0, False, "Invalid or expired connection attempt — try again")

    account_id, owner_id = entry
    account = get_object_or_404(LinkedInAccount, id=account_id, owner_id=owner_id)

    try:
        token_data = linkedin_client.exchange_code_for_token(
            code, account.linkedin_client_id, account.linkedin_client_secret
        )
    except http_requests.RequestException as exc:
        logger.error("LinkedIn token exchange failed for account %s: %s", account_id, exc)
        return _redirect_with_status(
            account_id, False, "Invalid Client ID/Secret, or redirect URI not authorized on your LinkedIn app"
        )

    account.access_token = token_data["access_token"]
    if "refresh_token" in token_data:
        account.refresh_token = token_data["refresh_token"]
    expires_in = token_data.get("expires_in", 3600)
    account.token_expires_at = timezone.now() + timedelta(seconds=expires_in)
    account.save()

    client = linkedin_client.LinkedInClient(account.access_token)
    urn = client.get_user_urn()
    if not urn:
        return _redirect_with_status(account_id, False, "Connected but could not verify the LinkedIn profile")

    account.linkedin_urn = urn
    account.save(update_fields=["linkedin_urn"])

    return _redirect_with_status(account_id, True)


# ---------- Posts ----------

@api.get("/accounts/{account_id}/posts", response=list[PostOut], auth=django_auth)
def list_posts(request: HttpRequest, account_id: int):
    account = _owned_account_or_404(request, account_id)
    return [_post_to_out(p) for p in account.posts.all()[:30]]


@api.post("/accounts/{account_id}/post-now", auth=django_auth)
def trigger_post_now(request: HttpRequest, account_id: int):
    account = _owned_account_or_404(request, account_id)
    if not account.is_connected:
        raise HttpError(400, "Connect this account to LinkedIn first")
    # Runs in a background thread so the request returns immediately —
    # the caption/image/publish pipeline can take 10-20+ seconds.
    threading.Thread(target=generate_and_post, args=(account.id,), daemon=True).start()
    return {"queued": True}