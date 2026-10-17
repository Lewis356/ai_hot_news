"""Feishu webhook sender with HMAC signing and retry logic.

When ``config.feishu_webhook_secret`` is non-empty the body is signed per
Feishu's webhook signing spec: ``string_to_sign = "{timestamp}\n{secret}"``
hashed with HMAC-SHA256 and base64-encoded. Otherwise the webhook receives
the original unsigned body.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from enum import Enum

import httpx
from loguru import logger

from src.utils.redact import redact

_MAX_RETRY_WAIT_SECONDS = 30.0

class PublishStatus(str, Enum):
    """Observable outcome of a Feishu publish attempt."""

    SENT = "sent"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PublishResult:
    status: PublishStatus
    error: str | None = None


def _retry_wait(attempt: int, response: httpx.Response | None = None) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return min(max(float(retry_after), 0.0), _MAX_RETRY_WAIT_SECONDS)
            except ValueError:
                pass
    return min(float(2**attempt), _MAX_RETRY_WAIT_SECONDS)


def _sign_payload(secret: str, timestamp: int) -> str:
    """Compute Feishu webhook signature for ``timestamp`` using ``secret``."""
    signing_key = f"{timestamp}\n{secret}".encode()
    digest = hmac.new(
        signing_key,
        b"",
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def _signed_body(body: dict, secret: str) -> dict:
    """Return a signed copy of ``body``."""
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
) -> PublishResult:
    """Send a card message to Feishu and return an explicit delivery outcome.

    Only transient transport failures (network errors, 5xx) are retried; a
    ``code != 0`` application-level response fails immediately so we don't
    flood Feishu with a bad payload.
    """
    url = config.feishu_webhook_url
    if not url:
        error = "Feishu webhook URL is not configured"
        logger.error(error)
        return PublishResult(PublishStatus.FAILED, error)

    body = (
        _signed_body(card, config.feishu_webhook_secret)
        if config.feishu_webhook_secret
        else card
    )

    for attempt in range(max_retries):
        try:
            response = httpx.post(
                url,
                json=body,
                timeout=timeout,
                headers={"Content-Type": "application/json"},
            )
            if 400 <= response.status_code < 500 and response.status_code != 429:
                error = f"Feishu webhook returned HTTP {response.status_code}"
                logger.error(error)
                return PublishResult(PublishStatus.FAILED, error)
            response.raise_for_status()
            try:
                body_resp = response.json()
            except ValueError:
                error = "Feishu returned an invalid JSON response"
                logger.error(error)
                return PublishResult(PublishStatus.FAILED, error)
            if body_resp.get("code") == 0:
                logger.info("Feishu card sent successfully")
                return PublishResult(PublishStatus.SENT)
            # Application-level rejection: do NOT retry — same payload will
            # keep failing.
            error = (
                f"Feishu API rejected payload: code={body_resp.get('code')} "
                f"msg={body_resp.get('msg')}"
            )
            logger.error(error)
            return PublishResult(PublishStatus.FAILED, error)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code != 429 and status_code < 500:
                error = f"Feishu webhook returned HTTP {status_code}"
                logger.error(error)
                return PublishResult(PublishStatus.FAILED, error)
            if attempt < max_retries - 1:
                wait = _retry_wait(attempt, exc.response)
                logger.warning(
                    f"Feishu webhook returned HTTP {status_code}; retrying in {wait}s"
                )
                time.sleep(wait)
                continue
            error = (
                f"Feishu webhook returned HTTP {status_code} after "
                f"{max_retries} attempts"
            )
            logger.error(error)
            return PublishResult(PublishStatus.FAILED, error)
        except httpx.ReadTimeout:
            error = "Feishu response timed out; delivery status is unknown"
            logger.error(error)
            return PublishResult(PublishStatus.UNKNOWN, error)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            if attempt < max_retries - 1:
                wait = _retry_wait(attempt)
                logger.warning(
                    redact(
                        f"Feishu connection attempt {attempt + 1} failed: {exc}. "
                        f"Retrying in {wait}s..."
                    )
                )
                time.sleep(wait)
                continue
            error = redact(
                f"Feishu connection failed after {max_retries} attempts: {exc}"
            )
            logger.error(error)
            return PublishResult(PublishStatus.FAILED, error)
        except Exception as exc:
            error = redact(f"Feishu publish failed: {exc}")
            logger.error(error)
            return PublishResult(PublishStatus.FAILED, error)

    error = "Feishu publish requires at least one attempt"
    logger.error(error)
    return PublishResult(PublishStatus.FAILED, error)
