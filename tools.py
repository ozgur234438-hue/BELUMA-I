"""
BELUMA-I — Araç Sistemi
Hesap, hava, borsa, haber, döviz, web arama ve niyet tespiti.
"""
import operator
import ast
import re
import threading
import time
import xml.etree.ElementTree as ET
from typing import Dict, Tuple

import requests

from config import SABIT_KUR, WEB_TIMEOUT
from utils import _logger, _hata_say

# ══════════════════════════════════════════════════════════════════
# ARAÇ ANAHTAR KELİMELERİ
# ══════════════════════════════════════════════════════════════════
TOOL_KW = {
    "calc":    ["hesapla","hesaplat","kaç eder","topla","çarp","böl","çıkar"],
    "date":    ["bugün ne","tarih","saat kaç","gün ne"],
    "convert": ["kaç tl","kaç dolar","kaç euro","döviz","kur","usd","eur","gbp","try"],
    "weather": ["hava durumu","hava nasıl","bugün hava","yağmur","sıcaklık","derece"],
    "news":    ["son haberler","gündem","haberler","neler oluyor"],
    "bist":    ["borsa","bist","hisse","endeks","xu100"],
    "search":  ["internette ara","web'de ara","arama yap","kim kazandı","sonucu ne",
                "ne oldu","son durum","google"]
}
_SEHIRLER = ("istanbul","ankara","izmir","bursa","antalya","malatya","konya","adana",
             "gaziantep","samsun","eskişehir","kayseri","trabzon","diyarbakır","mersin")
_PARA_MAP = {"dolar":"USD","usd":"USD","euro":"EUR","eur":"EUR","sterlin":"GBP",
             "gbp":"GBP","tl":"TRY","try":"TRY","lira":"TRY"}

_GUNCEL_KALIPLARI    = ["bugün","dün","yarın","son ","güncel","hava durumu","hava nasıl",
                        "haber","borsa","bist","maç","skor","son durum","bu hafta","bu ay",
                        "şu an","döviz","kur "]
_HESAP_KALIPLARI     = ["hesapla","topla","çarp","böl","çıkar","kaç eder"]
_ARASTIRMA_KALIPLARI = ["derin araştır","deep research","kapsamlı araştır","detaylı araştır"]

# ══════════════════════════════════════════════════════════════════
# GÜVENLİ HESAP
# ══════════════════════════════════════════════════════════════════
_SAFE_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg
}

class UnsafeExpressionError(ValueError):
    pass

def safe_eval(expr):
    def _eval(node):
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                raise UnsafeExpressionError(f"Desteklenmeyen: {node.value}")
            return node.value
        if isinstance(node, ast.BinOp):
            op = _SAFE_OPS.get(type(node.op))
            if not op: raise UnsafeExpressionError(f"Desteklenmeyen op: {type(node.op).__name__}")
            l, r = _eval(node.left), _eval(node.right)
            if isinstance(node.op, ast.Div) and r == 0: raise ZeroDivisionError
            return op(l, r)
        if isinstance(node, ast.UnaryOp):
            op = _SAFE_OPS.get(type(node.op))
            if not op: raise UnsafeExpressionError
            return op(_eval(node.operand))
        raise UnsafeExpressionError(f"Desteklenmeyen: {type(node).__name__}")
    return _eval(ast.parse(expr, mode="eval").body)

# ══════════════════════════════════════════════════════════════════
# DDG CACHE'Lİ ARAMA
# ══════════════════════════════════════════════════════════════════
_DDG_CACHE: Dict[str, Tuple[float, list]] = {}
_DDG_CACHE_TTL = 300
_ddg_cache_lock = threading.Lock()

