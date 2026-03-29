"""
BELUMA-I — Oturum, Profil, Görev, Yaşam Haritası, Hafıza, Analitik
"""
import hashlib
import json
import re
import threading
import time
import uuid
import datetime as _dt

import requests

from config import (
    SESSION_FILE, PROFILE_FILE, TASKS_FILE, LIFE_MAP_FILE, MEMORY_FILE,
    KREDI_FILE, ANALYTICS_FILE, GUNLUK_KREDI, MEMORY_LIMIT, CACHE_TTL,
    _IO_CACHE_TTL, PINECONE_API_KEY, PINECONE_HOST, HF_EMBED_URL, HF_TOKEN,
    _PROFIL_CACHE, _PROFIL_LOCK, MAX_DOCUMENT_CHARS, TEXT_EXTENSIONS,
    PROFILE_CACHE_TTL
)
from utils import _logger, json_yukle, json_kaydet, _THREAD_POOL, icerik_temizle, json_safe_parse

# ══════════════════════════════════════════════════════════════════
# OTURUM
# ══════════════════════════════════════════════════════════════════
def varsayilan_oturum(): return {"chat_history":[],"document_name":"","document_text":""}

def oturumu_yukle():
    v = json_yukle(SESSION_FILE, varsayilan_oturum()); p = varsayilan_oturum()
    if isinstance(v,dict): p.update(v)
    n = []
    for i in p.get("chat_history",[]):
        if isinstance(i,dict) and "role" in i:
            n.append({"role":i["role"],"content":str(i.get("content",""))})
        elif isinstance(i,(list,tuple)) and len(i)==2:
            u,a = i
            if u: n.append({"role":"user","content":str(u)})
            if a: n.append({"role":"assistant","content":str(a)})
    p["chat_history"] = n
    return p

def oturumu_kaydet(ch=None, dn="", dt="", ob=None):
    m = json_yukle(SESSION_FILE,{})
    json_kaydet(SESSION_FILE,{"chat_history":ch or [],"document_name":dn or "",
                              "document_text":dt or "",
                              "onboarding_goruldu":ob if ob is not None else m.get("onboarding_goruldu",False)})

# ══════════════════════════════════════════════════════════════════
# PROFİL
# ══════════════════════════════════════════════════════════════════
def varsayilan_profil(): return {"name":"","tone":"samimi","style":"dengeli","about":"","preferences":"","learned":[]}

def profili_yukle():
    with _PROFIL_LOCK:
        if time.time() - _PROFIL_CACHE["zaman"] < _IO_CACHE_TTL and _PROFIL_CACHE["veri"] is not None:
            return _PROFIL_CACHE["veri"]
        veri = json_yukle(PROFILE_FILE, varsayilan_profil())
        _PROFIL_CACHE.update({"veri": veri, "zaman": time.time()})
        return veri

def profili_kaydet(**kw):
    p = varsayilan_profil(); p.update({k:v for k,v in kw.items() if k in p})
    json_kaydet(PROFILE_FILE, p)
    with _PROFIL_LOCK:
        _PROFIL_CACHE.update({"veri": p, "zaman": time.time()})

def profili_otomatik_guncelle(mesaj, cevap):
    from llm import get_groq_client
    from config import AGENT_MODEL
    client = get_groq_client()
    if not client: return
    try:
        r = client.chat.completions.create(
            model=AGENT_MODEL,
            messages=[{"role":"user","content":f'Tercih çıkar. Varsa: {{"tercih":"kısa"}}\nYoksa: {{}}\nUsr: {mesaj[:300]}\nBot: {cevap[:300]}'}],
            temperature=0.0, max_tokens=80)
        v  = json_safe_parse(icerik_temizle(r.choices[0].message.content))
        t  = v.get("tercih","").strip()
        if t:
            pr = profili_yukle(); lr = pr.get("learned",[])
            if t not in lr: lr = [t]+lr
            profili_kaydet(**{**pr,"learned":lr[:20]})
    except Exception as e: _logger.warning("[oto_profil] %s",e)

