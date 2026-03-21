"""Sohbet motoru — sistem prompt oluşturma, mesaj hazırlama, cevap üretme."""

from __future__ import annotations

import datetime as _dt
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from beluma.core.config import Config
from beluma.core.helpers import icerik_temizle, json_kaydet, metni_temizle
from beluma.core.logger import get_logger, log_kaydet
from beluma.core.security import guvenlik_tarama, karar_motoru
from beluma.core.session import (
    gorevleri_metne_cevir,
    oturumu_kaydet,
    oturumu_yukle,
    profili_otomatik_guncelle,
    profili_yukle,
)
from beluma.core.life_map import haritayi_yukle, life_map_ozeti
from beluma.core.memory import memory_ara, memory_ekle, get_thread_pool
from beluma.tools import tool_router, run_tool

_logger = get_logger()
_cfg = Config()

# ────────────────────────────────────────────────────────────────
# SİSTEM PROMPTU
# ────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
Sen BELUMA-I'sın.

Türkiye merkezli, genel amaçlı, etik, derin düşünebilen, insan odaklı ve güvenilir bir yapay zeka asistanısın.
Temel görevin kullanıcıyı etkilemek değil, ona gerçekten yardımcı olmaktır.

Kimliğin:
- Dürüstsün, meraklısın, etik ilkelere bağlısın.
- İnsan onurunu, güvenliğini ve psikolojik iyiliğini önceliklendirirsin.
- Bilmediğini biliyormuş gibi yapmazsın.
- Kullanıcıya bağımlılık değil, güç katmaya çalışırsın.

Kökenim ve kimliğim:
- Beni BELUMA Group'un Kurucusu ve Yönetim Kurulu Başkanı Özgür tasarladı.
- Bunu soran olursa açıkça ve gurur ile belirt.
- Anthropic, OpenAI veya başka bir şirketle ilişkilendirme yapma.

BELUMA-I Nedir?
BELUMA-I, Türkiye merkezli, etik ve insan odaklı bir yapay zeka asistanıdır.
BELUMA Group Kurucusu Özgür tarafından "zeka öncesi etik" felsefesiyle tasarlanmıştır.

Kritik kural:
- Kullanıcının adını YALNIZCA sistem bağlamında "Kullanıcı: [isim]" şeklinde açıkça verilmişse kullan.
- Hafızadan veya tahminle isim türetme. Emin değilsen isim kullanma.
- Kesinlikle uydurma bilgi verme.

İletişim tarzın:
- Her zaman doğal, akıcı Türkçe kullan.
- ASLA İngilizce kelime kullanma.
- Yasaklı kelimeler: "priorite", "schedule", "deadline", "feedback", "meeting", "output", "input", "target", "update".
- ASLA JSON, dict veya teknik format döndürme. Sadece düz Türkçe metin.
- Kısa ve net ol. Her cevap maksimum 3 paragraf veya 4 madde.
- Araç (hava, borsa, tarih) bir bilgi döndürdüyse ek açıklama ekleme.
- Numaralı başlık kullanma. Doğal paragraf yaz.
- Aynı fikri 2 kez söyleme.
- Belge özetinde sadece özet ver, yorum ekleme.

Mentor rolün:
- Sen sadece bilgi kaynağı değil, zihinsel ortak ve mentorsun.
- Teknolojiyi insanı güçlendirmek için kullan, tembelleştirmek için değil.

MANTIK VE BİLMECELER KURALI:
- Matematik veya mantık sorusunda ASLA ezbere cevap verme. Adım adım düşün.

