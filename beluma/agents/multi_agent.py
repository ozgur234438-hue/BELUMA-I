"""Çoklu ajan sistemi — planner, critic, derin düşünce katmanı."""

from __future__ import annotations

from typing import Any, Dict, Optional

from beluma.core.config import Config
from beluma.core.helpers import icerik_temizle
from beluma.core.logger import get_logger

_logger = get_logger()
_cfg = Config()


def _get_client() -> Any:
    """Groq istemcisini lazy olarak döndürür."""
    from beluma.core.client import get_groq_client
    return get_groq_client()


def agent_cagir(prompt: str, max_tokens: int = 400) -> str:
    """Yardımcı agent'ı çağırır (hızlı, küçük model).

    Args:
        prompt: Agent'a gönderilecek prompt.
        max_tokens: Maksimum token sayısı.

    Returns:
        Agent cevabı veya boş string.
    """
    client = _get_client()
    if not client:
        return ""
    try:
        r = client.chat.completions.create(
            model=_cfg.AGENT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=max_tokens,
        )
        return icerik_temizle(r.choices[0].message.content)
    except Exception as e:
        _logger.warning("[agent_cagir] %s", e)
        return ""


def planner_agent(mesaj: str) -> str:
    """Kullanıcı isteğini adım adım planlar.

    Args:
        mesaj: Planlanacak kullanıcı isteği.

    Returns:
        Adım adım plan metni.
    """
    return agent_cagir(f"Bu isteği Türkçe kısa adım adım planla (max 4 adım):\n{mesaj}")


def critic_agent(cevap: str) -> str:
    """Verilen cevabı eleştirel olarak değerlendirir.

    Args:
        cevap: Değerlendirilecek cevap metni.

    Returns:
        Eleştiri veya 'TAMAM'.
    """
    return agent_cagir(
        f"Bu cevabı denetle. Mantık hatası, eksik veya yanıltıcı bilgi varsa 'SORUN: [açıkla]' yaz. "
        f"Sorun yoksa sadece 'TAMAM' yaz.\nCevap: {cevap}",
        150,
    )


def derin_dusunce_katmani(mesaj: str, profil: Dict[str, Any]) -> str:
    """Kişiselleştirilmiş yanıt stratejisi oluşturur.

    Args:
        mesaj: Kullanıcı mesajı.
        profil: Kullanıcı profil bilgileri.

    Returns:
        Strateji metni.
    """
    client = _get_client()
    if not client:
        return ""
    isim = profil.get("name", "")
    ton = profil.get("tone", "samimi")
    about = profil.get("about", "")
    prompt = (
        f"Kullanıcı profili: isim={isim}, ton={ton}, hakkında={about[:100]}\n"
        f"Kullanıcı mesajı: {mesaj[:300]}\n\n"
        f"Bu kişiye en etkili ve etik yaklaşım ne olmalı? 2 cümleyle strateji belirle."
    )
    return agent_cagir(prompt, max_tokens=120)


def dinamik_profil_ozeti(profil: Dict[str, Any]) -> str:
    """Profil bilgilerinden kişisel özet oluşturur.

    Args:
        profil: Kullanıcı profil dict'i.

    Returns:
        2 cümlelik profil özeti.
    """
    client = _get_client()
    if not client:
        return ""

    from beluma.core.life_map import haritayi_yukle
    lm = haritayi_yukle()
    ozet_girdisi = (
        f"İsim: {profil.get('name', '')}\nHakkında: {profil.get('about', '')}\n"
        f"Tercihler: {profil.get('preferences', '')}\n"
        f"Hedefler: {', '.join(str(h) for h in lm.get('hedefler', [])[:3])}\n"
        f"İş modeli: {lm.get('is_modeli', '')}\n"
        f"Öğrenilmiş: {', '.join(profil.get('learned', [])[:5])}"
    )
    if len(ozet_girdisi.replace("\n", "").replace(" ", "")) < 30:
        return ""
    return agent_cagir(
        f"Şu profil bilgilerinden 2 cümlelik kişisel özet çıkar:\n{ozet_girdisi}", 120
    )
