"""
BELUMA-I — Görsel Üretim ve Ses Sistemi
"""
import concurrent.futures
import os
import random
import tempfile
import threading
import time
from pathlib import Path

import requests

from config import HF_TOKEN, IMAGE_MODELS, GORSEL_STILLER, TRANSCRIBE_MODEL
from utils import _logger, _hata_say, metni_temizle
from llm import get_groq_client, _agent_cagir, icerik_temizle

try:
    from gradio_client import Client as _GradioClient
except ImportError:
    _GradioClient = None

# ══════════════════════════════════════════════════════════════════
# GÖRSEL ÜRET
# ══════════════════════════════════════════════════════════════════
def _prompt_guclendir(p, stil):
    return f"({p.strip()}:1.3), {GORSEL_STILLER.get(stil,GORSEL_STILLER['Gerçekçi'])}, highest detailed, 8k, no text, no watermark, no signature"

def _negatif_prompt():
    return "text, watermark, low quality, deformed, duplicate, lowres, ugly, blurry, artist name, signature, (username:1.3), amateur"

def _gorseli_kaydet(image, seed):
    yol = Path(tempfile.gettempdir()) / f"beluma_{int(time.time())}_{seed}.png"
    image.save(str(yol))
    return str(yol)

def add_watermark(image_path, text="BELUMA-I", position="bottom-right", opacity=128):
    try:
        from PIL import Image as _I, ImageDraw as _D, ImageFont as _F
        img=_I.open(image_path).convert("RGBA"); w,h=img.size; fs=max(14,int(min(w,h)*0.025))
        try: font=_F.truetype("arial.ttf",fs)
        except OSError: font=_F.load_default()
        ov=_I.new("RGBA",img.size,(255,255,255,0)); dr=_D.Draw(ov)
        bb=dr.textbbox((0,0),text,font=font); tw,th=bb[2]-bb[0],bb[3]-bb[1]; m=int(min(w,h)*0.02)
        x=w-tw-m if "right" in position else m; y=h-th-m if "bottom" in position else m
        dr.text((x,y),text,fill=(255,255,255,opacity),font=font)
        _I.alpha_composite(img,ov).convert("RGB").save(image_path)
    except Exception as e: _logger.warning("[watermark] %s",e)

def gorsel_prompt_muhendisi(kullanici_istegi):
    client = get_groq_client()
    if not client: return kullanici_istegi
    from config import AGENT_MODEL
    try:
        r = client.chat.completions.create(
            model=AGENT_MODEL,
            messages=[{"role":"user","content":f"""Sen 'Görsel Komut Uzmanı'sın. FLUX için kusursuz prompt yap.
TALİMATLAR:
1. ANA KONU: Sadece kullanıcı ne istediyse onu çiz.
2. RENK: Belirtilen renkleri GÖZE ÇARPAN vurgula.
3. ARKA PLAN: Düz stüdyo veya doğa. ASLA bina/mimari ekleme.
4. YASAKLAR: Mimari, sütun, bina, yazı KESİNLİKLE OLMASIN.
İstek: "{kullanici_istegi}"
Sadece İngilizce, virgülle ayrılmış teknik çıktı:"""}],
            temperature=0.2, max_tokens=250)
        s = icerik_temizle(r.choices[0].message.content).strip()
        return s if s else kullanici_istegi
    except Exception as e: _logger.warning("[prompt_eng] %s",e); return kullanici_istegi

def generate_single(prompt, style, guidance=9.0, seed=None):
    if seed is None: seed=random.randint(1,999999)
    token=os.environ.get("HF_TOKEN") or HF_TOKEN
    fp=_prompt_guclendir(prompt,style); neg=_negatif_prompt()
    for model in IMAGE_MODELS:
        if not model: continue
        try:
            from huggingface_hub import InferenceClient as _IC
            img=_IC(model=model,token=token).text_to_image(fp,negative_prompt=neg,guidance_scale=guidance,num_inference_steps=25,seed=seed)
            return _gorseli_kaydet(img,seed),f"✅ Üretildi ({model.split('/')[-1]}, seed:{seed})",model,seed
        except ImportError:
            try:
                r=requests.post(f"https://api-inference.huggingface.co/models/{model}",
                                headers={"Authorization":f"Bearer {token}"},json={"inputs":fp},timeout=90)
                if r.status_code==200:
                    from PIL import Image as _PI; import io as _io
                    return _gorseli_kaydet(_PI.open(_io.BytesIO(r.content)),seed),"✅ Üretildi",model,seed
            except Exception as e: _logger.warning("[img/api] %s",e)
            break
        except Exception as e:
            err=str(e)
            if "503" in err or "loading" in err.lower(): continue
            if "429" in err:
                _hata_say("gorsel.rate_limit"); time.sleep(2); continue
            _logger.error("[img] beklenmeyen (%s): %s",model,err[:120]); _hata_say("gorsel.genel")
    return None,"❌ Tüm modeller başarısız.",None,seed

