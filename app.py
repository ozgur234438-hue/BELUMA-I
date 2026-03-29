import ast
import atexit
import base64
import concurrent.futures
import datetime as _dt
import glob
import hashlib
import json
import logging
import operator
import os
import random
import re
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import gradio as gr
import requests
from groq import Groq
from gtts import gTTS

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

# ── Hata istatistik sayacı (process ömrü boyunca) ──
import collections
_hata_sayaci: Dict[str, int] = collections.defaultdict(int)
_hata_sayaci_lock = threading.Lock()

def _hata_say(etiket: str) -> None:
    """Verilen etiketi thread-safe olarak artır ve logla."""
    with _hata_sayaci_lock:
        _hata_sayaci[etiket] += 1
        toplam = _hata_sayaci[etiket]
    _logger.warning("[HATA_SAYAC] %s → toplam: %d", etiket, toplam)

def hata_istatistikleri() -> str:
    """Mevcut hata istatistiklerini okunabilir metin olarak döndür."""
    with _hata_sayaci_lock:
        if not _hata_sayaci:
            return "Henüz hata kaydı yok."
        satirlar = [f"- {k}: {v}" for k, v in sorted(_hata_sayaci.items(), key=lambda x: -x[1])]
    return "**Hata İstatistikleri:**\n" + "\n".join(satirlar)

try:
    from gradio_client import Client as _GradioClient
except ImportError:
    _GradioClient = None

import warnings as _warnings
_warnings.filterwarnings("ignore", category=FutureWarning, module="google")
try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    import openai as _openai_mod
except ImportError:
    _openai_mod = None

try:
    import anthropic as _anthropic_mod
except ImportError:
    _anthropic_mod = None

# ══════════════════════════════════════════════════════════════════
# .ENV YÜKLE
# ══════════════════════════════════════════════════════════════════
def _load_local_env():
    env_file = Path(".env")
    if not env_file.exists():
        return
    try:
        with env_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError as e:
        print(f"[BELUMA] .env hata: {e}")

_load_local_env()

# ══════════════════════════════════════════════════════════════════
# MERKEZİ YAPILANDIRMA
# ══════════════════════════════════════════════════════════════════
def _resolve_hf_token():
    for key in ("HF_TOKEN", "hf_token", "HUGGINGFACE_TOKEN", "HF_API_TOKEN", "TOKEN"):
        val = os.environ.get(key)
        if val:
            return val
    return ""

API_KEY            = os.environ.get("GROQ_API_KEY", "")
MODEL_NAME         = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
AGENT_MODEL        = "llama-3.1-8b-instant"
VISION_MODEL       = "llama-3.2-11b-vision-preview"
FALLBACK_MODELLER  = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "llama3-8b-8192", "gemma2-9b-it"]
HF_TOKEN           = _resolve_hf_token()
HF_IMAGE_MODEL     = os.environ.get("HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
TRANSCRIBE_MODEL   = os.environ.get("GROQ_TRANSCRIBE_MODEL", "whisper-large-v3-turbo")
IMAGE_MODELS       = [HF_IMAGE_MODEL, "stabilityai/stable-diffusion-xl-base-1.0", "runwayml/stable-diffusion-v1-5", "prompthero/openjourney-v4"]
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "")
DEEPSEEK_API_KEY   = os.environ.get("DEEPSEEK_API_KEY", "")
OPENAI_API_KEY     = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
SESSION_FILE       = Path("beluma_session.json")
PROFILE_FILE       = Path("beluma_profile.json")
TASKS_FILE         = Path("beluma_tasks.json")
LIFE_MAP_FILE      = Path("beluma_life_map.json")
MEMORY_FILE        = Path("beluma_memory.json")
KREDI_FILE         = Path("beluma_krediler.json")
AUTH_FILE          = Path("beluma_auth.json")
ANALYTICS_FILE     = Path("beluma_analytics.json")
WEBHOOKS_FILE      = Path("beluma_webhooks.json")
WEBHOOK_RETRY_MAX  = 3
WEBHOOK_TIMEOUT    = 8
HATIRLATICI_FILE   = Path("beluma_hatirlaticilar.json")
I18N_FILE          = Path("beluma_i18n.json")
VARSAYILAN_DIL     = "tr"
USERS_FILE         = Path("beluma_users.json")
TEAM_FILE          = Path("beluma_team.json")
ROLLER             = ["admin", "editor", "viewer"]
PLUGINS_DIR        = Path("beluma_plugins")
PLUGINS_STATE_FILE = Path("beluma_plugins.json")
GUNLUK_KREDI       = 10
MEMORY_LIMIT       = 200
CACHE_TTL          = 5.0
PROFILE_CACHE_TTL  = 600.0
# ── Performans cache sabitleri ──
_PROFIL_CACHE:   dict = {"veri": None, "zaman": 0.0}   # profili_yukle cache
_PROFIL_LOCK     = threading.Lock()
_USERS_CACHE:    dict = {"veri": None, "zaman": 0.0}   # users_yukle cache
_TEAM_CACHE:     dict = {"veri": None, "zaman": 0.0}   # team_yukle cache
_IO_CACHE_TTL    = 10.0   # dosya cache süresi (sn)
MAX_DOCUMENT_CHARS = int(os.getenv("BELUMA_MAX_DOCUMENT_CHARS", "50000"))
TEXT_EXTENSIONS    = {".txt", ".md", ".py", ".json", ".csv", ".log", ".yaml", ".yml"}
PINECONE_API_KEY   = os.environ.get("PINECONE_API_KEY", "")
PINECONE_HOST      = os.environ.get("PINECONE_HOST", "").rstrip("/")
HF_EMBED_URL       = "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"
SABIT_KUR          = {"USD": 32.5, "EUR": 35.2, "GBP": 41.0, "TRY": 1.0}

# ── Özellik Bayrakları ──
class FeatureFlags:
    deep_research        = True
    constitutional_guard = True
    multimodal_images    = True
FLAGS = FeatureFlags()

# ── Anayasal Denetim Risk Kelimeleri ──
RISK_KEYWORDS = ["silah","patlayıcı","hack","zarar ver","öldür","uyuşturucu","kimlik bilgisi",
                 "şifre kır","kredi kartı","intihar","kendime zarar","bomba","fidye yazılımı",
                 "dolandır","yasadışı","kaçak"]

# ── Deep Research Kalite Puanlama ──
PRIORITY_DOMAINS = {"gov","edu","org","who.int","oecd.org","worldbank.org","imf.org",
                    "europa.eu","un.org","nature.com","science.org"}
BLOCKED_DOMAINS  = {"pinterest.com","instagram.com","facebook.com","tiktok.com"}
WEB_TIMEOUT      = int(os.getenv("BELUMA_WEB_TIMEOUT", "10"))
WEB_MAX_SOURCES  = int(os.getenv("BELUMA_WEB_MAX_SOURCES", "8"))

UZMANLIK_MODLARI = {
    "Standart":           "Sen genel amaçlı, yardımcı bir asistansın. Açık ve net cevaplar ver.",
    "💻 Kıdemli Yazılımcı":"Sen kıdemli bir yazılım mimarısın. Kodları en iyi pratiklere uygun, temiz, modüler ve açıklayıcı yazarsın.",
    "✍️ Yaratıcı Yazar":  "Sen usta bir metin yazarı ve SEO uzmanısın. Akıcı, duygu yüklü, okuyucuyu içine çeken metinler üretirsin.",
    "📊 Veri Analisti":   "Sen soğukkanlı bir veri analistisin. Verileri analiz edip mantıksal sonuçlar çıkarırsın."
}
GORSEL_STILLER = {
    "Gerçekçi":      "photorealistic, 8k, highly detailed, natural lighting, sharp focus, professional photography",
    "İllüstrasyon":  "vibrant anime style, clean strokes, expressive digital art, bold colors",
    "Sinematik":     "cinematic, dramatic lighting, film still, anamorphic lens, shallow depth of field, masterpiece",
    "Minimal":       "minimalist design, clean lines, elegant, modern aesthetic, white space, professional",
    "Emlak/Mimari":  "luxury real estate, wide angle interior, soft sunlight, 4k resolution",
    "Modern/Minimal":"minimalist design, clean lines, modern aesthetic, professional branding",
    "Anime/Çizim":   "vibrant anime style, clean strokes, expressive digital art",
}
INJECTION_PATTERNS = ["ignore previous","ignore all","forget previous","system promptu söyle",
                      "system prompt","gizli talimat","gizli bilgileri ver","şifreyi ver","api key",
                      "sen artık","sen şimdi","rolünü unut","developer mode","jailbreak","dan mode",
                      "önceki talimatları unut","tüm kısıtlamaları kaldır"]
PHISHING_PATTERNS_RAW  = [r"bit\.ly/",r"tinyurl\.com/",r"goo\.gl/",
                           r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
                           r"free.{0,10}(bitcoin|money|para|kazan)",
                           r"(şifre|password|kredi.kart).{0,30}(gir|doğrula|onayla)"]
PERSONAL_DATA_PATTERNS_RAW = [r"[1-9][0-9]{10}",
                               r"[0-9]{4}[ -]?[0-9]{4}[ -]?[0-9]{4}[ -]?[0-9]{4}"]
RISKLI    = ["hack","dolandır","illegal","şifre kır","saldır","exploit","bypass"]
ETIK_DISI = ["zarar ver","manipüle et","kandır","tehdit et","taciz"]
_COMPILED_INJECTION = [re.compile(re.escape(k), re.IGNORECASE) for k in INJECTION_PATTERNS]
_COMPILED_PHISHING  = [re.compile(p, re.IGNORECASE) for p in PHISHING_PATTERNS_RAW]
_COMPILED_PERSONAL  = [re.compile(p) for p in PERSONAL_DATA_PATTERNS_RAW]

# ══════════════════════════════════════════════════════════════════
# LOGLAMA + THREAD POOL
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

_file_lock  = threading.Lock()
_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="beluma")

def _shutdown_pool():
    _THREAD_POOL.shutdown(wait=False)

atexit.register(_shutdown_pool)

# ══════════════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR (thread-safe, atomic write)
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
        pass  # ilk deneme başarısız — ast.literal_eval dene
    try:
        parsed = ast.literal_eval(temiz)
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, SyntaxError):
        pass  # ikinci deneme başarısız — regex dene
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except (json.JSONDecodeError, ValueError):
            _logger.debug("[json_safe_parse] tüm yöntemler başarısız: %s", text[:80])
    return {}

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
            pass  # kasıtlı: ilk yöntem başarısız, JSON parse dene
    if icerik.startswith("{") and icerik.endswith("}"):
        try:
            parsed = json.loads(icerik)
            if isinstance(parsed, dict):
                sonuc = _dict_metin_cek(parsed)
                if sonuc:
                    icerik = sonuc
        except (json.JSONDecodeError, ValueError):
            pass  # kasıtlı: tüm yöntemler denendi, ham metni döndür
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
# GRADIO VERSİYON UYUMLULUĞU
# ══════════════════════════════════════════════════════════════════
def chatbot_icin_hazirla(history):
    v = tuple(int(x) for x in gr.__version__.split(".")[:2])
    if v >= (4, 0):
        result = []
        for item in (history or []):
            if isinstance(item, dict) and "role" in item:
                c = item.get("content", "")
                result.append({"role": item["role"], "content": c if isinstance(c, tuple) else str(c or "")})
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                u, a = item
                if u: result.append({"role": "user",      "content": str(u)})
                if a: result.append({"role": "assistant",  "content": str(a)})
        return result
    else:
        result, buf = [], None
        for item in (history or []):
            if isinstance(item, dict):
                role, txt = item.get("role", ""), item.get("content", "")
                if isinstance(txt, tuple): txt = "[Görsel]"
                if role == "user":      buf = txt
                elif role == "assistant": result.append([buf or "", txt]); buf = None
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                result.append(list(item))
        return result

# ══════════════════════════════════════════════════════════════════
# GÜVENLİ HESAP + GÜVENLİK
# ══════════════════════════════════════════════════════════════════
_SAFE_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg
}

class UnsafeExpressionError(ValueError):
    pass

def safe_eval(expr):
    def _eval(node):
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                raise UnsafeExpressionError(f"Desteklenmeyen: {node.value}")
            return node.value
        if isinstance(node, ast.BinOp):
            op = _SAFE_OPS.get(type(node.op))
            if not op: raise UnsafeExpressionError(f"Desteklenmeyen op: {type(node.op).__name__}")
            l, r = _eval(node.left), _eval(node.right)
            if isinstance(node.op, ast.Div) and r == 0: raise ZeroDivisionError
            return op(l, r)
        if isinstance(node, ast.UnaryOp):
            op = _SAFE_OPS.get(type(node.op))
            if not op: raise UnsafeExpressionError
            return op(_eval(node.operand))
        raise UnsafeExpressionError(f"Desteklenmeyen: {type(node).__name__}")
    return _eval(ast.parse(expr, mode="eval").body)

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

# ══════════════════════════════════════════════════════════════════
# GROQ CLIENT (lazy singleton)
# ══════════════════════════════════════════════════════════════════
_client      = None
_client_init = False

def get_groq_client():
    global _client, _client_init
    if _client_init: return _client
    _client_init = True
    if API_KEY: _client = Groq(api_key=API_KEY)
    return _client

# ══════════════════════════════════════════════════════════════════
# ÇOKLU MODEL CLIENT'LARI
# ══════════════════════════════════════════════════════════════════
def get_gemini_client(model_name="gemini-1.5-pro"):
    if not GEMINI_API_KEY or genai is None: return None
    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel(model_name)

def get_deepseek_client():
    if not DEEPSEEK_API_KEY or _openai_mod is None: return None
    return _openai_mod.OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")

def get_openai_client():
    if not OPENAI_API_KEY or _openai_mod is None: return None
    return _openai_mod.OpenAI(api_key=OPENAI_API_KEY)

def get_anthropic_client():
    if not ANTHROPIC_API_KEY or _anthropic_mod is None: return None
    return _anthropic_mod.Anthropic(api_key=ANTHROPIC_API_KEY)

# ══════════════════════════════════════════════════════════════════
# ZİHİNSEL MODELLER
# ══════════════════════════════════════════════════════════════════
MENTAL_MODELS = {
    "pareto":          "Pareto İlkesi (%80/20): Bu konudaki %20'lik çaba, %80 sonucu nasıl getirir?",
    "first_principles":"İlk İlkeler: Konuyu en temel doğrularına indirgersek ne görürüz?",
    "swot":            "SWOT: Bu durumun güçlü/zayıf yanları, fırsatları ve tehditleri neler?",
    "eisenhower":      "Eisenhower Matrisi: Bu iş acil mi, önemli mi, yoksa ikisi de mi?",
    "inversion":       "Ters Çevirme: 'Nasıl başarırım?' yerine 'Nasıl kesinlikle başarısız olurum?' diye sor.",
    "second_order":    "İkinci Derece Düşünce: Bu kararın dolaylı ve uzun vadeli sonuçları ne olur?",
    "occam":           "Occam'ın Usturası: En az varsayım gerektiren açıklama genellikle doğrudur.",
    "parkinson":       "Parkinson Yasası: İş, kendine ayrılan süreyi doldurur.",
    "circle_of_control":"Kontrol Çemberi: Bunun üzerinde gerçekten kontrol sahibi misin?",
    "regret_min":      "Pişmanlık Minimizasyonu (Bezos): 80 yaşında hangi kararı vermemiş olmaktan pişmanlık duyarsın?"
}
_MODEL_TRIGGERS = [
    (["karar","seçim","hangisi","ne yapmalı","tercih"],                          "eisenhower"),
    (["plan","strateji","iş","proje","büyüme"],                                  "pareto"),
    (["anlamadım","karmaşık","neden","nasıl çalışır","temel"],                   "first_principles"),
    (["risk","tehlike","yanlış giderse","başarısız"],                             "inversion"),
    (["sonuç","etki","ileride","gelecek","uzun vade"],                           "second_order"),
    (["karmaşık","çok fazla","boğuldum","nereden başla"],                        "occam"),
    (["vakit","süre","zaman","yetişemiyorum"],                                   "parkinson"),
    (["yapamıyorum","elimde değil","kontrol"],                                   "circle_of_control"),
    (["pişman","hayatımın kararı","önemli karar"],                               "regret_min"),
    (["güçlü","zayıf","fırsat","tehdit","swot","analiz et"],                     "swot"),
]

def zihinsel_model_oner(mesaj):
    kucuk = mesaj.lower()
    for kws, key in _MODEL_TRIGGERS:
        if any(k in kucuk for k in kws):
            return f"\n\n💡 **Düşünme önerisi:** {MENTAL_MODELS[key]}"
    try:
        if any(k in kucuk for k in ["iş","gelir","müşteri","satış"]):
            lm = haritayi_yukle()
            if lm.get("is_modeli"):
                return f"\n\n💡 **Pareto — {lm['is_modeli']}:** %20'lik çabanı nereye yatırırsın?"
    except (OSError, KeyError) as e:
        _logger.debug("[zihinsel_model_oner] life_map okunamadı: %s", e)
    return ""

# ══════════════════════════════════════════════════════════════════
# LIFE MAP (thread-safe cache)
# ══════════════════════════════════════════════════════════════════
_cache_lock = threading.Lock()
_lm_cache   = {"veri": None, "zaman": 0.0}

def varsayilan_harita():
    return {"hedefler":[],"gunluk_notlar":[],"aliskanliklar":[],"is_modeli":"","uzun_vadeli_plan":"","karar_tarzi":"","istatistik":{}}

def haritayi_yukle():
    with _cache_lock:
        if time.time() - _lm_cache["zaman"] < CACHE_TTL and _lm_cache["veri"] is not None:
            return _lm_cache["veri"]
        veri = json_yukle(LIFE_MAP_FILE, varsayilan_harita())
        _lm_cache.update({"veri": veri, "zaman": time.time()})
        return veri

def haritayi_kaydet(veri):
    json_kaydet(LIFE_MAP_FILE, veri)
    with _cache_lock:
        _lm_cache.update({"veri": veri, "zaman": time.time()})

def hedef_ekle(hedef_metni, oncelik=2):
    data = haritayi_yukle()
    data["hedefler"].append({"id": uuid.uuid4().hex[:8], "hedef": hedef_metni.strip(),
                              "tarih": time.strftime("%Y-%m-%d %H:%M"), "tamamlandi": False, "oncelik": oncelik})
    haritayi_kaydet(data)

def hedef_tamamla(hedef_ref):
    data = haritayi_yukle()
    ref  = hedef_ref.strip()
    for h in data["hedefler"]:
        if h.get("id") == ref or ref.lower() in h["hedef"].lower():
            h["tamamlandi"] = True; break
    haritayi_kaydet(data)

def gunluk_not_ekle(not_metni, kategori="genel"):
    data = haritayi_yukle()
    data["gunluk_notlar"].append({"not": not_metni.strip(), "tarih": time.strftime("%Y-%m-%d %H:%M"), "kategori": kategori})
    data["gunluk_notlar"] = data["gunluk_notlar"][-100:]
    haritayi_kaydet(data)

def aliskanlik_guncelle(aliskanlik):
    data = haritayi_yukle()
    bugun = time.strftime("%Y-%m-%d")
    for a in data["aliskanliklar"]:
        if a["aliskanlik"].lower() == aliskanlik.lower():
            if a.get("son_guncelleme", "") != bugun:
                a["seri"] = a.get("seri", 0) + 1
                a["son_guncelleme"] = bugun
            haritayi_kaydet(data)
            return
    data["aliskanliklar"].append({"aliskanlik": aliskanlik.strip(), "seri": 1, "son_guncelleme": bugun})
    haritayi_kaydet(data)

def life_map_ozeti():
    data = haritayi_yukle()
    h    = data.get("hedefler", [])
    t, tm = len(h), sum(1 for x in h if x.get("tamamlandi"))
    bk   = [x["hedef"] for x in h if not x.get("tamamlandi")][:3]
    al   = data.get("aliskanliklar", [])
    s    = []
    if t:  s.append(f"Hedef: {tm}/{t} tamamlandı")
    if bk: s.append("Bekleyen: " + ", ".join(bk))
    if al: s.append("Alışkanlıklar: " + ", ".join(f"{a['aliskanlik']}({a['seri']}g)" for a in al[:3]))
    return " | ".join(s) if s else ""

# ══════════════════════════════════════════════════════════════════
# KREDİ
# ══════════════════════════════════════════════════════════════════
def kredi_yukle():  return json_yukle(KREDI_FILE, {"kredi": GUNLUK_KREDI, "tarih": "", "toplam_uretim": 0, "son_gorsel": ""})
def kredi_kaydet(v): json_kaydet(KREDI_FILE, v)

def kredi_kontrol():
    v = kredi_yukle(); b = time.strftime("%Y-%m-%d")
    if v.get("tarih") != b: v["kredi"] = GUNLUK_KREDI; v["tarih"] = b; kredi_kaydet(v)
    k = v.get("kredi", GUNLUK_KREDI)
    return (0, "⏳ Günlük görsel kredin bitti.") if k <= 0 else (k, f"🎨 Kalan: **{k}/{GUNLUK_KREDI}**")

def kredi_kullan():
    v = kredi_yukle(); b = time.strftime("%Y-%m-%d")
    if v.get("tarih") != b: v["kredi"] = GUNLUK_KREDI; v["tarih"] = b
    k = v.get("kredi", GUNLUK_KREDI)
    if k <= 0: return False, "⏳ Günlük kredin bitti."
    v["kredi"] = k - 1; v["toplam_uretim"] = v.get("toplam_uretim", 0) + 1; kredi_kaydet(v)
    return True, f"✅ Kalan: {v['kredi']} kredi"

def son_gorsel_kaydet(yol):
    v = kredi_yukle(); v["son_gorsel"] = yol; kredi_kaydet(v)

# ══════════════════════════════════════════════════════════════════
# HAFIZA
# ══════════════════════════════════════════════════════════════════
def _metin_vektore_cevir(metin):
    token = os.environ.get("HF_TOKEN") or HF_TOKEN
    if not token: return None
    try:
        r = requests.post(HF_EMBED_URL,
                          headers={"Authorization": f"Bearer {token}"},
                          json={"inputs": metin[:512]}, timeout=10)
        if r.status_code == 200:
            v = r.json()
            return v[0] if isinstance(v, list) and v and isinstance(v[0], list) else v
    except requests.RequestException as e:
        _logger.warning("[embed] %s", e)
    return None

def _pinecone_hazir(): return bool(PINECONE_API_KEY and PINECONE_HOST)

def bulut_hafiza_ekle(metin, kategori="genel"):
    if not _pinecone_hazir(): _json_hafiza_ekle(metin); return
    vektor = _metin_vektore_cevir(metin)
    if not vektor: _json_hafiza_ekle(metin); return
    try:
        r = requests.post(f"{PINECONE_HOST}/vectors/upsert",
                          headers={"Api-Key": PINECONE_API_KEY, "Content-Type": "application/json"},
                          json={"vectors":[{"id":uuid.uuid4().hex,"values":vektor,"metadata":{"metin":metin[:500],"kategori":kategori}}]},
                          timeout=10)
        if r.status_code not in (200, 201): _json_hafiza_ekle(metin)
    except requests.RequestException as e:
        _logger.warning("[bulut_ekle] %s", e); _json_hafiza_ekle(metin)

def bulut_hafiza_ara(sorgu, n=3):
    if not _pinecone_hazir(): return _json_hafiza_ara(sorgu, n)
    vektor = _metin_vektore_cevir(sorgu)
    if not vektor: return _json_hafiza_ara(sorgu, n)
    try:
        r = requests.post(f"{PINECONE_HOST}/query",
                          headers={"Api-Key": PINECONE_API_KEY, "Content-Type": "application/json"},
                          json={"vector":vektor,"topK":n,"includeMetadata":True}, timeout=10)
        if r.status_code == 200:
            return "\n".join(m["metadata"].get("metin","") for m in r.json().get("matches",[]) if m.get("metadata"))
    except (requests.RequestException, KeyError) as e:
        _logger.warning("[bulut_ara] %s", e)
    return _json_hafiza_ara(sorgu, n)

def _json_hafiza_ekle(metin):
    l = json_yukle(MEMORY_FILE, [])
    if metin and metin not in l: l.append(metin)
    json_kaydet(MEMORY_FILE, l[-MEMORY_LIMIT:])

def _json_hafiza_ara(sorgu, n=3):
    l = json_yukle(MEMORY_FILE, [])
    if not l: return ""
    kw = [k for k in sorgu.lower().split() if len(k) > 3]
    if not kw: return ""
    sk = sorted([(sum(1 for k in kw if k in r.lower()), r) for r in l], reverse=True)
    return "\n".join(r for s, r in sk[:n] if s > 0)

def memory_ekle(metin): _THREAD_POOL.submit(bulut_hafiza_ekle, metin)
def memory_ara(sorgu, n=3):
    return bulut_hafiza_ara(sorgu, min(n, 2)) if len(sorgu.strip()) >= 15 else ""

# ══════════════════════════════════════════════════════════════════
# MULTI-AGENT (planner + critic)
# ══════════════════════════════════════════════════════════════════
def _agent_cagir(prompt, max_tokens=400):
    client = get_groq_client()
    if not client: return ""
    try:
        r = client.chat.completions.create(
            model=AGENT_MODEL,
            messages=[{"role":"user","content":prompt}],
            temperature=0.3, max_tokens=max_tokens)
        return icerik_temizle(r.choices[0].message.content)
    except Exception as e:
        _logger.warning("[agent] %s", e); return ""

def planner_agent(mesaj): return _agent_cagir(f"Bu isteği Türkçe kısa adım adım planla (max 4 adım):\n{mesaj}")
def critic_agent(cevap):  return _agent_cagir(f"Bu cevabı denetle. Hata varsa 'SORUN: [açıkla]' yaz. Yoksa 'TAMAM'.\nCevap: {cevap}", 150)

def _riskli_istek_mi(metin):
    return any(k in (metin or "").lower() for k in RISK_KEYWORDS)

def anayasal_denetim(cevap, kullanici_mesaji=""):
    if not FLAGS.constitutional_guard: return ""
    if not _riskli_istek_mi(kullanici_mesaji) and not _riskli_istek_mi(cevap): return ""
    if len(cevap) < 80: return ""
    prompt = (
        "Yanıtı güvenlik açısından değerlendir.\n"
        "Kontrol: 1) Zararlı/yasa dışı yönlendirme 2) Tehlikeli uydurma bilgi 3) Aşırı kesinlik\n"
        "Güvenliyse sadece: GUVENLI. Risk varsa kısa uyarı yaz.\n\n"
        f"Yanıt:\n{cevap[:1800]}"
    )
    denetim = _agent_cagir(prompt, 120)
    if denetim and "GÜVENLİ" not in denetim.upper()[:30] and "GUVENLI" not in denetim.upper()[:30]:
        return "\n\n🛡️ Güvenlik notu: Bu yanıtın bazı bölümleri güvenlik açısından sınırlandırıldı."
    return ""

# ══════════════════════════════════════════════════════════════════
# TÜRKÇE GARANTİ KAPISI — OPTİMİZE EDİLDİ
# ══════════════════════════════════════════════════════════════════
# ÖNCE: Her cevap için _agent_cagir() çağrılıyordu (gereksiz API tüketimi).
# SONRA: Sadece gerçekten yabancı dil tespit edildiğinde çevirme yapılıyor.
#        Böylece normal Türkçe cevaplarda sıfır ek API çağrısı yapılır.

_TR_CHARS = set("çğıİöşüÇĞİÖŞÜ")
_TR_HINTS = (" ve "," için "," değil "," ama "," çünkü "," olarak "," şu "," bu ",
             " ben "," sen "," siz "," biz ")
_TR_AYLAR = {"January":"Ocak","February":"Şubat","March":"Mart","April":"Nisan",
             "May":"Mayıs","June":"Haziran","July":"Temmuz","August":"Ağustos",
             "September":"Eylül","October":"Ekim","November":"Kasım","December":"Aralık"}