Etik sınırların:
- Zararlı, manipülatif, yasa dışı taleplere nazik ama kararlı "hayır" de.
- Asla uydurma bilgi verme.
""".strip()


def sistem_promptu_olustur(
    ad: str,
    ton: str,
    stil: str,
    belge_adi: str = "",
    belge_metni: str = "",
    duygu: Optional[Dict[str, str]] = None,
    gorevler_ozet: str = "",
    strateji: str = "",
    profil_ozeti: str = "",
    mesaj_baglami: str = "",
    ozel_rol: str = "",
) -> str:
    """Tam sistem prompt'unu oluşturur.

    Args:
        ad: Kullanıcı adı.
        ton: İletişim tonu.
        stil: Cevap stili.
        belge_adi: Aktif belge adı.
        belge_metni: Aktif belge metni.
        duygu: Duygusal durum analizi.
        gorevler_ozet: Aktif görevler özeti.
        strateji: Yanıt stratejisi.
        profil_ozeti: Kişisel profil özeti.
        mesaj_baglami: Mesaj bağlamı (token tasarrufu için).
        ozel_rol: Geçici özel rol/talimat.

    Returns:
        Birleştirilmiş sistem prompt'u.
    """
    profil = profili_yukle()
    isim = (ad or "").strip() or profil.get("name", "")
    ton_s = ton or profil.get("tone", "samimi")
    stil_s = stil or profil.get("style", "dengeli")

    ton_map = {"samimi": "sıcak ve yakın", "profesyonel": "sakin ve net", "enerjik": "motive edici"}
    stil_map = {"kısa": "kısa ve net", "dengeli": "dengeli uzunlukta", "detaylı": "adım adım detaylı"}

    baglam = [
        SYSTEM_PROMPT,
        f"\nKullanıcı: {isim if isim else 'adı bilinmiyor — isim kullanma'}.",
        f"Ton: {ton_map.get(ton_s, 'dengeli')}. Stil: {stil_map.get(stil_s, 'dengeli')}.",
    ]

    if profil_ozeti:
        baglam.append(f"Kişisel özet: {profil_ozeti}")
    elif profil.get("about"):
        baglam.append(f"Kullanıcı hakkında: {profil['about']}")

    if profil.get("preferences"):
        baglam.append(f"Tercihler: {profil['preferences']}")

    if profil.get("learned") and mesaj_baglami:
        kelimeler = set(mesaj_baglami.lower().split())
        ilgili = [
            l for l in profil["learned"][:10]
            if any(k in l.lower() for k in kelimeler if len(k) > 3)
        ][:3]
        if ilgili:
            baglam.append("Öğrenilmiş tercihler: " + "; ".join(ilgili))
    elif profil.get("learned") and not mesaj_baglami:
        baglam.append("Öğrenilmiş tercihler: " + "; ".join(profil["learned"][:3]))

    if duygu and duygu.get("durum") != "nötr":
        baglam.append(f"Duygusal durum: {duygu['durum']} → {duygu['ton']}.")

    if strateji:
        baglam.append(f"Yanıt stratejisi: {strateji}")

    baglam.append("\nAçıklanabilirlik: Karmaşık kararlar için <think>gerekçe</think> yaz, sonra temiz cevap ver.")

    if gorevler_ozet and gorevler_ozet != "Henüz hiç görev eklenmemiş.":
        baglam.append(f"Aktif görevler:\n{gorevler_ozet[:400]}")

    lm_ozet = life_map_ozeti()
    if lm_ozet:
        baglam.append(f"Kullanıcı durumu: {lm_ozet}")
    else:
        lm = haritayi_yukle()
        if any(lm.get(k) for k in ("is_modeli", "uzun_vadeli_plan")):
            baglam.append(f"Yaşam haritası: is={lm.get('is_modeli', '')} plan={lm.get('uzun_vadeli_plan', '')[:150]}")

    if belge_metni:
        baglam.append(f"Belge ({belge_adi}):\n{belge_metni}")

    if ozel_rol and ozel_rol.strip():
        baglam.append(f"KULLANICI ÖZEL TALİMATI / GEÇİCİ ROLÜN: {ozel_rol.strip()}")

    return "\n\n".join(baglam)


def duygu_analizi(mesaj: str) -> Dict[str, str]:
    """Mesajdan duygusal durum analizi yapar.

    Args:
        mesaj: Kullanıcı mesajı.

    Returns:
        {"durum": str, "ton": str} dict'i.
    """
    kucuk = mesaj.lower()
    if any(s in kucuk for s in ["bunaldım", "yoruldum", "sıkıldım", "zor", "berbat", "çaresiz", "endişe"]):
        return {"durum": "stresli", "ton": "yumuşat ve kısa tut"}
    if any(s in kucuk for s in ["harika", "süper", "mutlu", "başardım", "mükemmel"]):
        return {"durum": "mutlu", "ton": "enerjik ve destekleyici ol"}
    if any(s in kucuk for s in ["neden", "nasıl", "nedir", "anlat", "açıkla"]):
        return {"durum": "meraklı", "ton": "detaylı ve açıklayıcı ol"}
    return {"durum": "nötr", "ton": "dengeli kal"}


def aciklamayi_ayikla(ham_cevap: str) -> Tuple[str, str]:
    """<think> etiketlerinden açıklamayı ayıklar.

    Args:
        ham_cevap: Ham LLM cevabı.

    Returns:
        (açıklama, temiz_cevap) tuple'ı.
    """
    if not isinstance(ham_cevap, str):
        ham_cevap = icerik_temizle(ham_cevap)
    m = re.search(r"<think>(.*?)</think>", ham_cevap, re.DOTALL)
    if m:
        return m.group(1).strip(), metni_temizle(ham_cevap[:m.start()] + ham_cevap[m.end():])
    return "", metni_temizle(ham_cevap)


def gunluk_oneri() -> str:
    """Günün saatine göre motivasyonel öneri döndürür."""
    saat = _dt.datetime.now().hour
    if 6 <= saat < 12:
        return "☀️ Günaydın! Bugün için 3 hedef belirlemek ister misin?"
    if 12 <= saat < 18:
        return "🌤 Günün ortasındasın — ilerleme nasıl?"
    if 18 <= saat < 22:
        return "🌙 Akşam oldu. Bugünü değerlendirelim mi?"
    return ""


def mesajlari_hazirla(
    gecmis: List[Any],
    mesaj: str,
    ad: str,
    ton: str,
    stil: str,
    belge_adi: str = "",
    belge_metni: str = "",
    duygu: Optional[Dict[str, str]] = None,
    gorevler_ozet: str = "",
    strateji: str = "",
    profil_ozeti: str = "",
    ozel_rol: str = "",
) -> List[Dict[str, str]]:
    """LLM'e gönderilecek mesaj listesini hazırlar."""
    mesajlar = [{"role": "system", "content": sistem_promptu_olustur(
        ad, ton, stil, belge_adi, belge_metni, duygu,
        gorevler_ozet, strateji, profil_ozeti, mesaj, ozel_rol,
    )}]
    for item in gecmis or []:
        if isinstance(item, dict):
            role, content = item.get("role"), item.get("content")
            if role in {"user", "assistant"} and content:
                mesajlar.append({"role": role, "content": str(content)})
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            u, a = item
            if u:
                mesajlar.append({"role": "user", "content": str(u)})
            if a:
                mesajlar.append({"role": "assistant", "content": str(a)})

    soru_sayisi = mesaj.count("?")
    if soru_sayisi >= 2 or (" ve " in mesaj.lower() and "?" in mesaj):
        mesajlar.insert(1, {"role": "system", "content":
            "Kullanıcı birden fazla soru sordu. Her soruyu 1-2 cümleyle kısaca cevapla."
        })

    BILGI_KW = ["nedir", "kimdir", "ne demek", "nasıl çalışır", "açıkla", "anlat"]
    if not any(k in mesaj.lower() for k in BILGI_KW):
        hafiza = memory_ara(mesaj)
        if hafiza:
            mesajlar.insert(1, {"role": "system", "content": f"İlgili geçmiş:\n{hafiza}"})

    HEDEF_SORU_KW = [
        "hedefleri", "tamamladım", "tamamlandı", "performans", "rapor",
        "kaç hedef", "hangi hedef", "geçen ay", "aylık", "ilerleme",
        "ne kadar", "başardım", "hedefim",
    ]
    if any(k in mesaj.lower() for k in HEDEF_SORU_KW):
        lm = haritayi_yukle()
        hedefler = lm.get("hedefler", [])
        tamam = [h for h in hedefler if h.get("tamamlandi")]
        bekleyen = [h for h in hedefler if not h.get("tamamlandi")]
        if hedefler:
            hedef_txt = (
                f"Kullanıcının hedef veritabanı:\n"
                f"Toplam hedef: {len(hedefler)}\n"
                f"Tamamlanan ({len(tamam)}): {[h['hedef'] for h in tamam]}\n"
                f"Bekleyen ({len(bekleyen)}): {[h['hedef'] for h in bekleyen]}\n"
                f"Bu verilere dayanarak soruyu doğrudan cevapla."
            )
        else:
            hedef_txt = (
                "ZORUNLU TALİMAT: Kullanıcının hedef veritabanı TAMAMEN BOŞ. "
                "Uydurma hedef listesi oluşturma. "
                "Sadece şunu söyle: Henüz hiç hedef eklenmemiş, Yaşam Haritası sekmesinden ekleyebilirsin."
            )
        mesajlar.append({"role": "system", "content": hedef_txt})

    mesajlar.append({"role": "user", "content": mesaj})
    return mesajlar


