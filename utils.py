"""
BELUMA-I — Yardımcı Fonksiyonlar
Loglama, JSON I/O, metin temizleme, thread pool
"""
import ast
import atexit
import base64
import collections
import concurrent.futures
import json
import logging
import re
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict

from config import (
    HF_TOKEN, _COMPILED_INJECTION, _COMPILED_PHISHING, _COMPILED_PERSONAL,
    RISKLI, ETIK_DISI
)

# ══════════════════════════════════════════════════════════════════
# LOGLAMA
# ══════════════════════════════════════════════════════════════════
def _get_logger(name="beluma"):
    lg = logging.getLogger(name)
    if not lg.handlers:
        h = RotatingFileHandler("beluma.log", maxBytes=1_048_576, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        lg.addHandler(h)
        lg.setLevel(logging.INFO)
    return lg

_logger = _get_logger()
_logger.info("HF_TOKEN %s.", "yüklendi" if HF_TOKEN else "bulunamadı")

def log_kaydet(kullanici_mesaj, ai_cevap, model=""):
    try:
        _logger.info("model=%s | USR: %s | BOT: %s", model, kullanici_mesaj[:200], ai_cevap[:300])
    except (OSError, ValueError) as e:
        print(f"[log_kaydet] logger hatası: {e}", flush=True)

# ══════════════════════════════════════════════════════════════════
# THREAD POOL
# ══════════════════════════════════════════════════════════════════
_file_lock   = threading.Lock()
_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="beluma")

def _shutdown_pool():
    _THREAD_POOL.shutdown(wait=False)

atexit.register(_shutdown_pool)

# ══════════════════════════════════════════════════════════════════
# ÖZEL EXCEPTION SINIFLARI
# ══════════════════════════════════════════════════════════════════
class BelumaBazHata(Exception):
    """Tüm BELUMA hatalarının ortak tabanı."""

class AracHatasi(BelumaBazHata):
    """Araç (hesap, döviz, hava vb.) çalışma hatası."""

class ModelHatasi(BelumaBazHata):
    """LLM model çağrısı hatası."""

class BelgeHatasi(BelumaBazHata):
    """Belge okuma / ayrıştırma hatası."""

class HafizaHatasi(BelumaBazHata):
    """Bellek okuma / yazma hatası."""

class GorevHatasi(BelumaBazHata):
    """Görev CRUD hatası."""

# ── Hata istatistik sayacı ──
_hata_sayaci: Dict[str, int] = collections.defaultdict(int)
_hata_sayaci_lock = threading.Lock()

def _hata_say(etiket: str) -> None:
    with _hata_sayaci_lock:
        _hata_sayaci[etiket] += 1
        toplam = _hata_sayaci[etiket]
    _logger.warning("[HATA_SAYAC] %s → toplam: %d", etiket, toplam)

def hata_istatistikleri() -> str:
    with _hata_sayaci_lock:
        if not _hata_sayaci:
            return "Henüz hata kaydı yok."
        satirlar = [f"- {k}: {v}" for k, v in sorted(_hata_sayaci.items(), key=lambda x: -x[1])]
    return "**Hata İstatistikleri:**\n" + "\n".join(satirlar)

# ══════════════════════════════════════════════════════════════════
# JSON I/O (thread-safe, atomic write)
# ══════════════════════════════════════════════════════════════════
def json_yukle(dosya_yolu, varsayilan):
    if not dosya_yolu.exists():
        return varsayilan
    try:
        with dosya_yolu.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        _logger.warning("JSON hata (%s): %s", dosya_yolu, e)
        return varsayilan

def json_kaydet(dosya_yolu, veri):
    with _file_lock:
        try:
            tmp = dosya_yolu.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(veri, f, ensure_ascii=False, indent=2)
            tmp.replace(dosya_yolu)
        except (OSError, TypeError, ValueError) as e:
            _logger.error("Yazma hata (%s): %s", dosya_yolu, e)

