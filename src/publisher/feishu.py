"""Feishu webhook sender with HMAC signing and retry logic.

When ``config.feishu_webhook_secret`` is non-empty the body is signed per
Feishu's webhook signing spec: ``string_to_sign = "{timestamp}\n{secret}"``
hashed with HMAC-SHA256 and base64-encoded. The webhook receiver verifies
the signature before accepting the message.

When the secret is empty we fall back to the legacy unauthenticated path so
existing deployments aren't broken, but we log a one-shot WARNING so the
operator knows their webhook is unprotected.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Any

import httpx
from loguru import logger

from src.utils.redact import redact

_SIGNATURE_WARNED = False


def _sign_payload(secret: str, timestamp: int) -> str:
    """Compute Feishu webhook signature for ``timestamp`` using ``secret``."""
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def _maybe_sign_payload(body: dict, secret: str) -> dict:
    """Return a copy of ``body`` with ``timestamp`` + ``sign`` injected, or
    return ``body`` unchanged and log a one-time warning when no secret is set.
    """
    global _SIGNATURE_WARNED
    if not secret:
        if not _SIGNATURE_WARNED:
            logger.warning(
                "FEISHU_WEBHOOK_SECRET is empty — sending unsigned. "
                "Set it in .env and enable '签名校验' in Feishu bot settings."
            )
            _SIGNATURE_WARNED = True
        return body

    timestamp = int(time.time())
    signed = dict(body)
    signed["timestamp"] = str(timestamp)
    signed["sign"] = _sign_payload(secret, timestamp)
    return signed


def send_card(
    card: dict,
    config,
    max_retries: int = 3,
    timeout: float = 10.0,
) -> bool:
    """Send a card message to Feishu via webhook. Returns True on success.

    Only transient transport failures (network errors, 5xx) are retried; a
    ``code != 0`` application-level response fails immediately so we don't
    flood Feishu with a bad payload.
    """
    url = config.feishu_webhook_url
    if not url:
        logger.error("Feishu webhook URL is not configured")
        return False

    body = _maybe_sign_payload(card, config.feishu_webhook_secret)

    for attempt in range(max_retries):
        try:
            response = httpx.post(
                url,
                json=body,
                timeout=timeout,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            body_resp = response.json()
            if body_resp.get("code") == 0:
                logger.info("Feishu card sent successfully")
                return True
            # Application-level rejection: do NOT retry — same payload will
            # keep failing.
            logger.error(
                f"Feishu API rejected payload: code={body_resp.get('code')} "
                f"msg={body_resp.get('msg')}"
            )
            return False
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(
                redact(
                    f"Feishu send attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {wait}s..."
                )
            )
            if attempt < max_retries - 1:
                time.sleep(wait)

    logger.error(f"Failed to send Feishu card after {max_retries} attempts")
    return False