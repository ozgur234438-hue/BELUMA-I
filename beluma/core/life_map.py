"""Yaşam Haritası (Life Map Engine v6) — hedef, alışkanlık ve günlük not yönetimi."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from beluma.core.config import Config
from beluma.core.helpers import json_yukle, json_kaydet
from beluma.core.logger import get_logger

_logger = get_logger()
_cfg = Config()

# 5 saniyelik bellek cache — disk I/O azaltır
_lm_cache: Dict[str, Any] = {"veri": None, "zaman": 0.0}


def varsayilan_harita() -> Dict[str, Any]:
    """Boş yaşam haritası şablonu döndürür."""
    return {
        "hedefler": [],
        "gunluk_notlar": [],
        "aliskanliklar": [],
        "is_modeli": "",
        "uzun_vadeli_plan": "",
        "karar_tarzi": "",
        "istatistik": {},
    }


def haritayi_yukle() -> Dict[str, Any]:
    """Yaşam haritasını yükler (önbellekli).

    Returns:
        Yaşam haritası dict'i.
    """
    if time.time() - _lm_cache["zaman"] < _cfg.CACHE_TTL and _lm_cache["veri"] is not None:
        return _lm_cache["veri"]
    veri = json_yukle(_cfg.LIFE_MAP_FILE, varsayilan_harita())
    _lm_cache.update({"veri": veri, "zaman": time.time()})
    return veri


def haritayi_kaydet(veri: Dict[str, Any]) -> None:
    """Yaşam haritasını kaydeder ve önbelleği günceller.

    Args:
        veri: Kaydedilecek yaşam haritası dict'i.
    """
    json_kaydet(_cfg.LIFE_MAP_FILE, veri)
    _lm_cache.update({"veri": veri, "zaman": time.time()})


def hedef_ekle(hedef_metni: str, oncelik: int = 2) -> None:
    """Yeni hedef ekler.

    Args:
        hedef_metni: Hedef açıklaması.
        oncelik: Öncelik seviyesi (1=düşük, 2=orta, 3=yüksek).
    """
    data = haritayi_yukle()
    data["hedefler"].append({
        "id": uuid.uuid4().hex[:8],
        "hedef": hedef_metni.strip(),
        "tarih": time.strftime("%Y-%m-%d %H:%M"),
        "tamamlandi": False,
        "oncelik": oncelik,
    })
    haritayi_kaydet(data)


def hedef_tamamla(hedef_ref: str) -> None:
    """Hedefi tamamlandı olarak işaretler.

    Args:
        hedef_ref: Hedef ID'si veya hedef metninin parçası.
    """
    data = haritayi_yukle()
    ref = hedef_ref.strip()
    for h in data["hedefler"]:
        if h.get("id") == ref or ref.lower() in h["hedef"].lower():
            h["tamamlandi"] = True
            break
    haritayi_kaydet(data)


def gunluk_not_ekle(not_metni: str, kategori: str = "genel") -> None:
    """Günlük not ekler.

    Args:
        not_metni: Not içeriği.
        kategori: Not kategorisi.
    """
    data = haritayi_yukle()
    data["gunluk_notlar"].append({
        "not": not_metni.strip(),
        "tarih": time.strftime("%Y-%m-%d %H:%M"),
        "kategori": kategori,
    })
    data["gunluk_notlar"] = data["gunluk_notlar"][-100:]
    haritayi_kaydet(data)


def aliskanlik_guncelle(aliskanlik: str) -> None:
    """Alışkanlık serisini günceller veya yeni alışkanlık ekler.

    Args:
        aliskanlik: Alışkanlık adı.
    """
    data = haritayi_yukle()
    bugun = time.strftime("%Y-%m-%d")
    for a in data["aliskanliklar"]:
        if a["aliskanlik"].lower() == aliskanlik.lower():
            if a.get("son_guncelleme", "") != bugun:
                a["seri"] = a.get("seri", 0) + 1
                a["son_guncelleme"] = bugun
            haritayi_kaydet(data)
            return
    data["aliskanliklar"].append({
        "aliskanlik": aliskanlik.strip(),
        "seri": 1,
        "son_guncelleme": bugun,
    })
    haritayi_kaydet(data)


def life_map_ozeti() -> str:
    """Yaşam haritasının kısa özetini döndürür.

    Returns:
        Özet metni.
    """
    data = haritayi_yukle()
    hedefler = data.get("hedefler", [])
    toplam = len(hedefler)
    tamamlanan = sum(1 for h in hedefler if h.get("tamamlandi"))
    bekleyen = [h["hedef"] for h in hedefler if not h.get("tamamlandi")][:3]
    aliskanliklar = data.get("aliskanliklar", [])
    satirlar: List[str] = []
    if toplam:
        satirlar.append(f"Hedef: {tamamlanan}/{toplam} tamamlandı")
    if bekleyen:
        satirlar.append("Bekleyen: " + ", ".join(bekleyen))
    if aliskanliklar:
        satirlar.append("Alışkanlıklar: " + ", ".join(
            f"{a['aliskanlik']}({a['seri']} gün)" for a in aliskanliklar[:3]
        ))
    return " | ".join(satirlar) if satirlar else ""