def _turkce_tarih():
    now   = _dt.datetime.now()
    ay_tr = _TR_AYLAR.get(now.strftime("%B"), now.strftime("%B"))
    return f"📅 Bugün **{now.strftime('%d')} {ay_tr} {now.strftime('%Y')}**, saat **{now.strftime('%H:%M')}**."

def _turkce_gibi_mi(text):
    """Hızlı ön kontrol — Türkçe karakter veya sözcük varsa True döner."""
    t = (text or "").strip()
    if not t: return True
    if any(ch in _TR_CHARS for ch in t): return True
    low = t.lower()
    return any(w in low for w in _TR_HINTS)

def _numarali_listeyi_duzelt(text):
    return re.sub(r"^\s*\d+[\.\)]\s+", "- ", text, flags=re.MULTILINE)

def _hata_turkce(provider, err):
    e = str(err)[:200]
    if "timeout"    in e.lower() or "timed out"  in e.lower(): return f"⚠️ {provider} bağlantısı zaman aşımına uğradı. Tekrar deneyin."
    if "rate_limit" in e.lower() or "429"         in e.lower(): return f"⏳ {provider} istek limiti aşıldı. Biraz bekleyip tekrar deneyin."
    if "api_key"    in e.lower() or "auth"        in e.lower(): return f"🔑 {provider} için geçerli bir anahtar gerekli."
    if "connection" in e.lower() or "network"     in e.lower(): return f"⚠️ {provider} bağlantı hatası. İnternet bağlantınızı kontrol edin."
    return f"⚠️ {provider} beklenmeyen hata: lütfen tekrar deneyin."

# OPTİMİZASYON 1 — enforce_turkish_output
# Eski davranış: her çağrıda ajan invoke ediliyor.
# Yeni davranış: _turkce_gibi_mi() True → hiç ajan çağrısı yapma, direkt döndür.
def enforce_turkish_output(text, max_chars=2200):
    t = (text or "").strip()
    if not t: return ""
    t = _numarali_listeyi_duzelt(t)
    for en, tr in _TR_AYLAR.items():
        t = t.replace(en, tr).replace(en.lower(), tr.lower())
    # ── Türkçe ise direkt döndür, ajan çağırma ──
    if _turkce_gibi_mi(t):
        return t[:max_chars]
    # ── Ancak gerçekten yabancı dil algılanırsa çevir ──
    rewritten = _agent_cagir(
        f"Aşağıdaki metni TAMAMEN Türkçeye çevir. Yabancı kelime kullanma. Kısa ve net yaz.\n\nMETİN:\n{t[:3500]}",
        600)
    rewritten = metni_temizle(rewritten or "")
    if rewritten:
        rewritten = _numarali_listeyi_duzelt(rewritten)
    return (rewritten or t)[:max_chars]

def derin_dusunce_katmani(mesaj, profil):
    client = get_groq_client()
    if not client: return ""
    return _agent_cagir(
        f"Profil: isim={profil.get('name','')}, ton={profil.get('tone','samimi')}, "
        f"hakkında={profil.get('about','')[:100]}\nMesaj: {mesaj[:300]}\n\n"
        f"Bu kişiye en etkili yaklaşım? 2 cümle strateji.", 120)

def dinamik_profil_ozeti(profil):
    client = get_groq_client()
    if not client: return ""
    lm   = haritayi_yukle()
    ozet = (f"İsim: {profil.get('name','')}\nHakkında: {profil.get('about','')}\n"
            f"Tercihler: {profil.get('preferences','')}\n"
            f"Hedefler: {', '.join(h.get('hedef','') if isinstance(h,dict) else str(h) for h in lm.get('hedefler',[])[:3])}\n"
            f"İş: {lm.get('is_modeli','')}\nÖğrenilmiş: {', '.join(profil.get('learned',[])[:5])}")
    if len(ozet.replace("\n","").replace(" ","")) < 30: return ""
    return _agent_cagir(f"2 cümlelik kişisel özet çıkar:\n{ozet}", 120)

# ══════════════════════════════════════════════════════════════════
# ARAÇ SİSTEMİ
# ══════════════════════════════════════════════════════════════════
TOOL_KW = {
    "calc":    ["hesapla","hesaplat","kaç eder","topla","çarp","böl","çıkar"],
    "date":    ["bugün ne","tarih","saat kaç","gün ne"],
    "convert": ["kaç tl","kaç dolar","kaç euro","döviz","kur","usd","eur","gbp","try"],
    "weather": ["hava durumu","hava nasıl","bugün hava","yağmur","sıcaklık","derece"],
    "news":    ["son haberler","gündem","haberler","neler oluyor"],
    "bist":    ["borsa","bist","hisse","endeks","xu100"],
    "search":  ["internette ara","web'de ara","arama yap","kim kazandı","sonucu ne",
                "ne oldu","son durum","google"]
}
_SEHIRLER   = ("istanbul","ankara","izmir","bursa","antalya","malatya","konya","adana",
               "gaziantep","samsun","eskişehir","kayseri","trabzon","diyarbakır","mersin")
_PARA_MAP   = {"dolar":"USD","usd":"USD","euro":"EUR","eur":"EUR","sterlin":"GBP",
               "gbp":"GBP","tl":"TRY","try":"TRY","lira":"TRY"}

def tool_router(mesaj):
    kucuk = mesaj.lower()
    for tool, kws in TOOL_KW.items():
        if any(k in kucuk for k in kws): return tool
    if re.search(r"[0-9]+\s*[+\-*/]\s*[0-9]+", mesaj): return "calc"
    if any(k in kucuk for k in ["bugün","dün","son","güncel","kim kazandı","sonuç"]): return "search"
    return None

# ══════════════════════════════════════════════════════════════════
# OPTİMİZASYON 2 — DDG Arama Sonuç Cache'i
# Eski davranış: Her sorguda DuckDuckGo'ya yeni istek atılıyor.
# Yeni davranış: Aynı sorgu 5 dakika içinde tekrar gelirse cache'den döndür.
#               Bu sayede deep research gibi çok sorgu yapan modüller
#               gereksiz ağ isteği yapmaz, yanıt hızı artar.
# ══════════════════════════════════════════════════════════════════
_DDG_CACHE: Dict[str, Tuple[float, list]] = {}
_DDG_CACHE_TTL = 300  # 5 dakika
_ddg_cache_lock = threading.Lock()

def _ddg_sonuclari_al(sorgu, n=4):
    """Cache'li DuckDuckGo araması. Aynı sorgu 5dk içinde tekrarlanırsa API çağrısı yapılmaz."""
    anahtar = f"{sorgu.lower().strip()}:{n}"
    with _ddg_cache_lock:
        if anahtar in _DDG_CACHE:
            ts, sonuclar = _DDG_CACHE[anahtar]
            if time.time() - ts < _DDG_CACHE_TTL:
                _logger.info("[ddg_cache] hit: %s", sorgu[:60])
                return sonuclar

    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            sonuclar = [
                {"title": str(r.get("title",""))[:200],
                 "body":  str(r.get("body",""))[:400],
                 "url":   str(r.get("href",""))[:700]}
                for r in list(ddgs.text(sorgu, region="tr-tr", max_results=n))[:n]
            ]
    except Exception as e:
        _logger.warning("[ddg] %s", e)
        sonuclar = []

    with _ddg_cache_lock:
        _DDG_CACHE[anahtar] = (time.time(), sonuclar)
        # Bellek taşmasını önle: 200'den fazla girdi varsa eskilerini temizle
        if len(_DDG_CACHE) > 200:
            eskiler = sorted(_DDG_CACHE.items(), key=lambda x: x[1][0])[:50]
            for k, _ in eskiler:
                del _DDG_CACHE[k]

    return sonuclar

def run_tool(tool, mesaj):
    if tool == "calc":
        t = re.sub(r"(?i)hesapla[t]?|kaç eder|topla|çarp|böl|çıkar|sonucu nedir|ne eder","",mesaj)
        t = re.sub(r"[^0-9+\-*/().\s]","",t).strip()
        t = re.sub(r"\s+"," ",t).strip()
        if not t: return None
        t = re.sub(r"([+\-*/])\s*[+\-*/]+",r"\1",t)
        try:
            s = safe_eval(t)
            if isinstance(s,float) and s.is_integer(): s=int(s)
            return f"🧮 **{t.strip()} = {s}**"
        except ZeroDivisionError: return "⚠️ Sıfıra bölme hatası."
        except (UnsafeExpressionError,SyntaxError): return None

    if tool == "date": return _turkce_tarih()

    if tool == "weather":
        m = re.search("|".join(_SEHIRLER), mesaj.lower())
        if not m: return "🌤 Hangi şehir için?"
        s = m.group(0).capitalize()
        try:
            r = requests.get(f"https://wttr.in/{s}?format=%C+%t+Nem:+%h+Rüzgar:+%w&lang=tr",
                             timeout=5, headers={"User-Agent":"BELUMA-I/1.0"})
            if r.status_code==200 and r.text.strip(): return f"🌤 **{s}:** {r.text.strip()}"
        except requests.RequestException as e: _logger.warning("[weather] %s",e); _hata_say("arac.weather")
        return f"🌤 Alınamadı. [wttr.in/{s}](https://wttr.in/{s})"

    if tool == "news":
        try:
            r = requests.get("https://feeds.bbci.co.uk/turkce/rss.xml",timeout=6,headers={"User-Agent":"BELUMA-I/1.0"})
            if r.status_code==200:
                root = ET.fromstring(r.content)
                bl = [i.find("title").text for i in root.findall(".//item")[:5] if i.find("title") is not None]
                if bl: return "📰 **Son haberler:**\n"+"".join(f"• {b}\n" for b in bl)
        except (requests.RequestException,ET.ParseError) as e: _logger.warning("[news] %s",e); _hata_say("arac.news")
        return "📰 Haberler alınamadı."

    if tool == "bist":
        try:
            r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/XU100.IS?interval=1d&range=1d",
                             timeout=6,headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code==200:
                meta = r.json()["chart"]["result"][0]["meta"]
                f2,o = meta.get("regularMarketPrice",0), meta.get("previousClose",0)
                d    = ((f2-o)/o*100) if o else 0
                return f"{'📈' if d>=0 else '📉'} **BIST 100:** {f2:,.0f} ({d:+.2f}%)"
        except (requests.RequestException,KeyError,TypeError) as e: _logger.warning("[bist] %s",e); _hata_say("arac.bist")
        return "📉 Borsa alınamadı."

    if tool == "convert":
        m  = re.search(r"(\d+\.?\d*)\s*(usd|eur|gbp|tl|try|dolar|euro|sterlin|lira)",mesaj.lower())
        hm = re.search(r"(?:kaç|to)\s*(usd|eur|gbp|tl|try|dolar|euro|sterlin|lira)",mesaj.lower())
        if not m: return None
        miktar,fc = float(m.group(1)), _PARA_MAP.get(m.group(2),"USD")
        tc = _PARA_MAP.get((hm.group(1) if hm else "try"),"TRY")
        try:
            r   = requests.get(f"https://api.exchangerate-api.com/v4/latest/{fc}",timeout=5)
            kur = r.json()["rates"].get(tc,SABIT_KUR.get(tc,1)) if r.status_code==200 else SABIT_KUR.get(tc,1)/SABIT_KUR.get(fc,1)
        except requests.RequestException as e:
            _logger.warning("[convert/ag] %s", e); _hata_say("convert.ag")
            kur = SABIT_KUR.get(tc,1)/SABIT_KUR.get(fc,1)
        except (KeyError, ValueError, ZeroDivisionError) as e:
            _logger.warning("[convert/parse] %s", e); _hata_say("convert.parse")
            kur = SABIT_KUR.get(tc,1)/SABIT_KUR.get(fc,1)
        return f"💱 **{miktar} {fc} = {miktar*kur:.2f} {tc}** (yaklaşık)"

    if tool == "search":
        temiz_sorgu = re.sub(r"(?i)internette ara|web'de ara|arama yap|bul|bana|google","",mesaj).strip()
        if not temiz_sorgu: temiz_sorgu = mesaj
        sonuclar = _ddg_sonuclari_al(temiz_sorgu, n=5)
        return {"query": temiz_sorgu, "results": sonuclar}

    return None

# ══════════════════════════════════════════════════════════════════
# v7 AGENT MİMARİSİ: Niyet Orkestratörü + Birleşik Arama
# ══════════════════════════════════════════════════════════════════
_GUNCEL_KALIPLARI    = ["bugün","dün","yarın","son ","güncel","hava durumu","hava nasıl",
                        "haber","borsa","bist","maç","skor","son durum","bu hafta","bu ay",
                        "şu an","döviz","kur "]
_HESAP_KALIPLARI     = ["hesapla","topla","çarp","böl","çıkar","kaç eder"]
_ARASTIRMA_KALIPLARI = ["derin araştır","deep research","kapsamlı araştır","detaylı araştır"]

def guncel_bilgi_gerekli_mi(mesaj):
    k = mesaj.lower()
    return any(x in k for x in _GUNCEL_KALIPLARI)

def cevap_turu_belirle(mesaj, belge_var=False, resim_var=False):
    k = mesaj.lower()
    if any(x in k for x in _ARASTIRMA_KALIPLARI): return "deep_research"
    if any(x in k for x in _HESAP_KALIPLARI) or re.search(r"\d+\s*[+\-*/]\s*\d+",mesaj): return "tool_calc"
    if any(x in k for x in ["tarih","saat kaç","gün ne","bugün ne"]): return "tool_date"
    if any(x in k for x in ["kaç tl","kaç dolar","kaç euro","döviz","kur"]): return "tool_convert"
    if any(x in k for x in ["hava durumu","hava nasıl","sıcaklık","derece"]): return "tool_weather"
    if any(x in k for x in ["son haberler","gündem","haberler","neler oluyor"]): return "tool_news"
    if any(x in k for x in ["borsa","bist","hisse","endeks","xu100"]): return "tool_bist"
    if belge_var: return "document_qa"
    if guncel_bilgi_gerekli_mi(mesaj): return "tool_search"
    if any(x in k for x in ["internette ara","web'de ara","arama yap","kim kazandı","sonucu ne"]): return "tool_search"
    return "direct_llm"

def arama_yap(sorgu, max_results=5):
    return _ddg_sonuclari_al(sorgu, n=max_results)

def kaynak_kartlari_olustur(sonuclar):
    if not sonuclar: return ""
    lines = [f"[{i}] {r.get('title','')}: {r.get('body','')[:200]}" for i,r in enumerate(sonuclar[:5],start=1)]
    return "\n".join(lines)

def final_cevap_temizle(metin):
    if not metin: return ""
    metin = str(metin).strip()
    for en, tr in _TR_AYLAR.items():
        metin = metin.replace(en,tr).replace(en.lower(),tr.lower())
    metin = _numarali_listeyi_duzelt(metin)
    metin = re.sub(r"\n{3,}","\n\n",metin).strip()
    return metin

def _ayni_cevap_mi(a, b):
    return " ".join((a or "").split()) == " ".join((b or "").split())

# ══════════════════════════════════════════════════════════════════
# OTURUM & PROFİL & GÖREV
# ══════════════════════════════════════════════════════════════════
def varsayilan_oturum(): return {"chat_history":[],"document_name":"","document_text":""}

def oturumu_yukle():
    v = json_yukle(SESSION_FILE, varsayilan_oturum()); p = varsayilan_oturum()
    if isinstance(v,dict): p.update(v)
    n = []
    for i in p.get("chat_history",[]):
        if isinstance(i,dict) and "role" in i:
            n.append({"role":i["role"],"content":str(i.get("content",""))})
        elif isinstance(i,(list,tuple)) and len(i)==2:
            u,a = i
            if u: n.append({"role":"user","content":str(u)})
            if a: n.append({"role":"assistant","content":str(a)})
    p["chat_history"] = n
    return p

def oturumu_kaydet(ch=None, dn="", dt="", ob=None):
    m = json_yukle(SESSION_FILE,{})
    json_kaydet(SESSION_FILE,{"chat_history":ch or [],"document_name":dn or "",
                              "document_text":dt or "",
                              "onboarding_goruldu":ob if ob is not None else m.get("onboarding_goruldu",False)})

def varsayilan_profil(): return {"name":"","tone":"samimi","style":"dengeli","about":"","preferences":"","learned":[]}
def profili_yukle():
    """
    OPT: profili_yukle 10 saniyelik in-memory cache.
    Önceki versiyonda her çağrıda disk okuyordu (13 çağrı noktası).
    """
    with _PROFIL_LOCK:
        if time.time() - _PROFIL_CACHE["zaman"] < _IO_CACHE_TTL and _PROFIL_CACHE["veri"] is not None:
            return _PROFIL_CACHE["veri"]
        veri = json_yukle(PROFILE_FILE, varsayilan_profil())
        _PROFIL_CACHE.update({"veri": veri, "zaman": time.time()})
        return veri

def profili_kaydet(**kw):
    p = varsayilan_profil(); p.update({k:v for k,v in kw.items() if k in p})
    json_kaydet(PROFILE_FILE, p)
    # Cache'i geçersiz kıl
    with _PROFIL_LOCK:
        _PROFIL_CACHE.update({"veri": p, "zaman": time.time()})

def profili_otomatik_guncelle(mesaj, cevap):
    client = get_groq_client()
    if not client: return
    try:
        r = client.chat.completions.create(
            model=AGENT_MODEL,
            messages=[{"role":"user","content":f'Tercih çıkar. Varsa: {{"tercih":"kısa"}}\nYoksa: {{}}\nUsr: {mesaj[:300]}\nBot: {cevap[:300]}'}],
            temperature=0.0, max_tokens=80)
        v  = json_safe_parse(icerik_temizle(r.choices[0].message.content))
        t  = v.get("tercih","").strip()
        if t:
            pr = profili_yukle(); lr = pr.get("learned",[])
            if t not in lr: lr = [t]+lr
            profili_kaydet(**{**pr,"learned":lr[:20]})
    except Exception as e: _logger.warning("[oto_profil] %s",e)

def gorevleri_yukle():    return json_yukle(TASKS_FILE, {"gorevler":[]})
def gorevleri_kaydet(v):  json_kaydet(TASKS_FILE, v)

def gorev_ekle(baslik, alt_gorevler=None):
    v  = gorevleri_yukle()
    y  = {"id":int(time.time()*1000),"baslik":baslik,
          "alt_gorevler":[{"metin":a,"tamamlandi":False} for a in (alt_gorevler or [])],
          "tamamlandi":False,"olusturuldu":time.strftime("%Y-%m-%d %H:%M")}
    v["gorevler"].insert(0,y); gorevleri_kaydet(v); return y

def gorev_tamamla_id(gid):
    v = gorevleri_yukle()
    for g in v["gorevler"]:
        if g["id"] == gid: g["tamamlandi"] = True
    gorevleri_kaydet(v)

def gorev_sil_id(gid):
    v = gorevleri_yukle(); v["gorevler"] = [g for g in v["gorevler"] if g["id"]!=gid]; gorevleri_kaydet(v)

_GOREV_METIN_CACHE = {"metin": None, "hash": ""}

def gorevleri_metne_cevir():
    """OPT: Görev listesi değişmediyse string'i yeniden üretme."""
    gl = gorevleri_yukle().get("gorevler", [])
    if not gl:
        _GOREV_METIN_CACHE.update({"metin": "Henüz görev yok.", "hash": "empty"})
        return "Henüz görev yok."
    # Hash — sadece id+tamamlandi yeterli
    h = hashlib.md5(str([(g["id"], g["tamamlandi"]) for g in gl]).encode()).hexdigest()
    if _GOREV_METIN_CACHE["hash"] == h and _GOREV_METIN_CACHE["metin"]:
        return _GOREV_METIN_CACHE["metin"]
    s = []
    for g in gl:
        s.append(f"{'✓' if g['tamamlandi'] else '○'} [{g['id']}] {g['baslik']}  ({g['olusturuldu']})")
        for a in g.get("alt_gorevler", []): s.append(f"    {'✓' if a['tamamlandi'] else '·'} {a['metin']}")
    metin = "\n".join(s)
    _GOREV_METIN_CACHE.update({"metin": metin, "hash": h})
    return metin

def chat_gorev_isle(mesaj):
    client = get_groq_client()
    if not client: return "",False
    if any(k in mesaj.lower() for k in ["hava","haber","borsa","saat","tarih","nedir","kimdir","kaç","hesapla"]): return "",False
    if not any(k in mesaj.lower() for k in ["yapacak","lazım","planla","hatırlat","görev","hedef","hafta","bugün","yarın"]): return "",False
    try:
        r = client.chat.completions.create(
            model=AGENT_MODEL,
            messages=[{"role":"user","content":f'Görev varsa: {{"baslik":"...","alt_gorevler":["..."]}}\nYoksa: {{}}\nMesaj: "{mesaj}"'}],
            temperature=0.0, max_tokens=200)
        v = json_safe_parse(icerik_temizle(r.choices[0].message.content))
        if v.get("baslik"):
            y = gorev_ekle(v["baslik"],v.get("alt_gorevler",[]))
            b = f"\n\n📌 Görev eklendi: **{y['baslik']}**"
            if y["alt_gorevler"]: b+="\n"+"".join(f"  · {a['metin']}\n" for a in y["alt_gorevler"])
            return b,True
    except Exception as e: _logger.warning("[gorev_isle] %s",e)
    return "",False

# ══════════════════════════════════════════════════════════════════
# BELGE OKUMA
# ══════════════════════════════════════════════════════════════════
def _chunk_text(text, chunk_size=1800, overlap=250):
    if not text: return []
    parts, step = [], max(1,chunk_size-overlap)
    for i in range(0,len(text),step):
        piece = text[i:i+chunk_size]
        if piece.strip(): parts.append(piece)
    return parts

def _select_relevant_chunks(query, chunks, top_k=4):
    if not chunks: return []
    keywords = [k for k in re.split(r"\W+",query.lower()) if len(k)>=4]
    if not keywords: return chunks[:top_k]
    scored = [(sum(chunk.lower().count(k) for k in keywords),chunk) for chunk in chunks]
    scored.sort(key=lambda x:x[0],reverse=True)
    selected = [c for s,c in scored[:top_k] if s>0]
    return selected or chunks[:2]

def gelismis_rag_ara(sorgu, uzun_metin, chunk_size=1800, overlap=250, top_k=4):
    if not uzun_metin: return ""
    uzun_metin = uzun_metin[:MAX_DOCUMENT_CHARS]
    if len(uzun_metin) <= chunk_size: return uzun_metin
    parcalar = _chunk_text(uzun_metin,chunk_size=chunk_size,overlap=overlap)
    en_iyi   = _select_relevant_chunks(sorgu,parcalar,top_k=top_k)
    return "\n\n...[İlgili belge kesiti]...\n\n".join(en_iyi)

def belge_metnini_oku(file_obj, max_chars=0):
    if max_chars==0: max_chars=MAX_DOCUMENT_CHARS
    if not file_obj: return "",""
    path = Path(getattr(file_obj,"name","") or str(file_obj))
    if not path.exists(): return "",""
    ext = path.suffix.lower()
    try:
        if ext in TEXT_EXTENSIONS:  text = path.read_text(encoding="utf-8",errors="ignore")
        elif ext==".pdf":
            try:
                import pypdf
                text="\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(path)).pages)
            except ImportError:
                _hata_say("belge.pypdf_eksik")
                return path.name, "Kütüphane eksik: pypdf. `pip install pypdf` ile yükle."
        elif ext==".docx":
            try:
                import docx
                text="\n".join(p.text for p in docx.Document(str(path)).paragraphs)
            except ImportError:
                _hata_say("belge.docx_eksik")
                return path.name, "Kütüphane eksik: python-docx. `pip install python-docx` ile yükle."
        elif ext in (".xlsx",".xls"):
            try:
                import openpyxl
                wb=openpyxl.load_workbook(str(path),read_only=True,data_only=True)
                rows=[]
                for ws in wb.worksheets:
                    for row in ws.iter_rows(values_only=True): rows.append("\t".join(str(c) if c is not None else "" for c in row))
                text="\n".join(rows)
            except ImportError:
                _hata_say("belge.openpyxl_eksik")
                return path.name, "Kütüphane eksik: openpyxl. `pip install openpyxl` ile yükle."
        else:
            return path.name, f"{path.suffix} desteklenmiyor."
    except OSError as e:
        _logger.warning("[belge/os] %s", e); _hata_say("belge.os_hatasi")
        return path.name, f"Dosya okunamadı: {e}"
    except Exception as e:
        _logger.error("[belge/genel] %s", e); _hata_say("belge.genel")
        return path.name, "Beklenmeyen okuma hatası."
    text = text.strip()
    if not text: return path.name,"Dosya boş."
    if len(text)>max_chars: text=text[:max_chars].rsplit(" ",1)[0]+"\n\n[Kısaltıldı]"
    return path.name, text

# ══════════════════════════════════════════════════════════════════
# DUYGU & ÖNERİ & PROAKTİF & RAPOR
# ══════════════════════════════════════════════════════════════════
def duygu_analizi(mesaj):
    k = mesaj.lower()
    if any(s in k for s in ["bunaldım","yoruldum","sıkıldım","zor","berbat","çaresiz","endişe"]): return {"durum":"stresli","ton":"yumuşat ve kısa tut"}
    if any(s in k for s in ["harika","süper","mutlu","başardım","mükemmel"]):                      return {"durum":"mutlu","ton":"enerjik ve destekleyici ol"}
    if any(s in k for s in ["neden","nasıl","nedir","anlat","açıkla"]):                            return {"durum":"meraklı","ton":"detaylı ve açıklayıcı ol"}
    return {"durum":"nötr","ton":"dengeli kal"}

def gunluk_oneri():
    s = _dt.datetime.now().hour
    if  6 <= s < 12: return "☀️ Günaydın! Bugün için 3 hedef belirle?"
    if 12 <= s < 18: return "🌤 Günün ortası — ilerleme nasıl?"
    if 18 <= s < 22: return "🌙 Akşam oldu. Bugünü değerlendirelim?"
    return ""

def proaktif_kontrol(ctx=""):
    d  = haritayi_yukle(); h=d.get("hedefler",[]); bk=[x for x in h if not x.get("tamamlandi")]; tm=[x for x in h if x.get("tamamlandi")]
    if len(bk)>5:
        yk=[x["hedef"] for x in bk if x.get("oncelik",2)==3]
        if yk: return f"⚠️ **Odak:** {len(bk)} bekleyen. Öncelikli: _{yk[0]}_"
    if not bk and tm: return "🔥 **Tebrikler!** Tüm hedefler tamam. Yeni koy!"
    if not h and any(k in ctx.lower() for k in ["plan","hedef","strateji"]): return "💡 Henüz hedef yok. Yaşam Haritası'ndan ekle."
    bg=time.strftime("%Y-%m-%d")
    for a in d.get("aliskanliklar",[]):
        if a.get("son_guncelleme","") and a["son_guncelleme"]<bg and a.get("seri",0)>2:
            return f"🔔 _{a['aliskanlik']}_ serisi ({a['seri']}g) kırılmak üzere!"
    return ""

# ══════════════════════════════════════════════════════════════════
# ANALİTİK SİSTEM
# ══════════════════════════════════════════════════════════════════
_ANALYTICS_LOCK = threading.Lock()

