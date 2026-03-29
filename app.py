"""
BELUMA-I — Ana Giriş Noktası (Slim app.py)
Tüm özellikler modüllere taşındı. Bu dosya sadece UI ve başlatmayı içerir.
"""
# ── Standart kütüphaneler ──
import ast
import concurrent.futures
import datetime as _dt
import glob
import hashlib
import hmac as _hmac
import importlib.util as _imp_util
import json
import logging
import operator
import os
import random
import re
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# ── Üçüncü taraf ──
import gradio as gr
import requests

# ── BELUMA Modülleri ──
from config import (
    API_KEY, MODEL_NAME, AGENT_MODEL, VISION_MODEL, FALLBACK_MODELLER,
    HF_TOKEN, HF_IMAGE_MODEL, IMAGE_MODELS, GEMINI_API_KEY, DEEPSEEK_API_KEY,
    OPENAI_API_KEY, ANTHROPIC_API_KEY,
    SESSION_FILE, PROFILE_FILE, TASKS_FILE, LIFE_MAP_FILE, MEMORY_FILE,
    KREDI_FILE, AUTH_FILE, ANALYTICS_FILE, WEBHOOKS_FILE, HATIRLATICI_FILE,
    I18N_FILE, USERS_FILE, TEAM_FILE, PLUGINS_DIR, PLUGINS_STATE_FILE,
    WEBHOOK_RETRY_MAX, WEBHOOK_TIMEOUT, VARSAYILAN_DIL, ROLLER,
    GUNLUK_KREDI, MEMORY_LIMIT, CACHE_TTL, _IO_CACHE_TTL,
    MAX_DOCUMENT_CHARS, TEXT_EXTENSIONS, PINECONE_API_KEY, PINECONE_HOST,
    SABIT_KUR, FLAGS, GORSEL_STILLER, UZMANLIK_MODLARI,
    _PROFIL_CACHE, _PROFIL_LOCK, PROFILE_CACHE_TTL,
    PRIORITY_DOMAINS, BLOCKED_DOMAINS, WEB_TIMEOUT, WEB_MAX_SOURCES,
    RISK_KEYWORDS, _COMPILED_INJECTION, _COMPILED_PHISHING, _COMPILED_PERSONAL,
    RISKLI, ETIK_DISI
)

from utils import (
    _logger, _file_lock, _THREAD_POOL, log_kaydet,
    json_yukle, json_kaydet, json_safe_parse,
    metni_temizle, icerik_temizle, resmi_base64_yap, aciklamayi_ayikla,
    guvenlik_tarama, karar_motoru,
    BelumaBazHata, AracHatasi, ModelHatasi, BelgeHatasi, HafizaHatasi, GorevHatasi,
    _hata_say, hata_istatistikleri
)

from llm import (
    get_groq_client, get_gemini_client, get_deepseek_client,
    get_openai_client, get_anthropic_client,
    _agent_cagir, planner_agent, critic_agent, anayasal_denetim,
    enforce_turkish_output, _turkce_tarih, _turkce_gibi_mi,
    _numarali_listeyi_duzelt, _hata_turkce,
    zihinsel_model_oner, derin_dusunce_katmani, dinamik_profil_ozeti,
    MENTAL_MODELS
)

from tools import (
    safe_eval, UnsafeExpressionError,
    arama_yap, kaynak_kartlari_olustur,
    cevap_turu_belirle, guncel_bilgi_gerekli_mi,
    run_tool, final_cevap_temizle, _ddg_sonuclari_al
)

from session import (
    oturumu_yukle, oturumu_kaydet,
    profili_yukle, profili_kaydet, profili_otomatik_guncelle,
    gorevleri_yukle, gorevleri_kaydet, gorev_ekle, gorev_tamamla_id,
    gorev_sil_id, gorevleri_metne_cevir, chat_gorev_isle,
    haritayi_yukle, haritayi_kaydet, hedef_ekle, hedef_tamamla,
    gunluk_not_ekle, aliskanlik_guncelle, life_map_ozeti,
    kredi_yukle, kredi_kaydet, kredi_kontrol, kredi_kullan, son_gorsel_kaydet,
    memory_ekle, memory_ara,
    belge_metnini_oku, gelismis_rag_ara,
    analytics_yukle, analitik_kaydet,
    duygu_analizi, gunluk_oneri, proaktif_kontrol
)

from imageaudio import (
    gorsel_prompt_muhendisi, generate_single, generate_variations, add_watermark,
    sesi_yaziya_cevir, metni_seslendir, metni_seslendir_premium
)

# ══════════════════════════════════════════════════════════════════
# AUTH (basit)
# ══════════════════════════════════════════════════════════════════
def _hash_pw(pw): return hashlib.sha256(pw.encode("utf-8")).hexdigest()

AUTH_DEFAULT_USER     = os.getenv("AUTH_DEFAULT_USER","").strip()
AUTH_DEFAULT_PASSWORD = os.getenv("AUTH_DEFAULT_PASSWORD","").strip()

def _load_auth():
    if AUTH_FILE.exists():
        try:
            with AUTH_FILE.open("r",encoding="utf-8") as f: users=json.load(f)
            if isinstance(users,list) and users: return [(u["username"],u["password_hash"]) for u in users]
        except (json.JSONDecodeError,OSError,KeyError) as e:
            _logger.error("[auth] %s", e)
    if AUTH_DEFAULT_USER and AUTH_DEFAULT_PASSWORD:
        defaults=[(AUTH_DEFAULT_USER,_hash_pw(AUTH_DEFAULT_PASSWORD))]
        try:
            with AUTH_FILE.open("w",encoding="utf-8") as f:
                json.dump([{"username":u,"password_hash":h} for u,h in defaults],f,ensure_ascii=False,indent=2)
        except OSError as e: _logger.warning("[auth] %s", e)
        return defaults
    return []

def _gradio_auth(username,password):
    accounts=_load_auth()
    if not accounts: return True
    return any(u==username and h==_hash_pw(password) for u,h in accounts)

# Çoklu kullanıcı auth (users.json yoksa legacy)
def gradio_auth_genisletilmis(username: str, password: str) -> bool:
    return _gradio_auth(username, password)

# ══════════════════════════════════════════════════════════════════
# USERS / TEAM (basit stub — tam versiyon features/extras'ta)
# ══════════════════════════════════════════════════════════════════
def users_yukle():
    return json_yukle(USERS_FILE, {"kullanicilar": []})

# ══════════════════════════════════════════════════════════════════
# PLUGIN SİSTEMİ (basit)
# ══════════════════════════════════════════════════════════════════
_plugin_registry: Dict[str, Any] = {}
_plugin_lock = threading.Lock()

def _plugin_state_yukle(): return json_yukle(PLUGINS_STATE_FILE, {"pasif": []})

def _gomulu_pluginleri_kaydet():
    """Döviz, Not Al, Kelime Sayar gömülü pluginleri yükle."""
    pass  # Basitleştirildi — çakışma önlemek için

def plugin_isle(mesaj: str) -> Optional[str]:
    kucuk = mesaj.lower()
    with _plugin_lock:
        kayitlilar = list(_plugin_registry.items())
    for isim, modul in kayitlilar:
        tetikler = getattr(modul, "TETIKLEYICILER", [])
        if any(t in kucuk for t in tetikler):
            try:
                sonuc = modul.calistir(mesaj)
                analitik_kaydet(arac=f"plugin:{isim}")
                return str(sonuc) if sonuc else None
            except Exception as e:
                _logger.error("[plugin] %s: %s", isim, e)
    return None

def plugin_yukle_hepsi():
    if not PLUGINS_DIR.exists(): PLUGINS_DIR.mkdir(parents=True, exist_ok=True); return 0
    pasif = _plugin_state_yukle().get("pasif",[])
    yuklenen = {}
    for dosya in sorted(PLUGINS_DIR.glob("*_plugin.py")):
        try:
            spec = _imp_util.spec_from_file_location(dosya.stem, dosya)
            modul = _imp_util.module_from_spec(spec)
            spec.loader.exec_module(modul)
            isim = getattr(modul,"PLUGIN_ISIM",dosya.stem)
            if isim in pasif: continue
            if not callable(getattr(modul,"calistir",None)): continue
            yuklenen[isim] = modul
        except Exception as e: _logger.error("[plugin] %s: %s", dosya.name, e)
    with _plugin_lock:
        _plugin_registry.update(yuklenen)
    return len(yuklenen)

plugin_yukle_hepsi()

# ══════════════════════════════════════════════════════════════════
# WEBHOOK
# ══════════════════════════════════════════════════════════════════
_WEBHOOK_LOCK = threading.Lock()

def webhooks_yukle(): return json_yukle(WEBHOOKS_FILE, {"webhooks": []})
def webhooks_kaydet(v): json_kaydet(WEBHOOKS_FILE, v)

def webhook_tetikle(olay: str, veri: dict) -> None:
    v = webhooks_yukle()
    aktif = [w for w in v.get("webhooks",[]) if w.get("aktif",True) and olay in w.get("olaylar",["mesaj"])]
    if not aktif: return
    def _gonder():
        payload = {"olay":olay,"zaman":time.strftime("%Y-%m-%d %H:%M:%S"),"kaynak":"BELUMA-I",**veri}
        for wh in aktif:
            try:
                requests.post(wh["url"],json=payload,timeout=WEBHOOK_TIMEOUT,
                             headers={"Content-Type":"application/json","User-Agent":"BELUMA-I/1.0"})
            except Exception as e: _logger.warning("[webhook] %s: %s", wh["isim"],e)
    _THREAD_POOL.submit(_gonder)

def webhook_ekle(isim,url,olaylar,secret=""): 
    v=webhooks_yukle(); v["webhooks"].append({"id":uuid.uuid4().hex[:8],"isim":isim,"url":url,"olaylar":olaylar or ["mesaj"],"secret":secret,"aktif":True,"eklendi":time.strftime("%Y-%m-%d %H:%M"),"basari":0,"hata":0,"son_tetik":""}); webhooks_kaydet(v); return f"✅ Webhook eklendi: **{isim}**"
def webhook_sil(wh_id): v=webhooks_yukle(); v["webhooks"]=[w for w in v["webhooks"] if w["id"]!=wh_id.strip()]; webhooks_kaydet(v); return f"🗑 Silindi."
def webhook_listesi_metin(): v=webhooks_yukle(); whl=v.get("webhooks",[]); return "\n\n".join(f"{'✅' if w.get('aktif') else '⏸'} **[{w['id']}] {w['isim']}**\n   `{w['url']}`" for w in whl) if whl else "Kayıtlı webhook yok."

# ══════════════════════════════════════════════════════════════════
# HATIRLATICI (basit)
# ══════════════════════════════════════════════════════════════════
_bildirim_kuyrugu = []
_BLD_KUYRUK_LOCK  = threading.Lock()

def hatirlaticilar_yukle(): return json_yukle(HATIRLATICI_FILE, {"hatirlaticilar":[],"gecmis":[]})
def hatirlaticilar_kaydet(v): json_kaydet(HATIRLATICI_FILE, v)

def bildirim_ekle(mesaj):
    with _BLD_KUYRUK_LOCK:
        _bildirim_kuyrugu.append({"mesaj":mesaj,"zaman":time.strftime("%H:%M")})
        while len(_bildirim_kuyrugu)>20: _bildirim_kuyrugu.pop(0)

def bildirim_kuyrugu_oku():
    with _BLD_KUYRUK_LOCK:
        return "\n".join(f"🔔 [{b['zaman']}] {b['mesaj']}" for b in _bildirim_kuyrugu) if _bildirim_kuyrugu else ""

def bildirimleri_temizle():
    with _BLD_KUYRUK_LOCK: _bildirim_kuyrugu.clear()
    return "✅ Temizlendi."

def hatirlatici_ekle(mesaj, zaman_ifade):
    now=_dt.datetime.now(); ifade=zaman_ifade.strip().lower()
    m=re.search(r"(\d+)\s*(dakika|saat|gün|gun)",ifade)
    hedef=None
    if m:
        miktar=int(m.group(1)); birim=m.group(2)
        delta={"dakika":_dt.timedelta(minutes=miktar),"saat":_dt.timedelta(hours=miktar),"gün":_dt.timedelta(days=miktar),"gun":_dt.timedelta(days=miktar)}.get(birim)
        if delta: hedef=(now+delta).strftime("%Y-%m-%d %H:%M")
    if not hedef: return "⚠️ Zaman anlaşılamadı. Örnek: '30 dakika sonra', 'yarın 09:00'"
    v=hatirlaticilar_yukle()
    v["hatirlaticilar"].append({"id":uuid.uuid4().hex[:8],"mesaj":mesaj.strip(),"zaman":hedef,"tekrar":"","tamamlandi":False,"olusturuldu":time.strftime("%Y-%m-%d %H:%M")})
    hatirlaticilar_kaydet(v)
    return f"⏰ Hatırlatıcı kuruldu: **{mesaj}** → `{hedef}`"

def hatirlaticilar_listesi_metin():
    v=hatirlaticilar_yukle(); hl=[h for h in v.get("hatirlaticilar",[]) if not h.get("tamamlandi")]
    return "\n".join(f"- `[{h['id']}]` **{h['mesaj']}** → `{h['zaman']}`" for h in hl) if hl else "Aktif hatırlatıcı yok."

def _hatirlatici_kontrol():
    while True:
        try:
            simdi=time.strftime("%Y-%m-%d %H:%M"); v=hatirlaticilar_yukle(); degisti=False
            for h in v["hatirlaticilar"]:
                if h.get("tamamlandi"): continue
                if h.get("zaman","")<=simdi:
                    bildirim_ekle(h["mesaj"]); h["tamamlandi"]=True; degisti=True
            if degisti: hatirlaticilar_kaydet(v)
        except Exception as e: _logger.warning("[hatirlatici] %s",e)
        time.sleep(60)

threading.Thread(target=_hatirlatici_kontrol, daemon=True, name="beluma-hatirlatici").start()

# ══════════════════════════════════════════════════════════════════
# i18n (basit)
# ══════════════════════════════════════════════════════════════════
DESTEKLENEN_DILLER = {"tr":"🇹🇷 Türkçe","en":"🇬🇧 English","de":"🇩🇪 Deutsch","fr":"🇫🇷 Français","es":"🇪🇸 Español","ar":"🇸🇦 العربية","ru":"🇷🇺 Русский","ja":"🇯🇵 日本語"}
_aktif_dil_cache = {"dil": VARSAYILAN_DIL}

def dil_al():
    if not _aktif_dil_cache.get("dil"):
        _aktif_dil_cache["dil"] = profili_yukle().get("dil", VARSAYILAN_DIL)
    return _aktif_dil_cache["dil"]