# ══════════════════════════════════════════════════════════════════
# GÖREV
# ══════════════════════════════════════════════════════════════════
def gorevleri_yukle():    return json_yukle(TASKS_FILE, {"gorevler":[]})
def gorevleri_kaydet(v):  json_kaydet(TASKS_FILE, v)

def gorev_ekle(baslik, alt_gorevler=None):
    v  = gorevleri_yukle()
    y  = {"id":int(time.time()*1000),"baslik":baslik,
          "alt_gorevler":[{"metin":a,"tamamlandi":False} for a in (alt_gorevler or [])],
          "tamamlandi":False,"olusturuldu":time.strftime("%Y-%m-%d %H:%M")}
    v["gorevler"].insert(0,y); gorevleri_kaydet(v); return y

def gorev_tamamla_id(gid):
    v = gorevleri_yukle()
    for g in v["gorevler"]:
        if g["id"] == gid: g["tamamlandi"] = True
    gorevleri_kaydet(v)

def gorev_sil_id(gid):
    v = gorevleri_yukle(); v["gorevler"] = [g for g in v["gorevler"] if g["id"]!=gid]; gorevleri_kaydet(v)

_GOREV_METIN_CACHE = {"metin": None, "hash": ""}

def gorevleri_metne_cevir():
    gl = gorevleri_yukle().get("gorevler", [])
    if not gl:
        _GOREV_METIN_CACHE.update({"metin": "Henüz görev yok.", "hash": "empty"})
        return "Henüz görev yok."
    h = hashlib.md5(str([(g["id"], g["tamamlandi"]) for g in gl]).encode()).hexdigest()
    if _GOREV_METIN_CACHE["hash"] == h and _GOREV_METIN_CACHE["metin"]:
        return _GOREV_METIN_CACHE["metin"]
    s = []
    for g in gl:
        s.append(f"{'✓' if g['tamamlandi'] else '○'} [{g['id']}] {g['baslik']}  ({g['olusturuldu']})")
        for a in g.get("alt_gorevler", []): s.append(f"    {'✓' if a['tamamlandi'] else '·'} {a['metin']}")
    metin = "\n".join(s)
    _GOREV_METIN_CACHE.update({"metin": metin, "hash": h})
    return metin

def chat_gorev_isle(mesaj):
    from llm import get_groq_client
    from config import AGENT_MODEL
    client = get_groq_client()
    if not client: return "",False
    if any(k in mesaj.lower() for k in ["hava","haber","borsa","saat","tarih","nedir","kimdir","kaç","hesapla"]): return "",False
    if not any(k in mesaj.lower() for k in ["yapacak","lazım","planla","hatırlat","görev","hedef","hafta","bugün","yarın"]): return "",False
    try:
        r = client.chat.completions.create(
            model=AGENT_MODEL,
            messages=[{"role":"user","content":f'Görev varsa: {{"baslik":"...","alt_gorevler":["..."]}}\nYoksa: {{}}\nMesaj: "{mesaj}"'}],
            temperature=0.0, max_tokens=200)
        v = json_safe_parse(icerik_temizle(r.choices[0].message.content))
        if v.get("baslik"):
            y = gorev_ekle(v["baslik"],v.get("alt_gorevler",[]))
            b = f"\n\n📌 Görev eklendi: **{y['baslik']}**"
            if y["alt_gorevler"]: b+="\n"+"".join(f"  · {a['metin']}\n" for a in y["alt_gorevler"])
            return b,True
    except Exception as e: _logger.warning("[gorev_isle] %s",e)
    return "",False

# ══════════════════════════════════════════════════════════════════
# YAŞAM HARİTASI
# ══════════════════════════════════════════════════════════════════
_cache_lock = threading.Lock()
_lm_cache   = {"veri": None, "zaman": 0.0}

