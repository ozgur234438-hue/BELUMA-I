"""
BELUMA-I — LLM Modülleri
Groq, Gemini, DeepSeek, OpenAI, Anthropic client'ları,
multi-agent sistemi ve Türkçe garantisi.
"""
import datetime as _dt
import re
import time
import warnings as _warnings

_warnings.filterwarnings("ignore", category=FutureWarning, module="google")

try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    import openai as _openai_mod
except ImportError:
    _openai_mod = None

try:
    import anthropic as _anthropic_mod
except ImportError:
    _anthropic_mod = None

try:
    from gradio_client import Client as _GradioClient
except ImportError:
    _GradioClient = None

from config import (
    API_KEY, AGENT_MODEL, MODEL_NAME, VISION_MODEL, FALLBACK_MODELLER,
    GEMINI_API_KEY, DEEPSEEK_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY,
    RISK_KEYWORDS, FLAGS, UZMANLIK_MODLARI
)
from utils import _logger, icerik_temizle, metni_temizle

# Zihinsel modeller burada import için
try:
    from config import UZMANLIK_MODLARI
except ImportError:
    UZMANLIK_MODLARI = {}

MENTAL_MODELS = {
    "pareto":           "Pareto İlkesi (%80/20): Bu konudaki %20'lik çaba, %80 sonucu nasıl getirir?",
    "first_principles": "İlk İlkeler: Konuyu en temel doğrularına indirgersek ne görürüz?",
    "swot":             "SWOT: Bu durumun güçlü/zayıf yanları, fırsatları ve tehditleri neler?",
    "eisenhower":       "Eisenhower Matrisi: Bu iş acil mi, önemli mi, yoksa ikisi de mi?",
    "inversion":        "Ters Çevirme: 'Nasıl başarırım?' yerine 'Nasıl kesinlikle başarısız olurum?' diye sor.",
    "second_order":     "İkinci Derece Düşünce: Bu kararın dolaylı ve uzun vadeli sonuçları ne olur?",
    "occam":            "Occam'ın Usturası: En az varsayım gerektiren açıklama genellikle doğrudur.",
    "parkinson":        "Parkinson Yasası: İş, kendine ayrılan süreyi doldurur.",
    "circle_of_control":"Kontrol Çemberi: Bunun üzerinde gerçekten kontrol sahibi misin?",
    "regret_min":       "Pişmanlık Minimizasyonu (Bezos): 80 yaşında hangi kararı vermemiş olmaktan pişmanlık duyarsın?"
}

_MODEL_TRIGGERS = [
    (["karar","seçim","hangisi","ne yapmalı","tercih"],                         "eisenhower"),
    (["plan","strateji","iş","proje","büyüme"],                                 "pareto"),
    (["anlamadım","karmaşık","neden","nasıl çalışır","temel"],                  "first_principles"),
    (["risk","tehlike","yanlış giderse","başarısız"],                           "inversion"),
    (["sonuç","etki","ileride","gelecek","uzun vade"],                          "second_order"),
    (["karmaşık","çok fazla","boğuldum","nereden başla"],                       "occam"),
    (["vakit","süre","zaman","yetişemiyorum"],                                  "parkinson"),
    (["yapamıyorum","elimde değil","kontrol"],                                  "circle_of_control"),
    (["pişman","hayatımın kararı","önemli karar"],                              "regret_min"),
    (["güçlü","zayıf","fırsat","tehdit","swot","analiz et"],                    "swot"),
]

# ══════════════════════════════════════════════════════════════════
# GROQ CLIENT (lazy singleton)
# ══════════════════════════════════════════════════════════════════
_client      = None
_client_init = False

def get_groq_client():
    global _client, _client_init
    if _client_init: return _client
    _client_init = True
    if API_KEY and Groq:
        _client = Groq(api_key=API_KEY)
    return _client

# ══════════════════════════════════════════════════════════════════
# ÇOKLU MODEL CLIENT'LARI
# ══════════════════════════════════════════════════════════════════
def get_gemini_client(model_name="gemini-1.5-pro"):
    if not GEMINI_API_KEY or genai is None: return None
    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel(model_name)

def get_deepseek_client():
    if not DEEPSEEK_API_KEY or _openai_mod is None: return None
    return _openai_mod.OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")

def get_openai_client():
    if not OPENAI_API_KEY or _openai_mod is None: return None
    return _openai_mod.OpenAI(api_key=OPENAI_API_KEY)

def get_anthropic_client():
    if not ANTHROPIC_API_KEY or _anthropic_mod is None: return None
    return _anthropic_mod.Anthropic(api_key=ANTHROPIC_API_KEY)

# ══════════════════════════════════════════════════════════════════
# MULTI-AGENT
# ══════════════════════════════════════════════════════════════════
def _agent_cagir(prompt, max_tokens=400):
    client = get_groq_client()
    if not client: return ""
    try:
        r = client.chat.completions.create(
            model=AGENT_MODEL,
            messages=[{"role":"user","content":prompt}],
            temperature=0.3, max_tokens=max_tokens)
        return icerik_temizle(r.choices[0].message.content)
    except Exception as e:
        _logger.warning("[agent] %s", e); return ""

def planner_agent(mesaj): return _agent_cagir(f"Bu isteği Türkçe kısa adım adım planla (max 4 adım):\n{mesaj}")
def critic_agent(cevap):  return _agent_cagir(f"Bu cevabı denetle. Hata varsa 'SORUN: [açıkla]' yaz. Yoksa 'TAMAM'.\nCevap: {cevap}", 150)