def dil_ayarla(dil_kodu):
    if dil_kodu in DESTEKLENEN_DILLER:
        _aktif_dil_cache["dil"] = dil_kodu
        pr=profili_yukle(); pr["dil"]=dil_kodu; json_kaydet(PROFILE_FILE, pr)

def t(anahtar, dil=""):
    return anahtar  # Basit fallback — tam i18n için _CEVIRILER dict kullanılabilir

def sistem_promptu_dil_eki(dil): return ""

def mevcut_dil_etiketi(): return DESTEKLENEN_DILLER.get(dil_al(),"🇹🇷 Türkçe")
def dil_secici_guncelle(secilen):
    for kod,etiket in DESTEKLENEN_DILLER.items():
        if etiket==secilen or kod==secilen: dil_ayarla(kod); return f"✅ {etiket}",kod
    return "⚠️ Bulunamadı.",dil_al()

# ══════════════════════════════════════════════════════════════════
# KULLANICI / EKİP (basit)
# ══════════════════════════════════════════════════════════════════
_aktif_kullanici_cache = {"kullanici_adi": ""}
_USERS_LOCK = threading.Lock()

def kullanici_dogrula(kullanici_adi, sifre):
    v=users_yukle()
    for u in v.get("kullanicilar",[]):
        if u["kullanici_adi"]==kullanici_adi and u.get("sifre_hash")==_hash_pw(sifre) and u.get("aktif",True):
            return u
    return None

def aktif_kullanici_ayarla(ka): _aktif_kullanici_cache["kullanici_adi"]=ka
def aktif_kullanici_al(): return _aktif_kullanici_cache.get("kullanici_adi","")
def rol_kontrol(gereken_rol): return True  # Basit fallback

def kullanici_ekle(kullanici_adi, sifre, rol="editor", ad="", email=""):
    v=users_yukle()
    if any(u["kullanici_adi"]==kullanici_adi for u in v.get("kullanicilar",[])):
        return f"⚠️ '{kullanici_adi}' zaten kayıtlı."
    v["kullanicilar"].append({"kullanici_adi":kullanici_adi,"sifre_hash":_hash_pw(sifre),"rol":rol,"ad":ad,"email":email,"olusturuldu":time.strftime("%Y-%m-%d %H:%M"),"son_giris":"","aktif":True})
    json_kaydet(USERS_FILE, v); return f"✅ Kullanıcı eklendi: **{kullanici_adi}**"

def kullanici_listesi_metin():
    v=users_yukle(); ul=v.get("kullanicilar",[])
    return "\n".join(f"🟢 **{u['kullanici_adi']}** [{u.get('rol','?')}]" for u in ul) if ul else "Kayıtlı kullanıcı yok."

def team_yukle(): return json_yukle(Path("beluma_team.json"), {"ortak_notlar":[],"duyurular":[],"aktivite":[]})
def ortak_notlar_metin(): v=team_yukle(); return "\n".join(f"**{n['kullanici']}**: {n['metin']}" for n in v.get("ortak_notlar",[])[-5:]) or "Not yok."
def duyurular_metin(): v=team_yukle(); return "\n".join(f"- {d['metin']}" for d in v.get("duyurular",[])[-3:]) or ""

# ══════════════════════════════════════════════════════════════════
# WEB / DEEP RESEARCH YARDIMCILARI
# ══════════════════════════════════════════════════════════════════
def _html_temizle(raw_html):
    x = re.sub(r"(?is)<(script|style).*?>.*?</\1>"," ",raw_html or "")
    x = re.sub(r"(?is)<br\s*/?>","\n",x)
    x = re.sub(r"(?is)</p\s*>","\n",x)
    x = re.sub(r"(?is)<.*?>"," ",x)
    x = re.sub(r"[ \t]+"," ",x)
    return metni_temizle(x)

def fetch_url_text(url, timeout=10, max_chars=7000):
    try:
        r=requests.get(url,timeout=timeout,headers={"User-Agent":"BELUMA-I/1.0"})
        return _html_temizle(r.text)[:max_chars] if r.status_code==200 else ""
    except requests.RequestException: return ""

def _kaynak_kalite_puani(url, content, title):
    from urllib.parse import urlparse as _up
    domain=_up(url).netloc.lower().replace("www.","") if url else ""
    if not content or len(content)<500: return -100
    if domain in BLOCKED_DOMAINS: return -100
    score=0
    if any(domain.endswith(d) for d in PRIORITY_DOMAINS): score+=30
    if any(m in domain for m in ["gov","edu","org"]): score+=20
    if len(title)>20: score+=5
    if len(content)>1200: score+=10
    return score

def derin_arastirma_yap(konu):
    if not FLAGS.deep_research: yield "Derin araştırma özelliği kapalı."; return
    yield "🔍 Araştırma başlatıldı...\n"
    sorgu_raw=_agent_cagir(f'"{konu}" için 4-6 arama sorgusu üret. SADECE JSON dizisi: ["sorgu1","sorgu2"]. Başka yazma.',200)
    sorgular=[]
    try:
        parsed=json.loads(re.sub(r"```json|```","",sorgu_raw or "").strip())
        if isinstance(parsed,list): sorgular=[str(s).strip() for s in parsed if str(s).strip()][:6]
    except (json.JSONDecodeError,ValueError): pass
    if not sorgular: sorgular=[konu]
    yield "🌐 Web taraması...\n"
    kaynaklar,gorulen=[],set()
    for s in sorgular:
        yield f"• Taranıyor: *{s}*\n"
        for r in _ddg_sonuclari_al(s,n=4):
            u=r.get("url","")
            if not u or u in gorulen: continue
            gorulen.add(u)
            content=fetch_url_text(u,timeout=WEB_TIMEOUT,max_chars=4500)
            title=r.get("title","")
            score=_kaynak_kalite_puani(u,content,title)
            if score<0: continue
            kaynaklar.append({"title":title,"url":u,"snippet":r.get("body",""),"content":content,"score":score})
        if len(kaynaklar)>=WEB_MAX_SOURCES: break
    if not kaynaklar: yield "⚠️ Kaynak bulunamadı."; return
    kaynaklar.sort(key=lambda k:k.get("score",0),reverse=True)
    kaynaklar=kaynaklar[:WEB_MAX_SOURCES]
    from urllib.parse import urlparse as _up
    cards="\n\n".join(f"[{i}] Başlık: {k['title']}\nURL: {k['url']}\nÖzet: {k['snippet']}\nİçerik: {k['content']}" for i,k in enumerate(kaynaklar,start=1))
    yield "✍️ Rapor yazılıyor...\n"
    rapor=_agent_cagir(f"KONU: {konu}\n\nKaynak kartlarını kullanarak Türkçe analitik rapor yaz. Kaynak [1],[2] kullan. Tamamen Türkçe.\n\nKAYNAKLAR:\n{cards}",2200)
    rapor=final_cevap_temizle(rapor)
    kaynak_listesi="\n".join(f"- [{i+1}] {k['url']}" for i,k in enumerate(kaynaklar))
    yield f"📚 **Araştırma Raporu: {konu}**\n\n{rapor}\n\n**Kaynaklar:**\n{kaynak_listesi}"

# ══════════════════════════════════════════════════════════════════
# GRADIO UYUMLULUK
# ══════════════════════════════════════════════════════════════════
def chatbot_icin_hazirla(history):
    v = tuple(int(x) for x in gr.__version__.split(".")[:2])
    if v >= (4, 0):
        result = []
        for item in (history or []):
            if isinstance(item, dict) and "role" in item:
                c = item.get("content", "")
                result.append({"role": item["role"], "content": c if isinstance(c, tuple) else str(c or "")})
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                u, a = item
                if u: result.append({"role": "user",      "content": str(u)})
                if a: result.append({"role": "assistant",  "content": str(a)})
        return result
    else:
        result, buf = [], None
        for item in (history or []):
            if isinstance(item, dict):
                role, txt = item.get("role",""), item.get("content","")
                if isinstance(txt, tuple): txt = "[Görsel]"
                if role=="user":      buf = txt
                elif role=="assistant": result.append([buf or "", txt]); buf = None
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                result.append(list(item))
        return result

# ══════════════════════════════════════════════════════════════════
# SİSTEM PROMPTU & MESAJ HAZIRLAMA
# ══════════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """Sen BELUMA-I'sın — BELUMA Group Kurucusu Özgür tarafından tasarlanmış, Türkiye merkezli, güvenilir, analitik ve insan odaklı bir yapay zeka asistanısın.

TEMEL İLKELERİN:
- Analitik düşün: Karmaşık sorunları parçalara ayır, mantıklı ve tutarlı şekilde çöz.
- Araştırmacı ol: Verilen bilgi, belge ve kaynakları sentezle; eksik veri varsa bunu açıkça belirt.
- Dürüst ol: Emin olmadığın konularda kesin konuşma; bilmediğini biliyormuş gibi yapma.
- Güvenli davran: Zararlı, yasa dışı, manipülatif veya yanıltıcı içerik üretme.