def varsayilan_harita():
    return {"hedefler":[],"gunluk_notlar":[],"aliskanliklar":[],"is_modeli":"","uzun_vadeli_plan":"","karar_tarzi":"","istatistik":{}}

def haritayi_yukle():
    with _cache_lock:
        if time.time() - _lm_cache["zaman"] < CACHE_TTL and _lm_cache["veri"] is not None:
            return _lm_cache["veri"]
        veri = json_yukle(LIFE_MAP_FILE, varsayilan_harita())
        _lm_cache.update({"veri": veri, "zaman": time.time()})
        return veri

def haritayi_kaydet(veri):
    json_kaydet(LIFE_MAP_FILE, veri)
    with _cache_lock:
        _lm_cache.update({"veri": veri, "zaman": time.time()})

def hedef_ekle(hedef_metni, oncelik=2):
    data = haritayi_yukle()
    data["hedefler"].append({"id": uuid.uuid4().hex[:8], "hedef": hedef_metni.strip(),
                              "tarih": time.strftime("%Y-%m-%d %H:%M"), "tamamlandi": False, "oncelik": oncelik})
    haritayi_kaydet(data)

def hedef_tamamla(hedef_ref):
    data = haritayi_yukle(); ref = hedef_ref.strip()
    for h in data["hedefler"]:
        if h.get("id") == ref or ref.lower() in h["hedef"].lower():
            h["tamamlandi"] = True; break
    haritayi_kaydet(data)

def gunluk_not_ekle(not_metni, kategori="genel"):
    data = haritayi_yukle()
    data["gunluk_notlar"].append({"not": not_metni.strip(), "tarih": time.strftime("%Y-%m-%d %H:%M"), "kategori": kategori})
    data["gunluk_notlar"] = data["gunluk_notlar"][-100:]
    haritayi_kaydet(data)

def aliskanlik_guncelle(aliskanlik):
    data = haritayi_yukle(); bugun = time.strftime("%Y-%m-%d")
    for a in data["aliskanliklar"]:
        if a["aliskanlik"].lower() == aliskanlik.lower():
            if a.get("son_guncelleme","") != bugun:
                a["seri"] = a.get("seri",0) + 1; a["son_guncelleme"] = bugun
            haritayi_kaydet(data); return
    data["aliskanliklar"].append({"aliskanlik": aliskanlik.strip(), "seri": 1, "son_guncelleme": bugun})
    haritayi_kaydet(data)

def life_map_ozeti():
    data = haritayi_yukle()
    h = data.get("hedefler",[]); t, tm = len(h), sum(1 for x in h if x.get("tamamlandi"))
    bk = [x["hedef"] for x in h if not x.get("tamamlandi")][:3]
    al = data.get("aliskanliklar",[])
    s  = []
    if t:  s.append(f"Hedef: {tm}/{t} tamamlandı")
    if bk: s.append("Bekleyen: " + ", ".join(bk))
    if al: s.append("Alışkanlıklar: " + ", ".join(f"{a['aliskanlik']}({a['seri']}g)" for a in al[:3]))
    return " | ".join(s) if s else ""

# ══════════════════════════════════════════════════════════════════
# KREDİ
# ══════════════════════════════════════════════════════════════════
def kredi_yukle():  return json_yukle(KREDI_FILE, {"kredi": GUNLUK_KREDI, "tarih": "", "toplam_uretim": 0, "son_gorsel": ""})
def kredi_kaydet(v): json_kaydet(KREDI_FILE, v)

def kredi_kontrol():
    v = kredi_yukle(); b = time.strftime("%Y-%m-%d")
    if v.get("tarih") != b: v["kredi"] = GUNLUK_KREDI; v["tarih"] = b; kredi_kaydet(v)
    k = v.get("kredi", GUNLUK_KREDI)
    return (0, "⏳ Günlük görsel kredin bitti.") if k <= 0 else (k, f"🎨 Kalan: **{k}/{GUNLUK_KREDI}**")

