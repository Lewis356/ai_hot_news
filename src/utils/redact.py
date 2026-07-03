"""Scrub secrets from log messages.

OpenAI / DeepSeek / httpx exceptions can embed Authorization headers, query
strings, and partial request bodies that contain API keys. Logging them raw
leaks credentials to disk. This module provides a single ``redact()`` helper
that masks common secret shapes before they hit loguru.
"""
from __future__ import annotations

import re

# Order matters: longer / more specific patterns first so they don't get
# partially redacted by a later generic pattern.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    # DeepSeek / OpenAI style keys (sk-..., sk-proj-...)
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{16,}"),
    # Standard Bearer tokens
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    # Query-string style token=... / api_key=... / key=...
    re.compile(r"(?P<k>token|api[_-]?key|access[_-]?token|secret)=(?P<v>[^\s&'\"\\]+)", re.IGNORECASE),
    # JSON-style "api_key": "..." values (preserve surrounding quotes)
    re.compile(r'(\b(?:api[_-]?key|token|access[_-]?token|secret)\b\s*[:=]\s*")([^"]+)(")', re.IGNORECASE),
    # Feishu webhook UUIDs (cc025b8e-378a-4cff-...)
    re.compile(r"https?://open\.feishu\.cn/open-apis/bot/v2/hook/[A-Za-z0-9\-]+"),
)

_REDACTED = "***REDACTED***"


def redact(text: str | object) -> str:
    """Return ``text`` with any embedded secrets replaced by ``***REDACTED***``.

    Non-string inputs are coerced via ``str()`` first; pass exceptions or
    arbitrary objects and you'll get a scrubbed string back. Never raises.
    """
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    for pat in _PATTERNS:
        s = pat.sub(_REDACTED, s)
    return s