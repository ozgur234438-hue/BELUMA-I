"""Loglama altyapısı — RotatingFileHandler ile dosya bazlı log."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from beluma.core.config import Config

_cfg = Config()


def get_logger(name: str = "beluma") -> logging.Logger:
    """Uygulama genelinde kullanılan logger'ı döndürür.

    Args:
        name: Logger adı.

    Returns:
        Yapılandırılmış Logger nesnesi.
    """
    lg = logging.getLogger(name)
    if not lg.handlers:
        handler = RotatingFileHandler(
            "beluma.log",
            maxBytes=_cfg.LOG_MAX_BYTES,
            backupCount=_cfg.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        lg.addHandler(handler)
        lg.setLevel(logging.INFO)
    return lg


_logger = get_logger()


def log_kaydet(kullanici_mesaj: str, ai_cevap: str, model: str = "") -> None:
    """Kullanıcı-bot etkileşimini loglar.

    Args:
        kullanici_mesaj: Kullanıcının gönderdiği mesaj.
        ai_cevap: Botun ürettiği cevap.
        model: Kullanılan model adı.
    """
    try:
        _logger.info("model=%s | USR: %s | BOT: %s", model, kullanici_mesaj[:200], ai_cevap[:300])
    except (OSError, ValueError) as e:
        _logger.warning("log_kaydet hatası: %s", e)