def kredi_kullan():
    v = kredi_yukle(); b = time.strftime("%Y-%m-%d")
    if v.get("tarih") != b: v["kredi"] = GUNLUK_KREDI; v["tarih"] = b
    k = v.get("kredi", GUNLUK_KREDI)
    if k <= 0: return False, "⏳ Günlük kredin bitti."
    v["kredi"] = k - 1; v["toplam_uretim"] = v.get("toplam_uretim",0) + 1; kredi_kaydet(v)
    return True, f"✅ Kalan: {v['kredi']} kredi"

def son_gorsel_kaydet(yol):
    v = kredi_yukle(); v["son_gorsel"] = yol; kredi_kaydet(v)

# ══════════════════════════════════════════════════════════════════
# HAFIZA
# ══════════════════════════════════════════════════════════════════
def _metin_vektore_cevir(metin):
    import os
    token = os.environ.get("HF_TOKEN") or HF_TOKEN
    if not token: return None
    try:
        r = requests.post(HF_EMBED_URL,
                          headers={"Authorization": f"Bearer {token}"},
                          json={"inputs": metin[:512]}, timeout=10)
        if r.status_code == 200:
            v = r.json()
            return v[0] if isinstance(v,list) and v and isinstance(v[0],list) else v
    except requests.RequestException as e:
        _logger.warning("[embed] %s", e)
    return None

def _pinecone_hazir(): return bool(PINECONE_API_KEY and PINECONE_HOST)

def bulut_hafiza_ekle(metin, kategori="genel"):
    if not _pinecone_hazir(): _json_hafiza_ekle(metin); return
    vektor = _metin_vektore_cevir(metin)
    if not vektor: _json_hafiza_ekle(metin); return
    try:
        r = requests.post(f"{PINECONE_HOST}/vectors/upsert",
                          headers={"Api-Key": PINECONE_API_KEY, "Content-Type": "application/json"},
                          json={"vectors":[{"id":uuid.uuid4().hex,"values":vektor,"metadata":{"metin":metin[:500],"kategori":kategori}}]},
                          timeout=10)
        if r.status_code not in (200, 201): _json_hafiza_ekle(metin)
    except requests.RequestException as e:
        _logger.warning("[bulut_ekle] %s", e); _json_hafiza_ekle(metin)

def bulut_hafiza_ara(sorgu, n=3):
    if not _pinecone_hazir(): return _json_hafiza_ara(sorgu, n)
    vektor = _metin_vektore_cevir(sorgu)
    if not vektor: return _json_hafiza_ara(sorgu, n)
    try:
        r = requests.post(f"{PINECONE_HOST}/query",
                          headers={"Api-Key": PINECONE_API_KEY, "Content-Type": "application/json"},
                          json={"vector":vektor,"topK":n,"includeMetadata":True}, timeout=10)
        if r.status_code == 200:
            return "\n".join(m["metadata"].get("metin","") for m in r.json().get("matches",[]) if m.get("metadata"))
    except (requests.RequestException, KeyError) as e:
        _logger.warning("[bulut_ara] %s", e)
    return _json_hafiza_ara(sorgu, n)

def _json_hafiza_ekle(metin):
    l = json_yukle(MEMORY_FILE, [])
    if metin and metin not in l: l.append(metin)
    json_kaydet(MEMORY_FILE, l[-MEMORY_LIMIT:])

def _json_hafiza_ara(sorgu, n=3):
    l = json_yukle(MEMORY_FILE, [])
    if not l: return ""
    kw = [k for k in sorgu.lower().split() if len(k) > 3]
    if not kw: return ""
    sk = sorted([(sum(1 for k in kw if k in r.lower()), r) for r in l], reverse=True)
    return "\n".join(r for s, r in sk[:n] if s > 0)