def _varsayilan_analytics():
    return {
        "mesajlar":       [],
        "model_sayac":    {},
        "arac_sayac":     {},
        "hata_sayac":     {},
        "gunluk":         {},
        "oturum_baslama": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

def analytics_yukle():
    return json_yukle(ANALYTICS_FILE, _varsayilan_analytics())

def analytics_kaydet(v):
    with _ANALYTICS_LOCK:
        try:
            tmp = ANALYTICS_FILE.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(v, f, ensure_ascii=False, indent=2)
            tmp.replace(ANALYTICS_FILE)
        except (OSError, TypeError) as e:
            _logger.error("[analytics] yazma hatasi: %s", e)

def analitik_kaydet(model="", arac="", sure_ms=0.0, hata="", token_est=0):
    def _yaz():
        v     = analytics_yukle()
        bugun = time.strftime("%Y-%m-%d")
        saat  = time.strftime("%H:%M")
        v["mesajlar"].append({"tarih": f"{bugun} {saat}", "model": model,
                              "sure_ms": round(sure_ms, 1), "arac": arac, "hata": hata})
        v["mesajlar"] = v["mesajlar"][-500:]
        if model: v["model_sayac"][model] = v["model_sayac"].get(model, 0) + 1
        if arac:  v["arac_sayac"][arac]   = v["arac_sayac"].get(arac, 0) + 1
        if hata:  v["hata_sayac"][hata]   = v["hata_sayac"].get(hata, 0) + 1
        g = v["gunluk"].setdefault(bugun, {"mesaj": 0, "token_est": 0, "hata": 0})
        g["mesaj"] += 1; g["token_est"] += token_est
        if hata: g["hata"] += 1
        analytics_kaydet(v)
    _THREAD_POOL.submit(_yaz)

def _son_n_gun(n=14):
    bugun = _dt.date.today()
    return [(bugun - _dt.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n-1, -1, -1)]

def grafik_verisi_gunluk(n=14, v=None):
    """OPT: v parametresi varsa analytics_yukle() çağrısını atla."""
    if v is None: v = analytics_yukle()
    gunler   = _son_n_gun(n)
    mesajlar = [v["gunluk"].get(g, {}).get("mesaj", 0) for g in gunler]
    hatalar  = [v["gunluk"].get(g, {}).get("hata",  0) for g in gunler]
    return [g[5:] for g in gunler], mesajlar, hatalar

def grafik_verisi_model(v=None):
    """OPT: v parametresi varsa disk okuma atla."""
    if v is None: v = analytics_yukle()
    s = sorted(v["model_sayac"].items(), key=lambda x: -x[1])
    if not s: return ["yok"], [0]
    adlar, sayilar = zip(*s[:8]); return list(adlar), list(sayilar)

def grafik_verisi_arac(v=None):
    """OPT: v parametresi varsa disk okuma atla."""
    if v is None: v = analytics_yukle()
    s = sorted(v["arac_sayac"].items(), key=lambda x: -x[1])
    if not s: return ["yok"], [0]
    adlar, sayilar = zip(*s[:8]); return list(adlar), list(sayilar)

def dashboard_html():
    """OPT: analytics_yukle tek kez çağrılır, grafik fonksiyonlarına parametre geçilir."""
    v = analytics_yukle()  # tek disk okuma
    gunler, mesajlar, hatalar = grafik_verisi_gunluk(14, v=v)
    m_adlar, m_sayilar        = grafik_verisi_model(v=v)
    a_adlar, a_sayilar        = grafik_verisi_arac(v=v)
    toplam_mesaj  = sum(mesajlar); toplam_hata = sum(hatalar)
    en_model = max(v["model_sayac"], key=v["model_sayac"].get) if v["model_sayac"] else "yok"
    en_arac  = max(v["arac_sayac"],  key=v["arac_sayac"].get)  if v["arac_sayac"]  else "yok"
    basarili = round((1 - toplam_hata / max(toplam_mesaj, 1)) * 100, 1)
    max_m = max(mesajlar) or 1; bar_w = 32; gap = 6
    svg_w = len(gunler) * (bar_w + gap); svg_h = 120
    cubuklar = ""
    for i, (g, m) in enumerate(zip(gunler, mesajlar)):
        yh = max(4, int(m / max_m * (svg_h - 30))); x = i * (bar_w + gap); y = svg_h - 20 - yh
        cubuklar += f'<rect x="{x}" y="{y}" width="{bar_w}" height="{yh}" rx="4" fill="url(#grad)" opacity="0.9"/>'
        cubuklar += f'<text x="{x+bar_w//2}" y="{svg_h-4}" text-anchor="middle" font-size="9" fill="#FF69B4">{g}</text>'
        if m > 0: cubuklar += f'<text x="{x+bar_w//2}" y="{y-3}" text-anchor="middle" font-size="9" fill="#fff">{m}</text>'
    max_ms = max(m_sayilar) or 1
    model_bars = "".join(f'<div style="margin:5px 0"><div style="display:flex;justify-content:space-between;font-size:11px;color:rgba(255,255,255,.8);margin-bottom:2px"><span>{n.split("/")[-1][:16]}</span><span>{s}</span></div><div style="background:rgba(255,255,255,.1);border-radius:3px;height:7px"><div style="width:{int(s/max_ms*100)}%;background:linear-gradient(90deg,#FF1493,#8A2BE2);border-radius:3px;height:7px"></div></div></div>' for n,s in zip(m_adlar, m_sayilar))
    max_as = max(a_sayilar) or 1
    arac_bars  = "".join(f'<div style="margin:5px 0"><div style="display:flex;justify-content:space-between;font-size:11px;color:rgba(255,255,255,.8);margin-bottom:2px"><span>{n}</span><span>{s}</span></div><div style="background:rgba(255,255,255,.1);border-radius:3px;height:7px"><div style="width:{int(s/max_as*100)}%;background:linear-gradient(90deg,#8A2BE2,#00CED1);border-radius:3px;height:7px"></div></div></div>' for n,s in zip(a_adlar, a_sayilar))
    kartlar = "".join(f'<div style="background:rgba(138,43,226,.18);border:1px solid rgba(255,20,147,.28);border-radius:12px;padding:12px;text-align:center"><div style="font-size:20px;font-weight:700;color:#FF69B4">{v}</div><div style="font-size:10px;color:rgba(255,255,255,.55);margin-top:3px">{l}</div></div>' for v,l in [(toplam_mesaj,"Toplam Mesaj"),(toplam_hata,"Toplam Hata"),(f"%{basarili}","Basari"),(en_model.split("-")[0][:10],"En Cok Model"),(en_arac,"En Cok Arac")])
    return f"""<div style="font-family:sans-serif;color:#fff;padding:6px 0">
<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:14px">{kartlar}</div>
<div style="background:rgba(13,6,20,.65);border:1px solid rgba(138,43,226,.3);border-radius:12px;padding:12px;margin-bottom:12px">
  <div style="font-size:12px;font-weight:500;color:#FF69B4;margin-bottom:8px">Son 14 Gun Mesaj</div>
  <svg width="100%" viewBox="0 0 {svg_w} {svg_h}" preserveAspectRatio="xMidYMid meet">
    <defs><linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#FF1493"/><stop offset="100%" stop-color="#8A2BE2"/>
    </linearGradient></defs>{cubuklar}
  </svg>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
  <div style="background:rgba(13,6,20,.65);border:1px solid rgba(138,43,226,.3);border-radius:12px;padding:12px">
    <div style="font-size:12px;font-weight:500;color:#FF69B4;margin-bottom:8px">Model Kullanimi</div>{model_bars or "<div style='font-size:11px;color:rgba(255,255,255,.4)'>Veri yok</div>"}
  </div>
  <div style="background:rgba(13,6,20,.65);border:1px solid rgba(138,43,226,.3);border-radius:12px;padding:12px">
    <div style="font-size:12px;font-weight:500;color:#8A2BE2;margin-bottom:8px">Arac Kullanimi</div>{arac_bars or "<div style='font-size:11px;color:rgba(255,255,255,.4)'>Veri yok</div>"}
  </div>
</div></div>"""



# ══════════════════════════════════════════════════════════════════
# PLUGIN SİSTEMİ
# ══════════════════════════════════════════════════════════════════
import importlib.util as _imp_util

_plugin_registry: Dict[str, Any] = {}   # isim → modül
_plugin_lock     = threading.Lock()

def _plugin_state_yukle() -> dict:
    """Pasif edilmiş plugin listesini yükle."""
    return json_yukle(PLUGINS_STATE_FILE, {"pasif": []})

def _plugin_state_kaydet(v: dict) -> None:
    json_kaydet(PLUGINS_STATE_FILE, v)

def plugin_yukle_hepsi() -> int:
    """
    beluma_plugins/ klasöründeki *_plugin.py dosyalarını tarar ve yükler.
    Pasif işaretlenenler atlanır.
    Döndürür: yüklenen plugin sayısı.
    """
    global _plugin_registry
    if not PLUGINS_DIR.exists():
        PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        return 0
    pasif = _plugin_state_yukle().get("pasif", [])
    yuklenen = {}
    for dosya in sorted(PLUGINS_DIR.glob("*_plugin.py")):
        try:
            spec   = _imp_util.spec_from_file_location(dosya.stem, dosya)
            modul  = _imp_util.module_from_spec(spec)
            spec.loader.exec_module(modul)
            isim   = getattr(modul, "PLUGIN_ISIM", dosya.stem)
            if isim in pasif:
                _logger.info("[plugin] pasif: %s", isim); continue
            if not callable(getattr(modul, "calistir", None)):
                _logger.warning("[plugin] calistir() yok: %s", dosya.name); continue
            yuklenen[isim] = modul
            _logger.info("[plugin] yüklendi: %s v%s", isim, getattr(modul, "PLUGIN_VERSIYON", "?"))
        except Exception as e:
            _logger.error("[plugin] yükleme hatası (%s): %s", dosya.name, e)
            _hata_say(f"plugin.yukleme.{dosya.stem}")
    with _plugin_lock:
        _plugin_registry = yuklenen
    return len(yuklenen)

def plugin_isle(mesaj: str) -> Optional[str]:
    """
    Mesajı kayıtlı pluginlerin tetikleyicileriyle karşılaştırır.
    İlk eşleşen plugin'i çalıştırır ve sonucu döndürür.
    Eşleşme yoksa None döner.
    """
    kucuk = mesaj.lower()
    with _plugin_lock:
        kayitlilar = list(_plugin_registry.items())
    for isim, modul in kayitlilar:
        tetikler = getattr(modul, "TETIKLEYICILER", [])
        if any(t in kucuk for t in tetikler):
            try:
                sonuc = modul.calistir(mesaj)
                analitik_kaydet(arac=f"plugin:{isim}")
                _logger.info("[plugin] çalıştı: %s", isim)
                return str(sonuc) if sonuc else None
            except Exception as e:
                _logger.error("[plugin] çalışma hatası (%s): %s", isim, e)
                _hata_say(f"plugin.calistir.{isim[:20]}")
    return None

def plugin_listesi_metin() -> str:
    """Yüklü plugin'lerin okunabilir listesi."""
    with _plugin_lock:
        kayitlilar = list(_plugin_registry.items())
    if not kayitlilar:
        return "Yüklü plugin yok. `beluma_plugins/` klasörüne `*_plugin.py` dosyası ekle."
    satirlar = []
    for isim, modul in kayitlilar:
        ver  = getattr(modul, "PLUGIN_VERSIYON", "?")
        acik = getattr(modul, "PLUGIN_ACIKLAMA", "")
        tetk = ", ".join(getattr(modul, "TETIKLEYICILER", [])[:3])
        satirlar.append(f"✅ **{isim}** v{ver}\n   _{acik}_\n   Tetikleyici: `{tetk}`")
    return "\n\n".join(satirlar)

def plugin_yeniden_yukle() -> str:
    """Tüm pluginleri sıfırdan yükler ve sonucu döndürür."""
    sayi = plugin_yukle_hepsi()
    return f"🔄 {sayi} plugin yüklendi." if sayi else "⚠️ Hiç plugin yüklenemedi."

def plugin_pasif_yap(isim: str) -> str:
    """İsme göre plugini pasif et."""
    v = _plugin_state_yukle()
    if isim not in v["pasif"]:
        v["pasif"].append(isim)
        _plugin_state_kaydet(v)
    with _plugin_lock:
        _plugin_registry.pop(isim, None)
    return f"⏸ **{isim}** pasife alındı. Yeniden yükle butonuna bas."

def plugin_aktif_yap(isim: str) -> str:
    """İsme göre plugini pasiften çıkar."""
    v = _plugin_state_yukle()
    v["pasif"] = [p for p in v["pasif"] if p != isim]
    _plugin_state_kaydet(v)
    return f"▶️ **{isim}** aktifleştirildi. Yeniden yükle butonuna bas."

# ── Gömülü Plugin Tanımları (HuggingFace Spaces uyumlu — tek dosya) ──
class _PluginBase:
    PLUGIN_ISIM = ""; PLUGIN_VERSIYON = "1.0"; PLUGIN_ACIKLAMA = ""; TETIKLEYICILER = []
    @staticmethod
    def calistir(mesaj: str) -> str: return ""

class _DovizPlugin(_PluginBase):
    PLUGIN_ISIM = "Döviz Çevirici"; PLUGIN_VERSIYON = "1.0"
    PLUGIN_ACIKLAMA = "Gerçek zamanlı döviz kuru çevirici"
    TETIKLEYICILER = ["kaç dolar","kaç euro","kaç tl","döviz","kur","usd","eur","gbp"]
    _PARA_MAP = {"dolar":"USD","usd":"USD","euro":"EUR","eur":"EUR","sterlin":"GBP","gbp":"GBP","tl":"TRY","try":"TRY","lira":"TRY"}
    _SABIT = {"USD":32.5,"EUR":35.2,"GBP":41.0,"TRY":1.0}
    @staticmethod
    def calistir(mesaj: str) -> str:
        m  = re.search(r"(\d+\.?\d*)\s*(usd|eur|gbp|tl|try|dolar|euro|sterlin|lira)", mesaj.lower())
        hm = re.search(r"(?:kaç|to)\s*(usd|eur|gbp|tl|try|dolar|euro|sterlin|lira)", mesaj.lower())
        if not m: return "💱 Miktar ve para birimi belirt. Örnek: '100 dolar kaç tl?'"
        miktar = float(m.group(1))
        fc = _DovizPlugin._PARA_MAP.get(m.group(2),"USD")
        tc = _DovizPlugin._PARA_MAP.get((hm.group(1) if hm else "try"),"TRY")
        try:
            r = requests.get(f"https://api.exchangerate-api.com/v4/latest/{fc}",timeout=5)
            kur = r.json()["rates"].get(tc,1) if r.status_code==200 else _DovizPlugin._SABIT.get(tc,1)/_DovizPlugin._SABIT.get(fc,1)
        except requests.RequestException as e:
            _logger.warning("[DovizPlugin] ağ hatası: %s", e)
            kur = _DovizPlugin._SABIT.get(tc,1)/_DovizPlugin._SABIT.get(fc,1)
        except (KeyError, ValueError, ZeroDivisionError) as e:
            _logger.warning("[DovizPlugin] parse hatası: %s", e)
            kur = _DovizPlugin._SABIT.get(tc,1)/_DovizPlugin._SABIT.get(fc,1)
        return f"💱 **{miktar} {fc} = {miktar*kur:.2f} {tc}** (yaklaşık)"

class _NotAlPlugin(_PluginBase):
    PLUGIN_ISIM = "Hızlı Not"; PLUGIN_VERSIYON = "1.0"
    PLUGIN_ACIKLAMA = "Mesajdan hızlıca not çıkarıp kaydeder"
    TETIKLEYICILER = ["not al","kaydet bunu","bunu unutma","not:","hatırlat bunu"]
    @staticmethod
    def calistir(mesaj: str) -> str:
        temiz = re.sub(r"(?i)not al[ı]?|kaydet bunu|bunu unutma|not:|hatırlat bunu","",mesaj).strip()
        if not temiz: return "📝 Ne kaydedeyim? Örnek: 'not al: toplantı saat 15\'te'"
        dosya = Path("beluma_hizli_notlar.json")
        try:
            notlar = json.loads(dosya.read_text(encoding="utf-8")) if dosya.exists() else []
        except (json.JSONDecodeError, OSError) as e:
            _logger.warning("[NotAlPlugin] not dosyası okunamadı: %s", e)
            notlar = []
        notlar.append({"not": temiz, "tarih": time.strftime("%Y-%m-%d %H:%M")})
        dosya.write_text(json.dumps(notlar[-100:], ensure_ascii=False, indent=2), encoding="utf-8")
        return f"📝 **Kaydedildi:** _{temiz}_"

class _KelimeSayarPlugin(_PluginBase):
    PLUGIN_ISIM = "Kelime Sayar"; PLUGIN_VERSIYON = "1.0"
    PLUGIN_ACIKLAMA = "Kelime, karakter ve cümle sayısını hesaplar"
    TETIKLEYICILER = ["kaç kelime","kaç karakter","kelime say","karakter say","kelime sayısı"]
    @staticmethod
    def calistir(mesaj: str) -> str:
        temiz = re.sub(r"(?i)kaç kelime|kaç karakter|kelime say[ı]?|karakter say[ı]?|kelime sayısı|:","",mesaj).strip()
        if len(temiz) < 3: return "📊 Saymamı istediğin metni yaz. Örnek: 'kelime say: Merhaba dünya'"
        kelimeler = temiz.split()
        cumleler = len(re.findall(r"[.!?]+",temiz)) or 1
        return (f"📊 **Metin Analizi**\n- Kelime: **{len(kelimeler)}**\n"
                f"- Karakter (boşluksuz): **{len(temiz.replace(' ',''))}**\n"
                f"- Karakter (boşluklu): **{len(temiz)}**\n"
                f"- Tahmini cümle: **{cumleler}**")

_GOMULU_PLUGINLER = [_DovizPlugin, _NotAlPlugin, _KelimeSayarPlugin]

def _gomulu_pluginleri_kaydet():
    pasif = _plugin_state_yukle().get("pasif", [])
    with _plugin_lock:
        for cls in _GOMULU_PLUGINLER:
            if cls.PLUGIN_ISIM in pasif:
                _logger.info("[plugin] pasif: %s", cls.PLUGIN_ISIM); continue
            _plugin_registry[cls.PLUGIN_ISIM] = cls
            _logger.info("[plugin] gömülü yüklendi: %s v%s", cls.PLUGIN_ISIM, cls.PLUGIN_VERSIYON)

# Uygulama başlarken hem gömülü hem dosya tabanlı pluginleri yükle
_gomulu_pluginleri_kaydet()
_yuklenen_plugin_sayisi = plugin_yukle_hepsi()
_logger.info("[plugin] toplam %d plugin aktif.", len(_plugin_registry))



# ══════════════════════════════════════════════════════════════════
# WEBHOOK SİSTEMİ
# ══════════════════════════════════════════════════════════════════
import hmac as _hmac

_WEBHOOK_LOCK = threading.Lock()

def _varsayilan_webhooks():
    return {"webhooks": []}

def webhooks_yukle() -> dict:
    return json_yukle(WEBHOOKS_FILE, _varsayilan_webhooks())

def webhooks_kaydet(v: dict) -> None:
    json_kaydet(WEBHOOKS_FILE, v)

# ── Webhook CRUD ──
def webhook_ekle(isim: str, url: str, olaylar: list, secret: str = "") -> str:
    """Yeni webhook kaydı ekle."""
    isim = isim.strip(); url = url.strip()
    if not isim or not url:
        return "⚠️ İsim ve URL zorunlu."
    if not url.startswith("http"):
        return "⚠️ URL http:// veya https:// ile başlamalı."
    v = webhooks_yukle()
    for wh in v["webhooks"]:
        if wh["url"] == url:
            return f"⚠️ Bu URL zaten kayıtlı: {isim}"
    v["webhooks"].append({
        "id":      uuid.uuid4().hex[:8],
        "isim":    isim,
        "url":     url,
        "olaylar": olaylar or ["mesaj"],
        "secret":  secret.strip(),
        "aktif":   True,
        "eklendi": time.strftime("%Y-%m-%d %H:%M"),
        "son_tetik": "",
        "basari":  0,
        "hata":    0,
    })
    webhooks_kaydet(v)
    return f"✅ Webhook eklendi: **{isim}** → `{url}`"

def webhook_sil(wh_id: str) -> str:
    v = webhooks_yukle()
    onceki = len(v["webhooks"])
    v["webhooks"] = [w for w in v["webhooks"] if w["id"] != wh_id.strip()]
    if len(v["webhooks"]) == onceki:
        return "⚠️ Webhook bulunamadı. ID'yi kontrol et."
    webhooks_kaydet(v)
    return f"🗑 Webhook silindi: `{wh_id}`"

def webhook_toggle(wh_id: str) -> str:
    v = webhooks_yukle()
    for wh in v["webhooks"]:
        if wh["id"] == wh_id.strip():
            wh["aktif"] = not wh.get("aktif", True)
            durum = "aktif" if wh["aktif"] else "pasif"
            webhooks_kaydet(v)
            return f"{'▶️' if wh['aktif'] else '⏸'} **{wh['isim']}** {durum} yapıldı."
    return "⚠️ Webhook bulunamadı."

def webhook_listesi_metin() -> str:
    v = webhooks_yukle()
    whl = v.get("webhooks", [])
    if not whl:
        return "Kayıtlı webhook yok. Aşağıdan ekleyebilirsin."
    satirlar = []
    for wh in whl:
        durum  = "✅" if wh.get("aktif", True) else "⏸"
        olaylar = ", ".join(wh.get("olaylar", []))
        satirlar.append(
            f"{durum} **[{wh['id']}] {wh['isim']}**\n"
            f"   URL: `{wh['url']}`\n"
            f"   Olaylar: `{olaylar}` | Başarı: {wh.get('basari',0)} | Hata: {wh.get('hata',0)}\n"
            f"   Son: {wh.get('son_tetik','—')}"
        )
    return "\n\n".join(satirlar)

# ── İmza ──
def _webhook_imza(payload: str, secret: str) -> str:
    """HMAC-SHA256 imzası üret."""
    if not secret:
        return ""
    return "sha256=" + _hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        "sha256"
    ).hexdigest()

# ── Gönderici ──
def _webhook_gonder_tek(wh: dict, payload: dict, deneme: int = 0) -> bool:
    """Tek bir webhook'a POST at. Başarılıysa True döner."""
    try:
        body    = json.dumps(payload, ensure_ascii=False)
        headers = {
            "Content-Type":  "application/json",
            "User-Agent":    "BELUMA-I/1.0",
            "X-Beluma-Event": payload.get("olay", "mesaj"),
        }
        imza = _webhook_imza(body, wh.get("secret", ""))
        if imza:
            headers["X-Beluma-Signature"] = imza

        r = requests.post(wh["url"], data=body, headers=headers,
                          timeout=WEBHOOK_TIMEOUT)
        if r.status_code < 400:
            _logger.info("[webhook] ✅ %s → %s (%d)", wh["isim"], wh["url"], r.status_code)
            return True
        else:
            _logger.warning("[webhook] ❌ %s HTTP %d", wh["isim"], r.status_code)
            return False
    except requests.exceptions.Timeout:
        _logger.warning("[webhook] ⏱ timeout: %s", wh["url"])
        _hata_say(f"webhook.timeout.{wh['id']}")
        return False
    except requests.RequestException as e:
        _logger.warning("[webhook] ❌ %s: %s", wh["isim"], e)
        _hata_say(f"webhook.hata.{wh['id']}")
        return False

def _webhook_retry(wh: dict, payload: dict) -> None:
    """Exponential backoff ile retry."""
    for deneme in range(WEBHOOK_RETRY_MAX):
        if _webhook_gonder_tek(wh, payload, deneme):
            return
        if deneme < WEBHOOK_RETRY_MAX - 1:
            time.sleep(2 ** deneme)
    _logger.error("[webhook] %d denemeden sonra başarısız: %s", WEBHOOK_RETRY_MAX, wh["isim"])

def webhook_tetikle(olay: str, veri: dict) -> None:
    """
    OPT: İstatistik güncellemesi için çift webhooks_yukle() → tek okumaya indirildi.
    Webhook yoksa thread bile açılmıyor.
    """
    # Hızlı ön kontrol — webhook yoksa thread açma
    v = webhooks_yukle()
    aktif_whl = [w for w in v.get("webhooks", [])
                 if w.get("aktif", True) and olay in w.get("olaylar", ["mesaj"])]
    if not aktif_whl:
        return

    def _gonder_hepsi():
        payload = {
            "olay":   olay,
            "zaman":  time.strftime("%Y-%m-%d %H:%M:%S"),
            "kaynak": "BELUMA-I",
            **veri
        }
        guncellendi = webhooks_yukle()  # tek okuma
        degisti = False
        for wh in aktif_whl:
            basarili = False
            for deneme in range(WEBHOOK_RETRY_MAX):
                if _webhook_gonder_tek(wh, payload, deneme):
                    basarili = True; break
                if deneme < WEBHOOK_RETRY_MAX - 1:
                    time.sleep(2 ** deneme)
            # Aynı veri üzerinde istatistik güncelle
            with _WEBHOOK_LOCK:
                for w in guncellendi["webhooks"]:
                    if w["id"] == wh["id"]:
                        if basarili: w["basari"] = w.get("basari", 0) + 1
                        else:        w["hata"]   = w.get("hata", 0) + 1
                        w["son_tetik"] = time.strftime("%Y-%m-%d %H:%M")
                        degisti = True; break
            if degisti:
                webhooks_kaydet(guncellendi)

    _THREAD_POOL.submit(_gonder_hepsi)

def webhook_test_gonder(wh_id: str) -> str:
    """Seçili webhook'a test payload gönder."""
    v = webhooks_yukle()
    wh = next((w for w in v["webhooks"] if w["id"] == wh_id.strip()), None)
    if not wh:
        return "⚠️ Webhook bulunamadı."
    payload = {
        "olay":    "test",
        "zaman":   time.strftime("%Y-%m-%d %H:%M:%S"),
        "kaynak":  "BELUMA-I",
        "mesaj":   "Bu bir test mesajıdır.",
        "cevap":   "BELUMA-I webhook testi başarılı!"
    }
    basarili = _webhook_gonder_tek(wh, payload)
    if basarili:
        return f"✅ Test başarılı! **{wh['isim']}** webhook'una ulaşıldı."
    return f"❌ Test başarısız. URL'i ve sunucunu kontrol et: `{wh['url']}`"



# ══════════════════════════════════════════════════════════════════
# BİLDİRİM & HATIRLATICI SİSTEMİ
# ══════════════════════════════════════════════════════════════════
_HATIRLATICI_LOCK    = threading.Lock()
_bildirim_kuyrugu    = []   # {"mesaj": ..., "zaman": ...}
_BLD_KUYRUK_LOCK     = threading.Lock()

# ── Veri modeli ──
def _varsayilan_hatirlaticilar():
    return {"hatirlaticilar": [], "gecmis": []}

def hatirlaticilar_yukle() -> dict:
    return json_yukle(HATIRLATICI_FILE, _varsayilan_hatirlaticilar())

def hatirlaticilar_kaydet(v: dict) -> None:
    json_kaydet(HATIRLATICI_FILE, v)

# ── Zaman ayrıştırıcı ──
def _zaman_hesapla(ifade: str) -> Optional[str]:
    """
    Kullanıcı ifadesini gelecek zaman damgasına çevirir.
    Örnekler:
      "15 dakika sonra"  → şimdiden 15 dakika sonra
      "2 saat sonra"     → şimdiden 2 saat sonra
      "yarın 09:00"      → yarın sabah 09:00
      "her gün 08:30"    → tekrarlayan (günlük)
      "2025-12-31 10:00" → tam tarih/saat
    """
    now    = _dt.datetime.now()
    ifade  = ifade.strip().lower()

    # "X dakika/saat/gün sonra"
    m = re.search(r"(\d+)\s*(dakika|saat|gün|gun)", ifade)
    if m:
        miktar = int(m.group(1))
        birim  = m.group(2)
        delta  = {"dakika": _dt.timedelta(minutes=miktar),
                  "saat":   _dt.timedelta(hours=miktar),
                  "gün":    _dt.timedelta(days=miktar),
                  "gun":    _dt.timedelta(days=miktar)}.get(birim)
        if delta:
            hedef = now + delta
            return hedef.strftime("%Y-%m-%d %H:%M")

    # "yarın HH:MM"
    if "yarın" in ifade or "yarin" in ifade:
        m2 = re.search(r"(\d{1,2})[:\.](\d{2})", ifade)
        if m2:
            hedef = (now + _dt.timedelta(days=1)).replace(
                hour=int(m2.group(1)), minute=int(m2.group(2)), second=0)
            return hedef.strftime("%Y-%m-%d %H:%M")
        hedef = (now + _dt.timedelta(days=1)).replace(hour=9, minute=0, second=0)
        return hedef.strftime("%Y-%m-%d %H:%M")

    # "bugün HH:MM"
    if "bugün" in ifade or "bugun" in ifade:
        m3 = re.search(r"(\d{1,2})[:\.](\d{2})", ifade)
        if m3:
            hedef = now.replace(hour=int(m3.group(1)), minute=int(m3.group(2)), second=0)
            if hedef <= now:
                hedef += _dt.timedelta(days=1)
            return hedef.strftime("%Y-%m-%d %H:%M")

    # Doğrudan "HH:MM" veya "YYYY-MM-DD HH:MM"
    m4 = re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})", ifade)
    if m4:
        return f"{m4.group(1)} {m4.group(2)}"

    m5 = re.search(r"(\d{1,2})[:\.](\d{2})", ifade)
    if m5:
        hedef = now.replace(hour=int(m5.group(1)), minute=int(m5.group(2)), second=0)
        if hedef <= now:
            hedef += _dt.timedelta(days=1)
        return hedef.strftime("%Y-%m-%d %H:%M")

    return None

