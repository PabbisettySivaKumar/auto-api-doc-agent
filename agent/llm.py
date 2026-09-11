"""Shared LLM helper with mode-based provider routing.

Two modes, deliberately separated so old repos can NEVER be sent to a cloud
model by accident:

  * mode="backfill"    -> LOCAL model only (Ollama). Fallback is the
                          deterministic stub. There is **no Gemini branch**
                          in this path, so backfilling old repos cannot hit
                          the cloud even on failure.
  * mode="incremental" -> Gemini (Google AI Studio), for the live PR/push
                          flow. Fallback is the stub.

Callers pass `mode`; the default is "incremental" to preserve existing
behavior. Ollama is called over its local HTTP API with the stdlib only
(no new dependency).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

BACKFILL = "backfill"
INCREMENTAL = "incremental"


def _ollama(cfg, prompt: str, temperature: float) -> str | None:
    host = getattr(cfg, "ollama_host", "http://localhost:11434").rstrip("/")
    model = getattr(cfg, "ollama_model", "qwen2.5-coder:7b")
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
    ).encode()
    req = urllib.request.Request(
        f"{host}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
        text = data.get("response", "").strip()
        return text or None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        print(f"  [llm] Ollama call failed ({e}); using stub.")
        return None


def _gemini(cfg, prompt: str, temperature: float) -> str | None:
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


def generate_text(
    cfg, prompt: str, mode: str = INCREMENTAL, temperature: float = 0.3
) -> str | None:
    """Return model text, or None (caller uses its stub) if unavailable.

    Routing is by `mode`; the backfill path intentionally cannot reach
    Gemini.
    """
    if mode == BACKFILL:
        return _ollama(cfg, prompt, temperature)  # local-only; None -> stub
    return _gemini(cfg, prompt, temperature)
