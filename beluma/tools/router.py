"""Araç yönlendirici — kullanıcı mesajına göre doğru aracı seçer ve çalıştırır."""

from __future__ import annotations

import datetime as _dt
import os
import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

import requests

from beluma.core.config import Config
from beluma.core.logger import get_logger
from beluma.core.safe_eval import safe_eval, UnsafeExpressionError

_logger = get_logger()
_cfg = Config()

# Araç tetikleyici anahtar kelimeler
TOOL_KW: Dict[str, List[str]] = {
    "calc": ["hesapla", "hesaplat", "kaç eder", "topla", "çarp", "böl", "çıkar"],
    "date": ["bugün ne", "tarih", "saat kaç", "gün ne"],
    "convert": ["kaç tl", "kaç dolar", "kaç euro", "döviz", "kur", "usd", "eur", "gbp", "try"],
    "weather": ["hava durumu", "hava nasıl", "bugün hava", "yağmur", "sıcaklık", "derece"],
    "news": ["son haberler", "gündem", "haberler", "neler oluyor"],
    "bist": ["borsa", "bist", "hisse", "endeks", "xu100"],
}

# Şehir listesi — hava durumu sorgusu için
_SEHIRLER = (
    "istanbul", "ankara", "izmir", "bursa", "antalya", "malatya", "konya",
    "adana", "gaziantep", "samsun", "eskişehir", "kayseri", "trabzon",
    "diyarbakır", "mersin",
)

# Döviz eşleme tablosu
_PARA_MAP: Dict[str, str] = {
    "dolar": "USD", "usd": "USD",
    "euro": "EUR", "eur": "EUR",
    "sterlin": "GBP", "gbp": "GBP",
    "tl": "TRY", "try": "TRY", "lira": "TRY",
}


def tool_router(mesaj: str) -> Optional[str]:
    """Mesaja göre hangi aracın kullanılacağını belirler.

    Args:
        mesaj: Kullanıcı mesajı.

    Returns:
        Araç adı (str) veya None.
    """
    kucuk = mesaj.lower()
    for tool, kws in TOOL_KW.items():
        if any(k in kucuk for k in kws):
            return tool
    if re.search(r"[0-9]+\s*[+\-*/]\s*[0-9]+", mesaj):
        return "calc"
    return None


def run_tool(tool: str, mesaj: str) -> Optional[str]:
    """Belirlenen aracı çalıştırır.

    Args:
        tool: Çalıştırılacak araç adı.
        mesaj: Kullanıcı mesajı.

    Returns:
        Araç sonucu (str) veya None.
    """
    if tool == "calc":
        return _run_calc(mesaj)
    if tool == "date":
        return _run_date()
    if tool == "weather":
        return _run_weather(mesaj)
    if tool == "news":
        return _run_news()
    if tool == "bist":
        return _run_bist()
    if tool == "convert":
        return _run_convert(mesaj)
    return None


def _run_calc(mesaj: str) -> Optional[str]:
    """Güvenli hesaplama aracı."""
    temiz = re.sub(r"(?i)hesapla[t]?|kaç eder|topla|çarp|böl|çıkar|sonucu nedir|ne eder", "", mesaj)
    temiz = re.sub(r"[^0-9+\-*/().\s]", "", temiz).strip()
    temiz = re.sub(r"\s+", " ", temiz).strip()
    if not temiz:
        return None
    temiz = re.sub(r"([+\-*/])\s*[+\-*/]+", r"\1", temiz)
    try:
        sonuc = safe_eval(temiz)
        if isinstance(sonuc, float) and sonuc.is_integer():
            sonuc = int(sonuc)
        return f"🧮 **{temiz.strip()} = {sonuc}**"
    except ZeroDivisionError:
        return "⚠️ Sıfıra bölme hatası."
    except (UnsafeExpressionError, SyntaxError):
        return None


def _run_date() -> str:
    """Tarih ve saat aracı."""
    now = _dt.datetime.now()
    return f"📅 Bugün **{now.strftime('%d %B %Y')}**, saat **{now.strftime('%H:%M')}**."