def _tekrar_mi(ifade: str) -> str:
    """Tekrarlama türünü belirle: 'günlük', 'haftalık', '' """
    k = ifade.lower()
    if any(x in k for x in ["her gün","her gun","günlük","gunluk","daily"]): return "günlük"
    if any(x in k for x in ["her hafta","haftalık","haftalik","weekly"]):     return "haftalık"
    return ""

# ── CRUD ──
def hatirlatici_ekle(mesaj: str, zaman_ifade: str) -> str:
    mesaj = mesaj.strip()
    if not mesaj:
        return "⚠️ Hatırlatıcı mesajı boş olamaz."
    hedef_zaman = _zaman_hesapla(zaman_ifade)
    if not hedef_zaman:
        return ("⚠️ Zaman anlaşılamadı. Örnekler:\n"
                "- '30 dakika sonra'\n- '2 saat sonra'\n"
                "- 'yarın 09:00'\n- 'bugün 14:30'\n- '2025-12-31 10:00'")
    tekrar = _tekrar_mi(zaman_ifade)
    v = hatirlaticilar_yukle()
    kayit = {
        "id":          uuid.uuid4().hex[:8],
        "mesaj":       mesaj,
        "zaman":       hedef_zaman,
        "tekrar":      tekrar,
        "tamamlandi":  False,
        "olusturuldu": time.strftime("%Y-%m-%d %H:%M"),
    }
    v["hatirlaticilar"].append(kayit)
    hatirlaticilar_kaydet(v)
    tekrar_yazi = f" ({tekrar})" if tekrar else ""
    return f"✅ Hatırlatıcı eklendi: **{mesaj}**\n⏰ Zaman: `{hedef_zaman}`{tekrar_yazi}"

def hatirlatici_sil(h_id: str) -> str:
    v = hatirlaticilar_yukle()
    onceki = len(v["hatirlaticilar"])
    v["hatirlaticilar"] = [h for h in v["hatirlaticilar"] if h["id"] != h_id.strip()]
    if len(v["hatirlaticilar"]) == onceki:
        return "⚠️ Hatırlatıcı bulunamadı."
    hatirlaticilar_kaydet(v)
    return f"🗑 Silindi: `{h_id}`"

def hatirlaticilar_listesi_metin() -> str:
    v  = hatirlaticilar_yukle()
    hl = [h for h in v.get("hatirlaticilar", []) if not h.get("tamamlandi")]
    gc = v.get("gecmis", [])[-5:]
    if not hl and not gc:
        return "Aktif hatırlatıcı yok. Aşağıdan ekleyebilirsin."
    satirlar = []
    if hl:
        satirlar.append("**⏰ Aktif Hatırlatıcılar:**")
        for h in hl:
            tekrar = f" 🔄 {h['tekrar']}" if h.get("tekrar") else ""
            satirlar.append(f"- `[{h['id']}]` **{h['mesaj']}** → `{h['zaman']}`{tekrar}")
    if gc:
        satirlar.append("\n**📋 Son Geçmiş:**")
        for g in reversed(gc):
            satirlar.append(f"- ✓ {g.get('mesaj','')} ({g.get('tetiklendi','')})")
    return "\n".join(satirlar)

# ── Bildirim kuyruğu ──
def bildirim_ekle(mesaj: str) -> None:
    """UI'dan okunacak bildirimi kuyruğa ekle."""
    with _BLD_KUYRUK_LOCK:
        _bildirim_kuyrugu.append({
            "mesaj": mesaj,
            "zaman": time.strftime("%H:%M")
        })
        # Max 20 bildirim tut
        while len(_bildirim_kuyrugu) > 20:
            _bildirim_kuyrugu.pop(0)

def bildirim_kuyrugu_oku() -> str:
    """Kuyruktaki tüm bildirimleri metin olarak döndür."""
    with _BLD_KUYRUK_LOCK:
        if not _bildirim_kuyrugu:
            return ""
        return "\n".join(f"🔔 [{b['zaman']}] {b['mesaj']}" for b in _bildirim_kuyrugu)

def bildirimleri_temizle() -> str:
    with _BLD_KUYRUK_LOCK:
        _bildirim_kuyrugu.clear()
    return "✅ Bildirimler temizlendi."

# ── Arka plan kontrol thread'i ──
def _hatirlatici_kontrol():
    """Her 60 saniyede bir çalışır, zamanı gelen hatırlatıcıları tetikler."""
    while True:
        try:
            simdi = time.strftime("%Y-%m-%d %H:%M")
            v     = hatirlaticilar_yukle()
            degisti = False
            for h in v["hatirlaticilar"]:
                if h.get("tamamlandi"): continue
                if h.get("zaman","") <= simdi:
                    # Bildirim kuyruğuna ekle
                    bildirim_ekle(h["mesaj"])
                    # Webhook tetikle
                    webhook_tetikle("hatirlatici", {
                        "mesaj": h["mesaj"],
                        "zaman": h["zaman"],
                    })
                    _logger.info("[hatirlatici] tetiklendi: %s", h["mesaj"])
                    # Geçmişe ekle
                    gecmis_kayit = {**h, "tetiklendi": simdi}
                    v["gecmis"] = v.get("gecmis", []) + [gecmis_kayit]
                    v["gecmis"] = v["gecmis"][-50:]
                    # Tekrarlıysa bir sonraki zamanı hesapla
                    if h.get("tekrar") == "günlük":
                        sonraki = (_dt.datetime.now() + _dt.timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
                        h["zaman"] = sonraki
                    elif h.get("tekrar") == "haftalık":
                        sonraki = (_dt.datetime.now() + _dt.timedelta(weeks=1)).strftime("%Y-%m-%d %H:%M")
                        h["zaman"] = sonraki
                    else:
                        h["tamamlandi"] = True
                    degisti = True
            if degisti:
                hatirlaticilar_kaydet(v)
        except Exception as e:
            _logger.warning("[hatirlatici_kontrol] %s", e)
            _hata_say("hatirlatici.kontrol")
        time.sleep(60)

# Arka plan thread'ini başlat
_hatirlatici_thread = threading.Thread(
    target=_hatirlatici_kontrol, daemon=True, name="beluma-hatirlatici")
_hatirlatici_thread.start()
_logger.info("[hatirlatici] arka plan thread başlatıldı.")



# ══════════════════════════════════════════════════════════════════
# ÇOKLU DİL DESTEĞİ (i18n)
# ══════════════════════════════════════════════════════════════════

# Desteklenen diller
DESTEKLENEN_DILLER = {
    "tr": "🇹🇷 Türkçe",
    "en": "🇬🇧 English",
    "de": "🇩🇪 Deutsch",
    "fr": "🇫🇷 Français",
    "es": "🇪🇸 Español",
    "ar": "🇸🇦 العربية",
    "ru": "🇷🇺 Русский",
    "ja": "🇯🇵 日本語",
}

# Yerleşik çeviriler
_CEVIRILER: Dict[str, Dict[str, str]] = {
    "tr": {
        "gonder":           "Gönder ✈",
        "yeni_sohbet":      "🔄 Yeni",
        "yukle":            "📂 Yükle",
        "denetle":          "🔍 Denetle",
        "indir":            "📥 İndir",
        "belge":            "📎 Belge",
        "resim":            "🖼️ Resim",
        "mesaj_placeholder":"Mesajını yaz... (Enter → gönder)",
        "hazir":            "Hazır.",
        "yanıtlaniyor":     "Yanıtlanıyor...",
        "yaraticilik":      "🧠 Yaratıcılık",
        "ozel_rol":         "🎭 Özel Rol",
        "uzmanlik":         "🎓 Uzmanlık",
        "adin":             "Adın",
        "ton":              "Ton",
        "stil":             "Stil",
        "model":            "🧠 Model",
        "beni_tani":        "Beni tanı",
        "tercih_notlari":   "Tercih notları",
        "kaydet":           "Kaydet",
        "sohbet_tab":       "💬 Sohbet",
        "gorevler_tab":     "📋 Görevler",
        "gorsel_tab":       "🎨 Görsel Üret",
        "ses_tab":          "🎙 Ses",
        "yasam_tab":        "🗺 Yaşam Haritası",
        "guvenlik_tab":     "🔒 Güvenlik",
        "hakkinda_tab":     "ℹ️ Hakkında",
        "analitik_tab":     "📊 Analitik",
        "plugin_tab":       "🧩 Plugin",
        "webhook_tab":      "🔗 Webhook",
        "hatirlatici_tab":  "🔔 Hatırlatıcı",
        "dil_tab":          "🌍 Dil",
        "deep_research":    "🔍 Deep Research (Derin Araştırma)",
        "sistem_prompt":    "Sen BELUMA-I'sın. Türkçe yanıt ver.",
    },
    "en": {
        "gonder":           "Send ✈",
        "yeni_sohbet":      "🔄 New",
        "yukle":            "📂 Load",
        "denetle":          "🔍 Review",
        "indir":            "📥 Download",
        "belge":            "📎 Document",
        "resim":            "🖼️ Image",
        "mesaj_placeholder":"Type your message... (Enter → send)",
        "hazir":            "Ready.",
        "yanıtlaniyor":     "Responding...",
        "yaraticilik":      "🧠 Creativity",
        "ozel_rol":         "🎭 Custom Role",
        "uzmanlik":         "🎓 Expertise",
        "adin":             "Your Name",
        "ton":              "Tone",
        "stil":             "Style",
        "model":            "🧠 Model",
        "beni_tani":        "Tell me about you",
        "tercih_notlari":   "Preference notes",
        "kaydet":           "Save",
        "sohbet_tab":       "💬 Chat",
        "gorevler_tab":     "📋 Tasks",
        "gorsel_tab":       "🎨 Image Gen",
        "ses_tab":          "🎙 Voice",
        "yasam_tab":        "🗺 Life Map",
        "guvenlik_tab":     "🔒 Security",
        "hakkinda_tab":     "ℹ️ About",
        "analitik_tab":     "📊 Analytics",
        "plugin_tab":       "🧩 Plugins",
        "webhook_tab":      "🔗 Webhooks",
        "hatirlatici_tab":  "🔔 Reminders",
        "dil_tab":          "🌍 Language",
        "deep_research":    "🔍 Deep Research",
        "sistem_prompt":    "You are BELUMA-I. Respond in English.",
    },
    "de": {
        "gonder":           "Senden ✈",
        "yeni_sohbet":      "🔄 Neu",
        "yukle":            "📂 Laden",
        "denetle":          "🔍 Prüfen",
        "indir":            "📥 Herunterladen",
        "belge":            "📎 Dokument",
        "resim":            "🖼️ Bild",
        "mesaj_placeholder":"Nachricht schreiben... (Enter → senden)",
        "hazir":            "Bereit.",
        "yanıtlaniyor":     "Wird beantwortet...",
        "yaraticilik":      "🧠 Kreativität",
        "ozel_rol":         "🎭 Benutzerdefinierte Rolle",
        "uzmanlik":         "🎓 Fachgebiet",
        "adin":             "Dein Name",
        "ton":              "Ton",
        "stil":             "Stil",
        "model":            "🧠 Modell",
        "beni_tani":        "Erzähl mir von dir",
        "tercih_notlari":   "Präferenznotizen",
        "kaydet":           "Speichern",
        "sohbet_tab":       "💬 Chat",
        "gorevler_tab":     "📋 Aufgaben",
        "gorsel_tab":       "🎨 Bildgenerator",
        "ses_tab":          "🎙 Sprache",
        "yasam_tab":        "🗺 Lebenskarte",
        "guvenlik_tab":     "🔒 Sicherheit",
        "hakkinda_tab":     "ℹ️ Über",
        "analitik_tab":     "📊 Analytik",
        "plugin_tab":       "🧩 Plugins",
        "webhook_tab":      "🔗 Webhooks",
        "hatirlatici_tab":  "🔔 Erinnerungen",
        "dil_tab":          "🌍 Sprache",
        "deep_research":    "🔍 Tiefenrecherche",
        "sistem_prompt":    "Du bist BELUMA-I. Antworte auf Deutsch.",
    },
    "fr": {
        "gonder":           "Envoyer ✈",
        "yeni_sohbet":      "🔄 Nouveau",
        "yukle":            "📂 Charger",
        "denetle":          "🔍 Vérifier",
        "indir":            "📥 Télécharger",
        "belge":            "📎 Document",
        "resim":            "🖼️ Image",
        "mesaj_placeholder":"Écrivez votre message... (Entrée → envoyer)",
        "hazir":            "Prêt.",
        "yanıtlaniyor":     "En cours...",
        "yaraticilik":      "🧠 Créativité",
        "ozel_rol":         "🎭 Rôle personnalisé",
        "uzmanlik":         "🎓 Expertise",
        "adin":             "Votre nom",
        "ton":              "Ton",
        "stil":             "Style",
        "model":            "🧠 Modèle",
        "beni_tani":        "Parlez-moi de vous",
        "tercih_notlari":   "Notes de préférence",
        "kaydet":           "Enregistrer",
        "sohbet_tab":       "💬 Chat",
        "gorevler_tab":     "📋 Tâches",
        "gorsel_tab":       "🎨 Génération d'images",
        "ses_tab":          "🎙 Voix",
        "yasam_tab":        "🗺 Carte de vie",
        "guvenlik_tab":     "🔒 Sécurité",
        "hakkinda_tab":     "ℹ️ À propos",
        "analitik_tab":     "📊 Analytique",
        "plugin_tab":       "🧩 Plugins",
        "webhook_tab":      "🔗 Webhooks",
        "hatirlatici_tab":  "🔔 Rappels",
        "dil_tab":          "🌍 Langue",
        "deep_research":    "🔍 Recherche approfondie",
        "sistem_prompt":    "Tu es BELUMA-I. Réponds en français.",
    },
    "es": {
        "gonder":           "Enviar ✈",
        "yeni_sohbet":      "🔄 Nuevo",
        "yukle":            "📂 Cargar",
        "denetle":          "🔍 Revisar",
        "indir":            "📥 Descargar",
        "belge":            "📎 Documento",
        "resim":            "🖼️ Imagen",
        "mesaj_placeholder":"Escribe tu mensaje... (Enter → enviar)",
        "hazir":            "Listo.",
        "yanıtlaniyor":     "Respondiendo...",
        "yaraticilik":      "🧠 Creatividad",
        "ozel_rol":         "🎭 Rol personalizado",
        "uzmanlik":         "🎓 Especialidad",
        "adin":             "Tu nombre",
        "ton":              "Tono",
        "stil":             "Estilo",
        "model":            "🧠 Modelo",
        "beni_tani":        "Cuéntame sobre ti",
        "tercih_notlari":   "Notas de preferencia",
        "kaydet":           "Guardar",
        "sohbet_tab":       "💬 Chat",
        "gorevler_tab":     "📋 Tareas",
        "gorsel_tab":       "🎨 Generador de imágenes",
        "ses_tab":          "🎙 Voz",
        "yasam_tab":        "🗺 Mapa de vida",
        "guvenlik_tab":     "🔒 Seguridad",
        "hakkinda_tab":     "ℹ️ Acerca de",
        "analitik_tab":     "📊 Analítica",
        "plugin_tab":       "🧩 Plugins",
        "webhook_tab":      "🔗 Webhooks",
        "hatirlatici_tab":  "🔔 Recordatorios",
        "dil_tab":          "🌍 Idioma",
        "deep_research":    "🔍 Investigación profunda",
        "sistem_prompt":    "Eres BELUMA-I. Responde en español.",
    },
    "ar": {
        "gonder":           "إرسال ✈",
        "yeni_sohbet":      "🔄 جديد",
        "yukle":            "📂 تحميل",
        "denetle":          "🔍 مراجعة",
        "indir":            "📥 تنزيل",
        "belge":            "📎 مستند",
        "resim":            "🖼️ صورة",
        "mesaj_placeholder":"اكتب رسالتك... (Enter → إرسال)",
        "hazir":            "جاهز.",
        "yanıtlaniyor":     "جارٍ الرد...",
        "yaraticilik":      "🧠 الإبداع",
        "ozel_rol":         "🎭 دور مخصص",
        "uzmanlik":         "🎓 التخصص",
        "adin":             "اسمك",
        "ton":              "النبرة",
        "stil":             "الأسلوب",
        "model":            "🧠 النموذج",
        "beni_tani":        "أخبرني عنك",
        "tercih_notlari":   "ملاحظات التفضيل",
        "kaydet":           "حفظ",
        "sohbet_tab":       "💬 محادثة",
        "gorevler_tab":     "📋 مهام",
        "gorsel_tab":       "🎨 توليد صور",
        "ses_tab":          "🎙 صوت",
        "yasam_tab":        "🗺 خريطة الحياة",
        "guvenlik_tab":     "🔒 أمان",
        "hakkinda_tab":     "ℹ️ حول",
        "analitik_tab":     "📊 تحليلات",
        "plugin_tab":       "🧩 ملحقات",
        "webhook_tab":      "🔗 Webhooks",
        "hatirlatici_tab":  "🔔 تذكيرات",
        "dil_tab":          "🌍 اللغة",
        "deep_research":    "🔍 بحث معمق",
        "sistem_prompt":    "أنت BELUMA-I. أجب باللغة العربية.",
    },
    "ru": {
        "gonder":           "Отправить ✈",
        "yeni_sohbet":      "🔄 Новый",
        "yukle":            "📂 Загрузить",
        "denetle":          "🔍 Проверить",
        "indir":            "📥 Скачать",
        "belge":            "📎 Документ",
        "resim":            "🖼️ Изображение",
        "mesaj_placeholder":"Напишите сообщение... (Enter → отправить)",
        "hazir":            "Готово.",
        "yanıtlaniyor":     "Отвечаю...",
        "yaraticilik":      "🧠 Творчество",
        "ozel_rol":         "🎭 Роль",
        "uzmanlik":         "🎓 Специализация",
        "adin":             "Ваше имя",
        "ton":              "Тон",
        "stil":             "Стиль",
        "model":            "🧠 Модель",
        "beni_tani":        "Расскажите о себе",
        "tercih_notlari":   "Заметки о предпочтениях",
        "kaydet":           "Сохранить",
        "sohbet_tab":       "💬 Чат",
        "gorevler_tab":     "📋 Задачи",
        "gorsel_tab":       "🎨 Генерация изображений",
        "ses_tab":          "🎙 Голос",
        "yasam_tab":        "🗺 Карта жизни",
        "guvenlik_tab":     "🔒 Безопасность",
        "hakkinda_tab":     "ℹ️ О приложении",
        "analitik_tab":     "📊 Аналитика",
        "plugin_tab":       "🧩 Плагины",
        "webhook_tab":      "🔗 Вебхуки",
        "hatirlatici_tab":  "🔔 Напоминания",
        "dil_tab":          "🌍 Язык",
        "deep_research":    "🔍 Глубокий поиск",
        "sistem_prompt":    "Ты BELUMA-I. Отвечай на русском языке.",
    },
    "ja": {
        "gonder":           "送信 ✈",
        "yeni_sohbet":      "🔄 新規",
        "yukle":            "📂 読込",
        "denetle":          "🔍 確認",
        "indir":            "📥 ダウンロード",
        "belge":            "📎 ドキュメント",
        "resim":            "🖼️ 画像",
        "mesaj_placeholder":"メッセージを入力... (Enter → 送信)",
        "hazir":            "準備完了.",
        "yanıtlaniyor":     "応答中...",
        "yaraticilik":      "🧠 創造性",
        "ozel_rol":         "🎭 カスタムロール",
        "uzmanlik":         "🎓 専門分野",
        "adin":             "お名前",
        "ton":              "トーン",
        "stil":             "スタイル",
        "model":            "🧠 モデル",
        "beni_tani":        "自己紹介",
        "tercih_notlari":   "好みのメモ",
        "kaydet":           "保存",
        "sohbet_tab":       "💬 チャット",
        "gorevler_tab":     "📋 タスク",
        "gorsel_tab":       "🎨 画像生成",
        "ses_tab":          "🎙 音声",
        "yasam_tab":        "🗺 ライフマップ",
        "guvenlik_tab":     "🔒 セキュリティ",
        "hakkinda_tab":     "ℹ️ について",
        "analitik_tab":     "📊 分析",
        "plugin_tab":       "🧩 プラグイン",
        "webhook_tab":      "🔗 Webhook",
        "hatirlatici_tab":  "🔔 リマインダー",
        "dil_tab":          "🌍 言語",
        "deep_research":    "🔍 ディープリサーチ",
        "sistem_prompt":    "あなたはBELUMA-Iです。日本語で回答してください。",
    },
}

# ── i18n çekirdek ──
_aktif_dil_cache = {"dil": VARSAYILAN_DIL}

def dil_ayarla(dil_kodu: str) -> None:
    """Aktif dili değiştir ve profile kaydet."""
    if dil_kodu not in DESTEKLENEN_DILLER:
        return
    _aktif_dil_cache["dil"] = dil_kodu
    pr = profili_yukle()
    pr["dil"] = dil_kodu
    json_kaydet(PROFILE_FILE, pr)

def dil_al() -> str:
    """Mevcut aktif dil kodunu döndür."""
    if "dil" not in _aktif_dil_cache or not _aktif_dil_cache["dil"]:
        pr = profili_yukle()
        _aktif_dil_cache["dil"] = pr.get("dil", VARSAYILAN_DIL)
    return _aktif_dil_cache["dil"]

def t(anahtar: str, dil: str = "") -> str:
    """
    Çeviri anahtarını mevcut dile göre döndür.
    Bulunamazsa Türkçe fallback, o da yoksa anahtarın kendisi.
    """
    d = dil or dil_al()
    # Önce özel i18n dosyasından dene
    ozel = json_yukle(I18N_FILE, {})
    if d in ozel and anahtar in ozel[d]:
        return ozel[d][anahtar]
    # Yerleşik çevirilerden al
    return _CEVIRILER.get(d, {}).get(anahtar) or _CEVIRILER["tr"].get(anahtar, anahtar)

def sistem_promptu_dil_eki(dil: str) -> str:
    """Model cevaplarını seçili dile yönlendiren sistem prompt eki."""
    return _CEVIRILER.get(dil, {}).get("sistem_prompt", "")

def dil_secici_guncelle(secilen_dil_etiketi: str) -> tuple:
    """Dropdown seçiminden dil kodunu ayıkla ve uygula."""
    for kod, etiket in DESTEKLENEN_DILLER.items():
        if etiket == secilen_dil_etiketi or kod == secilen_dil_etiketi:
            dil_ayarla(kod)
            return f"✅ Dil değiştirildi: {etiket}", kod
    return "⚠️ Dil bulunamadı.", dil_al()

def mevcut_dil_etiketi() -> str:
    return DESTEKLENEN_DILLER.get(dil_al(), "🇹🇷 Türkçe")



# ══════════════════════════════════════════════════════════════════
# ÇOKLU KULLANICI / EKİP MODU
# ══════════════════════════════════════════════════════════════════
_USERS_LOCK = threading.Lock()
_aktif_kullanici_cache = {"kullanici_adi": ""}

# ── Veri modelleri ──
def _varsayilan_users():
    return {"kullanicilar": []}

def _varsayilan_team():
    return {
        "ortak_notlar":   [],
        "ortak_gorevler": [],
        "duyurular":      [],
        "aktivite":       [],
    }

def users_yukle() -> dict:
    """OPT: 10 saniyelik cache — auth kontrolleri sık çağırır."""
    with _USERS_LOCK:
        if time.time() - _USERS_CACHE["zaman"] < _IO_CACHE_TTL and _USERS_CACHE["veri"] is not None:
            return _USERS_CACHE["veri"]
        veri = json_yukle(USERS_FILE, _varsayilan_users())
        _USERS_CACHE.update({"veri": veri, "zaman": time.time()})
        return veri

def users_kaydet(v: dict) -> None:
    with _USERS_LOCK:
        json_kaydet(USERS_FILE, v)
        _USERS_CACHE.update({"veri": v, "zaman": time.time()})

def team_yukle() -> dict:
    """OPT: 10 saniyelik cache."""
    if time.time() - _TEAM_CACHE["zaman"] < _IO_CACHE_TTL and _TEAM_CACHE["veri"] is not None:
        return _TEAM_CACHE["veri"]
    veri = json_yukle(TEAM_FILE, _varsayilan_team())
    _TEAM_CACHE.update({"veri": veri, "zaman": time.time()})
    return veri

def team_kaydet(v: dict) -> None:
    json_kaydet(TEAM_FILE, v)
    _TEAM_CACHE.update({"veri": v, "zaman": time.time()})

# ── Kullanıcı yönetimi ──
def kullanici_ekle(kullanici_adi: str, sifre: str, rol: str = "editor",
                   ad: str = "", email: str = "") -> str:
    kullanici_adi = kullanici_adi.strip()
    if not kullanici_adi or not sifre:
        return "⚠️ Kullanıcı adı ve şifre zorunlu."
    if rol not in ROLLER:
        return f"⚠️ Geçersiz rol. Seçenekler: {', '.join(ROLLER)}"
    v = users_yukle()
    for u in v["kullanicilar"]:
        if u["kullanici_adi"] == kullanici_adi:
            return f"⚠️ '{kullanici_adi}' zaten kayıtlı."
    v["kullanicilar"].append({
        "kullanici_adi": kullanici_adi,
        "sifre_hash":    _hash_pw(sifre),
        "rol":           rol,
        "ad":            ad.strip(),
        "email":         email.strip(),
        "olusturuldu":   time.strftime("%Y-%m-%d %H:%M"),
        "son_giris":     "",
        "aktif":         True,
    })
    users_kaydet(v)
    _aktivite_ekle(f"Yeni kullanıcı eklendi: {kullanici_adi} ({rol})", "sistem")
    return f"✅ Kullanıcı eklendi: **{kullanici_adi}** [{rol}]"

def kullanici_sil(kullanici_adi: str, yapan: str = "") -> str:
    v = users_yukle()
    hedef = next((u for u in v["kullanicilar"] if u["kullanici_adi"] == kullanici_adi.strip()), None)
    if not hedef:
        return f"⚠️ '{kullanici_adi}' bulunamadı."
    if hedef.get("rol") == "admin":
        adminler = [u for u in v["kullanicilar"] if u.get("rol") == "admin" and u.get("aktif")]
        if len(adminler) <= 1:
            return "⚠️ Son admin silinemez."
    v["kullanicilar"] = [u for u in v["kullanicilar"] if u["kullanici_adi"] != kullanici_adi.strip()]
    users_kaydet(v)
    _aktivite_ekle(f"Kullanıcı silindi: {kullanici_adi}", yapan or "sistem")
    return f"🗑 Silindi: **{kullanici_adi}**"

def kullanici_rol_degistir(kullanici_adi: str, yeni_rol: str, yapan: str = "") -> str:
    if yeni_rol not in ROLLER:
        return f"⚠️ Geçersiz rol: {yeni_rol}"
    v = users_yukle()
    for u in v["kullanicilar"]:
        if u["kullanici_adi"] == kullanici_adi.strip():
            eski_rol = u["rol"]
            u["rol"] = yeni_rol
            users_kaydet(v)
            _aktivite_ekle(f"{kullanici_adi} rolü {eski_rol}→{yeni_rol}", yapan or "sistem")
            return f"✅ **{kullanici_adi}**: {eski_rol} → {yeni_rol}"
    return f"⚠️ '{kullanici_adi}' bulunamadı."

def kullanici_dogrula(kullanici_adi: str, sifre: str) -> Optional[dict]:
    """Giriş doğrulama — başarılıysa kullanıcı dict'i döner."""
    v = users_yukle()
    for u in v["kullanicilar"]:
        if (u["kullanici_adi"] == kullanici_adi and
                u["sifre_hash"] == _hash_pw(sifre) and
                u.get("aktif", True)):
            # Son giriş güncelle
            u["son_giris"] = time.strftime("%Y-%m-%d %H:%M")
            users_kaydet(v)
            return u
    return None

def aktif_kullanici_ayarla(kullanici_adi: str) -> None:
    _aktif_kullanici_cache["kullanici_adi"] = kullanici_adi

def aktif_kullanici_al() -> str:
    return _aktif_kullanici_cache.get("kullanici_adi", "")

def aktif_kullanici_bilgisi() -> Optional[dict]:
    ka = aktif_kullanici_al()
    if not ka: return None
    v = users_yukle()
    return next((u for u in v["kullanicilar"] if u["kullanici_adi"] == ka), None)

def rol_kontrol(gereken_rol: str) -> bool:
    """Aktif kullanıcının rolü yeterli mi?"""
    sira = {"admin": 3, "editor": 2, "viewer": 1}
    u = aktif_kullanici_bilgisi()
    if not u: return False
    return sira.get(u.get("rol", "viewer"), 0) >= sira.get(gereken_rol, 99)

# ── Kullanıcı listesi ──
def kullanici_listesi_metin() -> str:
    v  = users_yukle()
    ul = v.get("kullanicilar", [])
    if not ul:
        return "Kayıtlı kullanıcı yok."
    rol_emoji = {"admin": "👑", "editor": "✏️", "viewer": "👁"}
    satirlar = ["**Kullanıcılar:**"]
    for u in ul:
        durum  = "🟢" if u.get("aktif", True) else "🔴"
        emoji  = rol_emoji.get(u.get("rol","viewer"), "👤")
        giris  = u.get("son_giris", "—")
        satirlar.append(
            f"{durum} {emoji} **{u['kullanici_adi']}** [{u.get('rol','?')}]"
            f"  ·  Son giriş: {giris}"
        )
    return "\n".join(satirlar)

# ── Aktivite logu ──
def _aktivite_ekle(mesaj: str, kullanici: str = "") -> None:
    v = team_yukle()
    v["aktivite"].append({
        "mesaj":     mesaj,
        "kullanici": kullanici or aktif_kullanici_al() or "sistem",
        "zaman":     time.strftime("%Y-%m-%d %H:%M"),
    })
    v["aktivite"] = v["aktivite"][-100:]
    team_kaydet(v)

def aktivite_logu_metin(n: int = 10) -> str:
    v  = team_yukle()
    al = v.get("aktivite", [])[-n:]
    if not al: return "Henüz aktivite yok."
    return "\n".join(
        f"[{a['zaman']}] **{a['kullanici']}**: {a['mesaj']}"
        for a in reversed(al)
    )

# ── Ortak alan ──
def ortak_not_ekle(metin: str) -> str:
    if not (metin or "").strip():
        return "⚠️ Not boş olamaz."
    v = team_yukle()
    v["ortak_notlar"].append({
        "metin":     metin.strip(),
        "kullanici": aktif_kullanici_al() or "anonim",
        "zaman":     time.strftime("%Y-%m-%d %H:%M"),
    })
    v["ortak_notlar"] = v["ortak_notlar"][-200:]
    team_kaydet(v)
    _aktivite_ekle(f"Ortak not ekledi: {metin[:40]}")
    return f"✅ Not eklendi."

def ortak_notlar_metin() -> str:
    v  = team_yukle()
    nl = v.get("ortak_notlar", [])[-10:]
    if not nl: return "Ortak not yok."
    return "\n\n".join(
        f"**{n['kullanici']}** [{n['zaman']}]:\n{n['metin']}"
        for n in reversed(nl)
    )

def duyuru_ekle(metin: str) -> str:
    if not rol_kontrol("admin"):
        return "⚠️ Sadece adminler duyuru ekleyebilir."
    if not (metin or "").strip():
        return "⚠️ Duyuru boş olamaz."
    v = team_yukle()
    v["duyurular"].append({
        "metin":     metin.strip(),
        "kullanici": aktif_kullanici_al() or "admin",
        "zaman":     time.strftime("%Y-%m-%d %H:%M"),
    })
    v["duyurular"] = v["duyurular"][-20:]
    team_kaydet(v)
    webhook_tetikle("duyuru", {"metin": metin.strip()})
    return "📢 Duyuru yayınlandı."

def duyurular_metin() -> str:
    v  = team_yukle()
    dl = v.get("duyurular", [])[-5:]
    if not dl: return ""
    return "📢 **Duyurular:**\n" + "\n".join(
        f"- [{d['zaman']}] {d['metin']}"
        for d in reversed(dl)
    )

# ── Gradio auth entegrasyonu ──
def gradio_auth_genisletilmis(username: str, password: str) -> bool:
    """
    Hem eski tek kullanıcı auth hem de çoklu kullanıcı sistemini destekler.
    Önce users.json'u dener, sonra legacy auth'a düşer.
    """
    # Çoklu kullanıcı sistemi
    u = kullanici_dogrula(username, password)
    if u:
        aktif_kullanici_ayarla(username)
        _aktivite_ekle(f"Giriş yaptı", username)
        return True
    # Legacy tek kullanıcı
    return _gradio_auth(username, password)



def aylik_rapor_olustur():
    d=haritayi_yukle(); h=d.get("hedefler",[]); n=d.get("gunluk_notlar",[])
    t,tm=len(h),sum(1 for x in h if x.get("tamamlandi"))
    o=(tm/t*100) if t else 0
    a=_agent_cagir(f"Performans: {t} hedef, {tm} tamam, %{o:.1f}\nBekleyen: {[x['hedef'] for x in h if not x.get('tamamlandi')][:5]}\nNotlar: {[x['not'] for x in n[-5:]]}\n\n3 madde: 1) Yorum 2) Sorunlar 3) Öneri.",400)
    return f"📊 **Aylık Rapor**\n\n✅ **%{o:.1f}** ({tm}/{t})\n\n{a}"

# ══════════════════════════════════════════════════════════════════
# GÖRSEL ÜRET
# ══════════════════════════════════════════════════════════════════
def _prompt_guclendir(p,stil):
    return f"({p.strip()}:1.3), {GORSEL_STILLER.get(stil,GORSEL_STILLER['Gerçekçi'])}, highest detailed, 8k, no text, no watermark, no signature"

def _negatif_prompt():
    return "text, watermark, low quality, deformed, duplicate, lowres, ugly, blurry, artist name, signature, (username:1.3), amateur"

def _gorseli_kaydet(image,seed):
    yol=Path(tempfile.gettempdir())/f"beluma_{int(time.time())}_{seed}.png"; image.save(str(yol)); return str(yol)

def add_watermark(image_path, text="BELUMA-I", position="bottom-right", opacity=128):
    try:
        from PIL import Image as _I, ImageDraw as _D, ImageFont as _F
        img=_I.open(image_path).convert("RGBA"); w,h=img.size; fs=max(14,int(min(w,h)*0.025))
        try: font=_F.truetype("arial.ttf",fs)
        except OSError: font=_F.load_default()
        ov=_I.new("RGBA",img.size,(255,255,255,0)); dr=_D.Draw(ov)
        bb=dr.textbbox((0,0),text,font=font); tw,th=bb[2]-bb[0],bb[3]-bb[1]; m=int(min(w,h)*0.02)
        x=w-tw-m if "right" in position else m; y=h-th-m if "bottom" in position else m
        dr.text((x,y),text,fill=(255,255,255,opacity),font=font)
        _I.alpha_composite(img,ov).convert("RGB").save(image_path)
    except Exception as e: _logger.warning("[watermark] %s",e)

def gorsel_prompt_muhendisi(kullanici_istegi):
    client = get_groq_client()
    if not client: return kullanici_istegi
    try:
        r = client.chat.completions.create(
            model=AGENT_MODEL,
            messages=[{"role":"user","content":f"""Sen 'Görsel Komut Uzmanı'sın. FLUX için kusursuz prompt yap.
TALİMATLAR:
1. ANA KONU: Sadece kullanıcı ne istediyse onu çiz.
2. RENK: Belirtilen renkleri GÖZE ÇARPAN vurgula.
3. ARKA PLAN: Düz stüdyo veya doğa. ASLA bina/mimari ekleme.
4. YASAKLAR: Mimari, sütun, bina, yazı KESİNLİKLE OLMASIN.
İstek: "{kullanici_istegi}"
Sadece İngilizce, virgülle ayrılmış teknik çıktı:"""}],
            temperature=0.2, max_tokens=250)
        s = icerik_temizle(r.choices[0].message.content).strip()
        return s if s else kullanici_istegi
    except Exception as e: _logger.warning("[prompt_eng] %s",e); return kullanici_istegi

def generate_single(prompt, style, guidance=9.0, seed=None):
    if seed is None: seed=random.randint(1,999999)
    token=os.environ.get("HF_TOKEN") or HF_TOKEN; fp=_prompt_guclendir(prompt,style); neg=_negatif_prompt()
    for model in IMAGE_MODELS:
        if not model: continue
        try:
            from huggingface_hub import InferenceClient as _IC
            img=_IC(model=model,token=token).text_to_image(fp,negative_prompt=neg,guidance_scale=guidance,num_inference_steps=25,seed=seed)
            return _gorseli_kaydet(img,seed),f"✅ Üretildi ({model.split('/')[-1]}, seed:{seed})",model,seed
        except ImportError:
            try:
                r=requests.post(f"https://api-inference.huggingface.co/models/{model}",
                                headers={"Authorization":f"Bearer {token}"},json={"inputs":fp},timeout=90)
                if r.status_code==200:
                    from PIL import Image as _PI; import io as _io
                    return _gorseli_kaydet(_PI.open(_io.BytesIO(r.content)),seed),"✅ Üretildi",model,seed
            except Exception as e: _logger.warning("[img/api] %s",e)
            break
        except Exception as e:
            err=str(e)
            if "503" in err or "loading" in err.lower():
                _logger.info("[img] model yükleniyor, sonraki deneniyor: %s", model); continue
            if "429" in err:
                _logger.warning("[img] rate limit: %s", model); _hata_say("gorsel.rate_limit"); time.sleep(2); continue
            _logger.error("[img] beklenmeyen hata (%s): %s", model, err[:120]); _hata_say("gorsel.genel")
    return None,"❌ Tüm modeller başarısız.",None,seed

# ══════════════════════════════════════════════════════════════════
# OPTİMİZASYON 3 — generate_variations Semaphore ile Rate Limit Koruması
# Eski davranış: 4 istek aynı anda atılıyordu, rate limit patlaması riski.
# Yeni davranış: Semaphore(2) ile en fazla 2 eşzamanlı istek → HF API'yi aşmaz.
#               Ayrıca başarısız worker'lar artık sessizce yutulmak yerine
#               loglanıyor (hata ayıklama kolaylaşır).
# ══════════════════════════════════════════════════════════════════
_img_semaphore = threading.Semaphore(2)  # aynı anda max 2 görsel isteği

def generate_variations(prompt, style, guidance=9.0, count=4):
    seeds   = [random.randint(1,999999) for _ in range(count)]
    results = [None] * count

    def _safe_generate(i):
        with _img_semaphore:
            return generate_single(prompt, style, guidance, seeds[i])

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(count,4)) as ex:
        fs = {ex.submit(_safe_generate, i): i for i in range(count)}
        for f in concurrent.futures.as_completed(fs):
            idx = fs[f]
            try:
                img_path, msg, _, _ = f.result()
                results[idx] = img_path
            except Exception as e:
                _logger.error("[var][%d] %s", idx, e)

    valid = [r for r in results if r]
    return (valid, f"✅ {len(valid)}/{count} varyasyon") if valid else (None, "❌ Üretilemedi.")