def _riskli_istek_mi(metin):
    return any(k in (metin or "").lower() for k in RISK_KEYWORDS)

def anayasal_denetim(cevap, kullanici_mesaji=""):
    if not FLAGS.constitutional_guard: return ""
    if not _riskli_istek_mi(kullanici_mesaji) and not _riskli_istek_mi(cevap): return ""
    if len(cevap) < 80: return ""
    prompt = (
        "Yanıtı güvenlik açısından değerlendir.\n"
        "Kontrol: 1) Zararlı/yasa dışı yönlendirme 2) Tehlikeli uydurma bilgi 3) Aşırı kesinlik\n"
        "Güvenliyse sadece: GUVENLI. Risk varsa kısa uyarı yaz.\n\n"
        f"Yanıt:\n{cevap[:1800]}"
    )
    denetim = _agent_cagir(prompt, 120)
    if denetim and "GÜVENLİ" not in denetim.upper()[:30] and "GUVENLI" not in denetim.upper()[:30]:
        return "\n\n🛡️ Güvenlik notu: Bu yanıtın bazı bölümleri güvenlik açısından sınırlandırıldı."
    return ""

# ══════════════════════════════════════════════════════════════════
# TÜRKÇE GARANTİSİ
# ══════════════════════════════════════════════════════════════════
_TR_CHARS = set("çğıİöşüÇĞİÖŞÜ")
_TR_HINTS = (" ve "," için "," değil "," ama "," çünkü "," olarak "," şu "," bu ",
             " ben "," sen "," siz "," biz ")
_TR_AYLAR = {"January":"Ocak","February":"Şubat","March":"Mart","April":"Nisan",
             "May":"Mayıs","June":"Haziran","July":"Temmuz","August":"Ağustos",
             "September":"Eylül","October":"Ekim","November":"Kasım","December":"Aralık"}

def _turkce_tarih():
    now   = _dt.datetime.now()
    ay_tr = _TR_AYLAR.get(now.strftime("%B"), now.strftime("%B"))
    return f"📅 Bugün **{now.strftime('%d')} {ay_tr} {now.strftime('%Y')}**, saat **{now.strftime('%H:%M')}**."

def _turkce_gibi_mi(text):
    t = (text or "").strip()
    if not t: return True
    if any(ch in _TR_CHARS for ch in t): return True
    low = t.lower()
    return any(w in low for w in _TR_HINTS)

def _numarali_listeyi_duzelt(text):
    return re.sub(r"^\s*\d+[\.\)]\s+", "- ", text, flags=re.MULTILINE)

def _hata_turkce(provider, err):
    e = str(err)[:200]
    if "timeout"    in e.lower() or "timed out"  in e.lower(): return f"⚠️ {provider} bağlantısı zaman aşımına uğradı. Tekrar deneyin."
    if "rate_limit" in e.lower() or "429"         in e.lower(): return f"⏳ {provider} istek limiti aşıldı. Biraz bekleyip tekrar deneyin."
    if "api_key"    in e.lower() or "auth"        in e.lower(): return f"🔑 {provider} için geçerli bir anahtar gerekli."
    if "connection" in e.lower() or "network"     in e.lower(): return f"⚠️ {provider} bağlantı hatası. İnternet bağlantınızı kontrol edin."
    return f"⚠️ {provider} beklenmeyen hata: lütfen tekrar deneyin."

def enforce_turkish_output(text, max_chars=2200):
    t = (text or "").strip()
    if not t: return ""
    t = _numarali_listeyi_duzelt(t)
    for en, tr in _TR_AYLAR.items():
        t = t.replace(en, tr).replace(en.lower(), tr.lower())
    if _turkce_gibi_mi(t):
        return t[:max_chars]
    rewritten = _agent_cagir(
        f"Aşağıdaki metni TAMAMEN Türkçeye çevir. Yabancı kelime kullanma. Kısa ve net yaz.\n\nMETİN:\n{t[:3500]}",
        600)
    rewritten = metni_temizle(rewritten or "")
    if rewritten:
        rewritten = _numarali_listeyi_duzelt(rewritten)
    return (rewritten or t)[:max_chars]

# ══════════════════════════════════════════════════════════════════
# ZİHİNSEL MODELLER
# ══════════════════════════════════════════════════════════════════
def zihinsel_model_oner(mesaj):
    kucuk = mesaj.lower()
    for kws, key in _MODEL_TRIGGERS:
        if any(k in kucuk for k in kws):
            return f"\n\n💡 **Düşünme önerisi:** {MENTAL_MODELS[key]}"
    return ""

def derin_dusunce_katmani(mesaj, profil):
    if not get_groq_client(): return ""
    return _agent_cagir(
        f"Profil: isim={profil.get('name','')}, ton={profil.get('tone','samimi')}, "
        f"hakkında={profil.get('about','')[:100]}\nMesaj: {mesaj[:300]}\n\n"
        f"Bu kişiye en etkili yaklaşım? 2 cümle strateji.", 120)

def dinamik_profil_ozeti(profil):
    if not get_groq_client(): return ""
    ozet = (f"İsim: {profil.get('name','')}\nHakkında: {profil.get('about','')}\n"
            f"Tercihler: {profil.get('preferences','')}\n"
            f"Öğrenilmiş: {', '.join(profil.get('learned',[])[:5])}")
    if len(ozet.replace("\n","").replace(" ","")) < 30: return ""
    return _agent_cagir(f"2 cümlelik kişisel özet çıkar:\n{ozet}", 120)
