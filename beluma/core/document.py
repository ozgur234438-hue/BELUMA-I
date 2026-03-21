"""Belge okuma modülü — PDF, Word, Excel, metin dosyaları."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

from beluma.core.config import Config
from beluma.core.logger import get_logger

_logger = get_logger()
_cfg = Config()


def belge_metnini_oku(file_obj: object, max_chars: int = 0) -> Tuple[str, str]:
    """Belge dosyasını okur ve metin olarak döndürür.

    Desteklenen formatlar: txt, md, py, json, csv, log, yaml, yml, pdf, docx, xlsx, xls

    Args:
        file_obj: Dosya nesnesi veya yol.
        max_chars: Maksimum karakter limiti (0=config'den al).

    Returns:
        (dosya_adı, metin) tuple'ı.
    """
    if max_chars == 0:
        max_chars = _cfg.MAX_DOCUMENT_CHARS
    if not file_obj:
        return "", ""
    path = Path(getattr(file_obj, "name", "") or str(file_obj))
    if not path.exists():
        return "", ""
    ext = path.suffix.lower()
    try:
        if ext in _cfg.TEXT_EXTENSIONS:
            text = path.read_text(encoding="utf-8", errors="ignore")
        elif ext == ".pdf":
            text = _read_pdf(path)
        elif ext == ".docx":
            text = _read_docx(path)
        elif ext in (".xlsx", ".xls"):
            text = _read_excel(path)
        else:
            return path.name, f"{path.suffix} desteklenmiyor."
    except ImportError as e:
        _logger.warning("[belge_metnini_oku] Eksik kütüphane: %s", e)
        return path.name, f"Gerekli kütüphane yüklü değil: {e}"
    except OSError as e:
        _logger.warning("[belge_metnini_oku] Dosya okuma hatası: %s", e)
        return path.name, "Dosya okunamadı."

    text = text.strip()
    if not text:
        return path.name, "Dosya boş."
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "\n\n[Belge kısaltıldı]"
    return path.name, text


def _read_pdf(path: Path) -> str:
    """PDF dosyasını okur."""
    import pypdf
    reader = pypdf.PdfReader(str(path))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def _read_docx(path: Path) -> str:
    """Word dosyasını okur."""
    import docx
    doc = docx.Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def _read_excel(path: Path) -> str:
    """Excel dosyasını okur."""
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    rows = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            rows.append("\t".join(str(c) if c is not None else "" for c in row))
    return "\n".join(rows)