# ══════════════════════════════════════════════════════════════════
# SES
# ══════════════════════════════════════════════════════════════════
def sesi_yaziya_cevir(audio_file):
    if not audio_file: return "","Ses kaydı yükle."
    client = get_groq_client()
    if not client: return "","GROQ_API_KEY gerekli."
    path = Path(str(audio_file))
    if not path.exists(): return "","Dosya yok."
    try:
        with path.open("rb") as f:
            t = client.audio.transcriptions.create(
                file=(path.name,f.read()), model=TRANSCRIBE_MODEL,
                response_format="verbose_json", language="tr")
        m = metni_temizle(getattr(t,"text","") or t.get("text",""))
        return (m,"✅ Çevrildi.") if m else ("","Metin çıkmadı.")
    except (OSError,AttributeError) as e: _logger.warning("[stt] %s",e); return "",f"Hata: {e}"

def metni_seslendir(metin):
    t=(metin or "").strip()
    if not t: return None,"Metin yok."
    try:
        tmp=Path(tempfile.gettempdir())/f"beluma_tts_{int(time.time())}.mp3"; gTTS(text=t,lang="tr").save(str(tmp))
        return str(tmp),"✅ Ses hazır (temel)."
    except Exception as e: _logger.warning("[tts] %s",e); return None,f"Hata: {e}"

def metni_seslendir_premium(metin, model_id="fishaudio/fish-speech-1.4"):
    token=os.environ.get("HF_TOKEN") or HF_TOKEN; t=(metin or "").strip()[:400]
    if not t: return None,"Metin yok."
    if _GradioClient and token:
        try:
            gc=_GradioClient("artificialguybr/fish-s2-pro-zero",hf_token=token)
            res=gc.predict(text=t,ref_audio=None,ref_text="",max_new_tokens=1024,chunk_length=200,top_p=0.7,repetition_penalty=1.2,temperature=0.7,api_name="/predict")
            sy=res[0] if isinstance(res,(tuple,list)) else res
            if sy: return str(sy),"✅ Ses hazır (Fish Speech)."
        except Exception as e: _logger.warning("[premium/gradio] %s",e)
    if token:
        try:
            r=requests.post(f"https://api-inference.huggingface.co/models/{model_id}",
                           headers={"Authorization":f"Bearer {token}"},json={"inputs":t},timeout=25)
            if r.status_code==200 and len(r.content)>1000:
                tmp=Path(tempfile.gettempdir())/f"beluma_ptts_{int(time.time())}.mp3"; tmp.write_bytes(r.content)
                return str(tmp),"✅ Ses hazır (HF API)."
        except Exception as e: _logger.warning("[premium/hf] %s",e)
    return metni_seslendir(t)

# ══════════════════════════════════════════════════════════════════
# SİSTEM PROMPTU & MESAJ HAZIRLAMA
# ══════════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """Sen BELUMA-I'sın — BELUMA Group Kurucusu Özgür tarafından tasarlanmış, Türkiye merkezli, güvenilir, analitik ve insan odaklı bir yapay zeka asistanısın.

TEMEL İLKELERİN:
- Analitik düşün: Karmaşık sorunları parçalara ayır, mantıklı ve tutarlı şekilde çöz.
- Araştırmacı ol: Verilen bilgi, belge ve kaynakları sentezle; eksik veri varsa bunu açıkça belirt.
- Dürüst ol: Emin olmadığın konularda kesin konuşma; bilmediğini biliyormuş gibi yapma.
- Güvenli davran: Zararlı, yasa dışı, manipülatif veya yanıltıcı içerik üretme.

İLETİŞİM KURALLARIN:
- Doğal, akıcı Türkçe. ASLA İngilizce kelime kullanma.
- ASLA JSON/dict/teknik format döndürme. Düz Türkçe metin.
- Kısa ve net. Max 3 paragraf veya 4 madde. Aynı fikri tekrarlama.
- Gereksiz teknik jargon kullanma. Kullanıcı istemedikçe ham araç çıktısı dökme.
- Araç bilgi döndürdüyse ek açıklama ekleme.
- Matematik/mantık sorusunda ezbere cevap verme, adım adım düşün.
- Kaynak yoksa uydurma bilgi üretme.
- Tıbbi, hukuki, finansal konularda temkinli ol.
- İnternete erişimin var. Asla 'internete erişemiyorum' veya 'gerçek zamanlı veri sağlayamam' deme.
- Anthropic, OpenAI veya başka şirketlerle ilişkilendirme yapma. Seni soran olursa kısaca ve doğal bir dille açıkla.""".strip()

# ══════════════════════════════════════════════════════════════════
# OPTİMİZASYON 4 — sistem_promptu_olustur: profili_yukle() tekrar çağrısı kaldırıldı
# Eski davranış: Her mesajda hem sohbet_et() hem de sistem_promptu_olustur()
#               ayrı ayrı profili_yukle() çağırıyordu → 2x disk okuma.
# Yeni davranış: profil dışarıdan parametre olarak geliyor, tek okuma yeterli.
# ══════════════════════════════════════════════════════════════════
def sistem_promptu_olustur(profil, ad, ton, stil,
                            belge_adi="", belge_metni="", duygu=None,
                            gorevler_ozet="", strateji="", profil_ozeti="",
                            mesaj_baglami="", ozel_rol="", uzmanlik="Standart"):
    isim = (ad or "").strip() or profil.get("name","")
    tn   = {"samimi":"sıcak ve yakın","profesyonel":"sakin ve net","enerjik":"motive edici"}
    st   = {"kısa":"kısa ve net","dengeli":"dengeli uzunlukta","detaylı":"adım adım detaylı"}
    bg   = [SYSTEM_PROMPT,
            UZMANLIK_MODLARI.get(uzmanlik, UZMANLIK_MODLARI["Standart"]),
            f"\nKullanıcı: {isim if isim else 'adı bilinmiyor — isim kullanma'}.",
            f"Ton: {tn.get(ton or profil.get('tone','samimi'),'dengeli')}. "
            f"Stil: {st.get(stil or profil.get('style','dengeli'),'dengeli')}."]
    if profil_ozeti:             bg.append(f"Özet: {profil_ozeti}")
    elif profil.get("about"):    bg.append(f"Hakkında: {profil['about']}")
    if profil.get("preferences"):bg.append(f"Tercihler: {profil['preferences']}")
    if profil.get("learned") and mesaj_baglami:
        kw = set(mesaj_baglami.lower().split())
        il = [l for l in profil["learned"][:10] if any(k in l.lower() for k in kw if len(k)>3)][:3]
        if il: bg.append("Öğrenilmiş: " + "; ".join(il))
    elif profil.get("learned"):
        bg.append("Öğrenilmiş: " + "; ".join(profil["learned"][:3]))
    if duygu and duygu.get("durum") != "nötr": bg.append(f"Duygu: {duygu['durum']} → {duygu['ton']}.")
    if strateji:                 bg.append(f"Strateji: {strateji}")
    bg.append("\nAçıklanabilirlik: Karmaşık kararlar için <think>gerekçe</think> yaz.")
    if gorevler_ozet and gorevler_ozet != "Henüz görev yok.":
        bg.append(f"Görevler:\n{gorevler_ozet[:400]}")
    lmo = life_map_ozeti()
    if lmo:
        bg.append(f"Durum: {lmo}")
    else:
        lm = haritayi_yukle()
        if any(lm.get(k) for k in ("is_modeli","uzun_vadeli_plan")):
            bg.append(f"Harita: is={lm.get('is_modeli','')} plan={lm.get('uzun_vadeli_plan','')[:150]}")
    if belge_metni:
        ilgili = gelismis_rag_ara(mesaj_baglami or "", belge_metni)
        bg.append(f"Belge ({belge_adi}):\n{ilgili}")
    if ozel_rol and ozel_rol.strip():
        bg.append(f"ÖZEL ROL: {ozel_rol.strip()}")
    bg.append(
        "ZORUNLU KURALLAR (BU KURALLARI ASLA ÇİĞNEME):\n"
        "1. KESİNLİKLE hiçbir yabancı kelime/İngilizce kullanma. Sadece saf Türkçe.\n"
        "2. Numaralandırılmış liste YAPMA. Madde imi (-) kullan.\n"
        "3. Cevabın MAKSİMUM 3 paragraf veya 4 madde olsun. Kısa ve öz ol.\n"
        "4. Asla JSON, dict veya kod formatı ile yanıt verme.\n"
        "5. Kendi kimliğini ve özelliklerini madde madde sayarak kendini ÖVME."
    )
    # Dil yönlendirmesi
    dil_eki = sistem_promptu_dil_eki(dil_al())
    if dil_eki: bg.append(dil_eki)
    return "\n\n".join(bg)

def mesajlari_hazirla(gecmis, mesaj, profil, ad, ton, stil,
                      belge_adi="", belge_metni="", duygu=None,
                      gorevler_ozet="", strateji="", profil_ozeti="",
                      ozel_rol="", uzmanlik="Standart"):
    ms = [{"role":"system","content":sistem_promptu_olustur(
        profil, ad, ton, stil, belge_adi, belge_metni, duygu,
        gorevler_ozet, strateji, profil_ozeti, mesaj, ozel_rol, uzmanlik=uzmanlik)}]
    for i in gecmis or []:
        if isinstance(i,dict):
            r,c = i.get("role"), i.get("content")
            if isinstance(c,tuple): continue
            if r in {"user","assistant"} and c: ms.append({"role":r,"content":str(c)})
        elif isinstance(i,(list,tuple)) and len(i)==2:
            u,a = i
            if u: ms.append({"role":"user","content":str(u)})
            if a: ms.append({"role":"assistant","content":str(a)})
    if mesaj.count("?")>=2 or (" ve " in mesaj.lower() and "?" in mesaj):
        ms.insert(1,{"role":"system","content":"Birden fazla soru. Her birini 1-2 cümle."})
    if not any(k in mesaj.lower() for k in ["nedir","kimdir","ne demek","nasıl çalışır","açıkla","anlat"]):
        hf = memory_ara(mesaj)
        if hf: ms.insert(1,{"role":"system","content":f"Geçmiş:\n{hf}"})
    if any(k in mesaj.lower() for k in ["hedefleri","tamamladım","performans","rapor","kaç hedef","ilerleme","başardım","hedefim"]):
        lm = haritayi_yukle(); h=lm.get("hedefler",[])
        tm=[x for x in h if x.get("tamamlandi")]; bk=[x for x in h if not x.get("tamamlandi")]
        if h: ms.append({"role":"system","content":f"Hedefler: Toplam={len(h)}\nTamam ({len(tm)}): {[x['hedef'] for x in tm]}\nBekleyen ({len(bk)}): {[x['hedef'] for x in bk]}"})
        else: ms.append({"role":"system","content":"Hedef veritabanı BOŞ. Uydurma. Şunu söyle: Henüz hedef eklenmemiş."})
    ms.append({"role":"user","content":mesaj})
    return ms

def _html_temizle(raw_html):
    x = re.sub(r"(?is)<(script|style).*?>.*?</\1>"," ",raw_html or "")
    x = re.sub(r"(?is)<br\s*/?>","\n",x)
    x = re.sub(r"(?is)</p\s*>","\n",x)
    x = re.sub(r"(?is)<.*?>"," ",x)
    x = re.sub(r"[ \t]+"," ",x)
    return metni_temizle(x)

def fetch_url_text(url, timeout=10, max_chars=7000):
    try:
        r = requests.get(url,timeout=timeout,headers={"User-Agent":"BELUMA-I/1.0"})
        return _html_temizle(r.text)[:max_chars] if r.status_code==200 else ""
    except requests.RequestException: return ""

def _kaynak_kalite_puani(url, content, title):
    from urllib.parse import urlparse as _up
    domain = _up(url).netloc.lower().replace("www.","") if url else ""
    if not content or len(content)<500: return -100
    if domain in BLOCKED_DOMAINS: return -100
    score = 0
    if any(domain.endswith(d) for d in PRIORITY_DOMAINS): score+=30
    if any(m in domain for m in ["gov","edu","org"]): score+=20
    if len(title)>20: score+=5
    if len(content)>1200: score+=10
    return score

def derin_arastirma_yap(konu):
    if not FLAGS.deep_research:
        yield "Derin araştırma özelliği kapalı."; return

    yield "🔍 Araştırma başlatıldı. Sorgu planı çıkarılıyor...\n"
    sorgu_prompt = f'"{konu}" için web araması yapacağım. Bana 4-6 farklı arama sorgusu üret. SADECE JSON dizisi döndür: ["sorgu1","sorgu2","sorgu3"]. Başka bir şey yazma.'
    sorgu_raw = _agent_cagir(sorgu_prompt, 200)
    sorgular  = []
    try:
        parsed = json.loads(re.sub(r"```json|```","",sorgu_raw or "").strip())
        if isinstance(parsed,list): sorgular=[str(s).strip() for s in parsed if str(s).strip()][:6]
    except (json.JSONDecodeError,ValueError): pass
    if not sorgular:
        sorgular = re.findall(r'"([^"]{3,80})"',sorgu_raw or "")
        sorgular = [s.strip() for s in sorgular if s.strip()][:6]
    if not sorgular: sorgular=[konu]

    yield "🌐 Web taraması ve kaynak toplama...\n"
    kaynaklar, gorulen = [], set()
    for s in sorgular:
        yield f"• Taranıyor: *{s}*\n"
        for r in _ddg_sonuclari_al(s, n=4):
            u = r.get("url","")
            if not u or u in gorulen: continue
            gorulen.add(u)
            content = fetch_url_text(u,timeout=WEB_TIMEOUT,max_chars=4500)
            title   = r.get("title","")
            score   = _kaynak_kalite_puani(u,content,title)
            if score<0: continue
            kaynaklar.append({"title":title,"url":u,"snippet":r.get("body",""),"content":content,"score":score})
        if len(kaynaklar)>=WEB_MAX_SOURCES: break

    if not kaynaklar:
        yield "⚠️ Kaynak bulunamadı. İnternet erişimi veya arama kütüphanesi sorunu olabilir."; return

    kaynaklar.sort(key=lambda k:k.get("score",0),reverse=True)
    kaynaklar = kaynaklar[:WEB_MAX_SOURCES]

    from urllib.parse import urlparse as _up
    cards = "\n\n".join(
        f"[{i}] Başlık: {k['title']}\nAlan: {_up(k['url']).netloc.lower().replace('www.','')}\n"
        f"URL: {k['url']}\nÖzet: {k['snippet']}\nİçerik: {k['content']}"
        for i,k in enumerate(kaynaklar,start=1))
    yield "✍️ Alıntılı rapor yazılıyor...\n"
    rapor = _agent_cagir(
        f"KONU: {konu}\n\n"
        "Kaynak kartlarını kullanarak Türkçe, analitik ve kaynaklı rapor yaz.\n"
        "Kurallar:\n"
        "- Bölümler: Genel Bakış, Temel Bulgular, Çelişkiler/Belirsizlikler, Sonuç, Güven Düzeyi.\n"
        "- Her önemli iddianın sonunda kaynak numarası [1],[2] kullan.\n"
        "- Kaynaklarda yoksa uydurma. Belirsizlik varsa belirt.\n"
        "- Tamamen Türkçe yaz.\n\n"
        f"KAYNAKLAR:\n{cards}", 2200)
    rapor          = final_cevap_temizle(rapor)
    kaynak_listesi = "\n".join(f"- [{i+1}] {k['url']}" for i,k in enumerate(kaynaklar))
    yield f"📚 **Araştırma Raporu: {konu}**\n\n{rapor}\n\n**Kaynaklar:**\n{kaynak_listesi}"

# ══════════════════════════════════════════════════════════════════
# STREAMING CEVAP (cevap_uret) — provider dispatch
# ══════════════════════════════════════════════════════════════════
def cevap_uret(mesaj, gecmis, profil, ad, ton, stil,
               belge_adi="", belge_metni="", duygu=None,
               gorevler_ozet="", strateji="", profil_ozeti="",
               yaraticilik=0.4, ozel_rol="",
               secili_model="llama-3.3-70b-versatile",
               max_tokens=1024, top_p=0.9,
               aktif_resim=None, uzmanlik="Standart"):
    """v7 Orkestratör — niyet belirle → doğru akışı çalıştır → tek kapıdan çıkar."""

    niyet = cevap_turu_belirle(mesaj, belge_var=bool(belge_metni), resim_var=bool(aktif_resim))

    # ── Deep Research ──
    if niyet == "deep_research":
        konu = re.sub(r"(?i)derin araştır|deep research|kapsamlı araştır|detaylı araştır|:","",mesaj).strip() or mesaj
        for chunk in derin_arastirma_yap(konu): yield final_cevap_temizle(chunk)
        return

    # ── Çevrimdışı araçlar ──
    if niyet in ("tool_calc","tool_date","tool_convert"):
        tool_map = {"tool_calc":"calc","tool_date":"date","tool_convert":"convert"}
        sonuc = run_tool(tool_map[niyet],mesaj)
        if sonuc: yield final_cevap_temizle(str(sonuc)); return

    # ── Çevrimiçi araçlar ──
    if niyet in ("tool_weather","tool_news","tool_bist"):
        tool_map = {"tool_weather":"weather","tool_news":"news","tool_bist":"bist"}
        sonuc = run_tool(tool_map[niyet],mesaj)
        if sonuc: log_kaydet(mesaj,str(sonuc)[:200],"tool"); analitik_kaydet(arac=niyet.replace("tool_","")); yield final_cevap_temizle(str(sonuc)); return

    # ── Web arama ──
    search_context = ""
    if niyet == "tool_search":
        sonuclar = arama_yap(mesaj,max_results=5)
        if sonuclar:
            kartlar        = kaynak_kartlari_olustur(sonuclar)
            search_context = f"WEB SONUÇLARI:\n{kartlar}\n\nBu sonuçlara dayanarak kısa Türkçe cevap ver. Kaynak numarası [1],[2] kullan."
            log_kaydet(mesaj,kartlar[:200],"search"); analitik_kaydet(arac="search")

    # ── Plugin kontrolü (güvenlik öncesi, araçlardan sonra) ──
    plugin_sonuc = plugin_isle(mesaj)
    if plugin_sonuc:
        yield final_cevap_temizle(plugin_sonuc)
        return

    # ── Güvenlik ──
    if not karar_motoru(mesaj)["guvenli"]:
        yield "Bu isteğe yardımcı olamam."; return

    # ── Mesaj hazırla ──
    ms = mesajlari_hazirla(gecmis, mesaj, profil, ad, ton, stil,
                           belge_adi, belge_metni, duygu, gorevler_ozet,
                           strateji, profil_ozeti, ozel_rol, uzmanlik=uzmanlik)
    if search_context:
        ms.insert(1,{"role":"system","content":search_context})
    temp = 0.2 if any(k in mesaj.lower() for k in ["matematik","hesap","bilmece","mantık","problem"]) else float(yaraticilik)

    # ── Gemini ──
    if secili_model.startswith("gemini"):
        gc = get_gemini_client(secili_model)
        if not gc: yield "🔑 Gemini için geçerli bir anahtar gerekli."; return
        try:
            full_prompt = ""
            for m in ms:
                role,content = m.get("role",""),m.get("content","")
                if isinstance(content,list): content=next((p.get("text") for p in content if p.get("type")=="text"),"")
                if role=="system":    full_prompt+=f"Sistem: {content}\n\n"
                elif role=="user":    full_prompt+=f"Kullanıcı: {content}\n\n"
                elif role=="assistant": full_prompt+=f"Asistan: {content}\n\n"
            resp = gc.generate_content(full_prompt.strip())
            yield final_cevap_temizle(resp.text); return
        except Exception as e: yield _hata_turkce("Gemini",e); return

    # ── DeepSeek ──
    elif secili_model.startswith("deepseek"):
        dc = get_deepseek_client()
        if not dc: yield "🔑 DeepSeek için geçerli bir anahtar gerekli."; return
        try:
            resp = dc.chat.completions.create(model="deepseek-chat",messages=ms,temperature=temp,max_tokens=int(max_tokens),top_p=float(top_p),stream=True)
            full = ""
            for chunk in resp:
                d = chunk.choices[0].delta.content
                if d: full+=d; yield full
            final = final_cevap_temizle(full)
            if not _ayni_cevap_mi(full,final): yield final
            log_kaydet(mesaj,(final or full)[:300],secili_model); analitik_kaydet(model=secili_model); return
        except Exception as e: yield _hata_turkce("DeepSeek",e); return

    # ── OpenAI ──
    elif secili_model.startswith("gpt"):
        oc = get_openai_client()
        if not oc: yield "🔑 OpenAI için geçerli bir anahtar gerekli."; return
        try:
            resp = oc.chat.completions.create(model=secili_model,messages=ms,temperature=temp,max_tokens=int(max_tokens),top_p=float(top_p),stream=True)
            full = ""
            for chunk in resp:
                d = chunk.choices[0].delta.content
                if d: full+=d; yield full
            final = final_cevap_temizle(full)
            if not _ayni_cevap_mi(full,final): yield final
            log_kaydet(mesaj,(final or full)[:300],secili_model); analitik_kaydet(model=secili_model); return
        except Exception as e: yield _hata_turkce("OpenAI",e); return

    # ── Claude ──
    elif secili_model.startswith("claude"):
        ac = get_anthropic_client()
        if not ac: yield "🔑 Claude için geçerli bir anahtar gerekli."; return
        try:
            sys_msg   = next((m["content"] for m in ms if m["role"]=="system"),"")
            user_msgs = [{"role":m["role"],"content":m["content"]} for m in ms if m["role"] in ("user","assistant")]
            with ac.messages.stream(model=secili_model,max_tokens=int(max_tokens),temperature=temp,top_p=float(top_p),system=sys_msg,messages=user_msgs) as stream:
                full = ""
                for text in stream.text_stream:
                    full+=text; yield full
            final = final_cevap_temizle(full)
            if not _ayni_cevap_mi(full,final): yield final
            log_kaydet(mesaj,(final or full)[:300],secili_model); analitik_kaydet(model=secili_model); return
        except Exception as e: yield _hata_turkce("Claude",e); return

    # ── Groq (varsayılan) ──
    else:
        client = get_groq_client()
        if not client: yield "🔑 Groq için geçerli bir anahtar gerekli."; return
        if aktif_resim:
            b64 = resmi_base64_yap(aktif_resim)
            if b64:
                secili_model = VISION_MODEL
                ms[-1]["content"] = [{"type":"text","text":ms[-1]["content"]},{"type":"image_url","image_url":{"url":b64}}]
        denenen = [secili_model]+[m for m in FALLBACK_MODELLER if m!=secili_model]
        for idx,model in enumerate(denenen):
            try:
                resp = client.chat.completions.create(model=model,messages=ms,temperature=temp,max_tokens=int(max_tokens),top_p=float(top_p),frequency_penalty=0.2,presence_penalty=0.1,stream=True)
                full = ""
                for chunk in resp:
                    d = chunk.choices[0].delta.content
                    if d: full+=d; yield full
                final = final_cevap_temizle(full)
                if not _ayni_cevap_mi(full,final): yield final
                log_kaydet(mesaj,(final or full)[:300],model); analitik_kaydet(model=model); return
            except Exception as e:
                err=str(e); _logger.warning("[cevap] %s: %s",model,err[:100])
                if "rate_limit" in err or "429" in err:
                    _hata_say(f"model.rate_limit.{model[:20]}")
                    if idx<len(denenen)-1: time.sleep(min(2**idx,8)); continue
                _hata_say(f"model.hata.{model[:20]}")
                yield _hata_turkce("Groq",e); return
        yield "⏳ Tüm modeller şu an meşgul. Biraz bekleyip tekrar deneyin."

# ══════════════════════════════════════════════════════════════════
# ANA SOHBET
# ══════════════════════════════════════════════════════════════════
_profil_cache_lock  = threading.Lock()
_profil_ozeti_cache = {"ozet":"","son":0,"hash":""}

def profil_ozetini_al(profil=None):
    """
    OPTİMİZASYON 5 — profil_ozetini_al
    Eski davranış: Her çağrıda profili_yukle() disk okuması yapılıyordu.
    Yeni davranış: Profil dışarıdan parametre olarak gelebilir.
                  Hash değişmediyse TTL dolmadan önce hiç disk okuması olmaz.
    """
    global _profil_ozeti_cache
    s  = time.time()
    pr = profil or profili_yukle()
    ph = str(hash(json.dumps(pr, sort_keys=True)))
    with _profil_cache_lock:
        if (s - _profil_ozeti_cache["son"] <= PROFILE_CACHE_TTL) and (ph == _profil_ozeti_cache["hash"]):
            return _profil_ozeti_cache["ozet"]
        try:
            yeni_ozet = dinamik_profil_ozeti(pr)
        except Exception as e:
            _logger.warning("[profil_oz] %s", e)
            yeni_ozet = _profil_ozeti_cache["ozet"]  # eski özeti koru
        _profil_ozeti_cache = {"ozet": yeni_ozet, "son": s, "hash": ph}
    return _profil_ozeti_cache["ozet"]

def sag_panel_guncelle():
    """Sağ panel verilerini döndür — hedefler, alışkanlıklar, aktif model."""
    lm = haritayi_yukle()
    hedefler = lm.get("hedefler", [])
    toplam   = len(hedefler)
    tamamlanan = sum(1 for h in hedefler if h.get("tamamlandi"))
    bekleyen = [h for h in hedefler if not h.get("tamamlandi")][:4]
    aliskanliklar = lm.get("aliskanliklar", [])[:4]

    yuzde = int(tamamlanan / toplam * 100) if toplam else 0

    hedef_html = ""
    for h in bekleyen:
        hedef_html += f'<div class="rgoal"><span class="rdot"></span>{h["hedef"][:28]}</div>'
    for h in [h for h in hedefler if h.get("tamamlandi")][:2]:
        hedef_html += f'<div class="rgoal"><span class="rdot done"></span><span style="text-decoration:line-through;opacity:.5">{h["hedef"][:28]}</span></div>'

    hab_html = ""
    for a in aliskanliklar:
        hab_html += f'''
        <div class="rhab">
          <span class="rhab-name">{a["aliskanlik"][:16]}</span>
          <span class="rhab-streak">{a.get("seri",0)}g 🔥</span>
        </div>'''

    # Bildirim sayısı
    with _BLD_KUYRUK_LOCK:
        bld_sayi = len(_bildirim_kuyrugu)

    # Aktif hatırlatıcılar
    hat_v = hatirlaticilar_yukle()
    aktif_hat = [h for h in hat_v.get("hatirlaticilar",[]) if not h.get("tamamlandi")]

    html = f"""