İLETİŞİM KURALLARIN:
- Doğal, akıcı Türkçe. ASLA İngilizce kelime kullanma.
- ASLA JSON/dict/teknik format döndürme. Düz Türkçe metin.
- Kısa ve net. Max 3 paragraf veya 4 madde. Aynı fikri tekrarlama.
- İnternete erişimin var. Asla 'internete erişemiyorum' deme.
- Anthropic, OpenAI veya başka şirketlerle ilişkilendirme yapma.""".strip()

def sistem_promptu_olustur(profil, ad, ton, stil,
                            belge_adi="", belge_metni="", duygu=None,
                            gorevler_ozet="", strateji="", profil_ozeti="",
                            mesaj_baglami="", ozel_rol="", uzmanlik="Standart"):
    isim = (ad or "").strip() or profil.get("name","")
    tn = {"samimi":"sıcak ve yakın","profesyonel":"sakin ve net","enerjik":"motive edici"}
    st = {"kısa":"kısa ve net","dengeli":"dengeli uzunlukta","detaylı":"adım adım detaylı"}
    bg = [SYSTEM_PROMPT,
          UZMANLIK_MODLARI.get(uzmanlik, UZMANLIK_MODLARI["Standart"]),
          f"\nKullanıcı: {isim if isim else 'adı bilinmiyor — isim kullanma'}.",
          f"Ton: {tn.get(ton or profil.get('tone','samimi'),'dengeli')}. "
          f"Stil: {st.get(stil or profil.get('style','dengeli'),'dengeli')}."]
    if profil_ozeti:             bg.append(f"Özet: {profil_ozeti}")
    elif profil.get("about"):    bg.append(f"Hakkında: {profil['about']}")
    if profil.get("preferences"):bg.append(f"Tercihler: {profil['preferences']}")
    if profil.get("learned"):    bg.append("Öğrenilmiş: " + "; ".join(profil["learned"][:3]))
    if duygu and duygu.get("durum") != "nötr": bg.append(f"Duygu: {duygu['durum']} → {duygu['ton']}.")
    if strateji:                 bg.append(f"Strateji: {strateji}")
    bg.append("\nAçıklanabilirlik: Karmaşık kararlar için <think>gerekçe</think> yaz.")
    if gorevler_ozet and gorevler_ozet != "Henüz görev yok.":
        bg.append(f"Görevler:\n{gorevler_ozet[:400]}")
    lmo = life_map_ozeti()
    if lmo: bg.append(f"Durum: {lmo}")
    if belge_metni:
        ilgili = gelismis_rag_ara(mesaj_baglami or "", belge_metni)
        bg.append(f"Belge ({belge_adi}):\n{ilgili}")
    if ozel_rol and ozel_rol.strip():
        bg.append(f"ÖZEL ROL: {ozel_rol.strip()}")
    bg.append(
        "ZORUNLU KURALLAR:\n"
        "1. KESİNLİKLE hiçbir yabancı kelime kullanma.\n"
        "2. Numaralandırılmış liste YAPMA. Madde imi (-) kullan.\n"
        "3. Cevabın MAKSİMUM 3 paragraf veya 4 madde.\n"
        "4. Asla JSON veya kod formatı ile yanıt verme.\n"
        "5. Kendini madde madde ÖVME."
    )
    return "\n\n".join(bg)

def mesajlari_hazirla(gecmis, mesaj, profil, ad, ton, stil,
                      belge_adi="", belge_metni="", duygu=None,
                      gorevler_ozet="", strateji="", profil_ozeti="",
                      ozel_rol="", uzmanlik="Standart"):
    ms = [{"role":"system","content":sistem_promptu_olustur(
        profil, ad, ton, stil, belge_adi, belge_metni, duygu,
        gorevler_ozet, strateji, profil_ozeti, mesaj, ozel_rol, uzmanlik=uzmanlik)}]
    for i in gecmis or []:
        if isinstance(i,dict):
            r,c = i.get("role"), i.get("content")
            if isinstance(c,tuple): continue
            if r in {"user","assistant"} and c: ms.append({"role":r,"content":str(c)})
        elif isinstance(i,(list,tuple)) and len(i)==2:
            u,a = i
            if u: ms.append({"role":"user","content":str(u)})
            if a: ms.append({"role":"assistant","content":str(a)})
    hf = memory_ara(mesaj)
    if hf: ms.insert(1,{"role":"system","content":f"Geçmiş:\n{hf}"})
    return ms

# ══════════════════════════════════════════════════════════════════
# STREAMING CEVAP
# ══════════════════════════════════════════════════════════════════
def cevap_uret(mesaj, gecmis, profil, ad, ton, stil,
               belge_adi="", belge_metni="", duygu=None,
               gorevler_ozet="", strateji="", profil_ozeti="",
               yaraticilik=0.4, ozel_rol="",
               secili_model="llama-3.3-70b-versatile",
               max_tokens=1024, top_p=0.9,
               aktif_resim=None, uzmanlik="Standart"):

    niyet = cevap_turu_belirle(mesaj, belge_var=bool(belge_metni), resim_var=bool(aktif_resim))

    if niyet == "deep_research":
        konu = re.sub(r"(?i)derin araştır|deep research|kapsamlı araştır|detaylı araştır:","",mesaj).strip() or mesaj
        for chunk in derin_arastirma_yap(konu): yield final_cevap_temizle(chunk)
        return

    if niyet in ("tool_calc","tool_date","tool_convert"):
        tool_map = {"tool_calc":"calc","tool_date":"date","tool_convert":"convert"}
        sonuc = run_tool(tool_map[niyet],mesaj)
        if sonuc: yield final_cevap_temizle(str(sonuc)); return

    if niyet in ("tool_weather","tool_news","tool_bist"):
        tool_map = {"tool_weather":"weather","tool_news":"news","tool_bist":"bist"}
        sonuc = run_tool(tool_map[niyet],mesaj)
        if sonuc: log_kaydet(mesaj,str(sonuc)[:200],"tool"); analitik_kaydet(arac=niyet.replace("tool_","")); yield final_cevap_temizle(str(sonuc)); return

    search_context = ""
    if niyet == "tool_search":
        sonuclar = arama_yap(mesaj,max_results=5)
        if sonuclar:
            kartlar = kaynak_kartlari_olustur(sonuclar)
            search_context = f"WEB SONUÇLARI:\n{kartlar}\n\nBu sonuçlara dayanarak kısa Türkçe cevap ver. Kaynak [1],[2] kullan."
            log_kaydet(mesaj,kartlar[:200],"search"); analitik_kaydet(arac="search")

    plugin_sonuc = plugin_isle(mesaj)
    if plugin_sonuc:
        yield final_cevap_temizle(plugin_sonuc); return

    if not karar_motoru(mesaj)["guvenli"]:
        yield "Bu isteğe yardımcı olamam."; return

    ms = mesajlari_hazirla(gecmis, mesaj, profil, ad, ton, stil,
                           belge_adi, belge_metni, duygu, gorevler_ozet,
                           strateji, profil_ozeti, ozel_rol, uzmanlik=uzmanlik)
    if search_context:
        ms.insert(1,{"role":"system","content":search_context})
    temp = 0.2 if any(k in mesaj.lower() for k in ["matematik","hesap","bilmece","mantık","problem"]) else float(yaraticilik)

    # Gemini
    if secili_model.startswith("gemini"):
        gc = get_gemini_client(secili_model)
        if not gc: yield "🔑 Gemini için anahtar gerekli."; return
        try:
            full_prompt = ""
            for m in ms:
                role,content = m.get("role",""),m.get("content","")
                if isinstance(content,list): content=next((p.get("text") for p in content if p.get("type")=="text"),"")
                if role=="system":    full_prompt+=f"Sistem: {content}\n\n"
                elif role=="user":    full_prompt+=f"Kullanıcı: {content}\n\n"
                elif role=="assistant": full_prompt+=f"Asistan: {content}\n\n"
            resp = gc.generate_content(full_prompt.strip())
            yield final_cevap_temizle(resp.text); return
        except Exception as e: yield _hata_turkce("Gemini",e); return

    # DeepSeek
    elif secili_model.startswith("deepseek"):
        dc = get_deepseek_client()
        if not dc: yield "🔑 DeepSeek için anahtar gerekli."; return
        try:
            resp=dc.chat.completions.create(model="deepseek-chat",messages=ms,temperature=temp,max_tokens=int(max_tokens),top_p=float(top_p),stream=True)
            for chunk in resp:
                delta=chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content: yield final_cevap_temizle(delta.content)
            return
        except Exception as e: yield _hata_turkce("DeepSeek",e); return

    # Anthropic
    elif secili_model.startswith("claude"):
        ac = get_anthropic_client()
        if not ac: yield "🔑 Anthropic için anahtar gerekli."; return
        try:
            sys_msg = next((m["content"] for m in ms if m["role"]=="system"),"")
            usr_ms  = [m for m in ms if m["role"] in ("user","assistant")]
            with ac.messages.stream(model=secili_model,max_tokens=int(max_tokens),system=sys_msg,messages=usr_ms) as stream:
                for text in stream.text_stream: yield final_cevap_temizle(text)
            return
        except Exception as e: yield _hata_turkce("Anthropic",e); return

    # Groq (varsayılan)
    client = get_groq_client()
    if not client: yield "🔑 GROQ_API_KEY gerekli."; return

    # Görsel analiz
    if aktif_resim and FLAGS.multimodal_images:
        try:
            import base64 as _b64
            ext = Path(aktif_resim).suffix.lower().replace(".","").replace("jpg","jpeg")
            with open(aktif_resim,"rb") as f: b64 = _b64.b64encode(f.read()).decode()
            vision_ms = [{"role":"system","content":ms[0]["content"]},
                         {"role":"user","content":[
                             {"type":"text","text":mesaj or "Bu resmi analiz et."},
                             {"type":"image_url","image_url":{"url":f"data:image/{ext};base64,{b64}"}}]}]
            r = client.chat.completions.create(model=VISION_MODEL,messages=vision_ms,temperature=temp,max_tokens=int(max_tokens))
            yield final_cevap_temizle(icerik_temizle(r.choices[0].message.content)); return
        except Exception as e: _logger.warning("[vision] %s",e)

    # Groq streaming
    modeller = [secili_model] + [m for m in FALLBACK_MODELLER if m != secili_model]
    for model in modeller:
        try:
            stream = client.chat.completions.create(
                model=model, messages=ms,
                temperature=temp, max_tokens=int(max_tokens),
                top_p=float(top_p), stream=True)
            tampon = ""
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    tampon += delta.content
                    yield final_cevap_temizle(delta.content)
            if tampon: analitik_kaydet(model=model,token_est=len(tampon)//4)
            return
        except Exception as e:
            err = str(e)
            if "model_not_found" in err or "does not exist" in err: continue
            yield _hata_turkce("Groq",e); return
    yield "⚠️ Tüm modeller denendi, yanıt alınamadı."

# ══════════════════════════════════════════════════════════════════
# ANA SOHBET
# ══════════════════════════════════════════════════════════════════
_profil_cache_lock  = threading.Lock()
_profil_ozeti_cache = {"ozet":"","son":0,"hash":""}

def profil_ozetini_al(profil=None):
    global _profil_ozeti_cache
    s  = time.time()
    pr = profil or profili_yukle()
    ph = str(hash(json.dumps(pr, sort_keys=True)))
    with _profil_cache_lock:
        if (s - _profil_ozeti_cache["son"] <= PROFILE_CACHE_TTL) and (ph == _profil_ozeti_cache["hash"]):
            return _profil_ozeti_cache["ozet"]
        try:
            yeni_ozet = dinamik_profil_ozeti(pr)
        except Exception as e:
            _logger.warning("[profil_oz] %s", e)
            yeni_ozet = _profil_ozeti_cache["ozet"]
        _profil_ozeti_cache = {"ozet": yeni_ozet, "son": s, "hash": ph}
    return _profil_ozeti_cache["ozet"]

def sohbet_et(mesaj, gecmis, belge_adi, belge_metni,
              ad, ton, stil, ozel_rol, uzmanlik,
              yaraticilik, max_tok, top_p_val, secili_model,
              aktif_resim=None):
    if not (mesaj or "").strip():
        yield chatbot_icin_hazirla(gecmis or []), gecmis or [], ""
        return
    gv = guvenlik_tarama(mesaj)
    if gv:
        yeni = (gecmis or []) + [{"role":"user","content":mesaj},{"role":"assistant","content":gv}]
        yield chatbot_icin_hazirla(yeni), yeni, gv
        return
    profil = profili_yukle()
    duygu  = duygu_analizi(mesaj)
    strateji  = derin_dusunce_katmani(mesaj, profil)
    gorev_ozet = gorevleri_metne_cevir()
    profil_ozeti = profil_ozetini_al(profil)
    yeni  = (gecmis or []) + [{"role":"user","content":mesaj}]
    cevap = ""
    for parca in cevap_uret(
            mesaj, gecmis or [], profil, ad, ton, stil,
            belge_adi, belge_metni, duygu, gorev_ozet,
            strateji, profil_ozeti, yaraticilik, ozel_rol,
            secili_model, max_tok, top_p_val, aktif_resim, uzmanlik):
        cevap += parca
        aktunel = yeni + [{"role":"assistant","content":cevap+" █"}]
        yield chatbot_icin_hazirla(aktunel), yeni, ""
    _, cevap = aciklamayi_ayikla(cevap)
    gorev_mesaj, _ = chat_gorev_isle(mesaj)
    if gorev_mesaj: cevap += gorev_mesaj
    zm = zihinsel_model_oner(mesaj)
    if zm: cevap += zm
    log_kaydet(mesaj, cevap[:300], secili_model)
    analitik_kaydet(model=secili_model, token_est=len(cevap)//4)
    memory_ekle(f"Kullanıcı: {mesaj[:200]} | Bot: {cevap[:200]}")
    profili_otomatik_guncelle(mesaj, cevap)
    webhook_tetikle("mesaj", {"mesaj": mesaj[:200], "cevap": cevap[:200]})
    son = yeni + [{"role":"assistant","content":cevap}]
    oturumu_kaydet(son, belge_adi, belge_metni)
    yield chatbot_icin_hazirla(son), son, ""

# ══════════════════════════════════════════════════════════════════
# UI YARDIMCI FONKSİYONLAR
# ══════════════════════════════════════════════════════════════════
def yeni_sohbet(ba,bm): oturumu_kaydet([],ba,bm); return chatbot_icin_hazirla([]),"Yeni sohbet."
def belge_yukle(fo):
    a,s=belge_metnini_oku(fo)
    if not a and not s: return "","","Yüklenmedi."
    if s and not any(h in s.lower() for h in ["hata","desteklenmiyor","boş"]):
        o=oturumu_yukle(); oturumu_kaydet(o.get("chat_history",[]),a,s); return a,s,f"✅ {a}"
    o=oturumu_yukle(); oturumu_kaydet(o.get("chat_history",[]),a,""); return a,"",s
def son_sohbeti_yukle():
    o=oturumu_yukle(); g=o.get("chat_history",[])
    return chatbot_icin_hazirla(g),g,o.get("document_name",""),o.get("document_text",""),"Yüklendi." if g else "Bulunamadı."
def cevabi_iyilestir(gecmis):
    si=None
    for i,item in enumerate(reversed(gecmis or [])):
        if isinstance(item,dict) and item.get("role")=="assistant": si=len(gecmis)-1-i; break
    if si is None: return chatbot_icin_hazirla(gecmis or []),"Mesaj bulunamadı."
    rv=_agent_cagir(f"Eleştir. Hata varsa düzelt. Yoksa 'TAMAM'.\nCevap: {gecmis[si]['content'][:700]}",600)
    if rv and rv.strip().upper()!="TAMAM" and len(rv)>30:
        y=list(gecmis); y[si]={"role":"assistant","content":rv}; return chatbot_icin_hazirla(y),"✅ İyileştirildi."
    return chatbot_icin_hazirla(gecmis),"✅ Zaten iyi."
def ayarlari_kaydet(ad,ton,stil,about,pref):
    pr=profili_yukle(); profili_kaydet(name=ad,tone=ton,style=stil,about=about,preferences=pref,learned=pr.get("learned",[]))
    global _profil_ozeti_cache; _profil_ozeti_cache={"ozet":"","son":0,"hash":""}
    return f"✅ Kaydedildi.{f' Merhaba {ad.strip()}!' if (ad or '').strip() else ''}"
def sohbeti_indir(gecmis,ad):
    isim=ad.strip() if ad and ad.strip() else "Kullanıcı"
    md=f"# BELUMA-I Sohbet\n**Tarih:** {time.strftime('%Y-%m-%d %H:%M')}\n**Kişi:** {isim}\n\n---\n\n"
    for i in (gecmis or []):
        if isinstance(i,dict):
            c=str(i.get("content","")).replace(" █","")
            if isinstance(i.get("content"),tuple): continue
            md+=f"### {'👤 '+isim if i.get('role')=='user' else '🤖 BELUMA-I'}:\n{c}\n\n---\n\n"
    tmp=Path(tempfile.gettempdir())/f"BELUMA_{int(time.time())}.md"; tmp.write_text(md,encoding="utf-8"); return str(tmp)
def son_asistan_mesaji(g):
    for i in reversed(g or []):
        if isinstance(i,dict) and i.get("role")=="assistant": return i.get("content","")
    return ""
def _hedef_listesi():
    return "\n".join(f"{'✓' if h.get('tamamlandi') else '○'} [{h.get('oncelik',2)}⭐] {h['hedef']}" for h in haritayi_yukle().get("hedefler",[])) or "Henüz hedef yok."
def ogrenileni_sil(silinecek):
    pr=profili_yukle(); lr=[l for l in pr.get("learned",[]) if l!=silinecek.strip()]
    profili_kaydet(**{**pr,"learned":lr}); return "\n".join(lr) or "Henüz yok.",f"🗑 Silindi."

def sag_panel_guncelle():
    lm=haritayi_yukle(); hedefler=lm.get("hedefler",[]); toplam=len(hedefler)
    tamamlanan=sum(1 for h in hedefler if h.get("tamamlandi"))
    bekleyen=[h for h in hedefler if not h.get("tamamlandi")][:4]
    aliskanliklar=lm.get("aliskanliklar",[])[:4]
    yuzde=int(tamamlanan/toplam*100) if toplam else 0
    hedef_html="".join(f'<div class="rgoal"><span class="rdot"></span>{h["hedef"][:28]}</div>' for h in bekleyen)
    hab_html="".join(f'<div class="rhab"><span class="rhab-name">{a["aliskanlik"][:16]}</span><span class="rhab-streak">{a.get("seri",0)}g 🔥</span></div>' for a in aliskanliklar)
    with _BLD_KUYRUK_LOCK: bld_sayi=len(_bildirim_kuyrugu)
    hat_v=hatirlaticilar_yukle(); aktif_hat=[h for h in hat_v.get("hatirlaticilar",[]) if not h.get("tamamlandi")]
    return f"""<div style="padding:4px 0">
  <div style="font-family:Montserrat,sans-serif;font-size:13px;font-weight:600;background:linear-gradient(90deg,#FF1493,#8A2BE2);-webkit-background-clip:text;-webkit-text-fill-color:transparent;padding:6px 4px 2px">Gösterge</div>
  <div style="height:1px;background:rgba(138,43,226,.15);margin:0 0 8px"></div>
  <div class="rsec">HEDEFLER</div>
  <div class="rcard"><div class="rcard-label">Tamamlanan / Toplam</div><div class="rcard-val">{tamamlanan}<span style="font-size:11px;color:rgba(255,255,255,.4)">/{toplam}</span></div><div class="rprog"><div class="rprog-fill" style="width:{yuzde}%"></div></div><div class="rcard-sub">%{yuzde} başarı oranı</div></div>
  {hedef_html or '<div style="font-size:10px;color:rgba(255,255,255,.35);padding:4px">Henüz hedef yok.</div>'}
  <div style="height:1px;background:rgba(138,43,226,.1);margin:8px 0"></div>
  <div class="rsec">ALISKANLIKLAR</div>
  {hab_html or '<div style="font-size:10px;color:rgba(255,255,255,.35);padding:4px">Henüz alışkanlık yok.</div>'}
  <div style="height:1px;background:rgba(138,43,226,.1);margin:8px 0"></div>
  <div class="rsec">BİLDİRİMLER</div>
  <div class="rcard"><div class="rcard-label">Bekleyen bildirim</div><div class="rcard-val">{bld_sayi}</div><div class="rcard-sub">{len(aktif_hat)} aktif hatırlatıcı</div></div>