def memory_ekle(metin): _THREAD_POOL.submit(bulut_hafiza_ekle, metin)
def memory_ara(sorgu, n=3):
    return bulut_hafiza_ara(sorgu, min(n,2)) if len(sorgu.strip()) >= 15 else ""

# ══════════════════════════════════════════════════════════════════
# BELGE OKUMA
# ══════════════════════════════════════════════════════════════════
def _chunk_text(text, chunk_size=1800, overlap=250):
    if not text: return []
    parts, step = [], max(1, chunk_size-overlap)
    for i in range(0, len(text), step):
        piece = text[i:i+chunk_size]
        if piece.strip(): parts.append(piece)
    return parts

def _select_relevant_chunks(query, chunks, top_k=4):
    if not chunks: return []
    keywords = [k for k in re.split(r"\W+",query.lower()) if len(k)>=4]
    if not keywords: return chunks[:top_k]
    scored = [(sum(chunk.lower().count(k) for k in keywords),chunk) for chunk in chunks]
    scored.sort(key=lambda x:x[0],reverse=True)
    selected = [c for s,c in scored[:top_k] if s>0]
    return selected or chunks[:2]

def gelismis_rag_ara(sorgu, uzun_metin, chunk_size=1800, overlap=250, top_k=4):
    if not uzun_metin: return ""
    uzun_metin = uzun_metin[:MAX_DOCUMENT_CHARS]
    if len(uzun_metin) <= chunk_size: return uzun_metin
    parcalar = _chunk_text(uzun_metin,chunk_size=chunk_size,overlap=overlap)
    en_iyi   = _select_relevant_chunks(sorgu,parcalar,top_k=top_k)
    return "\n\n...[İlgili belge kesiti]...\n\n".join(en_iyi)

def belge_metnini_oku(file_obj, max_chars=0):
    from pathlib import Path
    from utils import _hata_say
    if max_chars==0: max_chars=MAX_DOCUMENT_CHARS
    if not file_obj: return "",""
    path = Path(getattr(file_obj,"name","") or str(file_obj))
    if not path.exists(): return "",""
    ext = path.suffix.lower()
    try:
        if ext in TEXT_EXTENSIONS: text = path.read_text(encoding="utf-8",errors="ignore")
        elif ext==".pdf":
            try:
                import pypdf
                text="\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(path)).pages)
            except ImportError:
                _hata_say("belge.pypdf_eksik")
                return path.name, "Kütüphane eksik: pypdf."
        elif ext==".docx":
            try:
                import docx
                text="\n".join(p.text for p in docx.Document(str(path)).paragraphs)
            except ImportError:
                _hata_say("belge.docx_eksik")
                return path.name, "Kütüphane eksik: python-docx."
        elif ext in (".xlsx",".xls"):
            try:
                import openpyxl
                wb=openpyxl.load_workbook(str(path),read_only=True,data_only=True)
                rows=[]
                for ws in wb.worksheets:
                    for row in ws.iter_rows(values_only=True):
                        rows.append("\t".join(str(c) if c is not None else "" for c in row))
                text="\n".join(rows)
            except ImportError:
                _hata_say("belge.openpyxl_eksik")
                return path.name, "Kütüphane eksik: openpyxl."
        else:
            return path.name, f"{path.suffix} desteklenmiyor."
    except OSError as e:
        _logger.warning("[belge/os] %s", e); return path.name, f"Dosya okunamadı: {e}"
    except Exception as e:
        _logger.error("[belge/genel] %s", e); return path.name, "Beklenmeyen okuma hatası."
    text = text.strip()
    if not text: return path.name,"Dosya boş."
    if len(text)>max_chars: text=text[:max_chars].rsplit(" ",1)[0]+"\n\n[Kısaltıldı]"
    return path.name, text

# ══════════════════════════════════════════════════════════════════
# ANALİTİK
# ══════════════════════════════════════════════════════════════════
_ANALYTICS_LOCK = threading.Lock()

