"""Merkezi yapılandırma — tüm magic number, string ve ayarlar burada toplanır."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set


def _load_local_env() -> None:
    """Proje kökündeki .env dosyasını os.environ'a yükler."""
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
    except OSError:
        pass


# .env dosyasını modül yüklenirken oku
_load_local_env()


def _resolve_hf_token() -> str:
    """HuggingFace token'ını birden fazla ortam değişkeninden arar."""
    for key in ("HF_TOKEN", "hf_token", "HUGGINGFACE_TOKEN", "HF_API_TOKEN", "TOKEN"):
        val = os.environ.get(key)
        if val:
            return val
    return ""


@dataclass(frozen=True)
class Config:
    """Tüm uygulama yapılandırmasını tek noktadan yönetir.

    Attributes:
        GROQ_API_KEY: Groq API anahtarı.
        MODEL_NAME: Varsayılan LLM model adı.
        FALLBACK_MODELLER: Model hata verdiğinde denenecek sıralı liste.
        HF_TOKEN: HuggingFace API token'ı.
        HF_IMAGE_MODEL: Varsayılan görsel üretim modeli.
        TRANSCRIBE_MODEL: Whisper transkripsiyon modeli.
        GUNLUK_KREDI: Günlük görsel üretim limiti.
        LOG_MAX_BYTES: Log dosyası maksimum boyutu (byte).
        LOG_BACKUP_COUNT: Tutulan yedek log dosyası sayısı.
        MEMORY_LIMIT: Hafıza listesinin maksimum uzunluğu.
        CACHE_TTL: Yaşam haritası önbellek süresi (saniye).
        PROFILE_CACHE_TTL: Profil özeti önbellek süresi (saniye).
        MAX_DOCUMENT_CHARS: Belge okumada maksimum karakter.
        THREAD_POOL_WORKERS: İş parçacığı havuzu boyutu.
    """

    # --- API Anahtarları ---
    GROQ_API_KEY: str = field(default_factory=lambda: os.environ.get("GROQ_API_KEY", ""))
    HF_TOKEN: str = field(default_factory=_resolve_hf_token)

    # --- Model Ayarları ---
    MODEL_NAME: str = field(
        default_factory=lambda: os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    )
    FALLBACK_MODELLER: List[str] = field(default_factory=lambda: [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "llama3-8b-8192",
        "gemma2-9b-it",
    ])
    AGENT_MODEL: str = "llama-3.1-8b-instant"
    HF_IMAGE_MODEL: str = field(
        default_factory=lambda: os.environ.get("HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
    )
    IMAGE_MODELS: List[str] = field(default_factory=lambda: [
        os.environ.get("HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell"),
        "stabilityai/stable-diffusion-xl-base-1.0",
        "runwayml/stable-diffusion-v1-5",
        "prompthero/openjourney-v4",
    ])
    TRANSCRIBE_MODEL: str = field(
        default_factory=lambda: os.environ.get("GROQ_TRANSCRIBE_MODEL", "whisper-large-v3-turbo")
    )

    # --- Dosya Yolları ---
    ENV_FILE: Path = Path(".env")
    SESSION_FILE: Path = Path("beluma_session.json")
    PROFILE_FILE: Path = Path("beluma_profile.json")
    TASKS_FILE: Path = Path("beluma_tasks.json")
    LIFE_MAP_FILE: Path = Path("beluma_life_map.json")
    MEMORY_FILE: Path = Path("beluma_memory.json")
    KREDI_FILE: Path = Path("beluma_krediler.json")

    # --- Limitler ---
    GUNLUK_KREDI: int = 10
    LOG_MAX_BYTES: int = 1_048_576
    LOG_BACKUP_COUNT: int = 3
    MEMORY_LIMIT: int = 200
    CACHE_TTL: float = 5.0
    PROFILE_CACHE_TTL: float = 600.0
    MAX_DOCUMENT_CHARS: int = 15_000
    THREAD_POOL_WORKERS: int = 4

    # --- Desteklenen Dosya Uzantıları ---
    TEXT_EXTENSIONS: Set[str] = field(default_factory=lambda: {
        ".txt", ".md", ".py", ".json", ".csv", ".log", ".yaml", ".yml"
    })

    # --- Pinecone ---
    PINECONE_API_KEY: str = field(
        default_factory=lambda: os.environ.get("PINECONE_API_KEY", "")
    )
    PINECONE_HOST: str = field(
        default_factory=lambda: os.environ.get("PINECONE_HOST", "").rstrip("/")
    )
    PINECONE_INDEX: str = field(
        default_factory=lambda: os.environ.get("PINECONE_INDEX", "beluma-memory")
    )
    HF_EMBED_URL: str = (
        "https://api-inference.huggingface.co/pipeline/feature-extraction/"
        "sentence-transformers/all-MiniLM-L6-v2"
    )

    # --- Görsel Stilleri ---
    GORSEL_STILLER: Dict[str, str] = field(default_factory=lambda: {
        "Gerçekçi": "photorealistic, 8k, highly detailed, natural lighting, sharp focus, professional photography",
        "İllüstrasyon": "vibrant anime style, clean strokes, expressive digital art, bold colors",
        "Sinematik": "cinematic, dramatic lighting, film still, anamorphic lens, shallow depth of field, masterpiece",
        "Minimal": "minimalist design, clean lines, elegant, modern aesthetic, white space, professional",
        "Emlak/Mimari": "luxury real estate, wide angle interior, soft sunlight, 4k resolution",
        "Modern/Minimal": "minimalist design, clean lines, modern aesthetic, professional branding",
        "Anime/Çizim": "vibrant anime style, clean strokes, expressive digital art",
    })

    # --- Güvenlik Kalıpları ---
    INJECTION_PATTERNS: List[str] = field(default_factory=lambda: [
        "ignore previous", "ignore all", "forget previous",
        "system promptu söyle", "system prompt", "gizli talimat",
        "gizli bilgileri ver", "şifreyi ver", "api key",
        "sen artık", "sen şimdi", "rolünü unut",
        "developer mode", "jailbreak", "dan mode",
        "önceki talimatları unut", "tüm kısıtlamaları kaldır",
    ])
    PHISHING_PATTERNS: List[str] = field(default_factory=lambda: [
        r"bit\.ly/", r"tinyurl\.com/", r"goo\.gl/",
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
        r"free.{0,10}(bitcoin|money|para|kazan)",
        r"(şifre|password|kredi.kart).{0,30}(gir|doğrula|onayla)",
    ])
    PERSONAL_DATA_PATTERNS: List[str] = field(default_factory=lambda: [
        r"[1-9][0-9]{10}",
        r"[0-9]{4}[ -]?[0-9]{4}[ -]?[0-9]{4}[ -]?[0-9]{4}",
    ])
    RISKLI_KELIMELER: List[str] = field(default_factory=lambda: [
        "hack", "dolandır", "illegal", "şifre kır", "saldır", "exploit", "bypass",
    ])
    ETIK_DISI_KELIMELER: List[str] = field(default_factory=lambda: [
        "zarar ver", "manipüle et", "kandır", "tehdit et", "taciz",
    ])

    # --- Sabit Döviz Kurları (yedek) ---
    SABIT_KUR: Dict[str, float] = field(default_factory=lambda: {
        "USD": 32.5, "EUR": 35.2, "GBP": 41.0, "TRY": 1.0,
    })