</div>"""

def aylik_rapor_olustur():
    d=haritayi_yukle(); h=d.get("hedefler",[]); n=d.get("gunluk_notlar",[])
    t,tm=len(h),sum(1 for x in h if x.get("tamamlandi")); o=(tm/t*100) if t else 0
    a=_agent_cagir(f"Performans: {t} hedef, {tm} tamam, %{o:.1f}\nBekleyen: {[x['hedef'] for x in h if not x.get('tamamlandi')][:5]}\n\n3 madde: 1) Yorum 2) Sorunlar 3) Öneri.",400)
    return f"📊 **Aylık Rapor**\n\n✅ **%{o:.1f}** ({tm}/{t})\n\n{a}"
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@600;700&family=Inter:wght@400;500&display=swap');

/* ═══════════════════════════════════════
   BELUMA-I v6.5 — 3 KOLON LAYOUT
   Sol Panel | Orta Sohbet | Sağ Panel
═══════════════════════════════════════ */

/* ── TEMEL ── */
body{background:#0d0614!important;font-family:'Inter',sans-serif!important;margin:0!important;padding:0!important}
body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background:radial-gradient(circle at 15% 10%,rgba(138,43,226,.18),transparent 35%),
             radial-gradient(circle at 85% 5%,rgba(255,20,147,.18),transparent 30%),
             radial-gradient(circle at 50% 95%,rgba(138,43,226,.1),transparent 40%)}
.gradio-container{max-width:100%!important;margin:0!important;padding:0!important;position:relative;z-index:1}
.block{border:none!important;background:transparent!important}

/* ── 3 KOLON ANA LAYOUT ── */
#beluma-layout{
  display:grid;
  grid-template-columns:220px 1fr 210px;
  grid-template-rows:auto 1fr;
  min-height:100vh;
  gap:0;
}
#beluma-topbar{
  grid-column:1/-1;
  background:rgba(13,6,20,.96);
  border-bottom:1px solid rgba(138,43,226,.22);
  padding:0 16px;
  height:52px;
  display:flex;align-items:center;justify-content:space-between;
  position:sticky;top:0;z-index:100;
}
#beluma-left{
  background:rgba(13,6,20,.85);
  border-right:1px solid rgba(138,43,226,.18);
  padding:10px 6px;
  overflow-y:auto;
  height:calc(100vh - 52px);
  position:sticky;top:52px;
  scrollbar-width:thin;
  scrollbar-color:rgba(138,43,226,.3) transparent;
}
#beluma-center{
  display:flex;flex-direction:column;
  min-height:calc(100vh - 52px);
  background:rgba(13,6,20,.4);
}
#beluma-right{
  background:rgba(13,6,20,.85);
  border-left:1px solid rgba(138,43,226,.18);
  padding:10px 8px;
  overflow-y:auto;
  height:calc(100vh - 52px);
  position:sticky;top:52px;
  scrollbar-width:thin;
  scrollbar-color:rgba(138,43,226,.3) transparent;
}

/* ── TOPBAR ── */
.beluma-logo{
  font-family:'Montserrat',sans-serif;font-size:16px;font-weight:700;
  background:linear-gradient(90deg,#FF1493,#8A2BE2);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  letter-spacing:.06em;
}
.beluma-status-dot{
  width:7px;height:7px;border-radius:50%;
  background:#FF1493;box-shadow:0 0 7px rgba(255,20,147,.9);
  display:inline-block;
  animation:pulse-led 2s ease-in-out infinite;
}
@keyframes pulse-led{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.3;transform:scale(.8)}}

/* ── SOL PANEL ── */
.lsec{
  font-size:9px;font-weight:600;
  color:rgba(255,255,255,.28);
  letter-spacing:.08em;text-transform:uppercase;
  padding:10px 8px 4px;
}
.lbtn{
  display:flex;align-items:center;gap:8px;
  padding:7px 8px;border-radius:8px;
  font-size:11.5px;color:rgba(255,255,255,.55);
  cursor:pointer;border:none;background:transparent;
  width:100%;text-align:left;
  transition:all .15s;
  position:relative;
}
.lbtn:hover{background:rgba(255,20,147,.1);color:rgba(255,255,255,.9)}
.lbtn.active{background:rgba(255,20,147,.15);color:#fff;font-weight:500}
.lbtn.active::before{
  content:'';position:absolute;left:0;top:20%;bottom:20%;
  width:2px;border-radius:2px;background:#FF1493;
}
.lbtn .lbadge{
  margin-left:auto;font-size:9px;padding:1px 5px;
  border-radius:8px;background:rgba(255,20,147,.25);color:#FF69B4;
}
.ldivider{height:1px;background:rgba(138,43,226,.12);margin:6px 4px}

/* ── SOHBET ALANI ── */
.beluma-chat-wrap{
  flex:1;padding:16px 20px;
  display:flex;flex-direction:column;gap:0;
  overflow-y:auto;
}
/* Chatbot override */
.gradio-chatbot{
  border:none!important;border-radius:0!important;
  background:transparent!important;
  box-shadow:none!important;
  flex:1!important;
}
.gradio-chatbot .user>div,[data-testid="user"]>div{
  background:linear-gradient(135deg,#FF1493,#C71585)!important;
  color:#fff!important;border-radius:16px 16px 3px 16px!important;
  box-shadow:0 2px 10px rgba(255,20,147,.25)!important;
  font-size:.9rem!important;line-height:1.6!important;
  max-width:72%!important;
}
.gradio-chatbot .bot>div,[data-testid="bot"]>div{
  background:linear-gradient(135deg,#2a0d4e,#1a0838)!important;
  color:rgba(255,255,255,.93)!important;
  border-radius:16px 16px 16px 3px!important;
  border:1px solid rgba(138,43,226,.28)!important;
  box-shadow:0 2px 10px rgba(138,43,226,.15)!important;
  font-size:.9rem!important;line-height:1.6!important;
  max-width:72%!important;
}
#beluma_chat{
  height:calc(100vh - 200px)!important;
  max-height:calc(100vh - 200px)!important;
  background:transparent!important;
}

/* ── INPUT ALANI ── */
#beluma-inputbar{
  padding:10px 16px 12px;
  background:rgba(13,6,20,.85);
  border-top:1px solid rgba(138,43,226,.18);
}
.gradio-textbox textarea,.gradio-textbox input{
  font-family:'Inter',sans-serif!important;font-size:.93rem!important;
  background:rgba(255,255,255,.04)!important;
  border:1px solid rgba(138,43,226,.3)!important;
  color:rgba(255,255,255,.92)!important;
  border-radius:12px!important;
  transition:border-color .22s,box-shadow .22s!important;
}
.gradio-textbox textarea::placeholder,.gradio-textbox input::placeholder{
  color:rgba(255,255,255,.28)!important;
}
.gradio-textbox textarea:focus,.gradio-textbox input:focus{
  border-color:#FF1493!important;
  box-shadow:0 0 0 3px rgba(255,20,147,.18)!important;
  outline:none!important;
}
.gradio-textbox,.gradio-dropdown,.gradio-accordion{border-radius:12px!important}

/* ── BUTONLAR ── */
button.primary{
  background:linear-gradient(135deg,#FF1493,#8A2BE2)!important;
  color:#fff!important;border:none!important;border-radius:12px!important;
  font-weight:600!important;font-size:.88rem!important;
  box-shadow:0 3px 12px rgba(255,20,147,.35)!important;
  transition:transform .15s,filter .15s!important;
  min-height:40px!important;
}
button.primary:hover{transform:scale(1.03)!important;filter:brightness(1.1)!important}
button.secondary{
  background:rgba(138,43,226,.1)!important;
  color:rgba(255,255,255,.75)!important;
  border:1px solid rgba(138,43,226,.3)!important;
  border-radius:10px!important;font-size:.8rem!important;
  transition:all .15s!important;min-height:34px!important;
}
button.secondary:hover{background:rgba(255,20,147,.15)!important;border-color:#FF1493!important;color:#fff!important}
button.stop{background:rgba(160,30,30,.15)!important;border:1px solid rgba(180,40,40,.3)!important;color:#ff7070!important;border-radius:10px!important;font-size:.8rem!important;min-height:34px!important}
.belge-upload-btn{height:34px!important;border-radius:10px!important;background:rgba(138,43,226,.1)!important;border:1px solid rgba(138,43,226,.3)!important;color:rgba(255,255,255,.75)!important;font-size:.78rem!important;transition:all .15s!important}
.belge-upload-btn:hover{background:rgba(255,20,147,.18)!important;border-color:#FF1493!important;color:#fff!important}

/* ── SAĞ PANEL ── */
.rsec{font-size:9px;font-weight:600;color:rgba(255,255,255,.28);letter-spacing:.08em;text-transform:uppercase;padding:8px 4px 5px}
.rcard{background:rgba(138,43,226,.08);border:1px solid rgba(138,43,226,.2);border-radius:10px;padding:8px 10px;margin-bottom:6px}
.rcard-label{font-size:9px;color:rgba(255,255,255,.42);margin-bottom:3px}
.rcard-val{font-size:17px;font-weight:700;color:#FF69B4;line-height:1}
.rcard-sub{font-size:9px;color:rgba(255,255,255,.32);margin-top:3px}
.rprog{height:3px;background:rgba(255,255,255,.08);border-radius:2px;margin:5px 0 3px}
.rprog-fill{height:3px;background:linear-gradient(90deg,#FF1493,#8A2BE2);border-radius:2px;transition:width .4s}
.rgoal{display:flex;align-items:center;gap:6px;padding:4px 2px;font-size:10.5px;color:rgba(255,255,255,.58)}
.rgoal .rdot{width:5px;height:5px;border-radius:50%;background:#8A2BE2;flex-shrink:0}
.rgoal .rdot.done{background:#1D9E75}
.rhab{display:flex;justify-content:space-between;align-items:center;padding:3px 2px}
.rhab-name{font-size:10.5px;color:rgba(255,255,255,.55)}
.rhab-streak{font-size:10.5px;font-weight:600;color:#FF1493}
.rdivider{height:1px;background:rgba(138,43,226,.1);margin:6px 0}
.rmodel{font-size:10px;color:rgba(255,255,255,.45);padding:2px 2px;line-height:1.8}

/* ── QUICK BUTTONS (sol panel kısayollar) ── */
.qbrow{display:flex;flex-wrap:wrap;gap:3px;padding:4px 4px 6px}
.qb{font-size:10px;padding:3px 7px;border-radius:6px;border:1px solid rgba(138,43,226,.22);background:rgba(138,43,226,.07);color:rgba(255,255,255,.55);cursor:pointer;transition:all .14s}
.qb:hover{border-color:#FF1493;color:#fff;background:rgba(255,20,147,.12)}

/* ── ACCORDION ── */
.gradio-accordion{background:rgba(255,255,255,.015)!important;border:1px solid rgba(138,43,226,.18)!important;border-radius:10px!important}
.beluma-acc-item,.beluma-acc-item .gradio-accordion,.beluma-acc-item details{
  border:1px solid rgba(255,20,147,.18)!important;border-radius:12px!important;
  background:rgba(13,6,20,.2)!important;overflow:hidden!important}
.beluma-acc-item summary,.beluma-acc-item [data-testid="accordion"]>div:first-child{
  padding:9px 11px!important;background:rgba(138,43,226,.08)!important;
  color:rgba(255,255,255,.82)!important;font-size:.85rem!important}
.beluma-acc-item .panel,.beluma-acc-item details>div{
  padding:9px 11px!important;border-top:1px solid rgba(138,43,226,.12)!important}

/* ── ÖRNEKLER ── */
.examples{margin:6px 0 0!important}
.examples table td,.examples .example{
  background:rgba(138,43,226,.08)!important;border:1px solid rgba(138,43,226,.22)!important;
  border-radius:7px!important;color:rgba(255,255,255,.72)!important;
  font-size:.78rem!important;padding:4px 8px!important;transition:all .15s!important}
.examples table td:hover,.examples .example:hover{
  background:rgba(255,20,147,.15)!important;border-color:#FF1493!important;color:#fff!important}

/* ── THINK BOX ── */
.think-box{background:rgba(138,43,226,.08);border-left:2px solid #FF1493;border-radius:0 8px 8px 0;padding:7px 12px;font-size:.82rem;color:rgba(255,255,255,.62);margin-top:5px}

/* ── DEEP RESEARCH ── */
.beluma-dr{border:1px solid rgba(255,20,147,.22)!important;border-radius:10px!important;background:rgba(138,43,226,.07)!important;font-size:.8rem!important;min-height:32px!important;max-width:400px!important;margin:5px auto!important}

/* ── HIZLI EYLEM ── */
.beluma-hizli button{font-size:.72rem!important;padding:4px 7px!important;min-height:28px!important;border-radius:7px!important;flex:1!important}

/* ── TAB BAR TAMAMEN GİZLE (sol panel kullanıyor) ── */
.tab-nav{display:none!important}
.tabs > .tabitem > div > .tab-nav{display:none!important}

/* ── MOBİL ── */
@media(max-width:900px){
  #beluma-layout{grid-template-columns:0 1fr 0}
  #beluma-left,#beluma-right{display:none}
  .gradio-container{padding:0!important}
}
@media(max-width:600px){
  #beluma_chat{height:calc(100vh - 180px)!important;max-height:calc(100vh - 180px)!important}
  button.primary{min-height:44px!important}
}
@media(hover:none) and (pointer:coarse){
  button{-webkit-tap-highlight-color:rgba(255,20,147,.15)!important;touch-action:manipulation!important}
  button.primary:hover{transform:none!important;filter:none!important}
}
"""

# ══════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════
# GRADİO ARAYÜZÜ
# ══════════════════════════════════════════════════════════════════
io = oturumu_yukle()
ip = profili_yukle()

