"""
LinkedIn OAuth (OpenID Connect) + posting via the Consumer tier
(w_member_social / Share on LinkedIn). This is per-account, personal-profile
posting — no Community Management API / partner approval needed.
"""
import logging
from datetime import timedelta

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("poster")

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
ASSETS_URL = "https://api.linkedin.com/v2/assets?action=registerUpload"
UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"

SCOPES = "openid profile w_member_social"


def build_authorization_url(state: str, client_id: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": settings.LINKEDIN_REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
    }
    query = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    return f"{AUTH_URL}?{query}"


def exchange_code_for_token(code: str, client_id: str, client_secret: str) -> dict:
    """Returns {access_token, expires_in, refresh_token (if granted)}."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.LINKEDIN_REDIRECT_URI,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    response = requests.post(TOKEN_URL, data=data, timeout=15)
    response.raise_for_status()
    return response.json()


def refresh_access_token(refresh_token: str, client_id: str, client_secret: str) -> dict:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    response = requests.post(TOKEN_URL, data=data, timeout=15)
    response.raise_for_status()
    return response.json()


class LinkedInClient:
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": "202401",
        }

    def get_user_urn(self) -> str | None:
        response = requests.get(USERINFO_URL, headers=self.headers, timeout=15)
        if response.status_code != 200:
            logger.error("LinkedIn userinfo failed: %s", response.text)
            return None
        return response.json().get("sub")

    def _register_image_upload(self, user_urn: str):
        payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": f"urn:li:person:{user_urn}",
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        }
        headers = {**self.headers, "Content-Type": "application/json"}
        response = requests.post(ASSETS_URL, headers=headers, json=payload, timeout=15)
        if response.status_code != 200:
            logger.error("LinkedIn registerUpload failed: %s", response.text)
            return None, None
        data = response.json()
        upload_url = data["value"]["uploadMechanism"][
            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
        ]["uploadUrl"]
        asset_urn = data["value"]["asset"]
        return upload_url, asset_urn

    def _upload_image_binary(self, upload_url: str, image_bytes: bytes) -> bool:
        response = requests.put(
            upload_url,
            headers={"Authorization": f"Bearer {self.access_token}"},
            data=image_bytes,
            timeout=30,
        )
        if response.status_code not in (200, 201):
            logger.error(
                "LinkedIn image upload failed: %s %s",
                response.status_code,
                response.text,
            )
            return False
        return True

    def publish_post(self, caption: str, image_bytes: bytes | None = None) -> tuple[bool, str]:
        """Returns (success, linkedin_post_urn_or_error_message)."""
        user_urn = self.get_user_urn()
        if not user_urn:
            return False, "Could not resolve LinkedIn user id (token invalid/expired?)"

        media_category = "NONE"
        media = []

        if image_bytes:
            upload_url, asset_urn = self._register_image_upload(user_urn)
            if not upload_url:
                return False, "Failed to register image upload with LinkedIn"
            if not self._upload_image_binary(upload_url, image_bytes):
                return False, "Failed to upload image bytes to LinkedIn"
            media_category = "IMAGE"
            media = [{"status": "READY", "media": asset_urn}]

        payload = {
            "author": f"urn:li:person:{user_urn}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": caption[:2999]},
                    "shareMediaCategory": media_category,
                    "media": media,
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        headers = {**self.headers, "Content-Type": "application/json"}
        response = requests.post(UGC_POSTS_URL, headers=headers, json=payload, timeout=20)
        if response.status_code == 201:
            post_urn = response.headers.get("x-restli-id", "")
            return True, post_urn
        logger.error("LinkedIn publish failed: %s %s", response.status_code, response.text)
        return False, f"LinkedIn API error {response.status_code}: {response.text[:300]}"


def ensure_fresh_token(account) -> str:
    """Refreshes the account's token if expired, saves it, returns a usable access token."""
    if account.token_expired and account.refresh_token:
        token_data = refresh_access_token(
            account.refresh_token, account.linkedin_client_id, account.linkedin_client_secret
        )
        account.access_token = token_data["access_token"]
        if "refresh_token" in token_data:
            account.refresh_token = token_data["refresh_token"]
        expires_in = token_data.get("expires_in", 3600)
        account.token_expires_at = timezone.now() + timedelta(seconds=expires_in)
        account.save(update_fields=[
            "access_token_encrypted", "refresh_token_encrypted", "token_expires_at"
        ])
    return account.access_token