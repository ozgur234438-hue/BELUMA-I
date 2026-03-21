"""Yardımcı fonksiyonlar — JSON I/O, metin temizleme, thread-safe dosya erişimi."""

from __future__ import annotations

import ast
import json
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from beluma.core.logger import get_logger

_logger = get_logger()

# Thread-safe dosya yazımı için global kilit
_file_lock = threading.Lock()


def json_yukle(dosya_yolu: Path, varsayilan: Any) -> Any:
    """JSON dosyasını okur; hata durumunda varsayılan değer döner.

    Args:
        dosya_yolu: Okunacak JSON dosyasının yolu.
        varsayilan: Dosya yoksa veya okunamazsa dönen değer.

    Returns:
        Parse edilmiş JSON verisi veya varsayılan değer.
    """
    if not dosya_yolu.exists():
        return varsayilan
    try:
        with dosya_yolu.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        _logger.warning("JSON parse hatası (%s): %s", dosya_yolu, e)
        return varsayilan
    except OSError as e:
        _logger.warning("Dosya okuma hatası (%s): %s", dosya_yolu, e)
        return varsayilan


def json_kaydet(dosya_yolu: Path, veri: Any) -> None:
    """JSON verisini thread-safe biçimde dosyaya yazar.

    Args:
        dosya_yolu: Yazılacak JSON dosyasının yolu.
        veri: Kaydedilecek veri.

    Raises:
        Hata loglanır ancak fırlatılmaz — çağıranı bloklamaz.
    """
    with _file_lock:
        try:
            tmp_path = dosya_yolu.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(veri, f, ensure_ascii=False, indent=2)
            tmp_path.replace(dosya_yolu)
        except OSError as e:
            _logger.error("Dosya yazma hatası (%s): %s", dosya_yolu, e)
        except (TypeError, ValueError) as e:
            _logger.error("JSON serialize hatası (%s): %s", dosya_yolu, e)


def json_safe_parse(text: str) -> Dict[str, Any]:
    """Esnek JSON/dict parse — LLM çıktısını parse etmek için.

    Önce standart JSON, sonra ast.literal_eval, en son regex ile
    JSON bloğu arar.

    Args:
        text: Parse edilecek metin.

    Returns:
        Parse edilmiş dict veya boş dict.
    """
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
            pass
    return {}


def metni_temizle(metin: Optional[str]) -> str:
    """Metindeki gereksiz boşlukları ve satır başlarını temizler.

    Args:
        metin: Temizlenecek metin.

    Returns:
        Temizlenmiş metin.
    """
    if not metin:
        return ""
    temiz = str(metin).replace("\r\n", "\n").replace("\r", "\n")
    while "\n\n\n" in temiz:
        temiz = temiz.replace("\n\n\n", "\n\n")
    return temiz.strip()


def _dict_metin_cek(d: Dict[str, Any]) -> str:
    """Dict'ten metin alanını çıkarır."""
    return str(d.get("text") or d.get("content") or d.get("response") or "")


def icerik_temizle(icerik: Any) -> str:
    """Farklı formatlardaki içeriği düz metin haline getirir.

    LLM'den gelen list, dict veya string formatındaki cevapları
    düz metin olarak normalize eder.

    Args:
        icerik: Temizlenecek içerik (str, list, dict veya None).

    Returns:
        Temizlenmiş düz metin.
    """
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
