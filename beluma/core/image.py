"""Görsel üretim modülü — FLUX + Stable Diffusion."""

from __future__ import annotations

import concurrent.futures
import os
import random
import tempfile
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

import requests

from beluma.core.config import Config
from beluma.core.logger import get_logger

_logger = get_logger()
_cfg = Config()


def _prompt_guclendir(kullanici_prompt: str, stil: str) -> str:
    """Kullanıcı prompt'unu stil ile güçlendirir."""
    stil_desc = _cfg.GORSEL_STILLER.get(stil, _cfg.GORSEL_STILLER["Gerçekçi"])
    return f"({kullanici_prompt.strip()}:1.3), {stil_desc}, highest detailed, 8k, no text, no watermark, no signature"


def _negatif_prompt() -> str:
    """Negatif prompt döndürür."""
    return "text, watermark, low quality, deformed, duplicate, lowres, ugly, blurry, artist name, signature, (username:1.3), amateur"


def _gorseli_kaydet(image: Any, seed: int) -> str:
    """Görseli geçici dosyaya kaydeder.

    Args:
        image: PIL Image nesnesi.
        seed: Rastgele tohum.

    Returns:
        Dosya yolu.
    """
    yol = Path(tempfile.gettempdir()) / f"beluma_{int(time.time())}_{seed}.png"
    image.save(str(yol))
    return str(yol)


def add_watermark(
    image_path: str,
    text: str = "BELUMA-I",
    position: str = "bottom-right",
    opacity: int = 128,
) -> None:
    """Görsele filigran ekler.

    Args:
        image_path: Görsel dosya yolu.
        text: Filigran metni.
        position: Konum (top-left, top-right, bottom-left, bottom-right).
        opacity: Şeffaflık (0-255).
    """
    try:
        from PIL import Image as _Img, ImageDraw as _Draw, ImageFont as _Font

        img = _Img.open(image_path).convert("RGBA")
        w, h = img.size
        fs = max(14, int(min(w, h) * 0.025))
        try:
            font = _Font.truetype("arial.ttf", fs)
        except OSError:
            font = _Font.load_default()
        overlay = _Img.new("RGBA", img.size, (255, 255, 255, 0))
        draw = _Draw.Draw(overlay)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        m = int(min(w, h) * 0.02)
        x = w - tw - m if "right" in position else m
        y = h - th - m if "bottom" in position else m
        draw.text((x, y), text, fill=(255, 255, 255, opacity), font=font)
        _Img.alpha_composite(img, overlay).convert("RGB").save(image_path)
        _logger.info("Filigran eklendi: %s", image_path)
    except ImportError:
        _logger.warning("PIL yüklü değil — filigran eklenemedi")
    except OSError as e:
        _logger.warning("Filigran eklenemedi: %s", e)


def generate_single(
    prompt: str,
    style: str,
    guidance: float = 9.0,
    seed: Optional[int] = None,
) -> Tuple[Optional[str], str, Optional[str], int]:
    """Tek görsel üretir.

    Args:
        prompt: Görsel açıklaması.
        style: Görsel stili.
        guidance: Guidance scale.
        seed: Rastgele tohum.

    Returns:
        (dosya_yolu, mesaj, model_adı, seed) tuple'ı.
    """
    if seed is None:
        seed = random.randint(1, 999999)
    token = os.environ.get("HF_TOKEN") or _cfg.HF_TOKEN
    final_prompt = _prompt_guclendir(prompt, style)
    negative = _negatif_prompt()

    for model in _cfg.IMAGE_MODELS:
        if not model:
            continue
        try:
            from huggingface_hub import InferenceClient as _IC

            ic = _IC(model=model, token=token)
            image = ic.text_to_image(
                final_prompt,
                negative_prompt=negative,
                guidance_scale=guidance,
                num_inference_steps=25,
                seed=seed,
            )
            file_path = _gorseli_kaydet(image, seed)
            _logger.info("[generate_single] model=%s seed=%d", model, seed)
            return file_path, f"✅ Üretildi (model: {model.split('/')[-1]}, seed: {seed})", model, seed
        except ImportError:
            try:
                r = requests.post(
                    f"https://api-inference.huggingface.co/models/{model}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"inputs": final_prompt},
                    timeout=90,
                )
                if r.status_code == 200:
                    from PIL import Image as _PI
                    import io as _io

                    file_path = _gorseli_kaydet(_PI.open(_io.BytesIO(r.content)), seed)
                    return file_path, f"✅ Üretildi (seed: {seed})", model, seed
            except (requests.RequestException, ImportError, OSError) as e:
                _logger.warning("[generate_single/HF_API] %s", e)
            break
        except Exception as e:
            err = str(e)
            _logger.warning("[generate_single] %s: %s", model, err[:80])
            if "503" in err or "loading" in err.lower():
                continue
            if "429" in err:
                time.sleep(2)
                continue
            continue

    return None, "❌ Tüm modeller başarısız.", None, seed


def generate_variations(
    prompt: str,
    style: str,
    guidance: float = 9.0,
    count: int = 4,
) -> Tuple[Optional[List[str]], str]:
    """Birden fazla varyasyon üretir.

    Args:
        prompt: Görsel açıklaması.
        style: Görsel stili.
        guidance: Guidance scale.
        count: Varyasyon sayısı.

    Returns:
        (dosya_yolları_listesi, mesaj) tuple'ı.
    """
    seeds = [random.randint(1, 999999) for _ in range(count)]
    results: List[Optional[str]] = [None] * count

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(count, 4)) as executor:
        future_to_idx = {
            executor.submit(generate_single, prompt, style, guidance, seeds[idx]): idx
            for idx in range(count)
        }
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                img_path, _, _, _ = future.result()
                results[idx] = img_path
            except Exception as e:
                _logger.error("[generate_variations] Varyasyon %d: %s", idx, e)

    valid = [r for r in results if r is not None]
    if valid:
        return valid, f"✅ {len(valid)}/{count} varyasyon üretildi."
    return None, "❌ Hiç varyasyon üretilemedi."
