"""Groq istemcisi — lazy initialization ile API bağlantısı."""

from __future__ import annotations

from typing import Any, Optional

from beluma.core.config import Config

_cfg = Config()
_client: Optional[Any] = None
_initialized: bool = False


def get_groq_client() -> Optional[Any]:
    """Groq API istemcisini döndürür (lazy init).

    API anahtarı yoksa None döner.

    Returns:
        Groq istemci nesnesi veya None.
    """
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True
    if _cfg.GROQ_API_KEY:
        from groq import Groq
        _client = Groq(api_key=_cfg.GROQ_API_KEY)
    return _client