def _ddg_sonuclari_al(sorgu, n=4):
    anahtar = f"{sorgu.lower().strip()}:{n}"
    with _ddg_cache_lock:
        if anahtar in _DDG_CACHE:
            ts, sonuclar = _DDG_CACHE[anahtar]
            if time.time() - ts < _DDG_CACHE_TTL:
                return sonuclar
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            sonuclar = [
                {"title": str(r.get("title",""))[:200],
                 "body":  str(r.get("body",""))[:400],
                 "url":   str(r.get("href",""))[:700]}
                for r in list(ddgs.text(sorgu, region="tr-tr", max_results=n))[:n]
            ]
    except Exception as e:
        _logger.warning("[ddg] %s", e)
        sonuclar = []
    with _ddg_cache_lock:
        _DDG_CACHE[anahtar] = (time.time(), sonuclar)
        if len(_DDG_CACHE) > 200:
            eskiler = sorted(_DDG_CACHE.items(), key=lambda x: x[1][0])[:50]
            for k, _ in eskiler:
                del _DDG_CACHE[k]
    return sonuclar

def arama_yap(sorgu, max_results=5):
    return _ddg_sonuclari_al(sorgu, n=max_results)

def kaynak_kartlari_olustur(sonuclar):
    if not sonuclar: return ""
    lines = [f"[{i}] {r.get('title','')}: {r.get('body','')[:200]}" for i,r in enumerate(sonuclar[:5],start=1)]
    return "\n".join(lines)

# ══════════════════════════════════════════════════════════════════
# NİYET TESPİTİ
# ══════════════════════════════════════════════════════════════════
def guncel_bilgi_gerekli_mi(mesaj):
    k = mesaj.lower()
    return any(x in k for x in _GUNCEL_KALIPLARI)

def cevap_turu_belirle(mesaj, belge_var=False, resim_var=False):
    k = mesaj.lower()
    if any(x in k for x in _ARASTIRMA_KALIPLARI): return "deep_research"
    if any(x in k for x in _HESAP_KALIPLARI) or re.search(r"\d+\s*[+\-*/]\s*\d+", mesaj): return "tool_calc"
    if any(x in k for x in ["tarih","saat kaç","gün ne","bugün ne"]): return "tool_date"
    if any(x in k for x in ["kaç tl","kaç dolar","kaç euro","döviz","kur"]): return "tool_convert"
    if any(x in k for x in ["hava durumu","hava nasıl","sıcaklık","derece"]): return "tool_weather"
    if any(x in k for x in ["son haberler","gündem","haberler","neler oluyor"]): return "tool_news"
    if any(x in k for x in ["borsa","bist","hisse","endeks","xu100"]): return "tool_bist"
    if belge_var: return "document_qa"
    if guncel_bilgi_gerekli_mi(mesaj): return "tool_search"
    if any(x in k for x in ["internette ara","web'de ara","arama yap"]): return "tool_search"
    return "direct_llm"