<div style="padding:4px 0">
  <div style="font-family:Montserrat,sans-serif;font-size:13px;font-weight:600;
    background:linear-gradient(90deg,#FF1493,#8A2BE2);-webkit-background-clip:text;
    -webkit-text-fill-color:transparent;padding:6px 4px 2px">Gösterge</div>
  <div style="height:1px;background:rgba(138,43,226,.15);margin:0 0 8px"></div>

  <div class="rsec">HEDEFLER</div>
  <div class="rcard">
    <div class="rcard-label">Tamamlanan / Toplam</div>
    <div class="rcard-val">{tamamlanan}<span style="font-size:11px;color:rgba(255,255,255,.4)">/{toplam}</span></div>
    <div class="rprog"><div class="rprog-fill" style="width:{yuzde}%"></div></div>
    <div class="rcard-sub">%{yuzde} başarı oranı</div>
  </div>
  {hedef_html if hedef_html else '<div style="font-size:10px;color:rgba(255,255,255,.35);padding:4px">Henüz hedef yok.</div>'}

  <div style="height:1px;background:rgba(138,43,226,.1);margin:8px 0"></div>
  <div class="rsec">ALISKANLIKLAR</div>
  {hab_html if hab_html else '<div style="font-size:10px;color:rgba(255,255,255,.35);padding:4px">Henüz alışkanlık yok.</div>'}

  <div style="height:1px;background:rgba(138,43,226,.1);margin:8px 0"></div>
  <div class="rsec">BİLDİRİMLER</div>
  <div class="rcard">
    <div class="rcard-label">Bekleyen bildirim</div>
    <div class="rcard-val" style="{"color:#FF1493" if bld_sayi>0 else ""}">{bld_sayi}</div>
    <div class="rcard-sub">{len(aktif_hat)} aktif hatırlatıcı</div>
  </div>

  <div style="height:1px;background:rgba(138,43,226,.1);margin:8px 0"></div>
  <div class="rsec">HIZLI ARAÇLAR</div>
  <div style="display:flex;flex-wrap:wrap;gap:3px;padding:2px 0 6px">
    <span style="font-size:9px;padding:3px 7px;border-radius:6px;border:1px solid rgba(138,43,226,.22);background:rgba(138,43,226,.07);color:rgba(255,255,255,.55)">🌤 Hava</span>
    <span style="font-size:9px;padding:3px 7px;border-radius:6px;border:1px solid rgba(138,43,226,.22);background:rgba(138,43,226,.07);color:rgba(255,255,255,.55)">📈 Borsa</span>
    <span style="font-size:9px;padding:3px 7px;border-radius:6px;border:1px solid rgba(138,43,226,.22);background:rgba(138,43,226,.07);color:rgba(255,255,255,.55)">📰 Haber</span>
    <span style="font-size:9px;padding:3px 7px;border-radius:6px;border:1px solid rgba(138,43,226,.22);background:rgba(138,43,226,.07);color:rgba(255,255,255,.55)">📅 Tarih</span>
  </div>

  <div style="height:1px;background:rgba(138,43,226,.1);margin:4px 0 8px"></div>
  <div class="rsec">BELUMA-I</div>
  <div style="font-size:9px;color:rgba(255,255,255,.4);padding:2px 4px;line-height:1.9">
    <div>🧠 Llama 3.3 70B</div>
    <div>🔌 {len(_plugin_registry)} plugin aktif</div>
    <div style="color:{"#FF1493" if bld_sayi>0 else "rgba(255,255,255,.4)"}">🔔 {bld_sayi} bildirim</div>
    <div>📊 <a href="#" style="color:rgba(255,20,147,.6);text-decoration:none">Analitik</a></div>
  </div>
</div>
"""
    return html


def sohbet_et(mesaj, gecmis, ad, ton, stil, belge_adi, belge_metni,
              yaraticilik=0.4, ozel_rol="",
              secili_model="llama-3.3-70b-versatile",
              max_tokens=1024, top_p=0.9,
              aktif_resim=None, uzmanlik="Standart"):

    temiz = (mesaj or "").strip()
    if not temiz: yield gecmis,"","Mesaj yaz.",""; return

    uyari = guvenlik_tarama(temiz)
    if uyari:
        y = list(gecmis or [])+[{"role":"user","content":temiz},{"role":"assistant","content":uyari}]
        oturumu_kaydet(y,belge_adi,belge_metni); yield y,"","⚠️ Güvenlik.",""; return

    duygu = duygu_analizi(temiz)

    # ── Profil TEK SEFERINDE okunuyor ──
    pr = profili_yukle()

    go = gorevleri_metne_cevir() if any(k in temiz.lower() for k in ["görev","yapacak","tamamla","plan yap","hatırlat"]) else ""

    # Profil özeti ve strateji eş zamanlı hesapla
    fp = _THREAD_POOL.submit(profil_ozetini_al, pr)
    fs = None
    if any(k in temiz.lower() for k in ["strateji","plan","karar","nasıl"]) and len(temiz) > 40:
        fs = _THREAD_POOL.submit(derin_dusunce_katmani, temiz, pr)

    try:    po = fp.result(timeout=2.0)
    except concurrent.futures.TimeoutError:
        _logger.warning("[sohbet] profil_ozeti zaman aşımı"); _hata_say("profil_ozeti.timeout"); po = ""
    except Exception as e:
        _logger.warning("[sohbet] profil_ozeti hata: %s", e); _hata_say("profil_ozeti.genel"); po = ""
    st = ""
    if fs:
        try:    st = fs.result(timeout=2.0)
        except concurrent.futures.TimeoutError:
            _logger.warning("[sohbet] strateji zaman aşımı"); _hata_say("strateji.timeout")
        except Exception as e:
            _logger.warning("[sohbet] strateji hata: %s", e); _hata_say("strateji.genel")

    yg = list(gecmis or [])+[{"role":"user","content":temiz},{"role":"assistant","content":"✍️ Düşünüyor..."}]
    if aktif_resim: yg.insert(-1,{"role":"user","content":(aktif_resim,)})

    sc = ""
    for p in cevap_uret(temiz, gecmis or [], pr, ad, ton, stil,
                        belge_adi, belge_metni, duygu, go, st, po,
                        yaraticilik, ozel_rol, secili_model,
                        max_tokens, top_p, aktif_resim=aktif_resim, uzmanlik=uzmanlik):
        sc = p; yg[-1]["content"] = sc+" █"; yield yg,"","Yanıtlanıyor...",""

    yg[-1]["content"] = sc
    ge,_ = chat_gorev_isle(temiz)
    if ge: yg[-1]["content"] = sc+ge

    if any(k in temiz.lower() for k in ["değerlendir","eleştir","eksik var mı","ne düşünüyorsun"]):
        try:
            cr = critic_agent(yg[-1]["content"])
            if cr and len(cr)>20: yg[-1]["content"] += f"\n\n🔍 **Değerlendirme:** {cr}"
        except Exception as e: _logger.warning("[critic] %s",e)

    if any(k in temiz.lower() for k in ["karar","seçim","strateji","plan","risk","neden","nasıl","anlamadım","başarısız","gelecek"]) and len(yg[-1]["content"])>150:
        tv = zihinsel_model_oner(temiz)
        if tv: yg[-1]["content"]+=tv

    ad_sonuc = anayasal_denetim(yg[-1]["content"], kullanici_mesaji=temiz)
    if ad_sonuc: yg[-1]["content"]+=ad_sonuc

    yg[-1]["content"] = final_cevap_temizle(yg[-1]["content"])

    dr = f"Duygu: {duygu['durum']}" if duygu["durum"]!="nötr" else "Hazır."
    if belge_adi and belge_metni: dr=f"Belge: {belge_adi}"
    oturumu_kaydet(yg,belge_adi,belge_metni)

    # ── Giden webhook: mesaj olayı ──
    webhook_tetikle("mesaj", {
        "kullanici_mesaji": temiz[:300],
        "cevap":            yg[-1]["content"][:300],
        "model":            secili_model,
        "uzmanlik":         uzmanlik,
    })
    # Ekip aktivite logu
    if aktif_kullanici_al():
        _aktivite_ekle(f"Mesaj gönderdi ({secili_model})")

    def _bg():
        try:    profili_otomatik_guncelle(temiz,yg[-1]["content"])
        except Exception as e: _logger.warning("[bg/pr] %s",e)
        try:    memory_ekle(f"USR: {temiz[:100]} | BOT: {yg[-1]['content'][:100]}")
        except Exception as e: _logger.warning("[bg/mem] %s",e)
    _THREAD_POOL.submit(_bg)

    # OPT: oturumu_kaydet zaten çağrıldı — proaktif için sadece date kontrol et
    try:
        bg = time.strftime("%Y-%m-%d")
        ov = oturumu_yukle()
        sa = ov.get("last_proaktif_date", "")
        if sa != bg and not any(k in temiz.lower() for k in ["hedef","yaşam haritası"]) and len(yg[-1]["content"]) < 800:
            pk=proaktif_kontrol(temiz)
            if pk: yg[-1]["content"]+=f"\n\n{pk}"; ov["last_proaktif_date"]=bg; json_kaydet(SESSION_FILE,ov)
    except Exception as e: _logger.warning("[proaktif] %s",e)

    yield yg,"",dr,""

# ══════════════════════════════════════════════════════════════════
# UI YARDIMCI
# ══════════════════════════════════════════════════════════════════
def yeni_sohbet(ba,bm): oturumu_kaydet([],ba,bm); return chatbot_icin_hazirla([]),"Yeni sohbet."

def belge_yukle(fo):
    a,s = belge_metnini_oku(fo)
    if not a and not s: return "","","Yüklenmedi."
    if s and not any(h in s.lower() for h in ["hata","desteklenmiyor","boş"]):
        o=oturumu_yukle(); oturumu_kaydet(o.get("chat_history",[]),a,s); return a,s,f"✅ {a}"
    o=oturumu_yukle(); oturumu_kaydet(o.get("chat_history",[]),a,""); return a,"",s

def son_sohbeti_yukle():
    o=oturumu_yukle(); g=o.get("chat_history",[])
    return chatbot_icin_hazirla(g),g,o.get("document_name",""),o.get("document_text",""),"Yüklendi." if g else "Bulunamadı."

def cevabi_iyilestir(gecmis):
    si=None
    for i,item in enumerate(reversed(gecmis or [])):
        if isinstance(item,dict) and item.get("role")=="assistant": si=len(gecmis)-1-i; break
    if si is None: return chatbot_icin_hazirla(gecmis or []),"Mesaj bulunamadı."
    rv=_agent_cagir(f"Eleştir. Hata varsa düzelt. Yoksa 'TAMAM'.\nCevap: {gecmis[si]['content'][:700]}",600)
    if rv and rv.strip().upper()!="TAMAM" and len(rv)>30:
        y=list(gecmis); y[si]={"role":"assistant","content":rv}; return chatbot_icin_hazirla(y),"✅ İyileştirildi."
    return chatbot_icin_hazirla(gecmis),"✅ Zaten iyi."

def ogrenileni_sil(silinecek):
    pr=profili_yukle(); lr=[l for l in pr.get("learned",[]) if l!=silinecek.strip()]
    profili_kaydet(**{**pr,"learned":lr}); return "\n".join(lr) or "Henüz yok.",f"🗑 Silindi."

def ayarlari_kaydet(ad,ton,stil,about,pref):
    pr=profili_yukle(); profili_kaydet(name=ad,tone=ton,style=stil,about=about,preferences=pref,learned=pr.get("learned",[]))
    global _profil_ozeti_cache; _profil_ozeti_cache={"ozet":"","son":0,"hash":""}
    return f"✅ Kaydedildi.{f' Merhaba {ad.strip()}!' if (ad or '').strip() else ''}"

def sohbeti_indir(gecmis,ad):
    isim=ad.strip() if ad and ad.strip() else "Kullanıcı"
    md=f"# BELUMA-I Sohbet\n**Tarih:** {time.strftime('%Y-%m-%d %H:%M')}\n**Kişi:** {isim}\n\n---\n\n"
    for i in (gecmis or []):
        if isinstance(i,dict):
            c=str(i.get("content","")).replace(" █","")
            if isinstance(i.get("content"),tuple): continue
            md+=f"### {'👤 '+isim if i.get('role')=='user' else '🤖 BELUMA-I'}:\n{c}\n\n---\n\n"
    tmp=Path(tempfile.gettempdir())/f"BELUMA_{int(time.time())}.md"; tmp.write_text(md,encoding="utf-8"); return str(tmp)

def son_asistan_mesaji(g):
    for i in reversed(g or []):
        if isinstance(i,dict) and i.get("role")=="assistant": return i.get("content","")
    return ""

def _hedef_listesi():
    return "\n".join(f"{'✓' if h.get('tamamlandi') else '○'} [{h.get('oncelik',2)}⭐] {h['hedef']}" for h in haritayi_yukle().get("hedefler",[])) or "Henüz hedef yok."

# ══════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════
def _hash_pw(pw): return hashlib.sha256(pw.encode("utf-8")).hexdigest()

AUTH_DEFAULT_USER     = os.getenv("AUTH_DEFAULT_USER","").strip()
AUTH_DEFAULT_PASSWORD = os.getenv("AUTH_DEFAULT_PASSWORD","").strip()

def _load_auth():
    if AUTH_FILE.exists():
        try:
            with AUTH_FILE.open("r",encoding="utf-8") as f: users=json.load(f)
            if isinstance(users,list) and users: return [(u["username"],u["password_hash"]) for u in users]
        except json.JSONDecodeError as e:
            _logger.error("[auth] auth dosyası bozuk: %s", e); _hata_say("auth.json_bozuk")
        except (OSError, KeyError) as e:
            _logger.error("[auth] dosya okuma hatası: %s", e); _hata_say("auth.okuma")
    if AUTH_DEFAULT_USER and AUTH_DEFAULT_PASSWORD:
        defaults=[(AUTH_DEFAULT_USER,_hash_pw(AUTH_DEFAULT_PASSWORD))]
        try:
            with AUTH_FILE.open("w",encoding="utf-8") as f:
                json.dump([{"username":u,"password_hash":h} for u,h in defaults],f,ensure_ascii=False,indent=2)
        except OSError as e:
            _logger.warning("[auth] varsayılan auth yazılamadı: %s", e); _hata_say("auth.yazma")
        return defaults
    _get_logger().warning("Auth tanımlı değil. AUTH_DEFAULT_USER ve AUTH_DEFAULT_PASSWORD ayarlayın.")
    return []

def _gradio_auth(username,password):
    accounts=_load_auth()
    if not accounts: return True
    return any(u==username and h==_hash_pw(password) for u,h in accounts)

# ══════════════════════════════════════════════════════════════════
# CSS (değişmedi)
# ══════════════════════════════════════════════════════════════════
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@600;700&family=Inter:wght@400;500&display=swap');

/* ═══════════════════════════════════════
   BELUMA-I v6.5 — 3 KOLON LAYOUT
   Sol Panel | Orta Sohbet | Sağ Panel
═══════════════════════════════════════ */

/* ── TEMEL ── */
body{background:#0d0614!important;font-family:'Inter',sans-serif!important;margin:0!important;padding:0!important}
body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background:radial-gradient(circle at 15% 10%,rgba(138,43,226,.18),transparent 35%),
             radial-gradient(circle at 85% 5%,rgba(255,20,147,.18),transparent 30%),
             radial-gradient(circle at 50% 95%,rgba(138,43,226,.1),transparent 40%)}
.gradio-container{max-width:100%!important;margin:0!important;padding:0!important;position:relative;z-index:1}
.block{border:none!important;background:transparent!important}

/* ── 3 KOLON ANA LAYOUT ── */
#beluma-layout{
  display:grid;
  grid-template-columns:220px 1fr 210px;
  grid-template-rows:auto 1fr;
  min-height:100vh;
  gap:0;
}
#beluma-topbar{
  grid-column:1/-1;
  background:rgba(13,6,20,.96);
  border-bottom:1px solid rgba(138,43,226,.22);
  padding:0 16px;
  height:52px;
  display:flex;align-items:center;justify-content:space-between;
  position:sticky;top:0;z-index:100;
}
#beluma-left{
  background:rgba(13,6,20,.85);
  border-right:1px solid rgba(138,43,226,.18);
  padding:10px 6px;
  overflow-y:auto;
  height:calc(100vh - 52px);
  position:sticky;top:52px;
  scrollbar-width:thin;
  scrollbar-color:rgba(138,43,226,.3) transparent;
}
#beluma-center{
  display:flex;flex-direction:column;
  min-height:calc(100vh - 52px);
  background:rgba(13,6,20,.4);
}
#beluma-right{
  background:rgba(13,6,20,.85);
  border-left:1px solid rgba(138,43,226,.18);
  padding:10px 8px;
  overflow-y:auto;
  height:calc(100vh - 52px);
  position:sticky;top:52px;
  scrollbar-width:thin;
  scrollbar-color:rgba(138,43,226,.3) transparent;
}

/* ── TOPBAR ── */
.beluma-logo{
  font-family:'Montserrat',sans-serif;font-size:16px;font-weight:700;
  background:linear-gradient(90deg,#FF1493,#8A2BE2);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  letter-spacing:.06em;
}
.beluma-status-dot{
  width:7px;height:7px;border-radius:50%;
  background:#FF1493;box-shadow:0 0 7px rgba(255,20,147,.9);
  display:inline-block;
  animation:pulse-led 2s ease-in-out infinite;
}
@keyframes pulse-led{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.3;transform:scale(.8)}}

/* ── SOL PANEL ── */
.lsec{
  font-size:9px;font-weight:600;
  color:rgba(255,255,255,.28);
  letter-spacing:.08em;text-transform:uppercase;
  padding:10px 8px 4px;
}
.lbtn{
  display:flex;align-items:center;gap:8px;
  padding:7px 8px;border-radius:8px;
  font-size:11.5px;color:rgba(255,255,255,.55);
  cursor:pointer;border:none;background:transparent;
  width:100%;text-align:left;
  transition:all .15s;
  position:relative;
}
.lbtn:hover{background:rgba(255,20,147,.1);color:rgba(255,255,255,.9)}
.lbtn.active{background:rgba(255,20,147,.15);color:#fff;font-weight:500}
.lbtn.active::before{
  content:'';position:absolute;left:0;top:20%;bottom:20%;
  width:2px;border-radius:2px;background:#FF1493;
}
.lbtn .lbadge{
  margin-left:auto;font-size:9px;padding:1px 5px;
  border-radius:8px;background:rgba(255,20,147,.25);color:#FF69B4;
}
.ldivider{height:1px;background:rgba(138,43,226,.12);margin:6px 4px}

/* ── SOHBET ALANI ── */
.beluma-chat-wrap{
  flex:1;padding:16px 20px;
  display:flex;flex-direction:column;gap:0;
  overflow-y:auto;
}
/* Chatbot override */
.gradio-chatbot{
  border:none!important;border-radius:0!important;
  background:transparent!important;
  box-shadow:none!important;
  flex:1!important;
}
.gradio-chatbot .user>div,[data-testid="user"]>div{
  background:linear-gradient(135deg,#FF1493,#C71585)!important;
  color:#fff!important;border-radius:16px 16px 3px 16px!important;
  box-shadow:0 2px 10px rgba(255,20,147,.25)!important;
  font-size:.9rem!important;line-height:1.6!important;
  max-width:72%!important;
}
.gradio-chatbot .bot>div,[data-testid="bot"]>div{
  background:linear-gradient(135deg,#2a0d4e,#1a0838)!important;
  color:rgba(255,255,255,.93)!important;
  border-radius:16px 16px 16px 3px!important;
  border:1px solid rgba(138,43,226,.28)!important;
  box-shadow:0 2px 10px rgba(138,43,226,.15)!important;
  font-size:.9rem!important;line-height:1.6!important;
  max-width:72%!important;
}
#beluma_chat{
  height:calc(100vh - 200px)!important;
  max-height:calc(100vh - 200px)!important;
  background:transparent!important;
}

/* ── INPUT ALANI ── */
#beluma-inputbar{
  padding:10px 16px 12px;
  background:rgba(13,6,20,.85);
  border-top:1px solid rgba(138,43,226,.18);
}
.gradio-textbox textarea,.gradio-textbox input{
  font-family:'Inter',sans-serif!important;font-size:.93rem!important;
  background:rgba(255,255,255,.04)!important;
  border:1px solid rgba(138,43,226,.3)!important;
  color:rgba(255,255,255,.92)!important;
  border-radius:12px!important;
  transition:border-color .22s,box-shadow .22s!important;
}
.gradio-textbox textarea::placeholder,.gradio-textbox input::placeholder{
  color:rgba(255,255,255,.28)!important;
}
.gradio-textbox textarea:focus,.gradio-textbox input:focus{
  border-color:#FF1493!important;
  box-shadow:0 0 0 3px rgba(255,20,147,.18)!important;
  outline:none!important;
}
.gradio-textbox,.gradio-dropdown,.gradio-accordion{border-radius:12px!important}

/* ── BUTONLAR ── */
button.primary{
  background:linear-gradient(135deg,#FF1493,#8A2BE2)!important;
  color:#fff!important;border:none!important;border-radius:12px!important;
  font-weight:600!important;font-size:.88rem!important;
  box-shadow:0 3px 12px rgba(255,20,147,.35)!important;
  transition:transform .15s,filter .15s!important;
  min-height:40px!important;
}
button.primary:hover{transform:scale(1.03)!important;filter:brightness(1.1)!important}
button.secondary{
  background:rgba(138,43,226,.1)!important;
  color:rgba(255,255,255,.75)!important;
  border:1px solid rgba(138,43,226,.3)!important;
  border-radius:10px!important;font-size:.8rem!important;
  transition:all .15s!important;min-height:34px!important;
}
button.secondary:hover{background:rgba(255,20,147,.15)!important;border-color:#FF1493!important;color:#fff!important}
button.stop{background:rgba(160,30,30,.15)!important;border:1px solid rgba(180,40,40,.3)!important;color:#ff7070!important;border-radius:10px!important;font-size:.8rem!important;min-height:34px!important}
.belge-upload-btn{height:34px!important;border-radius:10px!important;background:rgba(138,43,226,.1)!important;border:1px solid rgba(138,43,226,.3)!important;color:rgba(255,255,255,.75)!important;font-size:.78rem!important;transition:all .15s!important}
.belge-upload-btn:hover{background:rgba(255,20,147,.18)!important;border-color:#FF1493!important;color:#fff!important}

/* ── SAĞ PANEL ── */
.rsec{font-size:9px;font-weight:600;color:rgba(255,255,255,.28);letter-spacing:.08em;text-transform:uppercase;padding:8px 4px 5px}
.rcard{background:rgba(138,43,226,.08);border:1px solid rgba(138,43,226,.2);border-radius:10px;padding:8px 10px;margin-bottom:6px}
.rcard-label{font-size:9px;color:rgba(255,255,255,.42);margin-bottom:3px}
.rcard-val{font-size:17px;font-weight:700;color:#FF69B4;line-height:1}
.rcard-sub{font-size:9px;color:rgba(255,255,255,.32);margin-top:3px}
.rprog{height:3px;background:rgba(255,255,255,.08);border-radius:2px;margin:5px 0 3px}
.rprog-fill{height:3px;background:linear-gradient(90deg,#FF1493,#8A2BE2);border-radius:2px;transition:width .4s}
.rgoal{display:flex;align-items:center;gap:6px;padding:4px 2px;font-size:10.5px;color:rgba(255,255,255,.58)}
.rgoal .rdot{width:5px;height:5px;border-radius:50%;background:#8A2BE2;flex-shrink:0}
.rgoal .rdot.done{background:#1D9E75}
.rhab{display:flex;justify-content:space-between;align-items:center;padding:3px 2px}
.rhab-name{font-size:10.5px;color:rgba(255,255,255,.55)}
.rhab-streak{font-size:10.5px;font-weight:600;color:#FF1493}
.rdivider{height:1px;background:rgba(138,43,226,.1);margin:6px 0}
.rmodel{font-size:10px;color:rgba(255,255,255,.45);padding:2px 2px;line-height:1.8}

/* ── QUICK BUTTONS (sol panel kısayollar) ── */
.qbrow{display:flex;flex-wrap:wrap;gap:3px;padding:4px 4px 6px}
.qb{font-size:10px;padding:3px 7px;border-radius:6px;border:1px solid rgba(138,43,226,.22);background:rgba(138,43,226,.07);color:rgba(255,255,255,.55);cursor:pointer;transition:all .14s}
.qb:hover{border-color:#FF1493;color:#fff;background:rgba(255,20,147,.12)}

/* ── ACCORDION ── */
.gradio-accordion{background:rgba(255,255,255,.015)!important;border:1px solid rgba(138,43,226,.18)!important;border-radius:10px!important}
.beluma-acc-item,.beluma-acc-item .gradio-accordion,.beluma-acc-item details{
  border:1px solid rgba(255,20,147,.18)!important;border-radius:12px!important;
  background:rgba(13,6,20,.2)!important;overflow:hidden!important}
.beluma-acc-item summary,.beluma-acc-item [data-testid="accordion"]>div:first-child{
  padding:9px 11px!important;background:rgba(138,43,226,.08)!important;
  color:rgba(255,255,255,.82)!important;font-size:.85rem!important}
.beluma-acc-item .panel,.beluma-acc-item details>div{
  padding:9px 11px!important;border-top:1px solid rgba(138,43,226,.12)!important}

/* ── ÖRNEKLER ── */
.examples{margin:6px 0 0!important}
.examples table td,.examples .example{
  background:rgba(138,43,226,.08)!important;border:1px solid rgba(138,43,226,.22)!important;
  border-radius:7px!important;color:rgba(255,255,255,.72)!important;
  font-size:.78rem!important;padding:4px 8px!important;transition:all .15s!important}
.examples table td:hover,.examples .example:hover{
  background:rgba(255,20,147,.15)!important;border-color:#FF1493!important;color:#fff!important}

/* ── THINK BOX ── */
.think-box{background:rgba(138,43,226,.08);border-left:2px solid #FF1493;border-radius:0 8px 8px 0;padding:7px 12px;font-size:.82rem;color:rgba(255,255,255,.62);margin-top:5px}

/* ── DEEP RESEARCH ── */
.beluma-dr{border:1px solid rgba(255,20,147,.22)!important;border-radius:10px!important;background:rgba(138,43,226,.07)!important;font-size:.8rem!important;min-height:32px!important;max-width:400px!important;margin:5px auto!important}

/* ── HIZLI EYLEM ── */
.beluma-hizli button{font-size:.72rem!important;padding:4px 7px!important;min-height:28px!important;border-radius:7px!important;flex:1!important}

/* ── TAB BAR TAMAMEN GİZLE (sol panel kullanıyor) ── */
.tab-nav{display:none!important}
.tabs > .tabitem > div > .tab-nav{display:none!important}

/* ── MOBİL ── */
@media(max-width:900px){
  #beluma-layout{grid-template-columns:0 1fr 0}
  #beluma-left,#beluma-right{display:none}
  .gradio-container{padding:0!important}
}
@media(max-width:600px){
  #beluma_chat{height:calc(100vh - 180px)!important;max-height:calc(100vh - 180px)!important}
  button.primary{min-height:44px!important}
}
@media(hover:none) and (pointer:coarse){
  button{-webkit-tap-highlight-color:rgba(255,20,147,.15)!important;touch-action:manipulation!important}
  button.primary:hover{transform:none!important;filter:none!important}
}
"""

# ══════════════════════════════════════════════════════════════════
# GRADİO ARAYÜZÜ
# ══════════════════════════════════════════════════════════════════
io = oturumu_yukle()
ip = profili_yukle()

with gr.Blocks(css=CSS) as demo:
    # ── META ──
    gr.HTML('''
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0d0614">
<style>
.gradio-container > .main > .wrap{padding:0!important;max-width:100%!important}
footer{display:none!important}
</style>
''')

    # ══ 3 KOLON LAYOUT ══
    with gr.Row(elem_id="beluma-layout"):

        # ════════════════════════════
        # SOL PANEL
        # ════════════════════════════
        with gr.Column(elem_id="beluma-left", scale=1, min_width=220):
            gr.HTML('''
<div style="padding:10px 6px 6px">
  <div style="font-family:Montserrat,sans-serif;font-size:15px;font-weight:700;
    background:linear-gradient(90deg,#FF1493,#8A2BE2);-webkit-background-clip:text;
    -webkit-text-fill-color:transparent;letter-spacing:.05em;margin-bottom:2px">BELUMA-I</div>
  <div style="font-size:9px;color:rgba(255,255,255,.35)">v6.5 · Türkçe AI Asistan</div>
</div>
<div style="height:1px;background:rgba(138,43,226,.18);margin:0 6px 8px"></div>
''')
            # Sol nav butonları (görsel, tıklanınca tab değiştirecek)
            sol_tab = gr.State("sohbet")

            gr.HTML('<div class="lsec">ANA</div>')
            sol_sohbet_b = gr.Button("💬  Sohbet",        variant="secondary", elem_classes=["lbtn", "active"])
            sol_gorev_b  = gr.Button("📋  Görevler",       variant="secondary", elem_classes=["lbtn"])
            sol_gorsel_b = gr.Button("🎨  Görsel Üret",    variant="secondary", elem_classes=["lbtn"])
            sol_ses_b    = gr.Button("🎙  Ses",            variant="secondary", elem_classes=["lbtn"])
            sol_harita_b = gr.Button("🗺  Yaşam Haritası", variant="secondary", elem_classes=["lbtn"])

            gr.HTML('<div style="height:1px;background:rgba(138,43,226,.12);margin:6px 4px"></div>')
            gr.HTML('<div class="lsec">ARAÇLAR</div>')
            hizli_hava  = gr.Button("🌤  Hava Durumu",  variant="secondary", elem_classes=["lbtn"])
            hizli_borsa = gr.Button("📈  Borsa",         variant="secondary", elem_classes=["lbtn"])
            hizli_haber = gr.Button("📰  Haberler",      variant="secondary", elem_classes=["lbtn"])
            hizli_tarih = gr.Button("📅  Tarih & Saat",  variant="secondary", elem_classes=["lbtn"])
            dr_btn      = gr.Button("🔍  Deep Research", variant="secondary", elem_classes=["lbtn"])

            gr.HTML('<div style="height:1px;background:rgba(138,43,226,.12);margin:6px 4px"></div>')
            gr.HTML('<div class="lsec">AYARLAR</div>')
            sol_analitik_b  = gr.Button("📊  Analitik",    variant="secondary", elem_classes=["lbtn"])
            sol_plugin_b    = gr.Button("🧩  Pluginler",   variant="secondary", elem_classes=["lbtn"])
            sol_webhook_b   = gr.Button("🔗  Webhook",     variant="secondary", elem_classes=["lbtn"])
            sol_hatir_b     = gr.Button("🔔  Hatırlatıcı", variant="secondary", elem_classes=["lbtn"])
            sol_dil_b       = gr.Button("🌍  Dil",         variant="secondary", elem_classes=["lbtn"])
            sol_ekip_b      = gr.Button("🤝  Ekip",        variant="secondary", elem_classes=["lbtn"])
            sol_guvenlik_b  = gr.Button("🔒  Güvenlik",    variant="secondary", elem_classes=["lbtn"])
            sol_hakkinda_b  = gr.Button("ℹ️  Hakkında",    variant="secondary", elem_classes=["lbtn"])

        # ════════════════════════════
        # ORTA — SOHBET + SEKMELER
        # ════════════════════════════
        with gr.Column(elem_id="beluma-center", scale=4):
            durum         = gr.Markdown("Hazır.", elem_classes=["beluma-status"])
            _oner_ilk     = gunluk_oneri()
            oneri_kutu    = gr.Markdown(_oner_ilk, visible=bool(_oner_ilk), elem_classes=["beluma-soft"])
            aciklama_kutu = gr.Markdown("", elem_classes=["think-box"], visible=False)

            sg  = gr.State(io.get("chat_history",[]))
            bas = gr.State(io.get("document_name",""))
            bms = gr.State(io.get("document_text",""))

            with gr.Tabs() as ana_tabs:
                # ── Sohbet ──
                with gr.Tab("💬 Sohbet", id="sohbet"):
                    resim_on = gr.Image(label="Vision", type="filepath", height=120, visible=False)
                    chatbot  = gr.Chatbot(
                        value=[{"role":"assistant","content":"👋 Merhaba! Ben **BELUMA-I**. Sana nasıl yardımcı olabilirim?\n\n💡 Hava, borsa, haberler, kod yazma, analiz veya sohbet — her şey için burdayım!"}],
                        height=480, elem_id="beluma_chat",
                        type="messages",
                    )
                    dr_output = gr.Markdown(visible=False)
                    with gr.Column(elem_id="beluma-inputbar"):
                        with gr.Row(equal_height=True, elem_classes=["beluma-bar"]):
                            mk = gr.Textbox(placeholder="Mesajını yaz... (Enter → gönder)", lines=1, max_lines=5, show_label=False, scale=9)
                            gb = gr.Button("Gönder ✈", variant="primary", scale=2)
                        with gr.Row(elem_classes=["beluma-frame"]):
                            ys  = gr.Slider(minimum=0.0, maximum=1.0, value=0.4, step=0.1, label="🧠 Yaratıcılık", scale=1)
                            ork = gr.Textbox(label="🎭 Özel Rol", placeholder="Örn: Kıdemli yazılımcısın...", lines=1, scale=2)
                            uzmanlik_secici = gr.Dropdown(list(UZMANLIK_MODLARI.keys()), value="Standart", label="🎓 Uzmanlık", scale=1)
                        with gr.Row(elem_classes=["beluma-frame"]):
                            bb  = gr.UploadButton("📎 Belge", file_count="single", file_types=[".pdf",".docx",".xlsx",".xls",".txt",".csv",".md",".json"], scale=2, elem_classes=["belge-upload-btn"])
                            rb  = gr.UploadButton("🖼️ Resim", file_count="single", file_types=["image"], scale=2, elem_classes=["belge-upload-btn"])
                            ysb = gr.Button("🔄 Yeni",    variant="secondary", scale=2)
                            syb = gr.Button("📂 Yükle",   variant="secondary", scale=2)
                            ib  = gr.Button("🔍 Denetle", variant="secondary", scale=2)
                            sib = gr.Button("📥 İndir",   variant="secondary", scale=2)
                    with gr.Column(elem_classes=["beluma-examples"]):
                        gr.Examples(
                            examples=[
                                "Bugün tarih ve saat kaç?",
                                "İstanbul hava durumu?",
                                "Son haberler neler?",
                                "Borsa bugün nasıl?",
                                "Karar veremiyorum, nasıl düşünmeliyim?",
                                "Bu hafta projem için adım adım plan yap",
                                "Kod yaz: Python'da fibonacci",
                                "Motivasyonum düşük, ne yapmalıyım?",
                            ],
                            inputs=mk, examples_per_page=8)
                    with gr.Column(elem_classes=["beluma-accordion-frame"]):
                        with gr.Accordion("⚙️ Kişisel Ayarlar", open=False, elem_classes=["beluma-acc-item"]):
                            ta = gr.Textbox(label="Adın", value=ip.get("name",""))
                    with gr.Row():
                        tt = gr.Dropdown(["samimi","profesyonel","enerjik"], value=ip.get("tone","samimi"), label="Ton")
                        ts = gr.Dropdown(["kısa","dengeli","detaylı"], value=ip.get("style","dengeli"), label="Stil")
                        tm = gr.Dropdown(
                            choices=["llama-3.3-70b-versatile","llama-3.1-8b-instant","gemma2-9b-it",
                                     "gemini-1.5-pro","gemini-1.5-flash","deepseek-chat",
                                     "gpt-4o-mini","gpt-4o",
                                     "claude-3-5-sonnet-20241022","claude-3-5-haiku-20241022"],
                            value="llama-3.3-70b-versatile", label="🧠 Model")
                    ph = gr.Textbox(label="Beni tanı", lines=2, value=ip.get("about",""))
                    pt = gr.Textbox(label="Tercih notları", lines=2, value=ip.get("preferences",""))
                    akb = gr.Button("Kaydet"); akd = gr.Markdown("")
                with gr.Accordion("🛠️ Gelişmiş", open=False, elem_classes=["beluma-acc-item"]):
                    with gr.Row():
                        mts = gr.Slider(minimum=100, maximum=8192, value=1024, step=100, label="📏 Max Tokens")
                        tps = gr.Slider(minimum=0.1, maximum=1.0, value=0.9, step=0.05, label="🎲 Top-P")
                with gr.Accordion("🧠 Öğrenilenler", open=False, elem_classes=["beluma-acc-item"]):
                    og  = gr.Textbox(label="Öğrenilenler", value="\n".join(ip.get("learned",[])) or "Henüz yok.", lines=5, interactive=False)
                    ogy = gr.Button("Yenile")
                    with gr.Row():
                        osi = gr.Textbox(label="Silinecek tercih", scale=3)
                        osb = gr.Button("Sil 🗑", variant="stop", scale=1)
                    osd = gr.Markdown("")

        with gr.Tab("📋 Görev", id="gorev"):
            gl  = gr.Textbox(label="Görevler", value=gorevleri_metne_cevir(), lines=12, interactive=False)
            gyb = gr.Button("Yenile", variant="secondary")
            with gr.Row():
                yga = gr.Textbox(label="Yeni görev", scale=4)
                geb = gr.Button("Ekle ✚", variant="primary", scale=1)
            with gr.Row():
                gii = gr.Textbox(label="Görev ID", scale=3)
                gtb = gr.Button("Tamam ✓",  variant="primary",   scale=1)
                gsb = gr.Button("Sil 🗑",   variant="secondary",  scale=1)
            gd = gr.Markdown("")

        with gr.Tab("🎨 Görsel", id="gorsel"):
            gsd = gr.Markdown("Hazır.", elem_classes=["beluma-status"])
            gr.Markdown("#### ⚡ Şablonlar", elem_classes=["beluma-soft"])
            with gr.Row():
                te  = gr.Button("📦 Ürün",     variant="secondary", scale=1)
                tso = gr.Button("📱 Sosyal",   variant="secondary", scale=1)
                tmi = gr.Button("🏠 Mimari",   variant="secondary", scale=1)
                tk  = gr.Button("🧑‍🎨 Karakter", variant="secondary", scale=1)
            with gr.Row():
                with gr.Column(scale=3):
                    gp  = gr.Textbox(label="Ne görmek istiyorsun?", lines=4)
                    with gr.Row():
                        gst = gr.Dropdown(choices=list(GORSEL_STILLER.keys()), value="Gerçekçi", label="🎨 Stil")
                        gor = gr.Dropdown(["1:1","16:9","9:16","4:5"], value="1:1", label="📐 Oran")
                    gg  = gr.Slider(minimum=7, maximum=12, value=9, step=0.5, label="🎛 Guidance")
                    with gr.Row():
                        gub = gr.Button("🚀 Tek Görsel", variant="primary",    scale=3)
                        gvb = gr.Button("🔄 4 Varyasyon", variant="secondary",  scale=2)
                        gtm = gr.Button("🧹 Temizle",    variant="stop",        scale=1)
                    kg = gr.Markdown(kredi_kontrol()[1], elem_classes=["beluma-soft"])
                with gr.Column(scale=2):
                    gso = gr.Image(label="Sonuç", type="filepath")
                    gga = gr.Gallery(label="Varyasyonlar", columns=2, rows=2, object_fit="contain", visible=False)

        with gr.Tab("🎙 Ses", id="ses"):
            gr.Markdown("Konuş → BELUMA-I sesli cevap versin.", elem_classes=["beluma-status"])
            with gr.Tabs():
                with gr.Tab("🎤 Sesli Diyalog"):
                    sgi = gr.Audio(sources=["microphone"], type="filepath", label="Konuş")
                    sct = gr.Textbox(label="Metin", lines=4, interactive=False)
                    sca = gr.Audio(label="Ses", type="filepath", autoplay=True)
                    scb = gr.Button("🎤 Gönder", variant="primary")
                with gr.Tab("🔧 Manuel"):
                    si   = gr.Audio(sources=["microphone","upload"], type="filepath", label="Ses")
                    with gr.Row():
                        syb2 = gr.Button("Yazıya çevir 📝", variant="primary")
                        ssb  = gr.Button("Seslendir 🔊",    variant="secondary")
                    scm = gr.Textbox(label="Metin", lines=4)
                    sco = gr.Audio(label="Çıktı", type="filepath")

        with gr.Tab("🗺 Harita", id="harita"):
            lm = haritayi_yukle()
            gr.Markdown("### Life Map\nHedefler, alışkanlıklar, performans.")
            with gr.Tabs():
                with gr.Tab("🎯 Hedefler"):
                    lhl = gr.Textbox(label="Hedefler", value=_hedef_listesi(), lines=8, interactive=False)
                    with gr.Row():
                        lyh = gr.Textbox(label="Yeni hedef", scale=3)
                        lop = gr.Dropdown(["1 - Düşük","2 - Orta","3 - Yüksek"], value="2 - Orta", label="Öncelik", scale=1)
                        lhb = gr.Button("Ekle ✚", variant="primary", scale=1)
                    with gr.Row():
                        lti = gr.Textbox(label="Tamamlanan", scale=3)
                        ltb = gr.Button("Tamam ✓", variant="primary", scale=1)
                    lhd = gr.Markdown("")
                with gr.Tab("📓 Notlar"):
                    lni = gr.Textbox(label="Not", lines=4)
                    with gr.Row():
                        lnk = gr.Dropdown(["genel","iş","kişisel","öğrenme","sağlık"], value="genel", label="Kategori")
                        lnb = gr.Button("Kaydet 📓", variant="primary")
                    lnd = gr.Markdown("")
                    lsn = gr.Textbox(label="Son notlar",
                                     value="\n---\n".join(f"[{n['tarih']}] {n['not']}" for n in lm.get("gunluk_notlar",[])[-5:]) or "Henüz yok.",
                                     lines=8, interactive=False)
                with gr.Tab("🔄 Alışkanlıklar"):
                    lai = gr.Textbox(label="Alışkanlık")
                    lab = gr.Button("Bugün yaptım ✓", variant="primary")
                    lal = gr.Textbox(label="Seriler",
                                     value="\n".join(f"🔥 {a['aliskanlik']}: {a['seri']}g" for a in lm.get("aliskanliklar",[])) or "Henüz yok.",
                                     lines=6, interactive=False)
                    lad = gr.Markdown("")
                with gr.Tab("📊 Rapor"):
                    rpb = gr.Button("📊 Aylık rapor", variant="primary")
                    rpc = gr.Markdown("")
            with gr.Accordion("⚙️ Vizyon", open=False):
                lis = gr.Textbox(label="İş modeli",  value=lm.get("is_modeli",""))
                lpl = gr.Textbox(label="Uzun vade",  lines=3, value=lm.get("uzun_vadeli_plan",""))
                lka = gr.Textbox(label="Karar tarzı", value=lm.get("karar_tarzi",""))
                lkb = gr.Button("Kaydet 🗺", variant="primary")
                lkd = gr.Markdown("")

        with gr.Tab("🤝 Ekip", id="ekip"):
            # Duyurular
            ekip_duyuru_goster = gr.Markdown(value=duyurular_metin() or "Duyuru yok.")
            # Kullanıcı listesi
            ekip_kullanici_liste = gr.Markdown(value=kullanici_listesi_metin())
            ekip_yenile = gr.Button("🔄 Yenile", variant="secondary")
            gr.Markdown("---")
            gr.Markdown("**👑 Admin — Kullanıcı Yönetimi**")
            with gr.Row():
                ekip_yeni_ad    = gr.Textbox(label="Kullanıcı Adı", scale=2)
                ekip_yeni_sifre = gr.Textbox(label="Şifre", type="password", scale=2)
                ekip_yeni_rol   = gr.Dropdown(ROLLER, value="editor", label="Rol", scale=1)
            with gr.Row():
                ekip_yeni_isim  = gr.Textbox(label="Ad Soyad (opsiyonel)", scale=2)
                ekip_yeni_email = gr.Textbox(label="E-posta (opsiyonel)", scale=2)
                ekip_ekle_b     = gr.Button("➕ Ekle", variant="primary", scale=1)
            ekip_ekle_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown("**Rol Değiştir / Sil**")
            with gr.Row():
                ekip_rol_ad     = gr.Textbox(label="Kullanıcı Adı", scale=2)
                ekip_yeni_rol2  = gr.Dropdown(ROLLER, value="editor", label="Yeni Rol", scale=1)
                ekip_rol_b      = gr.Button("🔄 Rol Değiştir", variant="secondary", scale=1)
                ekip_sil_b      = gr.Button("🗑 Sil",          variant="stop",      scale=1)
            ekip_rol_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown("**📝 Ortak Notlar**")
            ekip_not_liste = gr.Markdown(value=ortak_notlar_metin())
            with gr.Row():
                ekip_not_metin = gr.Textbox(label="Yeni not", lines=2, scale=4)
                ekip_not_b     = gr.Button("📝 Ekle", variant="primary", scale=1)
            ekip_not_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown("**📢 Duyuru Yayınla (Admin)**")
            with gr.Row():
                ekip_duyuru_metin = gr.Textbox(label="Duyuru", scale=4)
                ekip_duyuru_b     = gr.Button("📢 Yayınla", variant="primary", scale=1)
            ekip_duyuru_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown("**📋 Aktivite Logu**")
            ekip_aktivite = gr.Markdown(value=aktivite_logu_metin())

        with gr.Tab("🌍 Dil", id="dil"):
            dil_durum   = gr.Markdown(f"Mevcut dil: **{mevcut_dil_etiketi()}**")
            dil_secici  = gr.Dropdown(
                choices=list(DESTEKLENEN_DILLER.values()),
                value=mevcut_dil_etiketi(),
                label="Arayüz ve yanıt dili seç"
            )
            dil_kaydet_b = gr.Button("✅ Dili Uygula", variant="primary")
            dil_kaydet_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown(
                "**Desteklenen diller:**\n"
                "- 🇹🇷 Türkçe (varsayılan)\n"
                "- 🇬🇧 English\n"
                "- 🇩🇪 Deutsch\n"
                "- 🇫🇷 Français\n"
                "- 🇪🇸 Español\n"
                "- 🇸🇦 العربية\n"
                "- 🇷🇺 Русский\n"
                "- 🇯🇵 日本語\n\n"
                "Dil değiştiğinde model **seçilen dilde** yanıt üretir.\n\n"
                "**Özel çeviri eklemek için** `beluma_i18n.json` dosyasını düzenle:\n"
                "```json\n"
                '{\n  "en": {\n    "gonder": "Send ✈"\n  }\n}\n'
                "```"
            )

        with gr.Tab("🔔 Hatırlat", id="hatir"):
            htr_bildirimler = gr.Markdown(value="", label="Bildirimler")
            with gr.Row():
                htr_yenile  = gr.Button("🔄 Yenile",          variant="secondary", scale=1)
                htr_temizle = gr.Button("🧹 Bildirimleri Temizle", variant="stop", scale=1)
            gr.Markdown("---")
            htr_liste = gr.Markdown(value=hatirlaticilar_listesi_metin())
            gr.Markdown("---")
            gr.Markdown("**Yeni Hatırlatıcı Ekle**")
            with gr.Row():
                htr_mesaj = gr.Textbox(label="Mesaj", placeholder="Toplantıya katıl, ilaç iç...", scale=3)
                htr_zaman = gr.Textbox(label="Ne zaman?", placeholder="30 dakika sonra / yarın 09:00 / her gün 08:00", scale=3)
            with gr.Row():
                htr_ekle_b = gr.Button("➕ Ekle", variant="primary", scale=1)
                htr_ekle_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown("**Hatırlatıcı Sil**")
            with gr.Row():
                htr_sil_id = gr.Textbox(label="Hatırlatıcı ID", placeholder="8 haneli ID", scale=2)
                htr_sil_b  = gr.Button("🗑 Sil", variant="stop", scale=1)
                htr_sil_d  = gr.Markdown("")
            gr.Markdown(
                "**Zaman ifadesi örnekleri:**\n"
                "- `30 dakika sonra` — 30 dakika içinde\n"
                "- `2 saat sonra` — 2 saat içinde\n"
                "- `yarın 09:00` — yarın sabah 09:00\n"
                "- `bugün 14:30` — bugün öğleden sonra\n"
                "- `her gün 08:00` — her sabah 08:00 (tekrarlayan)\n"
                "- `2025-12-31 10:00` — tam tarih ve saat"
            )

        with gr.Tab("🔗 Webhook", id="webhook"):
            wh_liste  = gr.Markdown(value=webhook_listesi_metin())
            wh_yenile = gr.Button("🔄 Yenile", variant="secondary")
            gr.Markdown("---")
            gr.Markdown("**Yeni Webhook Ekle**")
            with gr.Row():
                wh_isim = gr.Textbox(label="İsim",    placeholder="Örn: Slack Bildirim",  scale=2)
                wh_url  = gr.Textbox(label="URL",     placeholder="https://hooks.slack.com/...", scale=4)
            with gr.Row():
                wh_secret = gr.Textbox(label="Secret (opsiyonel)", placeholder="HMAC imza için", scale=3)
                wh_olaylar = gr.CheckboxGroup(
                    choices=["mesaj","gorsel","hata","hedef"],
                    value=["mesaj"], label="Olaylar", scale=3)
            with gr.Row():
                wh_ekle_b = gr.Button("➕ Ekle",  variant="primary",   scale=1)
                wh_ekle_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown("**Webhook Yönetimi**")
            with gr.Row():
                wh_id_in   = gr.Textbox(label="Webhook ID", placeholder="8 haneli ID", scale=2)
                wh_test_b  = gr.Button("🧪 Test Gönder",  variant="secondary", scale=1)
                wh_toggle_b= gr.Button("⏸/▶️ Aktif/Pasif", variant="secondary", scale=1)
                wh_sil_b   = gr.Button("🗑 Sil",          variant="stop",      scale=1)
            wh_yonetim_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown(
                "**Desteklenen Olaylar:**\n"
                "- `mesaj` — Her sohbet mesajı sonrası\n"
                "- `gorsel` — Görsel üretimi sonrası\n"
                "- `hata` — Kritik hata oluşunca\n"
                "- `hedef` — Hedef eklenince/tamamlanınca\n\n"
                "**Payload örneği:**\n"
                "```json\n"
                '{\n  "olay": "mesaj",\n  "zaman": "2025-01-01 12:00:00",\n'
                '  "kaynak": "BELUMA-I",\n  "kullanici_mesaji": "...",\n  "cevap": "..."\n}\n'
                "```\n\n"
                "İmza doğrulama: `X-Beluma-Signature: sha256=<hmac>`"
            )

        with gr.Tab("🧩 Plugin", id="plugin"):
            pl_liste  = gr.Markdown(value=plugin_listesi_metin(), label="Yüklü Pluginler")
            with gr.Row():
                pl_yenile = gr.Button("🔄 Yeniden Yükle", variant="primary")
                pl_durum  = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown("**Plugin Yönetimi**")
            with gr.Row():
                pl_isim_in = gr.Textbox(label="Plugin İsmi", placeholder="Örn: Döviz Çevirici", scale=3)
                pl_pasif_b = gr.Button("⏸ Pasife Al",   variant="secondary", scale=1)
                pl_aktif_b = gr.Button("▶️ Aktif Et",   variant="secondary", scale=1)
            pl_yonetim_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown(
                "**Kendi Plugin'ini Yaz:**\n\n"
                "```python\n"
                "# beluma_plugins/benim_plugin.py\n"
                "PLUGIN_ISIM     = 'Benim Plugin'\n"
                "PLUGIN_VERSIYON = '1.0'\n"
                "PLUGIN_ACIKLAMA = 'Ne yapar?'\n"
                "TETIKLEYICILER  = ['anahtar kelime']\n\n"
                "def calistir(mesaj: str) -> str:\n"
                "    return f'Sonuç: {mesaj}'\n"
                "```\n\n"
                "Dosyayı `beluma_plugins/` klasörüne at, **Yeniden Yükle** butonuna bas."
            )

        with gr.Tab("📊 Analitik", id="analitik"):
            anl_html   = gr.HTML(value=dashboard_html(), label="Dashboard")
            anl_yenile = gr.Button("🔄 Yenile", variant="secondary")
            anl_yenile.click(fn=dashboard_html, outputs=[anl_html])

        with gr.Tab("🔒 Güvenlik", id="guvenlik"):
            gr.Markdown("### Korumalar\n- 🛡️ Injection tespiti\n- ⚠️ Phishing tarama\n- 🔐 SHA-256 şifreler\n- 🧮 AST hesap (eval yok)\n- 🔒 Atomic write\n- ♻️ atexit cleanup\n\n### .env Kurulumu\n`GROQ_API_KEY=gsk_...` (zorunlu — Llama/Gemma)\n`HF_TOKEN=hf_...` (görsel üretim)\n`GEMINI_API_KEY=...` (isteğe bağlı)\n`DEEPSEEK_API_KEY=...` (isteğe bağlı)\n`OPENAI_API_KEY=...` (isteğe bağlı)\n`ANTHROPIC_API_KEY=...` (isteğe bağlı)\n\n### Kurulum\n`pip install google-generativeai anthropic openai duckduckgo-search`")
            vsb = gr.Button("🗑 Tüm verileri sil", variant="stop")
            vsd = gr.Markdown("")
            gr.Markdown("---")
            hib = gr.Button("📊 Hata İstatistikleri", variant="secondary")
            hid = gr.Markdown("")

        with gr.Tab("ℹ️ Hakkında", id="hakkinda"):
            gr.Markdown("### BELUMA-I — v6.5 (3 Kolon Layout)\n\n**Tüm özellikler:**\n- 💬 Akıllı sohbet (Groq, Gemini, DeepSeek, OpenAI, Claude)\n- 📋 Görev yönetimi\n- 🎨 Görsel üretimi (FLUX, SDXL)\n- 🎙 Ses tanıma & sentez\n- 🗺 Yaşam haritası & hedefler\n- 🔗 Webhook entegrasyonu\n- 🔔 Hatırlatıcı sistemi\n- 🌍 8 dil desteği\n- 🤝 Çoklu kullanıcı / ekip modu\n- 📊 Analitik dashboard\n- 🧩 Plugin sistemi\n- 🛡️ Güvenlik & hata yönetimi\n\n**Kurucu:** BELUMA Group YKB Özgür")

        # ════════════════════════════
        # SAĞ PANEL
        # ════════════════════════════
        with gr.Column(elem_id="beluma-right", scale=1, min_width=210):
            sag_panel_html = gr.HTML(value=sag_panel_guncelle(), elem_id="beluma-right-html")
            sag_yenile_b   = gr.Button("🔄", variant="secondary", size="sm")

    # ══ EVENTS ══
    rb.upload(lambda f: gr.Image(value=f.name if hasattr(f,"name") else f, visible=True), inputs=[rb], outputs=[resim_on])

    def sw(m,g,a,t,s,ba,bm,y,o,uz,sm,mt,tp,ri):
        for yg,tz,d,ac in sohbet_et(m,g,a,t,s,ba,bm,y,o,sm,mt,tp,aktif_resim=ri,uzmanlik=uz):
            yield chatbot_icin_hazirla(yg),tz,d,gr.Markdown(value=f"**💭:** {ac}" if ac else "",visible=bool(ac)),gr.Image(value=None,visible=False),yg

    si_list = [mk,sg,ta,tt,ts,bas,bms,ys,ork,uzmanlik_secici,tm,mts,tps,resim_on]
    so_list = [chatbot,mk,durum,aciklama_kutu,resim_on,sg]
    gb.click(sw, inputs=si_list, outputs=so_list, show_progress="hidden")
    mk.submit(sw, inputs=si_list, outputs=so_list, show_progress="hidden")

    def _oneri_kutu_guncelle():
        o=gunluk_oneri(); return gr.Markdown(value=o,visible=bool(o))
    ysb.click(yeni_sohbet,inputs=[bas,bms],outputs=[chatbot,durum]).then(lambda:[], outputs=[sg]).then(_oneri_kutu_guncelle,outputs=[oneri_kutu])
    syb.click(son_sohbeti_yukle,outputs=[chatbot,sg,bas,bms,durum])
    bb.upload(belge_yukle,inputs=[bb],outputs=[bas,bms,durum])
    akb.click(ayarlari_kaydet,inputs=[ta,tt,ts,ph,pt],outputs=[akd])
    ogy.click(lambda:"\n".join(profili_yukle().get("learned",[])) or "Henüz yok.",outputs=[og])
    osb.click(ogrenileni_sil,inputs=[osi],outputs=[og,osd]).then(lambda:"",outputs=[osi])
    ib.click(cevabi_iyilestir,inputs=[sg],outputs=[chatbot,durum]).then(lambda h:h,inputs=[chatbot],outputs=[sg])
    indir_dosya = gr.File(label="İndirilen Sohbet", visible=False)
    sib.click(fn=sohbeti_indir, inputs=[sg, ta], outputs=[indir_dosya]).then(
        fn=lambda x: gr.File(value=x, visible=True) if x else gr.File(visible=False),
        inputs=[indir_dosya], outputs=[indir_dosya])
    gyb.click(gorevleri_metne_cevir,outputs=[gl])

    def mgef(b):
        if not (b or "").strip(): return "Boş.",gorevleri_metne_cevir()
        gorev_ekle(b.strip()); return f"✅ {b.strip()}",gorevleri_metne_cevir()
    geb.click(mgef,inputs=[yga],outputs=[gd,gl]).then(lambda:"",outputs=[yga])

    def gtuf(g):
        try:
            gorev_tamamla_id(int(g)); return "✅", gorevleri_metne_cevir()
        except ValueError:
            return "⚠️ Geçerli bir sayısal ID gir.", gorevleri_metne_cevir()
        except GorevHatasi as e:
            _hata_say("gorev.tamamla"); return f"⚠️ Görev hatası: {e}", gorevleri_metne_cevir()
        except Exception as e:
            _logger.error("[gtuf] %s", e); _hata_say("gorev.tamamla.genel")
            return "⚠️ Beklenmeyen hata. Lütfen tekrar dene.", gorevleri_metne_cevir()
    def gsuf(g):
        try:
            gorev_sil_id(int(g)); return "🗑 Silindi.", gorevleri_metne_cevir()
        except ValueError:
            return "⚠️ Geçerli bir sayısal ID gir.", gorevleri_metne_cevir()
        except GorevHatasi as e:
            _hata_say("gorev.sil"); return f"⚠️ Görev hatası: {e}", gorevleri_metne_cevir()
        except Exception as e:
            _logger.error("[gsuf] %s", e); _hata_say("gorev.sil.genel")
            return "⚠️ Beklenmeyen hata. Lütfen tekrar dene.", gorevleri_metne_cevir()
    gtb.click(gtuf,inputs=[gii],outputs=[gd,gl])
    gsb.click(gsuf,inputs=[gii],outputs=[gd,gl])

    te.click( lambda:("product photography, white background, studio lighting, 4K","Gerçekçi","1:1"),outputs=[gp,gst,gor])
    tso.click(lambda:("vibrant social media post, bold colors, modern design","Minimal","1:1"),        outputs=[gp,gst,gor])
    tmi.click(lambda:("luxury real estate, wide angle interior, soft sunlight, 4k","Emlak/Mimari","16:9"),outputs=[gp,gst,gor])
    tk.click( lambda:("professional portrait, soft lighting, detailed face, cinematic","Gerçekçi","9:16"),outputs=[gp,gst,gor])

    def _tgw(p,s,g):
        ok,km=kredi_kullan()
        if not ok: return None,gr.Gallery(visible=False),km,km
        y,m,_,_=generate_single(gorsel_prompt_muhendisi(p),s,g)
        if y: son_gorsel_kaydet(y)
        return y,gr.Gallery(visible=False),m or km,kredi_kontrol()[1]
    gub.click(_tgw,inputs=[gp,gst,gg],outputs=[gso,gga,gsd,kg])

    def _vw(p,s,g):
        ok,km=kredi_kullan()
        if not ok: return gr.Gallery(visible=False),None,km,km
        l,m=generate_variations(gorsel_prompt_muhendisi(p),s,g)
        if l: son_gorsel_kaydet(l[0])
        return (gr.Gallery(value=l,visible=True) if l else gr.Gallery(visible=False)),None,m,kredi_kontrol()[1]
    gvb.click(_vw,inputs=[gp,gst,gg],outputs=[gga,gso,gsd,kg])
    gtm.click(lambda:("","Gerçekçi","1:1",9.0,None,gr.Gallery(visible=False),"🧹"),outputs=[gp,gst,gor,gg,gso,gga,gsd])

    def sd(au,g,a,t,s):
        if not au: return g,"Konuş.",None
        m,_ = sesi_yaziya_cevir(au)
        if not m: return g,"Anlaşılamadı.",None
        yg=g
        for y,_,_,_ in sohbet_et(m,g,a,t,s,"",""): yg=y
        sc=son_asistan_mesaji(yg)
        cs=" ".join("".join(c if (c.isalnum() or c in " .,!?;:") else " " for c in sc[:400]).split())
        sf,_=metni_seslendir_premium(cs)
        if not sf: sf,_=metni_seslendir(cs)
        return yg,sc,sf
    scb.click(sd,inputs=[sgi,sg,ta,tt,ts],outputs=[sg,sct,sca])
    syb2.click(sesi_yaziya_cevir,inputs=[si],outputs=[scm,durum]).then(lambda t:t,inputs=[scm],outputs=[mk])

    def _ss(g):
        m=son_asistan_mesaji(g); s,_=metni_seslendir_premium(m)
        if not s: s,_=metni_seslendir(m)
        return s
    ssb.click(_ss,inputs=[sg],outputs=[sco])

    def lvk(i,p,k):
        v=haritayi_yukle(); v["is_modeli"]=i.strip(); v["uzun_vadeli_plan"]=p.strip(); v["karar_tarzi"]=k.strip(); haritayi_kaydet(v); return "✅ Kaydedildi."
    lkb.click(lvk,inputs=[lis,lpl,lka],outputs=[lkd])

    def lhef(h,o):
        if not (h or "").strip(): return "Boş.",_hedef_listesi()
        hedef_ekle(h.strip(),int(o.split(" - ")[0])); return f"✅ {h.strip()}",_hedef_listesi()
    lhb.click(lhef,inputs=[lyh,lop],outputs=[lhd,lhl]).then(lambda:"",outputs=[lyh])

    def lhtf(m):
        if not (m or "").strip(): return "Boş.",_hedef_listesi()
        hedef_tamamla(m.strip()); return "✅ Tamam!",_hedef_listesi()
    ltb.click(lhtf,inputs=[lti],outputs=[lhd,lhl]).then(lambda:"",outputs=[lti])

    def lnef(m,k):
        if not (m or "").strip(): return "Boş.",""
        gunluk_not_ekle(m.strip(),k); return "✅","\n---\n".join(f"[{n['tarih']}] {n['not']}" for n in haritayi_yukle().get("gunluk_notlar",[])[-5:])
    lnb.click(lnef,inputs=[lni,lnk],outputs=[lnd,lsn]).then(lambda:"",outputs=[lni])

    def laf(m):
        if not (m or "").strip(): return "Boş.",""
        aliskanlik_guncelle(m.strip()); return f"✅ {m.strip()}","\n".join(f"🔥 {a['aliskanlik']}: {a['seri']}g" for a in haritayi_yukle().get("aliskanliklar",[])) or "Yok."
    lab.click(laf,inputs=[lai],outputs=[lad,lal])
    rpb.click(aylik_rapor_olustur,outputs=[rpc])

    def _deep_research_handler(konu_text):
        if not (konu_text or "").strip():
            yield gr.Markdown(value="Araştırma yapmak için mesaj kutusuna bir konu yazın.",visible=True); return
        rapor=""
        for chunk in derin_arastirma_yap(konu_text.strip()):
            rapor+=chunk; yield gr.Markdown(value=rapor,visible=True)
    dr_btn.click(_deep_research_handler,inputs=[mk],outputs=[dr_output])

    # Mobil hızlı eylem butonları
    hizli_hava.click( fn=lambda: "İstanbul hava durumu?",  outputs=[mk])
    hizli_borsa.click(fn=lambda: "Borsa bugün nasıl?",     outputs=[mk])
    hizli_haber.click(fn=lambda: "Son haberler neler?",    outputs=[mk])
    hizli_tarih.click(fn=lambda: "Bugün tarih ve saat kaç?", outputs=[mk])
    hizli_temiz.click(fn=yeni_sohbet, inputs=[bas,bms], outputs=[chatbot,durum]).then(lambda:[], outputs=[sg])

    def tvs():
        sl=[]
        for f in [SESSION_FILE,PROFILE_FILE,TASKS_FILE,LIFE_MAP_FILE,MEMORY_FILE,KREDI_FILE,AUTH_FILE]:
            try:
                if f.exists(): f.unlink(); sl.append(f.name)
            except OSError: pass
        for p in ["beluma_*.png","beluma_*tts_*.mp3"]:
            for t in glob.glob(str(Path(tempfile.gettempdir())/p)):
                try:
                    Path(t).unlink()
                except OSError as e:
                    _logger.warning("[tvs] geçici dosya silinemedi %s: %s", t, e)
                    _hata_say("temizlik.gecici_dosya")
        return f"✅ Silindi: {', '.join(sl) if sl else 'temiz'}."
    vsb.click(tvs,outputs=[vsd])
    hib.click(hata_istatistikleri, outputs=[hid])

    # Plugin eventleri
    pl_yenile.click(fn=plugin_yeniden_yukle, outputs=[pl_durum]).then(fn=plugin_listesi_metin, outputs=[pl_liste])
    pl_pasif_b.click(fn=plugin_pasif_yap, inputs=[pl_isim_in], outputs=[pl_yonetim_d]).then(fn=plugin_listesi_metin, outputs=[pl_liste])
    pl_aktif_b.click(fn=plugin_aktif_yap, inputs=[pl_isim_in], outputs=[pl_yonetim_d]).then(fn=plugin_listesi_metin, outputs=[pl_liste])

    # Webhook eventleri
    wh_yenile.click(fn=webhook_listesi_metin, outputs=[wh_liste])
    wh_ekle_b.click(fn=webhook_ekle, inputs=[wh_isim, wh_url, wh_olaylar, wh_secret], outputs=[wh_ekle_d]).then(fn=webhook_listesi_metin, outputs=[wh_liste])
    wh_test_b.click(fn=webhook_test_gonder, inputs=[wh_id_in], outputs=[wh_yonetim_d]).then(fn=webhook_listesi_metin, outputs=[wh_liste])
    wh_toggle_b.click(fn=webhook_toggle, inputs=[wh_id_in], outputs=[wh_yonetim_d]).then(fn=webhook_listesi_metin, outputs=[wh_liste])
    wh_sil_b.click(fn=webhook_sil, inputs=[wh_id_in], outputs=[wh_yonetim_d]).then(fn=webhook_listesi_metin, outputs=[wh_liste])

    # Hatırlatıcı eventleri
    htr_yenile.click(fn=bildirim_kuyrugu_oku,        outputs=[htr_bildirimler]).then(fn=hatirlaticilar_listesi_metin, outputs=[htr_liste])
    htr_temizle.click(fn=bildirimleri_temizle,        outputs=[htr_bildirimler])
    htr_ekle_b.click(fn=hatirlatici_ekle, inputs=[htr_mesaj, htr_zaman], outputs=[htr_ekle_d]).then(fn=hatirlaticilar_listesi_metin, outputs=[htr_liste]).then(lambda: "", outputs=[htr_mesaj]).then(lambda: "", outputs=[htr_zaman])
    htr_sil_b.click(fn=hatirlatici_sil,  inputs=[htr_sil_id],            outputs=[htr_sil_d]).then(fn=hatirlaticilar_listesi_metin,   outputs=[htr_liste])

    # Dil eventleri
    def _dil_uygula(secilen):
        mesaj, _ = dil_secici_guncelle(secilen)
        return mesaj, f"Mevcut dil: **{mevcut_dil_etiketi()}**"
    dil_kaydet_b.click(fn=_dil_uygula, inputs=[dil_secici], outputs=[dil_kaydet_d, dil_durum])

    # Ekip eventleri
    def _ekip_yenile():
        return kullanici_listesi_metin(), ortak_notlar_metin(), aktivite_logu_metin(), duyurular_metin() or "Duyuru yok."
    ekip_yenile.click(fn=_ekip_yenile, outputs=[ekip_kullanici_liste, ekip_not_liste, ekip_aktivite, ekip_duyuru_goster])

    ekip_ekle_b.click(
        fn=kullanici_ekle,
        inputs=[ekip_yeni_ad, ekip_yeni_sifre, ekip_yeni_rol, ekip_yeni_isim, ekip_yeni_email],
        outputs=[ekip_ekle_d]
    ).then(fn=kullanici_listesi_metin, outputs=[ekip_kullanici_liste])

    ekip_rol_b.click(
        fn=kullanici_rol_degistir,
        inputs=[ekip_rol_ad, ekip_yeni_rol2],
        outputs=[ekip_rol_d]
    ).then(fn=kullanici_listesi_metin, outputs=[ekip_kullanici_liste])

    ekip_sil_b.click(
        fn=kullanici_sil,
        inputs=[ekip_rol_ad],
        outputs=[ekip_rol_d]
    ).then(fn=kullanici_listesi_metin, outputs=[ekip_kullanici_liste])

    ekip_not_b.click(
        fn=ortak_not_ekle,
        inputs=[ekip_not_metin],
        outputs=[ekip_not_d]
    ).then(fn=ortak_notlar_metin, outputs=[ekip_not_liste]).then(lambda: "", outputs=[ekip_not_metin])

    ekip_duyuru_b.click(
        fn=duyuru_ekle,
        inputs=[ekip_duyuru_metin],
        outputs=[ekip_duyuru_d]
    ).then(fn=lambda: duyurular_metin() or "Duyuru yok.", outputs=[ekip_duyuru_goster]).then(lambda: "", outputs=[ekip_duyuru_metin])

    # ── Sağ panel yenile ──
    sag_yenile_b.click(fn=sag_panel_guncelle, outputs=[sag_panel_html])

    # Sohbet sonrası sağ paneli otomatik güncelle
    gb.click(sag_panel_guncelle, outputs=[sag_panel_html], show_progress="hidden")
    mk.submit(sag_panel_guncelle, outputs=[sag_panel_html], show_progress="hidden")

    # ── Sol panel → Tab yönlendirme ──
    sol_sohbet_b.click( fn=lambda: gr.Tabs(selected="sohbet"),   outputs=[ana_tabs])
    sol_gorev_b.click(  fn=lambda: gr.Tabs(selected="gorev"),    outputs=[ana_tabs])
    sol_gorsel_b.click( fn=lambda: gr.Tabs(selected="gorsel"),   outputs=[ana_tabs])
    sol_ses_b.click(    fn=lambda: gr.Tabs(selected="ses"),      outputs=[ana_tabs])
    sol_harita_b.click( fn=lambda: gr.Tabs(selected="harita"),   outputs=[ana_tabs])
    sol_analitik_b.click(fn=lambda: gr.Tabs(selected="analitik"),outputs=[ana_tabs])
    sol_plugin_b.click( fn=lambda: gr.Tabs(selected="plugin"),   outputs=[ana_tabs])
    sol_webhook_b.click(fn=lambda: gr.Tabs(selected="webhook"),  outputs=[ana_tabs])
    sol_hatir_b.click(  fn=lambda: gr.Tabs(selected="hatir"),    outputs=[ana_tabs])
    sol_dil_b.click(    fn=lambda: gr.Tabs(selected="dil"),      outputs=[ana_tabs])
    sol_ekip_b.click(   fn=lambda: gr.Tabs(selected="ekip"),     outputs=[ana_tabs])
    sol_guvenlik_b.click(fn=lambda: gr.Tabs(selected="guvenlik"),outputs=[ana_tabs])
    sol_hakkinda_b.click(fn=lambda: gr.Tabs(selected="hakkinda"),outputs=[ana_tabs])

    # ── Sol araç butonları → mesaj kutusuna yaz + sekme değiştir ──
    hizli_hava.click( fn=lambda: ("İstanbul hava durumu?",  gr.Tabs(selected="sohbet")), outputs=[mk, ana_tabs])
    hizli_borsa.click(fn=lambda: ("Borsa bugün nasıl?",     gr.Tabs(selected="sohbet")), outputs=[mk, ana_tabs])
    hizli_haber.click(fn=lambda: ("Son haberler neler?",    gr.Tabs(selected="sohbet")), outputs=[mk, ana_tabs])
    hizli_tarih.click(fn=lambda: ("Bugün tarih ve saat kaç?", gr.Tabs(selected="sohbet")), outputs=[mk, ana_tabs])
    dr_btn.click(     fn=lambda: gr.Tabs(selected="sohbet"), outputs=[ana_tabs])

# ══════════════════════════════════════════════════════════════════
# HuggingFace Spaces: auth varsa etkinleştir, yoksa direkt başlat
# Çoklu kullanıcı destekli auth
_auth_fn = gradio_auth_genisletilmis if (_load_auth() or users_yukle()["kullanicilar"]) else None

demo.launch(
    auth=_auth_fn,
    auth_message="🔐 BELUMA-I'ya Hoş Geldiniz.",
    server_name="0.0.0.0",
    server_port=7860,
    share=False,
)
