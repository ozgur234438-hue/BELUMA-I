"""Güvenlik modülü — injection, phishing ve kişisel veri tespiti."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from beluma.core.config import Config

_cfg = Config()

# Modül yüklenirken regex'leri bir kez derle — performans için
_COMPILED_INJECTION: List[re.Pattern[str]] = [
    re.compile(re.escape(k), re.IGNORECASE) for k in _cfg.INJECTION_PATTERNS
]
_COMPILED_PHISHING: List[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in _cfg.PHISHING_PATTERNS
]
_COMPILED_PERSONAL: List[re.Pattern[str]] = [
    re.compile(p) for p in _cfg.PERSONAL_DATA_PATTERNS
]


def guvenlik_tarama(metin: str) -> Optional[str]:
    """Metni güvenlik kalıplarına karşı tarar.

    Sırasıyla injection, phishing ve kişisel veri kalıplarını kontrol eder.

    Args:
        metin: Taranacak kullanıcı mesajı.

    Returns:
        Uyarı mesajı (str) veya None (güvenli).
    """
    kucuk = metin.lower()
    for pat in _COMPILED_INJECTION:
        if pat.search(kucuk):
            return "🛡️ **Güvenlik:** Bu mesaj sistem güvenliğini hedef alan bir kalıp içeriyor."
    for pat in _COMPILED_PHISHING:
        if pat.search(metin):
            return (
                "⚠️ **Güvenlik uyarısı:** Şüpheli içerik tespit edildi. "
                "Kimlik bilgilerini paylaşmadan önce dikkatli ol."
            )
    for pat in _COMPILED_PERSONAL:
        if pat.search(metin):
            return (
                "🛡️ **Kişisel veri uyarısı:** Mesajında TC Kimlik veya kredi kartı "
                "numarası olabilir. Paylaşmamaya dikkat et."
            )
    return None


def karar_motoru(mesaj: str) -> Dict[str, bool]:
    """Mesajın riskli veya etik dışı içerik barındırıp barındırmadığını kontrol eder.

    Args:
        mesaj: Kontrol edilecek kullanıcı mesajı.

    Returns:
        {"guvenli": True/False} dict'i.
    """
    kucuk = mesaj.lower()
    risk = sum(1 for r in _cfg.RISKLI_KELIMELER if r in kucuk)
    etik = sum(1 for e in _cfg.ETIK_DISI_KELIMELER if e in kucuk)
    return {"guvenli": risk == 0 and etik == 0}
