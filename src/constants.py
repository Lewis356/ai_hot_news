"""Centralised tunables.

Magic numbers used to live inside individual modules. Anything that an
operator might reasonably want to tweak belongs here so the change can be
made without hunting through the codebase.

Note: most of these are *defaults* — modules still read the active value
from ``Config`` (loaded from ``config.yaml``) first, falling back to the
constants below.
"""
from __future__ import annotations

# --- RSS fetch ---------------------------------------------------------------
FETCH_TIMEOUT_SECONDS: int = 15
FETCH_MAX_WORKERS: int = 8

# --- Dedup -------------------------------------------------------------------
DEFAULT_DEDUP_THRESHOLD: float = 0.80

# --- Time filter -------------------------------------------------------------
DEFAULT_RECENT_HOURS: int = 24
EPOCH_CUTOFF_YEAR: int = 2020  # Items older than this are treated as "no valid date"

# --- AI evaluator ------------------------------------------------------------
DEFAULT_TOP_N: int = 10
DEFAULT_MAX_CANDIDATES: int = 60
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_OLLAMA_TIMEOUT: float = 120.0

# --- LLM output sanitisation (Phase 1.2) ------------------------------------
IMPORTANCE_MIN: int = 1
IMPORTANCE_MAX: int = 10
IMPORTANCE_DEFAULT: int = 5
MAX_TITLE_LEN: int = 500
MAX_SUMMARY_LEN: int = 300
MAX_SOURCE_LEN: int = 50
MAX_KEYWORDS: int = 4

# --- Feishu publisher --------------------------------------------------------
FEISHU_TIMEOUT_SECONDS: float = 10.0
FEISHU_MAX_RETRIES: int = 3