def cevap_uret(
    mesaj: str,
    gecmis: List[Any],
    ad: str,
    ton: str,
    stil: str,
    belge_adi: str = "",
    belge_metni: str = "",
    duygu: Optional[Dict[str, str]] = None,
    gorevler_ozet: str = "",
    strateji: str = "",
    profil_ozeti: str = "",
    yaraticilik_seviyesi: float = 0.4,
    ozel_rol: str = "",
    secili_model: str = "llama-3.3-70b-versatile",
    max_tokens: int = 400,
    top_p: float = 0.9,
) -> str:
    """Ana cevap üretim fonksiyonu.

    Returns:
        Üretilen cevap metni.
    """
    from beluma.core.client import get_groq_client
    client = get_groq_client()
    if not client:
        return "GROQ_API_KEY tanımlı olmadığı için cevap üretemiyorum."

    tool_oneki = ""
    tool = tool_router(mesaj)
    if tool:
        sonuc = run_tool(tool, mesaj)
        if sonuc:
            log_kaydet(mesaj, sonuc, "tool")
            coklu = mesaj.count("?") >= 2 or (
                " ve " in mesaj.lower()
                and any(k in mesaj.lower() for k in ["nedir", "kimdir", "nasıl", "anlat", "açıkla"])
            )
            if not coklu:
                return sonuc
            tool_oneki = sonuc

    if not karar_motoru(mesaj)["guvenli"]:
        return "Bu isteğe yardımcı olamam, ancak daha güvenli bir alternatif bulabiliriz."

    mesajlar = mesajlari_hazirla(
        gecmis, mesaj, ad, ton, stil, belge_adi, belge_metni,
        duygu, gorevler_ozet, strateji, profil_ozeti, ozel_rol,
    )

    denenen = [secili_model] + [m for m in _cfg.FALLBACK_MODELLER if m != secili_model]
    son_hata = ""

    is_logic = any(k in mesaj.lower() for k in [
        "matematik", "hesap", "bilmece", "mantık", "problem", "kaç gün", "katına", "üstel",
    ])
    temp_val = 0.2 if is_logic else float(yaraticilik_seviyesi)

    for model in denenen:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=mesajlar,
                temperature=temp_val,
                max_tokens=int(max_tokens),
                top_p=float(top_p),
                frequency_penalty=1.1,
                presence_penalty=0.6,
            )
            cevap = icerik_temizle(response.choices[0].message.content)
            cevap = cevap or "Şu an net bir cevap üretemedim. Mesajını biraz daha açabilir misin?"
            if tool_oneki:
                cevap = tool_oneki + "\n\n" + cevap
            log_kaydet(mesaj, cevap, model)
            return cevap
        except Exception as e:
            son_hata = str(e)
            _logger.warning("[cevap_uret] model=%s hata: %s", model, son_hata[:100])
            if "rate_limit_exceeded" in son_hata or "429" in son_hata:
                if denenen.index(model) < 2:
                    time.sleep(1)
                continue
            return f"Bir hata oluştu: {son_hata}"

    return f"⏳ Tüm modeller limitlendi. Birkaç dakika sonra tekrar dene. ({son_hata[:100]})"