def _run_weather(mesaj: str) -> str:
    """Hava durumu aracı."""
    sehir_m = re.search("|".join(_SEHIRLER), mesaj.lower())
    if not sehir_m:
        return "🌤 Hangi şehir için hava durumuna bakmamı istersin?"
    sehir = sehir_m.group(0).capitalize()
    try:
        r = requests.get(
            f"https://wttr.in/{sehir}?format=%C+%t+Nem:+%h+Rüzgar:+%w&lang=tr",
            timeout=5,
            headers={"User-Agent": "BELUMA-I/1.0"},
        )
        if r.status_code == 200 and r.text.strip():
            return f"🌤 **{sehir} hava durumu:** {r.text.strip()}"
    except requests.RequestException as e:
        _logger.warning("[run_tool/weather] %s", e)
    return f"🌤 Hava durumu alınamadı. [wttr.in/{sehir}](https://wttr.in/{sehir}) adresine bakabilirsin."


def _run_news() -> str:
    """Haber aracı — BBC Türkçe RSS."""
    try:
        r = requests.get(
            "https://feeds.bbci.co.uk/turkce/rss.xml",
            timeout=6,
            headers={"User-Agent": "BELUMA-I/1.0"},
        )
        if r.status_code == 200:
            root = ET.fromstring(r.content)
            items = root.findall(".//item")[:5]
            basliklar = [
                item.find("title").text
                for item in items
                if item.find("title") is not None
            ]
            if basliklar:
                return "📰 **Son haberler (BBC Türkçe):**\n" + "\n".join(f"• {b}" for b in basliklar)
    except (requests.RequestException, ET.ParseError) as e:
        _logger.warning("[run_tool/news] %s", e)
    return "📰 Haberler alınamadı. news.google.com/tr adresine bakabilirsin."


def _run_bist() -> str:
    """Borsa aracı — Yahoo Finance API."""
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/XU100.IS?interval=1d&range=1d",
            timeout=6,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200:
            veri = r.json()
            meta = veri["chart"]["result"][0]["meta"]
            fiyat = meta.get("regularMarketPrice", 0)
            onceki = meta.get("previousClose", fiyat)
            degisim = ((fiyat - onceki) / onceki * 100) if onceki else 0
            isaret = "📈" if degisim >= 0 else "📉"
            return f"{isaret} **BIST 100:** {fiyat:,.0f} puan ({degisim:+.2f}%)"
    except (requests.RequestException, KeyError, TypeError) as e:
        _logger.warning("[run_tool/bist] %s", e)
    return "📉 Borsa verisi alınamadı. Borsaistanbul.com adresine bakabilirsin."


def _run_convert(mesaj: str) -> Optional[str]:
    """Döviz çevirme aracı."""
    m = re.search(r"(\d+\.?\d*)\s*(usd|eur|gbp|tl|try|dolar|euro|sterlin|lira)", mesaj.lower())
    hedef_m = re.search(r"(?:kaç|to)\s*(usd|eur|gbp|tl|try|dolar|euro|sterlin|lira)", mesaj.lower())
    if not m:
        return None
    miktar = float(m.group(1))
    from_cur = _PARA_MAP.get(m.group(2), "USD")
    to_cur = _PARA_MAP.get((hedef_m.group(1) if hedef_m else "try"), "TRY")
    try:
        r = requests.get(f"https://api.exchangerate-api.com/v4/latest/{from_cur}", timeout=5)
        if r.status_code == 200:
            kur = r.json()["rates"].get(to_cur, _cfg.SABIT_KUR.get(to_cur, 1))
        else:
            kur = _cfg.SABIT_KUR.get(to_cur, 1) / _cfg.SABIT_KUR.get(from_cur, 1)
    except (requests.RequestException, KeyError) as e:
        _logger.warning("[run_tool/convert] %s", e)
        kur = _cfg.SABIT_KUR.get(to_cur, 1) / _cfg.SABIT_KUR.get(from_cur, 1)
    sonuc = miktar * kur
    return f"💱 **{miktar} {from_cur} = {sonuc:.2f} {to_cur}** (yaklaşık)"
