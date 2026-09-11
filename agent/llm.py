"""Tiny shared Gemini helper (used by the layered-docs writer).

Mirrors the pattern in `draft.py`: call Gemini when a key is configured,
return None on any failure or when the SDK/key is absent so callers can
fall back to a deterministic stub. Kept separate so multiple modules can
reuse it without importing each other.
"""

from __future__ import annotations


def generate_text(cfg, prompt: str, temperature: float = 0.3) -> str | None:
    """Return Gemini's text response, or None if unavailable/failed."""
    if cfg is None or not getattr(cfg, "has_gemini", False):
        return None
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None
    try:
        client = genai.Client(api_key=cfg.gemini_api_key)
        resp = client.models.generate_content(
            model=cfg.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=temperature),
        )
        return resp.text
    except Exception as e:  # network / quota / parse
        print(f"  [llm] Gemini call failed ({e}); using stub.")
        return None
