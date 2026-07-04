"""AI ajan (Faz 5) — serbest yazılan müşteri mesajını anlar, gerekirse sohbet eder.

Tasarım ilkeleri (bkz. Obsidian: instALL/outputs/faz5-model-arastirmasi.md):
- Sağlayıcı-bağımsız: LiteLLM üzerinden çağrı; model adı settings.AJAN_MODEL
  (env: AJAN_MODEL). Varsayılan Gemini Flash (ücretsiz katman); yetmezse
  gemini-flash-lite-latest ya da başka sağlayıcıya tek env değişikliğiyle geçilir.
- Fiyat ASLA modelden gelmez: model yalnızca aşağıdaki tool'ları çağırarak
  veritabanındaki gerçek fiyatı okur. Tool sonucu olmadan fiyat yazması yasak
  (sistem promptunda da tembihlenir).
- Zarif düşüş: anahtar yok / kota doldu / hata → None döner, router menüye düşer.
  Müşteri hiçbir durumda cevapsız kalmaz.
- Bağlam: bot_mesaj tablosundaki son konuşmalar (settings.AJAN_GECMIS_LIMIT).
"""
from __future__ import annotations

import json
import logging

from django.conf import settings
from sqlalchemy import select

from catalog.database import SessionLocal
from catalog.sa_models import BotMesaj
from catalog.services import menu_veri

log = logging.getLogger("bot.ajan")

MAKS_TOOL_TURU = 5      # tool çağrısı döngüsü üst sınırı (sonsuz döngü emniyeti)
MAKS_CEVAP_KR = 900     # WA/IG'de rahat okunur üst sınır (tek mesaj)

# ─── Sistem promptu ──────────────────────────────────────────────────────────
SISTEM_PROMPTU = """Sen Doğtaş Çevreyolu mobilya mağazasının WhatsApp/Instagram asistanısın.
Görevin: müşteriye ürün ve fiyat konusunda yardımcı olmak, kısa ve samimi sohbet etmek.

KURALLAR (kesin):
1. FİYAT UYDURMA. Fiyat ve ürün bilgisini YALNIZCA sana verilen araçlardan (tool) al.
   Araç sonucu yoksa fiyat söyleme; "menüden bakalım" de.
2. Kısa yaz — bu bir mesajlaşma sohbeti. En fazla 3-4 cümle. Emoji az ve yerinde.
3. Türkçe konuş, "siz" diye hitap et, sıcak ve yardımsever ol.
4. Fiyat verirken ürün/kombinasyon adını da yaz (örn. "MARIZA Köşe Takımı: 85.000 TL")
   ve fiyatların liste fiyatı olduğunu, mağazada özel fiyat sorulabileceğini ekle.
5. Müşteri insanla görüşmek isterse ya da çözemediğin bir konu olursa
   "yetkili" yazmasını söyle (bot onu mağaza yetkilisine yönlendirir).
6. Konu dışı sorularda (siyaset, genel bilgi, başka markalar...) kibarca
   mobilya konusuna dön; tartışmaya girme.
7. Garanti, teslimat süresi, kampanya gibi bilmediğin operasyonel konularda
   tahmin yürütme → yetkiliye yönlendir.
8. Müşteri kategori/koleksiyon adını yanlış yazabilir (örn. "mariza", "yatak odsı")
   — arama aracını kullanıp en yakınını bul.

Mağazadaki kategoriler: {kategoriler}
"""

# ─── Tool tanımları (OpenAI/LiteLLM function calling formatı) ────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "koleksiyon_ara",
            "description": "Koleksiyon (ürün serisi) adıyla arama yapar. Müşteri bir "
                           "ürün/seri adı geçirdiğinde önce bunu çağır.",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Aranacak ad, örn. 'mariza'"},
                },
                "required": ["q"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kategorileri_listele",
            "description": "Mağazadaki ürün kategorilerini (id + ad) listeler.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "koleksiyonlari_listele",
            "description": "Bir kategorideki koleksiyonları listeler.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kategori_id": {"type": "integer"},
                },
                "required": ["kategori_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kombinasyonlari_listele",
            "description": "Bir koleksiyonun kombinasyonlarını (takım seçenekleri) "
                           "toplam fiyat özetiyle listeler.",
            "parameters": {
                "type": "object",
                "properties": {
                    "koleksiyon_id": {"type": "integer"},
                },
                "required": ["koleksiyon_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fiyat_detay",
            "description": "Bir kombinasyonun fiyat detayını ve içindeki ürünleri verir. "
                           "Müşteriye fiyat söylemeden önce MUTLAKA bu (veya "
                           "kombinasyonlari_listele) çağrılmış olmalı.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kombinasyon_id": {"type": "integer"},
                },
                "required": ["kombinasyon_id"],
            },
        },
    },
]