_img_semaphore = threading.Semaphore(2)

def generate_variations(prompt, style, guidance=9.0, count=4):
    seeds   = [random.randint(1,999999) for _ in range(count)]
    results = [None] * count
    def _safe_generate(i):
        with _img_semaphore:
            return generate_single(prompt, style, guidance, seeds[i])
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(count,4)) as ex:
        fs = {ex.submit(_safe_generate, i): i for i in range(count)}
        for f in concurrent.futures.as_completed(fs):
            idx = fs[f]
            try:
                img_path, msg, _, _ = f.result()
                results[idx] = img_path
            except Exception as e:
                _logger.error("[var][%d] %s", idx, e)
    valid = [r for r in results if r]
    return (valid, f"✅ {len(valid)}/{count} varyasyon") if valid else (None, "❌ Üretilemedi.")

# ══════════════════════════════════════════════════════════════════
# SES
# ══════════════════════════════════════════════════════════════════
def sesi_yaziya_cevir(audio_file):
    if not audio_file: return "","Ses kaydı yükle."
    client = get_groq_client()
    if not client: return "","GROQ_API_KEY gerekli."
    path = Path(str(audio_file))
    if not path.exists(): return "","Dosya yok."
    try:
        with path.open("rb") as f:
            t = client.audio.transcriptions.create(
                file=(path.name,f.read()), model=TRANSCRIBE_MODEL,
                response_format="verbose_json", language="tr")
        m = metni_temizle(getattr(t,"text","") or t.get("text",""))
        return (m,"✅ Çevrildi.") if m else ("","Metin çıkmadı.")
    except (OSError,AttributeError) as e:
        _logger.warning("[stt] %s",e); return "",f"Hata: {e}"

def metni_seslendir(metin):
    from gtts import gTTS
    t=(metin or "").strip()
    if not t: return None,"Metin yok."
    try:
        tmp=Path(tempfile.gettempdir())/f"beluma_tts_{int(time.time())}.mp3"
        gTTS(text=t,lang="tr").save(str(tmp))
        return str(tmp),"✅ Ses hazır."
    except Exception as e:
        _logger.warning("[tts] %s",e); return None,f"Hata: {e}"

def metni_seslendir_premium(metin, model_id="fishaudio/fish-speech-1.4"):
    token=os.environ.get("HF_TOKEN") or HF_TOKEN; t=(metin or "").strip()[:400]
    if not t: return None,"Metin yok."
    if _GradioClient and token:
        try:
            gc=_GradioClient("artificialguybr/fish-s2-pro-zero",hf_token=token)
            res=gc.predict(text=t,ref_audio=None,ref_text="",max_new_tokens=1024,chunk_length=200,top_p=0.7,repetition_penalty=1.2,temperature=0.7,api_name="/predict")
            sy=res[0] if isinstance(res,(tuple,list)) else res
            if sy: return str(sy),"✅ Ses hazır (Fish Speech)."
        except Exception as e: _logger.warning("[premium/gradio] %s",e)
    if token:
        try:
            r=requests.post(f"https://api-inference.huggingface.co/models/{model_id}",
                           headers={"Authorization":f"Bearer {token}"},json={"inputs":t},timeout=25)
            if r.status_code==200 and len(r.content)>1000:
                tmp=Path(tempfile.gettempdir())/f"beluma_ptts_{int(time.time())}.mp3"; tmp.write_bytes(r.content)
                return str(tmp),"✅ Ses hazır (HF API)."
        except Exception as e: _logger.warning("[premium/hf] %s",e)
    return metni_seslendir(t)
