"""Ses modülü — transkripsiyon (Whisper) ve metin-ses dönüşümü (TTS)."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Optional, Tuple

from beluma.core.config import Config
from beluma.core.helpers import metni_temizle
from beluma.core.logger import get_logger

_logger = get_logger()
_cfg = Config()


def sesi_yaziya_cevir(audio_file: Optional[str]) -> Tuple[str, str]:
    """Ses dosyasını metne çevirir (Whisper via Groq).

    Args:
        audio_file: Ses dosyası yolu.

    Returns:
        (metin, durum_mesajı) tuple'ı.
    """
    if not audio_file:
        return "", "Ses kaydı yükle."
    from beluma.core.client import get_groq_client
    client = get_groq_client()
    if not client:
        return "", "GROQ_API_KEY gerekli."
    path = Path(str(audio_file))
    if not path.exists():
        return "", "Dosya bulunamadı."
    try:
        with path.open("rb") as f:
            t = client.audio.transcriptions.create(
                file=(path.name, f.read()),
                model=_cfg.TRANSCRIBE_MODEL,
                response_format="verbose_json",
                language="tr",
            )
        metin = metni_temizle(getattr(t, "text", "") or t.get("text", ""))
        return (metin, "✅ Yazıya çevrildi.") if metin else ("", "Metin çıkmadı.")
    except (OSError, AttributeError) as e:
        _logger.warning("[sesi_yaziya_cevir] %s", e)
        return "", f"Hata: {e}"


def metni_seslendir(metin: Optional[str]) -> Tuple[Optional[str], str]:
    """Metni sese çevirir (gTTS — temel).

    Args:
        metin: Seslendirilecek metin.

    Returns:
        (ses_dosya_yolu, durum_mesajı) tuple'ı.
    """
    temiz = (metin or "").strip()
    if not temiz:
        return None, "Metin yok."
    try:
        from gtts import gTTS
        tmp = Path(tempfile.gettempdir()) / f"beluma_tts_{int(time.time())}.mp3"
        gTTS(text=temiz, lang="tr").save(str(tmp))
        return str(tmp), "✅ Ses hazır."
    except ImportError:
        _logger.warning("gTTS yüklü değil")
        return None, "gTTS kütüphanesi bulunamadı."
    except Exception as e:
        _logger.warning("[metni_seslendir] %s", e)
        return None, f"Hata: {e}"


def metni_seslendir_premium(
    metin: Optional[str],
    model_id: str = "fishaudio/fish-speech-1.4",
) -> Tuple[Optional[str], str]:
    """Metni yüksek kaliteli sese çevirir (Fish Speech).

    Gradio Client > HF API > gTTS sırasıyla dener.

    Args:
        metin: Seslendirilecek metin.
        model_id: TTS model ID.

    Returns:
        (ses_dosya_yolu, durum_mesajı) tuple'ı.
    """
    import os
    token = os.environ.get("HF_TOKEN") or _cfg.HF_TOKEN
    temiz = (metin or "").strip()[:400]
    if not temiz:
        return None, "Metin yok."

    # Gradio Client ile dene
    try:
        from gradio_client import Client as _GradioClient
        if token:
            gc = _GradioClient("artificialguybr/fish-s2-pro-zero", hf_token=token)
            res = gc.predict(
                text=temiz,
                ref_audio=None,
                ref_text="",
                max_new_tokens=1024,
                chunk_length=200,
                top_p=0.7,
                repetition_penalty=1.2,
                temperature=0.7,
                api_name="/predict",
            )
            ses_yol = res[0] if isinstance(res, (tuple, list)) else res
            if ses_yol:
                _logger.info("Premium TTS: Gradio Client başarılı")
                return str(ses_yol), "✅ Premium ses hazır."
    except ImportError:
        pass
    except Exception as e:
        _logger.warning("[metni_seslendir_premium/Gradio] %s", e)

    # HF API ile dene
    if token:
        try:
            import requests
            r = requests.post(
                f"https://api-inference.huggingface.co/models/{model_id}",
                headers={"Authorization": f"Bearer {token}"},
                json={"inputs": temiz},
                timeout=25,
            )
            if r.status_code == 200 and len(r.content) > 1000:
                tmp = Path(tempfile.gettempdir()) / f"beluma_premium_tts_{int(time.time())}.mp3"
                tmp.write_bytes(r.content)
                _logger.info("Premium TTS: HF API başarılı")
                return str(tmp), "✅ Yüksek kaliteli ses hazır."
            _logger.warning("[metni_seslendir_premium/HF_API] HTTP %d", r.status_code)
        except Exception as e:
            _logger.warning("[metni_seslendir_premium/HF_API] %s", e)

    # Fallback: gTTS
    return metni_seslendir(temiz)