def json_safe_parse(text):
    if not text:
        return {}
    temiz = re.sub(r"```json|```", "", str(text)).strip()
    try:
        return json.loads(temiz)
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        parsed = ast.literal_eval(temiz)
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, SyntaxError):
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except (json.JSONDecodeError, ValueError):
            _logger.debug("[json_safe_parse] tüm yöntemler başarısız: %s", text[:80])
    return {}

# ══════════════════════════════════════════════════════════════════
# METİN YARDIMCILARI
# ══════════════════════════════════════════════════════════════════
def metni_temizle(metin):
    if not metin:
        return ""
    temiz = str(metin).replace("\r\n", "\n").replace("\r", "\n")
    while "\n\n\n" in temiz:
        temiz = temiz.replace("\n\n\n", "\n\n")
    return temiz.strip()

def _dict_metin_cek(d):
    return str(d.get("text") or d.get("content") or d.get("response") or "")

def icerik_temizle(icerik):
    if icerik is None:
        return ""
    if isinstance(icerik, list):
        parcalar = [_dict_metin_cek(i) if isinstance(i, dict) else str(i) for i in icerik]
        icerik = "\n".join(p for p in parcalar if p)
    elif isinstance(icerik, dict):
        icerik = _dict_metin_cek(icerik)
    else:
        icerik = str(icerik)
    icerik = icerik.strip()
    if not icerik:
        return ""
    if icerik.startswith("[{") or icerik.startswith("[("):
        try:
            parsed = ast.literal_eval(icerik)
            if isinstance(parsed, list):
                parcalar = [_dict_metin_cek(i) for i in parsed if isinstance(i, dict)]
                sonuc = "\n".join(p for p in parcalar if p).strip()
                if sonuc:
                    icerik = sonuc
        except (ValueError, SyntaxError):
            pass
    if icerik.startswith("{") and icerik.endswith("}"):
        try:
            parsed = json.loads(icerik)
            if isinstance(parsed, dict):
                sonuc = _dict_metin_cek(parsed)
                if sonuc:
                    icerik = sonuc
        except (json.JSONDecodeError, ValueError):
            pass
    return metni_temizle(icerik)

def resmi_base64_yap(resim_yolu):
    if not resim_yolu or not Path(resim_yolu).exists():
        return None
    try:
        with open(resim_yolu, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        ext = Path(resim_yolu).suffix.lower().replace(".", "").replace("jpg", "jpeg")
        return f"data:image/{ext};base64,{encoded}"
    except OSError as e:
        _logger.warning("[resmi_base64_yap] %s", e)
        return None

def aciklamayi_ayikla(ham_cevap):
    if not isinstance(ham_cevap, str):
        ham_cevap = icerik_temizle(ham_cevap)
    m = re.search(r"<think>(.*?)</think>", ham_cevap, re.DOTALL)
    if m:
        return m.group(1).strip(), metni_temizle(ham_cevap[:m.start()] + ham_cevap[m.end():])
    return "", metni_temizle(ham_cevap)

# ══════════════════════════════════════════════════════════════════
# GÜVENLİK
# ══════════════════════════════════════════════════════════════════
def guvenlik_tarama(metin):
    kucuk = metin.lower()
    for pat in _COMPILED_INJECTION:
        if pat.search(kucuk): return "🛡️ **Güvenlik:** Bu mesaj sistem güvenliğini hedef alan bir kalıp içeriyor."
    for pat in _COMPILED_PHISHING:
        if pat.search(metin): return "⚠️ **Güvenlik uyarısı:** Şüpheli içerik tespit edildi."
    for pat in _COMPILED_PERSONAL:
        if pat.search(metin): return "🛡️ **Kişisel veri uyarısı:** TC Kimlik veya kredi kartı numarası olabilir."
    return None

def karar_motoru(mesaj):
    kucuk = mesaj.lower()
    return {"guvenli": sum(1 for r in RISKLI if r in kucuk) == 0 and sum(1 for e in ETIK_DISI if e in kucuk) == 0}