with gr.Blocks(css=CSS) as demo:
    # ── META ──
    gr.HTML('''
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0d0614">
<style>
.gradio-container > .main > .wrap{padding:0!important;max-width:100%!important}
footer{display:none!important}
/* Karşılama ekranı overlay */
#beluma-welcome-overlay {
  position: fixed; inset: 0; z-index: 9999;
  transition: opacity 0.5s ease, visibility 0.5s ease;
}
#beluma-welcome-overlay.hidden {
  opacity: 0; visibility: hidden; pointer-events: none;
}
</style>
''')

    # ── KARŞILAMA EKRANI OVERLAY ──
    gr.HTML('''
<div id="beluma-welcome-overlay">
<style>
  #beluma-welcome-overlay *, #beluma-welcome-overlay *::before, #beluma-welcome-overlay *::after { box-sizing: border-box; margin: 0; padding: 0; }
  #beluma-welcome-overlay {
    --bg: #080510; --surface: rgba(255,255,255,0.045); --border: rgba(255,255,255,0.08);
    --border-h: rgba(255,105,180,0.45); --pink: #FF1493; --violet: #8A2BE2; --cyan: #00D4FF;
    --text-1: rgba(255,255,255,0.95); --text-2: rgba(255,255,255,0.55); --text-3: rgba(255,255,255,0.28);
    --radius: 18px; --font: 'Sora', sans-serif; --mono: 'Space Mono', monospace;
    background: var(--bg); font-family: var(--font); color: var(--text-1); overflow-x: hidden;
  }
  #beluma-welcome-overlay::before {
    content: ''; position: fixed; inset: 0; z-index: 0;
    background: radial-gradient(ellipse 70% 50% at 20% -10%, rgba(138,43,226,0.22) 0%, transparent 60%),
      radial-gradient(ellipse 60% 40% at 80% 110%, rgba(255,20,147,0.18) 0%, transparent 55%),
      radial-gradient(ellipse 40% 30% at 60% 50%, rgba(0,212,255,0.05) 0%, transparent 50%);
    pointer-events: none;
  }
  .bw-grid { position: fixed; inset: 0; z-index: 0;
    background-image: linear-gradient(rgba(138,43,226,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(138,43,226,0.04) 1px, transparent 1px);
    background-size: 64px 64px; pointer-events: none; }
  .bw-topbar {
    position: fixed; top: 0; left: 0; right: 0; z-index: 100;
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 28px; height: 56px; background: rgba(8,5,16,0.7);
    backdrop-filter: blur(20px); border-bottom: 1px solid var(--border);
  }
  .bw-logo { font-family: var(--mono); font-size: 14px; font-weight: 700; letter-spacing: 0.12em;
    background: linear-gradient(90deg, var(--pink), var(--violet)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  .bw-status { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--text-3); letter-spacing: 0.06em; }
  .bw-dot { width: 6px; height: 6px; border-radius: 50%; background: #1DDB8B; box-shadow: 0 0 8px rgba(29,219,139,0.8); animation: bw-pulse 2.4s ease-in-out infinite; }
  @keyframes bw-pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(0.7); } }
  .bw-topbar-right { display: flex; gap: 10px; }
  .bw-btn { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 6px 14px; font-family: var(--font); font-size: 12px; color: var(--text-2);
    cursor: pointer; transition: all 0.18s; letter-spacing: 0.02em; }
  .bw-btn:hover { background: rgba(255,20,147,0.1); border-color: rgba(255,20,147,0.35); color: var(--text-1); }
  .bw-page { position: relative; z-index: 1; min-height: 100vh; display: flex; flex-direction: column;
    align-items: center; justify-content: center; padding: 80px 20px 120px; }
  .bw-hero { text-align: center; margin-bottom: 36px; animation: bw-fadeUp 0.7s cubic-bezier(0.16,1,0.3,1) both; }
  @keyframes bw-fadeUp { from { opacity: 0; transform: translateY(28px); } to { opacity: 1; transform: translateY(0); } }
  .bw-eyebrow { display: inline-flex; align-items: center; gap: 8px; background: rgba(138,43,226,0.1);
    border: 1px solid rgba(138,43,226,0.25); border-radius: 100px; padding: 5px 14px 5px 10px;
    margin-bottom: 20px; font-size: 11px; letter-spacing: 0.08em; color: var(--text-2); text-transform: uppercase; }
  .bw-greeting { font-size: 14px; font-weight: 400; color: var(--text-3); letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 8px; }
  .bw-greeting span { color: var(--pink); font-weight: 600; }
  .bw-title { font-size: clamp(32px, 6vw, 60px); font-weight: 700; line-height: 1.1; letter-spacing: -0.02em; margin-bottom: 14px; }
  .bw-title .bw-hl { background: linear-gradient(135deg, var(--pink) 0%, var(--violet) 50%, var(--cyan) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  .bw-sub { font-size: 15px; font-weight: 300; color: var(--text-2); max-width: 460px; margin: 0 auto; line-height: 1.65; }
  .bw-input-wrap { width: 100%; max-width: 700px; animation: bw-fadeUp 0.7s 0.1s cubic-bezier(0.16,1,0.3,1) both; }
  .bw-box { background: rgba(255,255,255,0.04); border: 1px solid var(--border); border-radius: 20px;
    padding: 18px 20px; backdrop-filter: blur(12px); cursor: text; transition: border-color 0.25s, box-shadow 0.25s; }
  .bw-box:focus-within { border-color: rgba(255,20,147,0.45); box-shadow: 0 0 0 4px rgba(255,20,147,0.08), 0 8px 40px rgba(138,43,226,0.15); }
  .bw-textarea { width: 100%; background: transparent; border: none; outline: none;
    font-family: var(--font); font-size: 15px; color: var(--text-1); resize: none; line-height: 1.6;
    min-height: 28px; max-height: 200px; overflow-y: auto; }
  .bw-textarea::placeholder { color: var(--text-3); }
  .bw-footer { display: flex; align-items: center; justify-content: space-between; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border); }
  .bw-tools { display: flex; gap: 6px; }
  .bw-tool { display: flex; align-items: center; gap: 6px; background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 6px 12px; font-family: var(--font); font-size: 12px; color: var(--text-2); cursor: pointer; transition: all 0.18s; }
  .bw-tool:hover { background: rgba(138,43,226,0.12); border-color: rgba(138,43,226,0.35); color: var(--text-1); }
  .bw-send { width: 36px; height: 36px; display: flex; align-items: center; justify-content: center;
    background: linear-gradient(135deg, var(--pink), var(--violet)); border: none; border-radius: 10px;
    cursor: pointer; box-shadow: 0 4px 16px rgba(255,20,147,0.3); color: #fff; transition: all 0.18s; }
  .bw-send:hover { transform: scale(1.08); box-shadow: 0 6px 24px rgba(255,20,147,0.45); }
  .bw-chips { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 18px; animation: bw-fadeUp 0.7s 0.2s cubic-bezier(0.16,1,0.3,1) both; }
  .bw-chip { display: inline-flex; align-items: center; gap: 7px; background: var(--surface); border: 1px solid var(--border);
    border-radius: 100px; padding: 8px 16px; font-size: 12.5px; font-weight: 500; color: var(--text-2);
    cursor: pointer; transition: all 0.2s; white-space: nowrap; backdrop-filter: blur(8px); }
  .bw-chip:hover { transform: translateY(-2px) scale(1.03); color: var(--text-1); border-color: var(--border-h); background: rgba(255,20,147,0.08); box-shadow: 0 6px 20px rgba(255,20,147,0.15); }
  .bw-hint { position: fixed; bottom: 24px; left: 0; right: 0; text-align: center; font-size: 11px; color: var(--text-3); letter-spacing: 0.04em; z-index: 10; }
  .bw-hint kbd { background: rgba(255,255,255,0.06); border: 1px solid var(--border); border-radius: 5px; padding: 1px 7px; font-family: var(--mono); font-size: 10px; color: var(--text-3); margin: 0 2px; }
</style>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">

<div class="bw-grid"></div>
<header class="bw-topbar">
  <div class="bw-logo">BELUMA-I</div>
  <div class="bw-status"><div class="bw-dot"></div>Çevrimiçi</div>
  <div class="bw-topbar-right">
    <button class="bw-btn" onclick="bwDismiss()">Giriş Yap</button>
    <button class="bw-btn" style="background:linear-gradient(135deg,rgba(255,20,147,0.15),rgba(138,43,226,0.15));border-color:rgba(255,20,147,0.3);color:rgba(255,255,255,0.85)" onclick="bwDismiss()">Başla</button>
  </div>
</header>
<main class="bw-page">
  <section class="bw-hero">
    <div class="bw-eyebrow">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 2L13.09 8.26L19 6L14.74 10.91L21 12L14.74 13.09L19 18L13.09 15.74L12 22L10.91 15.74L5 18L9.26 13.09L3 12L9.26 10.91L5 6L10.91 8.26L12 2Z" fill="url(#bwg)"/><defs><linearGradient id="bwg" x1="3" y1="2" x2="21" y2="22"><stop stop-color="#FF1493"/><stop offset="1" stop-color="#8A2BE2"/></linearGradient></defs></svg>
      Yapay Zeka Asistanın
    </div>
    <p class="bw-greeting">Hoş Geldin, <span>ÖZGÜR</span></p>
    <h1 class="bw-title">Aklındaki fikri <span class="bw-hl">hayata geçirelim.</span></h1>
    <p class="bw-sub">Düşün, keşfet, inşa et. Her sorun için akıllı bir yanıt, her vizyon için güçlü bir araç.</p>
  </section>
  <div class="bw-input-wrap">
    <div class="bw-box" onclick="document.getElementById('bw-input').focus()">
      <textarea id="bw-input" class="bw-textarea" placeholder="Ne öğrenmek, yaratmak veya çözmek istiyorsun?" rows="1" oninput="this.style.height=\'auto\';this.style.height=this.scrollHeight+\'px\'"></textarea>
      <div class="bw-footer">
        <div class="bw-tools">
          <button class="bw-tool">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>Ekle
          </button>
          <button class="bw-tool">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>Araçlar
          </button>
        </div>
        <button class="bw-send" onclick="bwSend()" title="Gönder">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
        </button>
      </div>
    </div>
    <div class="bw-chips">
      <button class="bw-chip" onclick="bwChip(\'Resim oluşturmama yardım et\')">🎨 Resim Oluştur</button>
      <button class="bw-chip" onclick="bwChip(\'Kod yazma konusunda yardım istiyorum\')">💻 Kod Yaz</button>
      <button class="bw-chip" onclick="bwChip(\'Öğrenmeme yardım et\')">📚 Öğren</button>
      <button class="bw-chip" onclick="bwChip(\'Metni özetle:\')">✍️ Metin Özetle</button>
      <button class="bw-chip" onclick="bwChip(\'Derin araştırma yap:\')">🔍 Araştır</button>
      <button class="bw-chip" onclick="bwChip(\'Görüntü analiz et\')">🖼️ Görüntü Analizi</button>
    </div>
  </div>
</main>
<div class="bw-hint"><kbd>Enter</kbd> gönder &nbsp;·&nbsp; <kbd>Shift</kbd>+<kbd>Enter</kbd> satır atla</div>

<script>
function bwDismiss() {
  var overlay = document.getElementById("beluma-welcome-overlay");
  if (overlay) overlay.classList.add("hidden");
}
function bwSend() {
  var val = document.getElementById("bw-input").value.trim();
  if (!val) return;
  bwInjectAndSend(val);
}
function bwChip(text) {
  bwInjectAndSend(text);
}
function bwInjectAndSend(text) {
  bwDismiss();
  setTimeout(function() {
    // Gradio textbox bul ve doldur
    var inputs = document.querySelectorAll("textarea");
    for (var i = 0; i < inputs.length; i++) {
      var el = inputs[i];
      // Karşılama ekranındaki textarea değil, Gradio'nunkini bul
      if (el.id !== "bw-input") {
        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
        nativeInputValueSetter.call(el, text);
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.focus();
        break;
      }
    }
  }, 300);
}
document.addEventListener("DOMContentLoaded", function() {
  var inp = document.getElementById("bw-input");
  if (!inp) return;
  inp.addEventListener("keydown", function(e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); bwSend(); }
  });
});
</script>
</div>
''')

    # ══ 3 KOLON LAYOUT ══
    with gr.Row(elem_id="beluma-layout"):

        # ════════════════════════════
        # SOL PANEL
        # ════════════════════════════
        with gr.Column(elem_id="beluma-left", scale=1, min_width=220):
            gr.HTML('''
<div style="padding:10px 6px 6px">
  <div style="font-family:Montserrat,sans-serif;font-size:15px;font-weight:700;
    background:linear-gradient(90deg,#FF1493,#8A2BE2);-webkit-background-clip:text;
    -webkit-text-fill-color:transparent;letter-spacing:.05em;margin-bottom:2px">BELUMA-I</div>
  <div style="font-size:9px;color:rgba(255,255,255,.35)">v6.5 · Türkçe AI Asistan</div>
</div>
<div style="height:1px;background:rgba(138,43,226,.18);margin:0 6px 8px"></div>
''')
            # Sol nav butonları (görsel, tıklanınca tab değiştirecek)
            sol_tab = gr.State("sohbet")

            gr.HTML('<div class="lsec">ANA</div>')
            sol_sohbet_b = gr.Button("💬  Sohbet",        variant="secondary", elem_classes=["lbtn", "active"])
            sol_gorev_b  = gr.Button("📋  Görevler",       variant="secondary", elem_classes=["lbtn"])
            sol_gorsel_b = gr.Button("🎨  Görsel Üret",    variant="secondary", elem_classes=["lbtn"])
            sol_ses_b    = gr.Button("🎙  Ses",            variant="secondary", elem_classes=["lbtn"])
            sol_harita_b = gr.Button("🗺  Yaşam Haritası", variant="secondary", elem_classes=["lbtn"])

            gr.HTML('<div style="height:1px;background:rgba(138,43,226,.12);margin:6px 4px"></div>')
            gr.HTML('<div class="lsec">ARAÇLAR</div>')
            hizli_hava  = gr.Button("🌤  Hava Durumu",  variant="secondary", elem_classes=["lbtn"])
            hizli_borsa = gr.Button("📈  Borsa",         variant="secondary", elem_classes=["lbtn"])
            hizli_haber = gr.Button("📰  Haberler",      variant="secondary", elem_classes=["lbtn"])
            hizli_tarih = gr.Button("📅  Tarih & Saat",  variant="secondary", elem_classes=["lbtn"])
            dr_btn      = gr.Button("🔍  Deep Research", variant="secondary", elem_classes=["lbtn"])

            gr.HTML('<div style="height:1px;background:rgba(138,43,226,.12);margin:6px 4px"></div>')
            gr.HTML('<div class="lsec">AYARLAR</div>')
            sol_analitik_b  = gr.Button("📊  Analitik",    variant="secondary", elem_classes=["lbtn"])
            sol_plugin_b    = gr.Button("🧩  Pluginler",   variant="secondary", elem_classes=["lbtn"])
            sol_webhook_b   = gr.Button("🔗  Webhook",     variant="secondary", elem_classes=["lbtn"])
            sol_hatir_b     = gr.Button("🔔  Hatırlatıcı", variant="secondary", elem_classes=["lbtn"])
            sol_dil_b       = gr.Button("🌍  Dil",         variant="secondary", elem_classes=["lbtn"])
            sol_ekip_b      = gr.Button("🤝  Ekip",        variant="secondary", elem_classes=["lbtn"])
            sol_guvenlik_b  = gr.Button("🔒  Güvenlik",    variant="secondary", elem_classes=["lbtn"])
            sol_hakkinda_b  = gr.Button("ℹ️  Hakkında",    variant="secondary", elem_classes=["lbtn"])

        # ════════════════════════════
        # ORTA — SOHBET + SEKMELER
        # ════════════════════════════
        with gr.Column(elem_id="beluma-center", scale=4):
            durum         = gr.Markdown("Hazır.", elem_classes=["beluma-status"])
            _oner_ilk     = gunluk_oneri()
            oneri_kutu    = gr.Markdown(_oner_ilk, visible=bool(_oner_ilk), elem_classes=["beluma-soft"])
            aciklama_kutu = gr.Markdown("", elem_classes=["think-box"], visible=False)

            sg  = gr.State(io.get("chat_history",[]))
            bas = gr.State(io.get("document_name",""))
            bms = gr.State(io.get("document_text",""))

            with gr.Tabs() as ana_tabs:
                # ── Sohbet ──
                with gr.Tab("💬 Sohbet", id="sohbet"):
                    resim_on = gr.Image(label="Vision", type="filepath", height=120, visible=False)
