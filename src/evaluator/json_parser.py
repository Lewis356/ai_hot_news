"""Utility to extract JSON from unstructured LLM text output."""
import json
import re


def extract_json_from_text(text: str):
    """Extract and parse JSON from text that may contain markdown fences,
    trailing commas, or surrounding explanatory prose.

    Returns the parsed JSON object (dict or list).
    Raises ValueError if no valid JSON can be extracted.
    """
    if not text or not text.strip():
        raise ValueError("Input text is empty")

    stripped = text.strip()

    # Attempt 1: direct parse
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Attempt 2: extract from markdown code fences
    fence_match = re.search(
        r'```(?:json)?\s*\n?(.*?)\n?```', stripped, re.DOTALL
    )
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Attempt 3: find the largest { ... } or [ ... ] block
    for pattern in [r'\{.*\}', r'\[.*\]']:
        brace_match = re.search(pattern, stripped, re.DOTALL)
        if brace_match:
            candidate = brace_match.group(0)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                # Attempt 4: fix trailing commas and retry
                cleaned = re.sub(r',\s*([}\]])', r'\1', candidate)
                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError:
                    continue

    raise ValueError(
        f"Could not extract valid JSON from text: {stripped[:200]}..."
    )
