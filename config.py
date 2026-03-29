"""
BELUMA-I — Merkezi Yapılandırma
Tüm sabitler, API key'ler ve feature flags buradan yönetilir.
"""
import os
import re
import threading
from pathlib import Path

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

# ── Dosya Yolları ──
SESSION_FILE       = Path("beluma_session.json")
PROFILE_FILE       = Path("beluma_profile.json")
TASKS_FILE         = Path("beluma_tasks.json")
LIFE_MAP_FILE      = Path("beluma_life_map.json")
MEMORY_FILE        = Path("beluma_memory.json")
KREDI_FILE         = Path("beluma_krediler.json")
AUTH_FILE          = Path("beluma_auth.json")
ANALYTICS_FILE     = Path("beluma_analytics.json")
WEBHOOKS_FILE      = Path("beluma_webhooks.json")
HATIRLATICI_FILE   = Path("beluma_hatirlaticilar.json")
I18N_FILE          = Path("beluma_i18n.json")
USERS_FILE         = Path("beluma_users.json")
TEAM_FILE          = Path("beluma_team.json")
PLUGINS_DIR        = Path("beluma_plugins")
PLUGINS_STATE_FILE = Path("beluma_plugins.json")

# ── Sistem Sabitleri ──
WEBHOOK_RETRY_MAX  = 3
WEBHOOK_TIMEOUT    = 8
VARSAYILAN_DIL     = "tr"
ROLLER             = ["admin", "editor", "viewer"]
GUNLUK_KREDI       = 10
MEMORY_LIMIT       = 200
CACHE_TTL          = 5.0
PROFILE_CACHE_TTL  = 600.0
_IO_CACHE_TTL      = 10.0
MAX_DOCUMENT_CHARS = int(os.getenv("BELUMA_MAX_DOCUMENT_CHARS", "50000"))
TEXT_EXTENSIONS    = {".txt", ".md", ".py", ".json", ".csv", ".log", ".yaml", ".yml"}

# ── Hafıza / Vektör ──
PINECONE_API_KEY   = os.environ.get("PINECONE_API_KEY", "")
PINECONE_HOST      = os.environ.get("PINECONE_HOST", "").rstrip("/")
HF_EMBED_URL       = "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"
SABIT_KUR          = {"USD": 32.5, "EUR": 35.2, "GBP": 41.0, "TRY": 1.0}

# ── Performans Cache ──
_PROFIL_CACHE:   dict = {"veri": None, "zaman": 0.0}
_PROFIL_LOCK     = threading.Lock()
_USERS_CACHE:    dict = {"veri": None, "zaman": 0.0}
_TEAM_CACHE:     dict = {"veri": None, "zaman": 0.0}

# ── Özellik Bayrakları ──
class FeatureFlags:
    deep_research        = True
    constitutional_guard = True
    multimodal_images    = True

FLAGS = FeatureFlags()

# ── Web Arama ──
PRIORITY_DOMAINS = {"gov","edu","org","who.int","oecd.org","worldbank.org","imf.org",
                    "europa.eu","un.org","nature.com","science.org"}
BLOCKED_DOMAINS  = {"pinterest.com","instagram.com","facebook.com","tiktok.com"}
WEB_TIMEOUT      = int(os.getenv("BELUMA_WEB_TIMEOUT", "10"))
WEB_MAX_SOURCES  = int(os.getenv("BELUMA_WEB_MAX_SOURCES", "8"))

# ── Güvenlik Desenleri ──
RISK_KEYWORDS = ["silah","patlayıcı","hack","zarar ver","öldür","uyuşturucu","kimlik bilgisi",
                 "şifre kır","kredi kartı","intihar","kendime zarar","bomba","fidye yazılımı",
                 "dolandır","yasadışı","kaçak"]
INJECTION_PATTERNS = ["ignore previous","ignore all","forget previous","system promptu söyle",
                      "system prompt","gizli talimat","gizli bilgileri ver","şifreyi ver","api key",
                      "sen artık","sen şimdi","rolünü unut","developer mode","jailbreak","dan mode",
                      "önceki talimatları unut","tüm kısıtlamaları kaldır"]
PHISHING_PATTERNS_RAW  = [r"bit\.ly/",r"tinyurl\.com/",r"goo\.gl/",
                           r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
                           r"free.{0,10}(bitcoin|money|para|kazan)",
                           r"(şifre|password|kredi.kart).{0,30}(gir|doğrula|onayla)"]
PERSONAL_DATA_PATTERNS_RAW = [r"[1-9][0-9]{10}", r"[0-9]{4}[ -]?[0-9]{4}[ -]?[0-9]{4}[ -]?[0-9]{4}"]
RISKLI    = ["hack","dolandır","illegal","şifre kır","saldır","exploit","bypass"]
ETIK_DISI = ["zarar ver","manipüle et","kandır","tehdit et","taciz"]

_COMPILED_INJECTION = [re.compile(re.escape(k), re.IGNORECASE) for k in INJECTION_PATTERNS]
_COMPILED_PHISHING  = [re.compile(p, re.IGNORECASE) for p in PHISHING_PATTERNS_RAW]
_COMPILED_PERSONAL  = [re.compile(p) for p in PERSONAL_DATA_PATTERNS_RAW]

# ── Uzmanlık & Görsel Modlar ──
UZMANLIK_MODLARI = {
    "Standart":            "Sen genel amaçlı, yardımcı bir asistansın. Açık ve net cevaplar ver.",
    "💻 Kıdemli Yazılımcı":"Sen kıdemli bir yazılım mimarısın. Kodları en iyi pratiklere uygun, temiz, modüler ve açıklayıcı yazarsın.",
    "✍️ Yaratıcı Yazar":   "Sen usta bir metin yazarı ve SEO uzmanısın. Akıcı, duygu yüklü, okuyucuyu içine çeken metinler üretirsin.",
    "📊 Veri Analisti":    "Sen soğukkanlı bir veri analistisin. Verileri analiz edip mantıksal sonuçlar çıkarırsın."
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