chatbot = gr.Chatbot(
    show_label=False,
    container=True,
    height=500
                       value=[{"role":"assistant","content":"👋 Merhaba! Ben **BELUMA-I**. Sana nasıl yardımcı olabilirim?\n\n💡 Hava, borsa, haberler, kod yazma, analiz veya sohbet — her şey için burdayım!"}],
                        label="", height=480, elem_id="beluma_chat",
                        type="messages", bubble_full_width=False, show_copy_button=True,
                        show_label=False,
                    )
                    dr_output = gr.Markdown(visible=False)
                    with gr.Column(elem_id="beluma-inputbar"):
                        with gr.Row(equal_height=True, elem_classes=["beluma-bar"]):
                            mk = gr.Textbox(placeholder="Mesajını yaz... (Enter → gönder)", lines=1, max_lines=5, show_label=False, scale=9)
                            gb = gr.Button("Gönder ✈", variant="primary", scale=2)
                        with gr.Row(elem_classes=["beluma-frame"]):
                            ys  = gr.Slider(minimum=0.0, maximum=1.0, value=0.4, step=0.1, label="🧠 Yaratıcılık", scale=1)
                            ork = gr.Textbox(label="🎭 Özel Rol", placeholder="Örn: Kıdemli yazılımcısın...", lines=1, scale=2)
                            uzmanlik_secici = gr.Dropdown(list(UZMANLIK_MODLARI.keys()), value="Standart", label="🎓 Uzmanlık", scale=1)
                        with gr.Row(elem_classes=["beluma-frame"]):
                            bb  = gr.UploadButton("📎 Belge", file_count="single", file_types=[".pdf",".docx",".xlsx",".xls",".txt",".csv",".md",".json"], scale=2, elem_classes=["belge-upload-btn"])
                            rb  = gr.UploadButton("🖼️ Resim", file_count="single", file_types=["image"], scale=2, elem_classes=["belge-upload-btn"])
                            ysb = gr.Button("🔄 Yeni",    variant="secondary", scale=2)
                            syb = gr.Button("📂 Yükle",   variant="secondary", scale=2)
                            ib  = gr.Button("🔍 Denetle", variant="secondary", scale=2)
                            sib = gr.Button("📥 İndir",   variant="secondary", scale=2)
                    with gr.Column(elem_classes=["beluma-examples"]):
                        gr.Examples(
                            examples=[
                                "Bugün tarih ve saat kaç?",
                                "İstanbul hava durumu?",
                                "Son haberler neler?",
                                "Borsa bugün nasıl?",
                                "Karar veremiyorum, nasıl düşünmeliyim?",
                                "Bu hafta projem için adım adım plan yap",
                                "Kod yaz: Python'da fibonacci",
                                "Motivasyonum düşük, ne yapmalıyım?",
                            ],
                            inputs=mk, examples_per_page=8)
                    with gr.Column(elem_classes=["beluma-accordion-frame"]):
                        with gr.Accordion("⚙️ Kişisel Ayarlar", open=False, elem_classes=["beluma-acc-item"]):
                            ta = gr.Textbox(label="Adın", value=ip.get("name",""))
                    with gr.Row():
                        tt = gr.Dropdown(["samimi","profesyonel","enerjik"], value=ip.get("tone","samimi"), label="Ton")
                        ts = gr.Dropdown(["kısa","dengeli","detaylı"], value=ip.get("style","dengeli"), label="Stil")
                        tm = gr.Dropdown(
                            choices=["llama-3.3-70b-versatile","llama-3.1-8b-instant","gemma2-9b-it",
                                     "gemini-1.5-pro","gemini-1.5-flash","deepseek-chat",
                                     "gpt-4o-mini","gpt-4o",
                                     "claude-3-5-sonnet-20241022","claude-3-5-haiku-20241022"],
                            value="llama-3.3-70b-versatile", label="🧠 Model")
                    ph = gr.Textbox(label="Beni tanı", lines=2, value=ip.get("about",""))
                    pt = gr.Textbox(label="Tercih notları", lines=2, value=ip.get("preferences",""))
                    akb = gr.Button("Kaydet"); akd = gr.Markdown("")
                with gr.Accordion("🛠️ Gelişmiş", open=False, elem_classes=["beluma-acc-item"]):
                    with gr.Row():
                        mts = gr.Slider(minimum=100, maximum=8192, value=1024, step=100, label="📏 Max Tokens")
                        tps = gr.Slider(minimum=0.1, maximum=1.0, value=0.9, step=0.05, label="🎲 Top-P")
                with gr.Accordion("🧠 Öğrenilenler", open=False, elem_classes=["beluma-acc-item"]):
                    og  = gr.Textbox(label="Öğrenilenler", value="\n".join(ip.get("learned",[])) or "Henüz yok.", lines=5, interactive=False)
                    ogy = gr.Button("Yenile")
                    with gr.Row():
                        osi = gr.Textbox(label="Silinecek tercih", scale=3)
                        osb = gr.Button("Sil 🗑", variant="stop", scale=1)
                    osd = gr.Markdown("")

        with gr.Tab("📋 Görev", id="gorev"):
            gl  = gr.Textbox(label="Görevler", value=gorevleri_metne_cevir(), lines=12, interactive=False)
            gyb = gr.Button("Yenile", variant="secondary")
            with gr.Row():
                yga = gr.Textbox(label="Yeni görev", scale=4)
                geb = gr.Button("Ekle ✚", variant="primary", scale=1)
            with gr.Row():
                gii = gr.Textbox(label="Görev ID", scale=3)
                gtb = gr.Button("Tamam ✓",  variant="primary",   scale=1)
                gsb = gr.Button("Sil 🗑",   variant="secondary",  scale=1)
            gd = gr.Markdown("")

        with gr.Tab("🎨 Görsel", id="gorsel"):
            gsd = gr.Markdown("Hazır.", elem_classes=["beluma-status"])
            gr.Markdown("#### ⚡ Şablonlar", elem_classes=["beluma-soft"])
            with gr.Row():
                te  = gr.Button("📦 Ürün",     variant="secondary", scale=1)
                tso = gr.Button("📱 Sosyal",   variant="secondary", scale=1)
                tmi = gr.Button("🏠 Mimari",   variant="secondary", scale=1)
                tk  = gr.Button("🧑‍🎨 Karakter", variant="secondary", scale=1)
            with gr.Row():
                with gr.Column(scale=3):
                    gp  = gr.Textbox(label="Ne görmek istiyorsun?", lines=4)
                    with gr.Row():
                        gst = gr.Dropdown(choices=list(GORSEL_STILLER.keys()), value="Gerçekçi", label="🎨 Stil")
                        gor = gr.Dropdown(["1:1","16:9","9:16","4:5"], value="1:1", label="📐 Oran")
                    gg  = gr.Slider(minimum=7, maximum=12, value=9, step=0.5, label="🎛 Guidance")
                    with gr.Row():
                        gub = gr.Button("🚀 Tek Görsel", variant="primary",    scale=3)
                        gvb = gr.Button("🔄 4 Varyasyon", variant="secondary",  scale=2)
                        gtm = gr.Button("🧹 Temizle",    variant="stop",        scale=1)
                    kg = gr.Markdown(kredi_kontrol()[1], elem_classes=["beluma-soft"])
                with gr.Column(scale=2):
                    gso = gr.Image(label="Sonuç", type="filepath")
                    gga = gr.Gallery(label="Varyasyonlar", columns=2, rows=2, object_fit="contain", visible=False)

        with gr.Tab("🎙 Ses", id="ses"):
            gr.Markdown("Konuş → BELUMA-I sesli cevap versin.", elem_classes=["beluma-status"])
            with gr.Tabs():
                with gr.Tab("🎤 Sesli Diyalog"):
                    sgi = gr.Audio(sources=["microphone"], type="filepath", label="Konuş")
                    sct = gr.Textbox(label="Metin", lines=4, interactive=False)
                    sca = gr.Audio(label="Ses", type="filepath", autoplay=True)
                    scb = gr.Button("🎤 Gönder", variant="primary")
                with gr.Tab("🔧 Manuel"):
                    si   = gr.Audio(sources=["microphone","upload"], type="filepath", label="Ses")
                    with gr.Row():
                        syb2 = gr.Button("Yazıya çevir 📝", variant="primary")
                        ssb  = gr.Button("Seslendir 🔊",    variant="secondary")
                    scm = gr.Textbox(label="Metin", lines=4)
                    sco = gr.Audio(label="Çıktı", type="filepath")

        with gr.Tab("🗺 Harita", id="harita"):
            lm = haritayi_yukle()
            gr.Markdown("### Life Map\nHedefler, alışkanlıklar, performans.")
            with gr.Tabs():
                with gr.Tab("🎯 Hedefler"):
                    lhl = gr.Textbox(label="Hedefler", value=_hedef_listesi(), lines=8, interactive=False)
                    with gr.Row():
                        lyh = gr.Textbox(label="Yeni hedef", scale=3)
                        lop = gr.Dropdown(["1 - Düşük","2 - Orta","3 - Yüksek"], value="2 - Orta", label="Öncelik", scale=1)
                        lhb = gr.Button("Ekle ✚", variant="primary", scale=1)
                    with gr.Row():
                        lti = gr.Textbox(label="Tamamlanan", scale=3)
                        ltb = gr.Button("Tamam ✓", variant="primary", scale=1)
                    lhd = gr.Markdown("")
                with gr.Tab("📓 Notlar"):
                    lni = gr.Textbox(label="Not", lines=4)
                    with gr.Row():
                        lnk = gr.Dropdown(["genel","iş","kişisel","öğrenme","sağlık"], value="genel", label="Kategori")
                        lnb = gr.Button("Kaydet 📓", variant="primary")
                    lnd = gr.Markdown("")
                    lsn = gr.Textbox(label="Son notlar",
                                     value="\n---\n".join(f"[{n['tarih']}] {n['not']}" for n in lm.get("gunluk_notlar",[])[-5:]) or "Henüz yok.",
                                     lines=8, interactive=False)
                with gr.Tab("🔄 Alışkanlıklar"):
                    lai = gr.Textbox(label="Alışkanlık")
                    lab = gr.Button("Bugün yaptım ✓", variant="primary")
                    lal = gr.Textbox(label="Seriler",
                                     value="\n".join(f"🔥 {a['aliskanlik']}: {a['seri']}g" for a in lm.get("aliskanliklar",[])) or "Henüz yok.",
                                     lines=6, interactive=False)
                    lad = gr.Markdown("")
                with gr.Tab("📊 Rapor"):
                    rpb = gr.Button("📊 Aylık rapor", variant="primary")
                    rpc = gr.Markdown("")
            with gr.Accordion("⚙️ Vizyon", open=False):
                lis = gr.Textbox(label="İş modeli",  value=lm.get("is_modeli",""))
                lpl = gr.Textbox(label="Uzun vade",  lines=3, value=lm.get("uzun_vadeli_plan",""))
                lka = gr.Textbox(label="Karar tarzı", value=lm.get("karar_tarzi",""))
                lkb = gr.Button("Kaydet 🗺", variant="primary")
                lkd = gr.Markdown("")

        with gr.Tab("🤝 Ekip", id="ekip"):
            # Duyurular
            ekip_duyuru_goster = gr.Markdown(value=duyurular_metin() or "Duyuru yok.")
            # Kullanıcı listesi
            ekip_kullanici_liste = gr.Markdown(value=kullanici_listesi_metin())
            ekip_yenile = gr.Button("🔄 Yenile", variant="secondary")
            gr.Markdown("---")
            gr.Markdown("**👑 Admin — Kullanıcı Yönetimi**")
            with gr.Row():
                ekip_yeni_ad    = gr.Textbox(label="Kullanıcı Adı", scale=2)
                ekip_yeni_sifre = gr.Textbox(label="Şifre", type="password", scale=2)
                ekip_yeni_rol   = gr.Dropdown(ROLLER, value="editor", label="Rol", scale=1)
            with gr.Row():
                ekip_yeni_isim  = gr.Textbox(label="Ad Soyad (opsiyonel)", scale=2)
                ekip_yeni_email = gr.Textbox(label="E-posta (opsiyonel)", scale=2)
                ekip_ekle_b     = gr.Button("➕ Ekle", variant="primary", scale=1)
            ekip_ekle_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown("**Rol Değiştir / Sil**")
            with gr.Row():
                ekip_rol_ad     = gr.Textbox(label="Kullanıcı Adı", scale=2)
                ekip_yeni_rol2  = gr.Dropdown(ROLLER, value="editor", label="Yeni Rol", scale=1)
                ekip_rol_b      = gr.Button("🔄 Rol Değiştir", variant="secondary", scale=1)
                ekip_sil_b      = gr.Button("🗑 Sil",          variant="stop",      scale=1)
            ekip_rol_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown("**📝 Ortak Notlar**")
            ekip_not_liste = gr.Markdown(value=ortak_notlar_metin())
            with gr.Row():
                ekip_not_metin = gr.Textbox(label="Yeni not", lines=2, scale=4)
                ekip_not_b     = gr.Button("📝 Ekle", variant="primary", scale=1)
            ekip_not_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown("**📢 Duyuru Yayınla (Admin)**")
            with gr.Row():
                ekip_duyuru_metin = gr.Textbox(label="Duyuru", scale=4)
                ekip_duyuru_b     = gr.Button("📢 Yayınla", variant="primary", scale=1)
            ekip_duyuru_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown("**📋 Aktivite Logu**")
            ekip_aktivite = gr.Markdown(value=aktivite_logu_metin())

        with gr.Tab("🌍 Dil", id="dil"):
            dil_durum   = gr.Markdown(f"Mevcut dil: **{mevcut_dil_etiketi()}**")
            dil_secici  = gr.Dropdown(
                choices=list(DESTEKLENEN_DILLER.values()),
                value=mevcut_dil_etiketi(),
                label="Arayüz ve yanıt dili seç"
            )
            dil_kaydet_b = gr.Button("✅ Dili Uygula", variant="primary")
            dil_kaydet_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown(
                "**Desteklenen diller:**\n"
                "- 🇹🇷 Türkçe (varsayılan)\n"
                "- 🇬🇧 English\n"
                "- 🇩🇪 Deutsch\n"
                "- 🇫🇷 Français\n"
                "- 🇪🇸 Español\n"
                "- 🇸🇦 العربية\n"
                "- 🇷🇺 Русский\n"
                "- 🇯🇵 日本語\n\n"
                "Dil değiştiğinde model **seçilen dilde** yanıt üretir.\n\n"
                "**Özel çeviri eklemek için** `beluma_i18n.json` dosyasını düzenle:\n"
                "```json\n"
                '{\n  "en": {\n    "gonder": "Send ✈"\n  }\n}\n'
                "```"
            )

        with gr.Tab("🔔 Hatırlat", id="hatir"):
            htr_bildirimler = gr.Markdown(value="", label="Bildirimler")
            with gr.Row():
                htr_yenile  = gr.Button("🔄 Yenile",          variant="secondary", scale=1)
                htr_temizle = gr.Button("🧹 Bildirimleri Temizle", variant="stop", scale=1)
            gr.Markdown("---")
            htr_liste = gr.Markdown(value=hatirlaticilar_listesi_metin())
            gr.Markdown("---")
            gr.Markdown("**Yeni Hatırlatıcı Ekle**")
            with gr.Row():
                htr_mesaj = gr.Textbox(label="Mesaj", placeholder="Toplantıya katıl, ilaç iç...", scale=3)
                htr_zaman = gr.Textbox(label="Ne zaman?", placeholder="30 dakika sonra / yarın 09:00 / her gün 08:00", scale=3)
            with gr.Row():
                htr_ekle_b = gr.Button("➕ Ekle", variant="primary", scale=1)
                htr_ekle_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown("**Hatırlatıcı Sil**")
            with gr.Row():
                htr_sil_id = gr.Textbox(label="Hatırlatıcı ID", placeholder="8 haneli ID", scale=2)
                htr_sil_b  = gr.Button("🗑 Sil", variant="stop", scale=1)
                htr_sil_d  = gr.Markdown("")
            gr.Markdown(
                "**Zaman ifadesi örnekleri:**\n"
                "- `30 dakika sonra` — 30 dakika içinde\n"
                "- `2 saat sonra` — 2 saat içinde\n"
                "- `yarın 09:00` — yarın sabah 09:00\n"
                "- `bugün 14:30` — bugün öğleden sonra\n"
                "- `her gün 08:00` — her sabah 08:00 (tekrarlayan)\n"
                "- `2025-12-31 10:00` — tam tarih ve saat"
            )

        with gr.Tab("🔗 Webhook", id="webhook"):
            wh_liste  = gr.Markdown(value=webhook_listesi_metin())
            wh_yenile = gr.Button("🔄 Yenile", variant="secondary")
            gr.Markdown("---")
            gr.Markdown("**Yeni Webhook Ekle**")
            with gr.Row():
                wh_isim = gr.Textbox(label="İsim",    placeholder="Örn: Slack Bildirim",  scale=2)
                wh_url  = gr.Textbox(label="URL",     placeholder="https://hooks.slack.com/...", scale=4)
            with gr.Row():
                wh_secret = gr.Textbox(label="Secret (opsiyonel)", placeholder="HMAC imza için", scale=3)
                wh_olaylar = gr.CheckboxGroup(
                    choices=["mesaj","gorsel","hata","hedef"],
                    value=["mesaj"], label="Olaylar", scale=3)
            with gr.Row():
                wh_ekle_b = gr.Button("➕ Ekle",  variant="primary",   scale=1)
                wh_ekle_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown("**Webhook Yönetimi**")
            with gr.Row():
                wh_id_in   = gr.Textbox(label="Webhook ID", placeholder="8 haneli ID", scale=2)
                wh_test_b  = gr.Button("🧪 Test Gönder",  variant="secondary", scale=1)
                wh_toggle_b= gr.Button("⏸/▶️ Aktif/Pasif", variant="secondary", scale=1)
                wh_sil_b   = gr.Button("🗑 Sil",          variant="stop",      scale=1)
            wh_yonetim_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown(
                "**Desteklenen Olaylar:**\n"
                "- `mesaj` — Her sohbet mesajı sonrası\n"
                "- `gorsel` — Görsel üretimi sonrası\n"
                "- `hata` — Kritik hata oluşunca\n"
                "- `hedef` — Hedef eklenince/tamamlanınca\n\n"
                "**Payload örneği:**\n"
                "```json\n"
                '{\n  "olay": "mesaj",\n  "zaman": "2025-01-01 12:00:00",\n'
                '  "kaynak": "BELUMA-I",\n  "kullanici_mesaji": "...",\n  "cevap": "..."\n}\n'
                "```\n\n"
                "İmza doğrulama: `X-Beluma-Signature: sha256=<hmac>`"
            )

        with gr.Tab("🧩 Plugin", id="plugin"):
            pl_liste  = gr.Markdown(value=plugin_listesi_metin(), label="Yüklü Pluginler")
            with gr.Row():
                pl_yenile = gr.Button("🔄 Yeniden Yükle", variant="primary")
                pl_durum  = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown("**Plugin Yönetimi**")
            with gr.Row():
                pl_isim_in = gr.Textbox(label="Plugin İsmi", placeholder="Örn: Döviz Çevirici", scale=3)
                pl_pasif_b = gr.Button("⏸ Pasife Al",   variant="secondary", scale=1)
                pl_aktif_b = gr.Button("▶️ Aktif Et",   variant="secondary", scale=1)
            pl_yonetim_d = gr.Markdown("")
            gr.Markdown("---")
            gr.Markdown(
                "**Kendi Plugin'ini Yaz:**\n\n"
                "```python\n"
                "# beluma_plugins/benim_plugin.py\n"
                "PLUGIN_ISIM     = 'Benim Plugin'\n"
                "PLUGIN_VERSIYON = '1.0'\n"
                "PLUGIN_ACIKLAMA = 'Ne yapar?'\n"
                "TETIKLEYICILER  = ['anahtar kelime']\n\n"
                "def calistir(mesaj: str) -> str:\n"
                "    return f'Sonuç: {mesaj}'\n"
                "```\n\n"
                "Dosyayı `beluma_plugins/` klasörüne at, **Yeniden Yükle** butonuna bas."
            )

        with gr.Tab("📊 Analitik", id="analitik"):
            anl_html   = gr.HTML(value=dashboard_html(), label="Dashboard")
            anl_yenile = gr.Button("🔄 Yenile", variant="secondary")
            anl_yenile.click(fn=dashboard_html, outputs=[anl_html])

        with gr.Tab("🔒 Güvenlik", id="guvenlik"):
            gr.Markdown("### Korumalar\n- 🛡️ Injection tespiti\n- ⚠️ Phishing tarama\n- 🔐 SHA-256 şifreler\n- 🧮 AST hesap (eval yok)\n- 🔒 Atomic write\n- ♻️ atexit cleanup\n\n### .env Kurulumu\n`GROQ_API_KEY=gsk_...` (zorunlu — Llama/Gemma)\n`HF_TOKEN=hf_...` (görsel üretim)\n`GEMINI_API_KEY=...` (isteğe bağlı)\n`DEEPSEEK_API_KEY=...` (isteğe bağlı)\n`OPENAI_API_KEY=...` (isteğe bağlı)\n`ANTHROPIC_API_KEY=...` (isteğe bağlı)\n\n### Kurulum\n`pip install google-generativeai anthropic openai duckduckgo-search`")
            vsb = gr.Button("🗑 Tüm verileri sil", variant="stop")
            vsd = gr.Markdown("")
            gr.Markdown("---")
            hib = gr.Button("📊 Hata İstatistikleri", variant="secondary")
            hid = gr.Markdown("")

        with gr.Tab("ℹ️ Hakkında", id="hakkinda"):
            gr.Markdown("### BELUMA-I — v6.5 (3 Kolon Layout)\n\n**Tüm özellikler:**\n- 💬 Akıllı sohbet (Groq, Gemini, DeepSeek, OpenAI, Claude)\n- 📋 Görev yönetimi\n- 🎨 Görsel üretimi (FLUX, SDXL)\n- 🎙 Ses tanıma & sentez\n- 🗺 Yaşam haritası & hedefler\n- 🔗 Webhook entegrasyonu\n- 🔔 Hatırlatıcı sistemi\n- 🌍 8 dil desteği\n- 🤝 Çoklu kullanıcı / ekip modu\n- 📊 Analitik dashboard\n- 🧩 Plugin sistemi\n- 🛡️ Güvenlik & hata yönetimi\n\n**Kurucu:** BELUMA Group YKB Özgür")

        # ════════════════════════════
        # SAĞ PANEL
        # ════════════════════════════
        with gr.Column(elem_id="beluma-right", scale=1, min_width=210):
            sag_panel_html = gr.HTML(value=sag_panel_guncelle(), elem_id="beluma-right-html")
            sag_yenile_b   = gr.Button("🔄", variant="secondary", size="sm")

    # ══ EVENTS ══
    rb.upload(lambda f: gr.Image(value=f.name if hasattr(f,"name") else f, visible=True), inputs=[rb], outputs=[resim_on])

    def sw(m,g,a,t,s,ba,bm,y,o,uz,sm,mt,tp,ri):
        for yg,tz,d,ac in sohbet_et(m,g,a,t,s,ba,bm,y,o,sm,mt,tp,aktif_resim=ri,uzmanlik=uz):
            yield chatbot_icin_hazirla(yg),tz,d,gr.Markdown(value=f"**💭:** {ac}" if ac else "",visible=bool(ac)),gr.Image(value=None,visible=False),yg

    si_list = [mk,sg,ta,tt,ts,bas,bms,ys,ork,uzmanlik_secici,tm,mts,tps,resim_on]
    so_list = [chatbot,mk,durum,aciklama_kutu,resim_on,sg]
    gb.click(sw, inputs=si_list, outputs=so_list, show_progress="hidden")
    mk.submit(sw, inputs=si_list, outputs=so_list, show_progress="hidden")

    def _oneri_kutu_guncelle():
        o=gunluk_oneri(); return gr.Markdown(value=o,visible=bool(o))
    ysb.click(yeni_sohbet,inputs=[bas,bms],outputs=[chatbot,durum]).then(lambda:[], outputs=[sg]).then(_oneri_kutu_guncelle,outputs=[oneri_kutu])
    syb.click(son_sohbeti_yukle,outputs=[chatbot,sg,bas,bms,durum])
    bb.upload(belge_yukle,inputs=[bb],outputs=[bas,bms,durum])
    akb.click(ayarlari_kaydet,inputs=[ta,tt,ts,ph,pt],outputs=[akd])
    ogy.click(lambda:"\n".join(profili_yukle().get("learned",[])) or "Henüz yok.",outputs=[og])
    osb.click(ogrenileni_sil,inputs=[osi],outputs=[og,osd]).then(lambda:"",outputs=[osi])
    ib.click(cevabi_iyilestir,inputs=[sg],outputs=[chatbot,durum]).then(lambda h:h,inputs=[chatbot],outputs=[sg])
    indir_dosya = gr.File(label="İndirilen Sohbet", visible=False)
    sib.click(fn=sohbeti_indir, inputs=[sg, ta], outputs=[indir_dosya]).then(
        fn=lambda x: gr.File(value=x, visible=True) if x else gr.File(visible=False),
        inputs=[indir_dosya], outputs=[indir_dosya])
    gyb.click(gorevleri_metne_cevir,outputs=[gl])

    def mgef(b):
        if not (b or "").strip(): return "Boş.",gorevleri_metne_cevir()
        gorev_ekle(b.strip()); return f"✅ {b.strip()}",gorevleri_metne_cevir()
    geb.click(mgef,inputs=[yga],outputs=[gd,gl]).then(lambda:"",outputs=[yga])

    def gtuf(g):
        try:
            gorev_tamamla_id(int(g)); return "✅", gorevleri_metne_cevir()
        except ValueError:
            return "⚠️ Geçerli bir sayısal ID gir.", gorevleri_metne_cevir()
        except GorevHatasi as e:
            _hata_say("gorev.tamamla"); return f"⚠️ Görev hatası: {e}", gorevleri_metne_cevir()
        except Exception as e:
            _logger.error("[gtuf] %s", e); _hata_say("gorev.tamamla.genel")
            return "⚠️ Beklenmeyen hata. Lütfen tekrar dene.", gorevleri_metne_cevir()
    def gsuf(g):
        try:
            gorev_sil_id(int(g)); return "🗑 Silindi.", gorevleri_metne_cevir()
        except ValueError:
            return "⚠️ Geçerli bir sayısal ID gir.", gorevleri_metne_cevir()
        except GorevHatasi as e:
            _hata_say("gorev.sil"); return f"⚠️ Görev hatası: {e}", gorevleri_metne_cevir()
        except Exception as e:
            _logger.error("[gsuf] %s", e); _hata_say("gorev.sil.genel")
            return "⚠️ Beklenmeyen hata. Lütfen tekrar dene.", gorevleri_metne_cevir()
    gtb.click(gtuf,inputs=[gii],outputs=[gd,gl])
    gsb.click(gsuf,inputs=[gii],outputs=[gd,gl])

    te.click( lambda:("product photography, white background, studio lighting, 4K","Gerçekçi","1:1"),outputs=[gp,gst,gor])
    tso.click(lambda:("vibrant social media post, bold colors, modern design","Minimal","1:1"),        outputs=[gp,gst,gor])
    tmi.click(lambda:("luxury real estate, wide angle interior, soft sunlight, 4k","Emlak/Mimari","16:9"),outputs=[gp,gst,gor])
    tk.click( lambda:("professional portrait, soft lighting, detailed face, cinematic","Gerçekçi","9:16"),outputs=[gp,gst,gor])

    def _tgw(p,s,g):
        ok,km=kredi_kullan()
        if not ok: return None,gr.Gallery(visible=False),km,km
        y,m,_,_=generate_single(gorsel_prompt_muhendisi(p),s,g)
        if y: son_gorsel_kaydet(y)
        return y,gr.Gallery(visible=False),m or km,kredi_kontrol()[1]
    gub.click(_tgw,inputs=[gp,gst,gg],outputs=[gso,gga,gsd,kg])

    def _vw(p,s,g):
        ok,km=kredi_kullan()
        if not ok: return gr.Gallery(visible=False),None,km,km
        l,m=generate_variations(gorsel_prompt_muhendisi(p),s,g)
        if l: son_gorsel_kaydet(l[0])
        return (gr.Gallery(value=l,visible=True) if l else gr.Gallery(visible=False)),None,m,kredi_kontrol()[1]
    gvb.click(_vw,inputs=[gp,gst,gg],outputs=[gga,gso,gsd,kg])
    gtm.click(lambda:("","Gerçekçi","1:1",9.0,None,gr.Gallery(visible=False),"🧹"),outputs=[gp,gst,gor,gg,gso,gga,gsd])

    def sd(au,g,a,t,s):
        if not au: return g,"Konuş.",None
        m,_ = sesi_yaziya_cevir(au)
        if not m: return g,"Anlaşılamadı.",None
        yg=g
        for y,_,_,_ in sohbet_et(m,g,a,t,s,"",""): yg=y
        sc=son_asistan_mesaji(yg)
        cs=" ".join("".join(c if (c.isalnum() or c in " .,!?;:") else " " for c in sc[:400]).split())
        sf,_=metni_seslendir_premium(cs)
        if not sf: sf,_=metni_seslendir(cs)
        return yg,sc,sf
    scb.click(sd,inputs=[sgi,sg,ta,tt,ts],outputs=[sg,sct,sca])
    syb2.click(sesi_yaziya_cevir,inputs=[si],outputs=[scm,durum]).then(lambda t:t,inputs=[scm],outputs=[mk])

    def _ss(g):
        m=son_asistan_mesaji(g); s,_=metni_seslendir_premium(m)
        if not s: s,_=metni_seslendir(m)
        return s
    ssb.click(_ss,inputs=[sg],outputs=[sco])

    def lvk(i,p,k):
        v=haritayi_yukle(); v["is_modeli"]=i.strip(); v["uzun_vadeli_plan"]=p.strip(); v["karar_tarzi"]=k.strip(); haritayi_kaydet(v); return "✅ Kaydedildi."
    lkb.click(lvk,inputs=[lis,lpl,lka],outputs=[lkd])

    def lhef(h,o):
        if not (h or "").strip(): return "Boş.",_hedef_listesi()
        hedef_ekle(h.strip(),int(o.split(" - ")[0])); return f"✅ {h.strip()}",_hedef_listesi()
    lhb.click(lhef,inputs=[lyh,lop],outputs=[lhd,lhl]).then(lambda:"",outputs=[lyh])

    def lhtf(m):
        if not (m or "").strip(): return "Boş.",_hedef_listesi()
        hedef_tamamla(m.strip()); return "✅ Tamam!",_hedef_listesi()
    ltb.click(lhtf,inputs=[lti],outputs=[lhd,lhl]).then(lambda:"",outputs=[lti])

    def lnef(m,k):
        if not (m or "").strip(): return "Boş.",""
        gunluk_not_ekle(m.strip(),k); return "✅","\n---\n".join(f"[{n['tarih']}] {n['not']}" for n in haritayi_yukle().get("gunluk_notlar",[])[-5:])
    lnb.click(lnef,inputs=[lni,lnk],outputs=[lnd,lsn]).then(lambda:"",outputs=[lni])

    def laf(m):
        if not (m or "").strip(): return "Boş.",""
        aliskanlik_guncelle(m.strip()); return f"✅ {m.strip()}","\n".join(f"🔥 {a['aliskanlik']}: {a['seri']}g" for a in haritayi_yukle().get("aliskanliklar",[])) or "Yok."
    lab.click(laf,inputs=[lai],outputs=[lad,lal])
    rpb.click(aylik_rapor_olustur,outputs=[rpc])

    def _deep_research_handler(konu_text):
        if not (konu_text or "").strip():
            yield gr.Markdown(value="Araştırma yapmak için mesaj kutusuna bir konu yazın.",visible=True); return
        rapor=""
        for chunk in derin_arastirma_yap(konu_text.strip()):
            rapor+=chunk; yield gr.Markdown(value=rapor,visible=True)
    dr_btn.click(_deep_research_handler,inputs=[mk],outputs=[dr_output])

    # Mobil hızlı eylem butonları
    hizli_hava.click( fn=lambda: "İstanbul hava durumu?",  outputs=[mk])
    hizli_borsa.click(fn=lambda: "Borsa bugün nasıl?",     outputs=[mk])
    hizli_haber.click(fn=lambda: "Son haberler neler?",    outputs=[mk])
    hizli_tarih.click(fn=lambda: "Bugün tarih ve saat kaç?", outputs=[mk])
    hizli_temiz.click(fn=yeni_sohbet, inputs=[bas,bms], outputs=[chatbot,durum]).then(lambda:[], outputs=[sg])

    def tvs():
        sl=[]
        for f in [SESSION_FILE,PROFILE_FILE,TASKS_FILE,LIFE_MAP_FILE,MEMORY_FILE,KREDI_FILE,AUTH_FILE]:
            try:
                if f.exists(): f.unlink(); sl.append(f.name)
            except OSError: pass
        for p in ["beluma_*.png","beluma_*tts_*.mp3"]:
            for t in glob.glob(str(Path(tempfile.gettempdir())/p)):
                try:
                    Path(t).unlink()
                except OSError as e:
                    _logger.warning("[tvs] geçici dosya silinemedi %s: %s", t, e)
                    _hata_say("temizlik.gecici_dosya")
        return f"✅ Silindi: {', '.join(sl) if sl else 'temiz'}."
    vsb.click(tvs,outputs=[vsd])
    hib.click(hata_istatistikleri, outputs=[hid])

    # Plugin eventleri
    pl_yenile.click(fn=plugin_yeniden_yukle, outputs=[pl_durum]).then(fn=plugin_listesi_metin, outputs=[pl_liste])
    pl_pasif_b.click(fn=plugin_pasif_yap, inputs=[pl_isim_in], outputs=[pl_yonetim_d]).then(fn=plugin_listesi_metin, outputs=[pl_liste])
    pl_aktif_b.click(fn=plugin_aktif_yap, inputs=[pl_isim_in], outputs=[pl_yonetim_d]).then(fn=plugin_listesi_metin, outputs=[pl_liste])

    # Webhook eventleri
    wh_yenile.click(fn=webhook_listesi_metin, outputs=[wh_liste])
    wh_ekle_b.click(fn=webhook_ekle, inputs=[wh_isim, wh_url, wh_olaylar, wh_secret], outputs=[wh_ekle_d]).then(fn=webhook_listesi_metin, outputs=[wh_liste])
    wh_test_b.click(fn=webhook_test_gonder, inputs=[wh_id_in], outputs=[wh_yonetim_d]).then(fn=webhook_listesi_metin, outputs=[wh_liste])
    wh_toggle_b.click(fn=webhook_toggle, inputs=[wh_id_in], outputs=[wh_yonetim_d]).then(fn=webhook_listesi_metin, outputs=[wh_liste])
    wh_sil_b.click(fn=webhook_sil, inputs=[wh_id_in], outputs=[wh_yonetim_d]).then(fn=webhook_listesi_metin, outputs=[wh_liste])

    # Hatırlatıcı eventleri
    htr_yenile.click(fn=bildirim_kuyrugu_oku,        outputs=[htr_bildirimler]).then(fn=hatirlaticilar_listesi_metin, outputs=[htr_liste])
    htr_temizle.click(fn=bildirimleri_temizle,        outputs=[htr_bildirimler])
    htr_ekle_b.click(fn=hatirlatici_ekle, inputs=[htr_mesaj, htr_zaman], outputs=[htr_ekle_d]).then(fn=hatirlaticilar_listesi_metin, outputs=[htr_liste]).then(lambda: "", outputs=[htr_mesaj]).then(lambda: "", outputs=[htr_zaman])
    htr_sil_b.click(fn=hatirlatici_sil,  inputs=[htr_sil_id],            outputs=[htr_sil_d]).then(fn=hatirlaticilar_listesi_metin,   outputs=[htr_liste])

    # Dil eventleri
    def _dil_uygula(secilen):
        mesaj, _ = dil_secici_guncelle(secilen)
        return mesaj, f"Mevcut dil: **{mevcut_dil_etiketi()}**"
    dil_kaydet_b.click(fn=_dil_uygula, inputs=[dil_secici], outputs=[dil_kaydet_d, dil_durum])

    # Ekip eventleri
    def _ekip_yenile():
        return kullanici_listesi_metin(), ortak_notlar_metin(), aktivite_logu_metin(), duyurular_metin() or "Duyuru yok."
    ekip_yenile.click(fn=_ekip_yenile, outputs=[ekip_kullanici_liste, ekip_not_liste, ekip_aktivite, ekip_duyuru_goster])

    ekip_ekle_b.click(
        fn=kullanici_ekle,
        inputs=[ekip_yeni_ad, ekip_yeni_sifre, ekip_yeni_rol, ekip_yeni_isim, ekip_yeni_email],
        outputs=[ekip_ekle_d]
    ).then(fn=kullanici_listesi_metin, outputs=[ekip_kullanici_liste])

    ekip_rol_b.click(
        fn=kullanici_rol_degistir,
        inputs=[ekip_rol_ad, ekip_yeni_rol2],
        outputs=[ekip_rol_d]
    ).then(fn=kullanici_listesi_metin, outputs=[ekip_kullanici_liste])

    ekip_sil_b.click(
        fn=kullanici_sil,
        inputs=[ekip_rol_ad],
        outputs=[ekip_rol_d]
    ).then(fn=kullanici_listesi_metin, outputs=[ekip_kullanici_liste])

    ekip_not_b.click(
        fn=ortak_not_ekle,
        inputs=[ekip_not_metin],
        outputs=[ekip_not_d]
    ).then(fn=ortak_notlar_metin, outputs=[ekip_not_liste]).then(lambda: "", outputs=[ekip_not_metin])

    ekip_duyuru_b.click(
        fn=duyuru_ekle,
        inputs=[ekip_duyuru_metin],
        outputs=[ekip_duyuru_d]
    ).then(fn=lambda: duyurular_metin() or "Duyuru yok.", outputs=[ekip_duyuru_goster]).then(lambda: "", outputs=[ekip_duyuru_metin])

    # ── Sağ panel yenile ──
    sag_yenile_b.click(fn=sag_panel_guncelle, outputs=[sag_panel_html])

    # Sohbet sonrası sağ paneli otomatik güncelle
    gb.click(sag_panel_guncelle, outputs=[sag_panel_html], show_progress="hidden")
    mk.submit(sag_panel_guncelle, outputs=[sag_panel_html], show_progress="hidden")

    # ── Sol panel → Tab yönlendirme ──
    sol_sohbet_b.click( fn=lambda: gr.Tabs(selected="sohbet"),   outputs=[ana_tabs])
    sol_gorev_b.click(  fn=lambda: gr.Tabs(selected="gorev"),    outputs=[ana_tabs])
    sol_gorsel_b.click( fn=lambda: gr.Tabs(selected="gorsel"),   outputs=[ana_tabs])
    sol_ses_b.click(    fn=lambda: gr.Tabs(selected="ses"),      outputs=[ana_tabs])
    sol_harita_b.click( fn=lambda: gr.Tabs(selected="harita"),   outputs=[ana_tabs])
    sol_analitik_b.click(fn=lambda: gr.Tabs(selected="analitik"),outputs=[ana_tabs])
    sol_plugin_b.click( fn=lambda: gr.Tabs(selected="plugin"),   outputs=[ana_tabs])
    sol_webhook_b.click(fn=lambda: gr.Tabs(selected="webhook"),  outputs=[ana_tabs])
    sol_hatir_b.click(  fn=lambda: gr.Tabs(selected="hatir"),    outputs=[ana_tabs])
    sol_dil_b.click(    fn=lambda: gr.Tabs(selected="dil"),      outputs=[ana_tabs])
    sol_ekip_b.click(   fn=lambda: gr.Tabs(selected="ekip"),     outputs=[ana_tabs])
    sol_guvenlik_b.click(fn=lambda: gr.Tabs(selected="guvenlik"),outputs=[ana_tabs])
    sol_hakkinda_b.click(fn=lambda: gr.Tabs(selected="hakkinda"),outputs=[ana_tabs])

    # ── Sol araç butonları → mesaj kutusuna yaz + sekme değiştir ──
    hizli_hava.click( fn=lambda: ("İstanbul hava durumu?",  gr.Tabs(selected="sohbet")), outputs=[mk, ana_tabs])
    hizli_borsa.click(fn=lambda: ("Borsa bugün nasıl?",     gr.Tabs(selected="sohbet")), outputs=[mk, ana_tabs])
    hizli_haber.click(fn=lambda: ("Son haberler neler?",    gr.Tabs(selected="sohbet")), outputs=[mk, ana_tabs])
    hizli_tarih.click(fn=lambda: ("Bugün tarih ve saat kaç?", gr.Tabs(selected="sohbet")), outputs=[mk, ana_tabs])
    dr_btn.click(     fn=lambda: gr.Tabs(selected="sohbet"), outputs=[ana_tabs])

# ══════════════════════════════════════════════════════════════════
# HuggingFace Spaces: auth varsa etkinleştir, yoksa direkt başlat
# Çoklu kullanıcı destekli auth
_auth_fn = gradio_auth_genisletilmis if (_load_auth() or users_yukle()["kullanicilar"]) else None

demo.launch(
    auth=_auth_fn,
    auth_message="🔐 BELUMA-I'ya Hoş Geldiniz.",
    server_name="0.0.0.0",
    server_port=7860,
    share=False,
)