# ══════════════════════════════════════════════════════════════════
# ARAÇ ÇALIŞTIRICI
# ══════════════════════════════════════════════════════════════════
def run_tool(tool, mesaj):
    from llm import _turkce_tarih, _numarali_listeyi_duzelt, _TR_AYLAR

    if tool == "calc":
        t = re.sub(r"(?i)hesapla[t]?|kaç eder|topla|çarp|böl|çıkar|sonucu nedir|ne eder","",mesaj)
        t = re.sub(r"[^0-9+\-*/().\s]","",t).strip()
        t = re.sub(r"\s+"," ",t).strip()
        if not t: return None
        t = re.sub(r"([+\-*/])\s*[+\-*/]+",r"\1",t)
        try:
            s = safe_eval(t)
            if isinstance(s,float) and s.is_integer(): s=int(s)
            return f"🧮 **{t.strip()} = {s}**"
        except ZeroDivisionError: return "⚠️ Sıfıra bölme hatası."
        except (UnsafeExpressionError,SyntaxError): return None

    if tool == "date": return _turkce_tarih()

    if tool == "weather":
        m = re.search("|".join(_SEHIRLER), mesaj.lower())
        if not m: return "🌤 Hangi şehir için?"
        s = m.group(0).capitalize()
        try:
            r = requests.get(f"https://wttr.in/{s}?format=%C+%t+Nem:+%h+Rüzgar:+%w&lang=tr",
                             timeout=5, headers={"User-Agent":"BELUMA-I/1.0"})
            if r.status_code==200 and r.text.strip(): return f"🌤 **{s}:** {r.text.strip()}"
        except requests.RequestException as e:
            _logger.warning("[weather] %s",e); _hata_say("arac.weather")
        return f"🌤 Alınamadı. [wttr.in/{s}](https://wttr.in/{s})"

    if tool == "news":
        try:
            r = requests.get("https://feeds.bbci.co.uk/turkce/rss.xml",timeout=6,headers={"User-Agent":"BELUMA-I/1.0"})
            if r.status_code==200:
                root = ET.fromstring(r.content)
                bl = [i.find("title").text for i in root.findall(".//item")[:5] if i.find("title") is not None]
                if bl: return "📰 **Son haberler:**\n"+"".join(f"• {b}\n" for b in bl)
        except (requests.RequestException,ET.ParseError) as e:
            _logger.warning("[news] %s",e); _hata_say("arac.news")
        return "📰 Haberler alınamadı."

    if tool == "bist":
        try:
            r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/XU100.IS?interval=1d&range=1d",
                             timeout=6,headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code==200:
                meta = r.json()["chart"]["result"][0]["meta"]
                f2,o = meta.get("regularMarketPrice",0), meta.get("previousClose",0)
                d = ((f2-o)/o*100) if o else 0
                return f"{'📈' if d>=0 else '📉'} **BIST 100:** {f2:,.0f} ({d:+.2f}%)"
        except (requests.RequestException,KeyError,TypeError) as e:
            _logger.warning("[bist] %s",e); _hata_say("arac.bist")
        return "📉 Borsa alınamadı."

    if tool == "convert":
        m  = re.search(r"(\d+\.?\d*)\s*(usd|eur|gbp|tl|try|dolar|euro|sterlin|lira)",mesaj.lower())
        hm = re.search(r"(?:kaç|to)\s*(usd|eur|gbp|tl|try|dolar|euro|sterlin|lira)",mesaj.lower())
        if not m: return None
        miktar,fc = float(m.group(1)), _PARA_MAP.get(m.group(2),"USD")
        tc = _PARA_MAP.get((hm.group(1) if hm else "try"),"TRY")
        try:
            r   = requests.get(f"https://api.exchangerate-api.com/v4/latest/{fc}",timeout=5)
            kur = r.json()["rates"].get(tc,SABIT_KUR.get(tc,1)) if r.status_code==200 else SABIT_KUR.get(tc,1)/SABIT_KUR.get(fc,1)
        except (requests.RequestException,KeyError,ValueError,ZeroDivisionError) as e:
            _logger.warning("[convert] %s", e)
            kur = SABIT_KUR.get(tc,1)/SABIT_KUR.get(fc,1)
        return f"💱 **{miktar} {fc} = {miktar*kur:.2f} {tc}** (yaklaşık)"

    if tool == "search":
        temiz = re.sub(r"(?i)internette ara|web'de ara|arama yap|bul|bana|google","",mesaj).strip()
        if not temiz: temiz = mesaj
        sonuclar = _ddg_sonuclari_al(temiz, n=5)
        return {"query": temiz, "results": sonuclar}

    return None

def final_cevap_temizle(metin):
    from llm import _TR_AYLAR, _numarali_listeyi_duzelt
    if not metin: return ""
    metin = str(metin).strip()
    for en, tr in _TR_AYLAR.items():
        metin = metin.replace(en,tr).replace(en.lower(),tr.lower())
    metin = _numarali_listeyi_duzelt(metin)
    metin = re.sub(r"\n{3,}","\n\n",metin).strip()
    return metin
