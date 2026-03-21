"""Zihinsel modeller — karar verme çerçeveleri ve bağlamsal öneri sistemi."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict

from beluma.core.logger import get_logger

_logger = get_logger()

if TYPE_CHECKING:
    pass

MENTAL_MODELS: Dict[str, str] = {
    "pareto": "Pareto İlkesi (%80/20): Bu konudaki %20'lik çaba, %80 sonucu nasıl getirir?",
    "first_principles": "İlk İlkeler: Konuyu en temel doğrularına indirgersek ne görürüz?",
    "swot": "SWOT: Bu durumun güçlü/zayıf yanları, fırsatları ve tehditleri neler?",
    "eisenhower": "Eisenhower Matrisi: Bu iş acil mi, önemli mi, yoksa ikisi de mi?",
    "inversion": "Ters Çevirme: 'Nasıl başarırım?' yerine 'Nasıl kesinlikle başarısız olurum?' diye sor.",
    "second_order": "İkinci Derece Düşünce: Bu kararın dolaylı ve uzun vadeli sonuçları ne olur?",
    "occam": "Occam'ın Usturası: En az varsayım gerektiren açıklama genellikle doğrudur. En sade çözüm nedir?",
    "parkinson": "Parkinson Yasası: İş, kendine ayrılan süreyi doldurur. Bu görev için gerçekten ne kadar süre gerekiyor?",
    "circle_of_control": "Kontrol Çemberi: Bunun üzerinde gerçekten kontrol sahibi misin? Değilse enerji nereye gitmeli?",
    "regret_min": "Pişmanlık Minimizasyonu (Bezos): 80 yaşında geriye bakınca hangi kararı vermemiş olmaktan pişmanlık duyarsın?",
}

# Anahtar kelime → model eşleme tablosu
_MODEL_TRIGGERS = [
    (["karar", "seçim", "hangisi", "ne yapmalı", "tercih"], "eisenhower"),
    (["plan", "strateji", "iş", "proje", "büyüme"], "pareto"),
    (["anlamadım", "karmaşık", "neden", "nasıl çalışır", "temel"], "first_principles"),
    (["risk", "tehlike", "yanlış giderse", "başarısız"], "inversion"),
    (["sonuç", "etki", "ileride", "gelecek", "uzun vade"], "second_order"),
    (["karmaşık", "çok fazla", "aşırı", "boğuldum", "nereden başla"], "occam"),
    (["vakit", "süre", "zaman", "yetişemiyorum", "deadline"], "parkinson"),
    (["yapamıyorum", "elimde değil", "bağlı değil", "kontrol"], "circle_of_control"),
    (["pişman", "regret", "hayatımın kararı", "önemli karar"], "regret_min"),
]


def zihinsel_model_oner(mesaj: str) -> str:
    """Mesaj bağlamına göre uygun zihinsel model önerir.

    Args:
        mesaj: Kullanıcı mesajı.

    Returns:
        Öneri metni veya boş string.
    """
    kucuk = mesaj.lower()
    for keywords, model_key in _MODEL_TRIGGERS:
        if any(k in kucuk for k in keywords):
            return f"\n\n💡 **Düşünme önerisi:** {MENTAL_MODELS[model_key]}"

    # Life map ile iş modeli kontrolü
    try:
        from beluma.core.life_map import haritayi_yukle
        if any(k in kucuk for k in ["iş", "gelir", "müşteri", "satış"]):
            lm = haritayi_yukle()
            if lm.get("is_modeli"):
                return f"\n\n💡 **Pareto — {lm['is_modeli']}:** %20'lik çabanı nereye yatırırsın?"
    except (ImportError, OSError) as e:
        _logger.warning("[zihinsel_model_oner] Life map yüklenemedi: %s", e)

    return ""