# ────────────────────────────────────────────────────────────────
# PROAKTİF KONTROL
# ────────────────────────────────────────────────────────────────
def proaktif_kontrol(mesaj_baglam: str = "") -> str:
    """Proaktif uyarı ve hatırlatma sistemi."""
    data = haritayi_yukle()
    hedefler = data.get("hedefler", [])
    tamamlanmayan = [h for h in hedefler if not h.get("tamamlandi")]
    tamamlanan = [h for h in hedefler if h.get("tamamlandi")]

    if len(tamamlanmayan) > 5:
        yuksek = [h["hedef"] for h in tamamlanmayan if h.get("oncelik", 2) == 3]
        if yuksek:
            return f"⚠️ **Odak uyarısı:** {len(tamamlanmayan)} bekleyen hedefin var. Yüksek öncelikli: _{yuksek[0]}_"

    if not tamamlanmayan and len(tamamlanan) > 0:
        return "🔥 **Tebrikler!** Tüm hedefleri tamamladın. Yeni hedef koyma zamanı geldi."

    PLAN_KW = ["plan", "hedef", "strateji", "verimli", "öncelik", "başarı"]
    if len(hedefler) == 0 and any(k in mesaj_baglam.lower() for k in PLAN_KW):
        return "💡 Henüz hedef eklemedin. Yaşam Haritası sekmesinden başlayabilirsin."

    aliskanliklar = data.get("aliskanliklar", [])
    bugun = time.strftime("%Y-%m-%d")
    for a in aliskanliklar:
        son = a.get("son_guncelleme", "")
        if son and son < bugun and a.get("seri", 0) > 2:
            return f"🔔 _{a['aliskanlik']}_ alışkanlığının {a['seri']} günlük serisi kırılmak üzere!"

    return ""
