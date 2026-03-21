"""Oturum, profil ve görev yönetimi."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

from beluma.core.config import Config
from beluma.core.helpers import json_yukle, json_kaydet, json_safe_parse, icerik_temizle
from beluma.core.logger import get_logger

_logger = get_logger()
_cfg = Config()


# ────────────────────────────────────────────────────────────────
# OTURUM
# ────────────────────────────────────────────────────────────────
def varsayilan_oturum() -> Dict[str, Any]:
    """Boş oturum şablonu."""
    return {"chat_history": [], "document_name": "", "document_text": ""}


def oturumu_yukle() -> Dict[str, Any]:
    """Kaydedilmiş oturumu yükler ve normalize eder.

    Returns:
        Normalize edilmiş oturum dict'i.
    """
    veri = json_yukle(_cfg.SESSION_FILE, varsayilan_oturum())
    payload = varsayilan_oturum()
    if isinstance(veri, dict):
        payload.update(veri)
    history = payload.get("chat_history", [])
    normalized: List[Dict[str, str]] = []
    for item in history:
        if isinstance(item, dict) and "role" in item:
            normalized.append({"role": item["role"], "content": str(item.get("content", ""))})
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            u, a = item
            if u:
                normalized.append({"role": "user", "content": str(u)})
            if a:
                normalized.append({"role": "assistant", "content": str(a)})
    payload["chat_history"] = normalized
    return payload


def oturumu_kaydet(
    chat_history: Optional[List[Any]] = None,
    document_name: str = "",
    document_text: str = "",
    onboarding_goruldu: Optional[bool] = None,
) -> None:
    """Oturumu kaydeder.

    Args:
        chat_history: Sohbet geçmişi.
        document_name: Yüklü belge adı.
        document_text: Yüklü belge metni.
        onboarding_goruldu: Onboarding ekranı görüldü mü.
    """
    mevcut = json_yukle(_cfg.SESSION_FILE, {})
    veri = {
        "chat_history": chat_history or [],
        "document_name": document_name or "",
        "document_text": document_text or "",
        "onboarding_goruldu": (
            onboarding_goruldu if onboarding_goruldu is not None
            else mevcut.get("onboarding_goruldu", False)
        ),
    }
    json_kaydet(_cfg.SESSION_FILE, veri)


# ────────────────────────────────────────────────────────────────
# PROFİL
# ────────────────────────────────────────────────────────────────
def varsayilan_profil() -> Dict[str, Any]:
    """Boş profil şablonu."""
    return {"name": "", "tone": "samimi", "style": "dengeli", "about": "", "preferences": "", "learned": []}


def profili_yukle() -> Dict[str, Any]:
    """Kullanıcı profilini yükler."""
    return json_yukle(_cfg.PROFILE_FILE, varsayilan_profil())


def profili_kaydet(**kwargs: Any) -> None:
    """Kullanıcı profilini kaydeder.

    Args:
        **kwargs: Profil alanları (name, tone, style, about, preferences, learned).
    """
    payload = varsayilan_profil()
    payload.update({k: v for k, v in kwargs.items() if k in payload})
    json_kaydet(_cfg.PROFILE_FILE, payload)


def profili_otomatik_guncelle(mesaj: str, cevap: str) -> None:
    """Sohbetten otomatik tercih çıkarır ve profile ekler.

    Args:
        mesaj: Kullanıcı mesajı.
        cevap: Bot cevabı.
    """
    from beluma.core.client import get_groq_client
    client = get_groq_client()
    if not client:
        return
    try:
        r = client.chat.completions.create(
            model=_cfg.AGENT_MODEL,
            messages=[{"role": "user", "content": (
                f"Kullanıcı mesajı ve cevabından kullanıcı tercihi çıkar.\n"
                f'Varsa: {{"tercih": "kısa açıklama"}}\nYoksa: {{}}\n'
                f"Kullanıcı: {mesaj[:300]}\nCevap: {cevap[:300]}"
            )}],
            temperature=0.0,
            max_tokens=80,
        )
        veri = json_safe_parse(icerik_temizle(r.choices[0].message.content))
        tercih = veri.get("tercih", "").strip()
        if tercih:
            profil = profili_yukle()
            learned = profil.get("learned", [])
            if tercih not in learned:
                learned = [tercih] + learned
            profili_kaydet(**{**profil, "learned": learned[:20]})
    except Exception as e:
        _logger.warning("[profili_otomatik_guncelle] %s", e)


# ────────────────────────────────────────────────────────────────
# GÖREVLER
# ────────────────────────────────────────────────────────────────
def gorevleri_yukle() -> Dict[str, Any]:
    """Görev listesini yükler."""
    return json_yukle(_cfg.TASKS_FILE, {"gorevler": []})


def gorevleri_kaydet(veri: Dict[str, Any]) -> None:
    """Görev listesini kaydeder."""
    json_kaydet(_cfg.TASKS_FILE, veri)


def gorev_ekle(baslik: str, alt_gorevler: Optional[List[str]] = None) -> Dict[str, Any]:
    """Yeni görev ekler.

    Args:
        baslik: Görev başlığı.
        alt_gorevler: Alt görev metinleri listesi.

    Returns:
        Oluşturulan görev dict'i.
    """
    veri = gorevleri_yukle()
    yeni: Dict[str, Any] = {
        "id": int(time.time() * 1000),
        "baslik": baslik,
        "alt_gorevler": [{"metin": a, "tamamlandi": False} for a in (alt_gorevler or [])],
        "tamamlandi": False,
        "olusturuldu": time.strftime("%Y-%m-%d %H:%M"),
    }
    veri["gorevler"].insert(0, yeni)
    gorevleri_kaydet(veri)
    return yeni


def gorev_tamamla(gid: int) -> None:
    """Görevi tamamlandı olarak işaretler."""
    veri = gorevleri_yukle()
    for g in veri["gorevler"]:
        if g["id"] == gid:
            g["tamamlandi"] = True
    gorevleri_kaydet(veri)


def gorev_sil(gid: int) -> None:
    """Görevi siler."""
    veri = gorevleri_yukle()
    veri["gorevler"] = [g for g in veri["gorevler"] if g["id"] != gid]
    gorevleri_kaydet(veri)


def gorevleri_metne_cevir() -> str:
    """Görev listesini okunabilir metin olarak döndürür."""
    gorevler = gorevleri_yukle().get("gorevler", [])
    if not gorevler:
        return "Henüz hiç görev eklenmemiş."
    satirlar: List[str] = []
    for g in gorevler:
        satirlar.append(
            f"{'✓' if g['tamamlandi'] else '○'} [{g['id']}] {g['baslik']}  ({g['olusturuldu']})"
        )
        for a in g.get("alt_gorevler", []):
            satirlar.append(f"    {'✓' if a['tamamlandi'] else '·'} {a['metin']}")
    return "\n".join(satirlar)


# ────────────────────────────────────────────────────────────────
# KREDİ SİSTEMİ
# ────────────────────────────────────────────────────────────────
def kredi_yukle() -> Dict[str, Any]:
    """Kredi bilgilerini yükler."""
    return json_yukle(
        _cfg.KREDI_FILE,
        {"kredi": _cfg.GUNLUK_KREDI, "tarih": "", "toplam_uretim": 0, "son_gorsel": ""},
    )


def kredi_kaydet(veri: Dict[str, Any]) -> None:
    """Kredi bilgilerini kaydeder."""
    json_kaydet(_cfg.KREDI_FILE, veri)


def kredi_kontrol() -> Tuple[int, str]:
    """Kalan krediyi kontrol eder.

    Returns:
        (kalan_kredi, mesaj) tuple'ı.
    """
    veri = kredi_yukle()
    bugun = time.strftime("%Y-%m-%d")
    if veri.get("tarih") != bugun:
        veri["kredi"] = _cfg.GUNLUK_KREDI
        veri["tarih"] = bugun
        kredi_kaydet(veri)
    kalan = veri.get("kredi", _cfg.GUNLUK_KREDI)
    if kalan <= 0:
        return 0, "⏳ Günlük görsel kredin bitti. Yarın sıfırlanır."
    return kalan, f"🎨 Kalan görsel kredisi: **{kalan}/{_cfg.GUNLUK_KREDI}**"


def kredi_kullan() -> Tuple[bool, str]:
    """Bir kredi kullanır.

    Returns:
        (başarılı, mesaj) tuple'ı.
    """
    veri = kredi_yukle()
    bugun = time.strftime("%Y-%m-%d")
    if veri.get("tarih") != bugun:
        veri["kredi"] = _cfg.GUNLUK_KREDI
        veri["tarih"] = bugun
    kalan = veri.get("kredi", _cfg.GUNLUK_KREDI)
    if kalan <= 0:
        return False, "⏳ Günlük kredin bitti. Yarın tekrar dene."
    veri["kredi"] = kalan - 1
    veri["toplam_uretim"] = veri.get("toplam_uretim", 0) + 1
    kredi_kaydet(veri)
    kalan_yeni = veri["kredi"]
    if kalan_yeni == 0:
        return True, f"✅ Görsel hazır! ⚠️ Son krediniydi, yarın {_cfg.GUNLUK_KREDI} yeni kredin olacak."
    return True, f"✅ Görsel hazır! Kalan: {kalan_yeni} kredi"


def son_gorsel_kaydet(yol: str) -> None:
    """Son üretilen görselin yolunu kaydeder."""
    veri = kredi_yukle()
    veri["son_gorsel"] = yol
    kredi_kaydet(veri)


def son_gorsel_getir() -> str:
    """Son üretilen görselin yolunu döndürür."""
    return kredi_yukle().get("son_gorsel", "")