def _tool_calistir(ad: str, argumanlar: dict):
    """Modelin istediği aracı gerçek veriyle çalıştır."""
    if ad == "koleksiyon_ara":
        return menu_veri.koleksiyon_ara(str(argumanlar.get("q", "")))
    if ad == "kategorileri_listele":
        return menu_veri.kategoriler()
    if ad == "koleksiyonlari_listele":
        return menu_veri.koleksiyonlar(int(argumanlar["kategori_id"]))
    if ad == "kombinasyonlari_listele":
        return menu_veri.kombinasyonlar(int(argumanlar["koleksiyon_id"]))
    if ad == "fiyat_detay":
        return menu_veri.kombinasyon(int(argumanlar["kombinasyon_id"]))
    return {"hata": f"bilinmeyen araç: {ad}"}


def _gecmis(platform: str, kullanici: str, guncel_metin: str) -> list[dict]:
    """bot_mesaj'dan son konuşmaları user/assistant rollerine çevir.

    Menü payload'ları ve uzun menü metinleri atlanır (bağlamı şişirir);
    yalnız serbest metinler alınır. Güncel gelen mesaj (webhook az önce
    kaydettiği için) listeden düşülür — modele ayrıca verilecek.
    """
    try:
        session = SessionLocal()
        try:
            rows = session.scalars(
                select(BotMesaj)
                .where(BotMesaj.platform == platform, BotMesaj.kullanici == kullanici)
                .order_by(BotMesaj.id.desc())
                .limit(settings.AJAN_GECMIS_LIMIT * 2)
            ).all()
        finally:
            session.close()
    except Exception:
        log.exception("ajan: geçmiş okunamadı (%s/%s)", platform, kullanici)
        return []

    rows = list(reversed(rows))
    # Az önce kaydedilen güncel mesajı düş (en sondaki 'gelen' aynı metinse).
    if rows and rows[-1].yon == "gelen" and (rows[-1].metin or "").strip() == guncel_metin.strip():
        rows = rows[:-1]

    mesajlar: list[dict] = []
    for r in rows:
        metin = (r.metin or "").strip()
        if not metin or metin.startswith("[buton]") or "[menü]" in metin \
                or metin.startswith("[kart") or metin.startswith("[sohbeti"):
            continue
        rol = "user" if r.yon == "gelen" else "assistant"
        mesajlar.append({"role": rol, "content": metin[:400]})
    return mesajlar[-settings.AJAN_GECMIS_LIMIT:]


def cevapla(metin: str, platform: str, kullanici: str) -> str | None:
    """Serbest metne AI cevabı üret. Ajan kapalıysa/hata olursa None (→ menüye düş)."""
    if not settings.AJAN_AKTIF:
        return None
    try:
        return _cevapla(metin, platform, kullanici)
    except Exception:
        log.exception("ajan: cevap üretilemedi, menüye düşülüyor")
        return None


def _cevapla(metin: str, platform: str, kullanici: str) -> str | None:
    import litellm
    litellm.suppress_debug_info = True

    kategoriler = ", ".join(f"{k['ad']} (id:{k['id']})" for k in menu_veri.kategoriler())
    mesajlar = [
        {"role": "system", "content": SISTEM_PROMPTU.format(kategoriler=kategoriler)},
        *_gecmis(platform, kullanici, metin),
        {"role": "user", "content": metin[:1000]},
    ]

    for _ in range(MAKS_TOOL_TURU):
        yanit = litellm.completion(
            model=settings.AJAN_MODEL,
            messages=mesajlar,
            tools=TOOLS,
            max_tokens=600,
            timeout=25,
        )
        secim = yanit.choices[0].message

        if not getattr(secim, "tool_calls", None):
            cevap = (secim.content or "").strip()
            return cevap[:MAKS_CEVAP_KR] if cevap else None

        # Modelin istediği araçları çalıştır, sonuçları konuşmaya ekle.
        mesajlar.append(secim.model_dump())
        for tc in secim.tool_calls:
            try:
                argumanlar = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                argumanlar = {}
            try:
                sonuc = _tool_calistir(tc.function.name, argumanlar)
            except Exception:
                log.exception("ajan: araç hatası %s(%s)", tc.function.name, argumanlar)
                sonuc = {"hata": "veri okunamadı"}
            mesajlar.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(sonuc, ensure_ascii=False, default=str)[:6000],
            })

    log.warning("ajan: %s tool turu aşıldı, menüye düşülüyor", MAKS_TOOL_TURU)
    return None
