"""Gradio versiyon uyumluluk katmanı."""

from __future__ import annotations

from typing import Any, Dict, List, Union

import gradio as gr


def chatbot_icin_hazirla(history: List[Any]) -> List[Any]:
    """Sohbet geçmişini Gradio versiyonuna uygun formata çevirir.

    Gradio v5+ dict format, v4 tuple format kullanır.

    Args:
        history: Ham sohbet geçmişi.

    Returns:
        Gradio uyumlu sohbet geçmişi.
    """
    v = tuple(int(x) for x in gr.__version__.split(".")[:2])
    if v >= (5, 0):
        result: List[Dict[str, str]] = []
        for item in (history or []):
            if isinstance(item, dict) and "role" in item:
                result.append(item)
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                u, a = item
                if u:
                    result.append({"role": "user", "content": str(u)})
                if a:
                    result.append({"role": "assistant", "content": str(a)})
        return result
    else:
        result_tuples: List[List[str]] = []
        buf = None
        for item in (history or []):
            if isinstance(item, dict):
                role = item.get("role", "")
                txt = item.get("content", "")
                if role == "user":
                    buf = txt
                elif role == "assistant":
                    result_tuples.append([buf or "", txt])
                    buf = None
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                result_tuples.append(list(item))
        return result_tuples