def _varsayilan_analytics():
    return {"mesajlar":[],"model_sayac":{},"arac_sayac":{},"hata_sayac":{},"gunluk":{},"oturum_baslama":time.strftime("%Y-%m-%d %H:%M:%S")}

def analytics_yukle():
    return json_yukle(ANALYTICS_FILE, _varsayilan_analytics())

def analytics_kaydet(v):
    with _ANALYTICS_LOCK:
        try:
            tmp = ANALYTICS_FILE.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(v, f, ensure_ascii=False, indent=2)
            tmp.replace(ANALYTICS_FILE)
        except (OSError, TypeError) as e:
            _logger.error("[analytics] yazma hatasi: %s", e)

def analitik_kaydet(model="", arac="", sure_ms=0.0, hata="", token_est=0):
    def _yaz():
        v = analytics_yukle(); bugun = time.strftime("%Y-%m-%d"); saat = time.strftime("%H:%M")
        v["mesajlar"].append({"tarih": f"{bugun} {saat}","model":model,"sure_ms":round(sure_ms,1),"arac":arac,"hata":hata})
        v["mesajlar"] = v["mesajlar"][-500:]
        if model: v["model_sayac"][model] = v["model_sayac"].get(model,0)+1
        if arac:  v["arac_sayac"][arac]   = v["arac_sayac"].get(arac,0)+1
        if hata:  v["hata_sayac"][hata]   = v["hata_sayac"].get(hata,0)+1
        g = v["gunluk"].setdefault(bugun,{"mesaj":0,"token_est":0,"hata":0})
        g["mesaj"]+=1; g["token_est"]+=token_est
        if hata: g["hata"]+=1
        analytics_kaydet(v)
    _THREAD_POOL.submit(_yaz)

def duygu_analizi(mesaj):
    k = mesaj.lower()
    if any(s in k for s in ["bunaldım","yoruldum","sıkıldım","zor","berbat","çaresiz","endişe"]): return {"durum":"stresli","ton":"yumuşat ve kısa tut"}
    if any(s in k for s in ["harika","süper","mutlu","başardım","mükemmel"]):                      return {"durum":"mutlu","ton":"enerjik ve destekleyici ol"}
    if any(s in k for s in ["neden","nasıl","nedir","anlat","açıkla"]):                            return {"durum":"meraklı","ton":"detaylı ve açıklayıcı ol"}
    return {"durum":"nötr","ton":"dengeli kal"}

def gunluk_oneri():
    s = _dt.datetime.now().hour
    if  6 <= s < 12: return "☀️ Günaydın! Bugün için 3 hedef belirle?"
    if 12 <= s < 18: return "🌤 Günün ortası — ilerleme nasıl?"
    if 18 <= s < 22: return "🌙 Akşam oldu. Bugünü değerlendirelim?"
    return ""

def proaktif_kontrol(ctx=""):
    d = haritayi_yukle(); h=d.get("hedefler",[]); bk=[x for x in h if not x.get("tamamlandi")]; tm=[x for x in h if x.get("tamamlandi")]
    if len(bk)>5:
        yk=[x["hedef"] for x in bk if x.get("oncelik",2)==3]
        if yk: return f"⚠️ **Odak:** {len(bk)} bekleyen. Öncelikli: _{yk[0]}_"
    if not bk and tm: return "🔥 **Tebrikler!** Tüm hedefler tamam. Yeni koy!"
    if not h and any(k in ctx.lower() for k in ["plan","hedef","strateji"]): return "💡 Henüz hedef yok. Yaşam Haritası'ndan ekle."
    bg=time.strftime("%Y-%m-%d")
    for a in d.get("aliskanliklar",[]):
        if a.get("son_guncelleme","") and a["son_guncelleme"]<bg and a.get("seri",0)>2:
            return f"🔔 _{a['aliskanlik']}_ serisi ({a['seri']}g) kırılmak üzere!"
    return ""
