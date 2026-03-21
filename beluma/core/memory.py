"""Hafıza modülü — Pinecone bulut hafıza + JSON yedek."""

from __future__ import annotations

import concurrent.futures
import os
import uuid
from typing import List, Optional

import requests

from beluma.core.config import Config
from beluma.core.helpers import json_yukle, json_kaydet
from beluma.core.logger import get_logger

_logger = get_logger()
_cfg = Config()

_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=_cfg.THREAD_POOL_WORKERS)


def get_thread_pool() -> concurrent.futures.ThreadPoolExecutor:
    """Global thread pool'u döndürür."""
    return _THREAD_POOL


def _metin_vektore_cevir(metin: str) -> Optional[List[float]]:
    """Metni embedding vektörüne çevirir (HuggingFace API).

    Args:
        metin: Vektöre çevrilecek metin.

    Returns:
        Float listesi veya None.
    """
    token = os.environ.get("HF_TOKEN") or _cfg.HF_TOKEN
    if not token:
        return None
    try:
        r = requests.post(
            _cfg.HF_EMBED_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={"inputs": metin[:512]},
            timeout=10,
        )
        if r.status_code == 200:
            vektor = r.json()
            if isinstance(vektor, list) and vektor and isinstance(vektor[0], list):
                vektor = vektor[0]
            return vektor
    except requests.RequestException as e:
        _logger.warning("[_metin_vektore_cevir] %s", e)
    return None


def _pinecone_hazir() -> bool:
    """Pinecone yapılandırmasının mevcut olup olmadığını kontrol eder."""
    return bool(_cfg.PINECONE_API_KEY and _cfg.PINECONE_HOST)


def bulut_hafiza_ekle(metin: str, kategori: str = "genel") -> None:
    """Metni bulut hafızaya ekler (Pinecone veya JSON yedek).

    Args:
        metin: Kaydedilecek metin.
        kategori: Hafıza kategorisi.
    """
    if not _pinecone_hazir():
        _json_hafiza_ekle(metin)
        return
    vektor = _metin_vektore_cevir(metin)
    if not vektor:
        _json_hafiza_ekle(metin)
        return
    try:
        kayit_id = uuid.uuid4().hex
        r = requests.post(
            f"{_cfg.PINECONE_HOST}/vectors/upsert",
            headers={"Api-Key": _cfg.PINECONE_API_KEY, "Content-Type": "application/json"},
            json={
                "vectors": [{
                    "id": kayit_id,
                    "values": vektor,
                    "metadata": {"metin": metin[:500], "kategori": kategori},
                }]
            },
            timeout=10,
        )
        if r.status_code not in (200, 201):
            _json_hafiza_ekle(metin)
    except requests.RequestException as e:
        _logger.warning("[bulut_hafiza_ekle] %s", e)
        _json_hafiza_ekle(metin)


def bulut_hafiza_ara(sorgu: str, n: int = 3) -> str:
    """Bulut hafızada arama yapar.

    Args:
        sorgu: Arama sorgusu.
        n: Döndürülecek sonuç sayısı.

    Returns:
        Eşleşen hafıza kayıtları.
    """
    if not _pinecone_hazir():
        return _json_hafiza_ara(sorgu, n)
    vektor = _metin_vektore_cevir(sorgu)
    if not vektor:
        return _json_hafiza_ara(sorgu, n)
    try:
        r = requests.post(
            f"{_cfg.PINECONE_HOST}/query",
            headers={"Api-Key": _cfg.PINECONE_API_KEY, "Content-Type": "application/json"},
            json={"vector": vektor, "topK": n, "includeMetadata": True},
            timeout=10,
        )
        if r.status_code == 200:
            eslesler = r.json().get("matches", [])
            metinler = [m["metadata"].get("metin", "") for m in eslesler if m.get("metadata")]
            return "\n".join(t for t in metinler if t)
    except (requests.RequestException, KeyError) as e:
        _logger.warning("[bulut_hafiza_ara] %s", e)
    return _json_hafiza_ara(sorgu, n)


def _json_hafiza_ekle(metin: str) -> None:
    """JSON tabanlı yerel hafızaya metin ekler."""
    liste = json_yukle(_cfg.MEMORY_FILE, [])
    if metin and metin not in liste:
        liste.append(metin)
    json_kaydet(_cfg.MEMORY_FILE, liste[-_cfg.MEMORY_LIMIT:])


def _json_hafiza_ara(sorgu: str, n: int = 3) -> str:
    """JSON tabanlı yerel hafızada anahtar kelime araması yapar."""
    liste = json_yukle(_cfg.MEMORY_FILE, [])
    if not liste:
        return ""
    kelimeler = [k for k in sorgu.lower().split() if len(k) > 3]
    if not kelimeler:
        return ""
    skorlar = [(sum(1 for k in kelimeler if k in r.lower()), r) for r in liste]
    skorlar = [(s, r) for s, r in skorlar if s > 0]
    skorlar.sort(reverse=True)
    return "\n".join(r for _, r in skorlar[:n])


def memory_ekle(metin: str) -> None:
    """Hafızaya arka planda metin ekler."""
    _THREAD_POOL.submit(bulut_hafiza_ekle, metin)


def memory_ara(sorgu: str, n: int = 3) -> str:
    """Hafızada arama yapar (minimum uzunluk kontrolü ile).

    Args:
        sorgu: Arama sorgusu.
        n: Sonuç sayısı.

    Returns:
        Eşleşen kayıtlar.
    """
    if len(sorgu.strip()) < 15:
        return ""
    return bulut_hafiza_ara(sorgu, min(n, 2))
