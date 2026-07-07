"""Webhook'un saf (framework'süz) mantığı — kolay test edilsin diye ayrıldı.

İki iş:
  1) verify_challenge: Meta'nın GET el sıkışması.
  2) extract_events: gelen POST gövdesinden (WhatsApp/Instagram) olayları çıkar.

(instALL köprüsünden Django app'ine taşındı — Faz 6, Render tek servis birleştirme.)
"""
from __future__ import annotations

from dataclasses import dataclass


def verify_challenge(mode: str, token: str, challenge: str, beklenen_token: str):
    """Meta GET doğrulaması. (status_code, body) döner.

    Eşleşirse challenge'ı OLDUĞU GİBI geri yazmak gerekir; yoksa 403.
    """
    if mode == "subscribe" and token and token == beklenen_token:
        return 200, challenge
    return 403, "dogrulama basarisiz"


@dataclass
class GelenOlay:
    """Tek bir kullanıcı etkileşimi (normalize edilmiş)."""
    platform: str          # "instagram" | "whatsapp"
    gonderen: str          # kullanıcı id'si (cevabı buraya yollarız)
    secim: str | None      # tıklanan buton payload'ı (KAT:48 gibi) ya da None
    metin: str | None      # serbest metin (varsa)
    gonderen_ad: str | None = None   # WA: contacts[].profile.name (pushname); IG: yok
    # Sesli mesaj: WA → {"tip":"wa","media_id":...}; IG → {"tip":"ig","url":...}.
    # views transkripte çevirip metin'e yazar (bot/ses.py); çözülmezse özür mesajı.
    ses: dict | None = None
    # Görsel: WA → {"tip":"wa","media_id":...};
    # IG doğrudan resim → {"tip":"ig","url":...};
    # IG story-reply → {"tip":"ig_story","url":...} (story'nin GÖRSELİ, mesaj değil).
    # views OCR'lar, okunan metni müşteri metnine ekler (bot/gorsel.py).
    gorsel: dict | None = None

    @property
    def tetik(self) -> str:
        """Yönlendiriciye verilecek token: buton seçimi > serbest metin > START."""
        if self.secim:
            return self.secim
        return (self.metin or "").strip() or "START"


def extract_events(govde: dict) -> list[GelenOlay]:
    """Meta webhook POST gövdesinden olayları normalize et.

    Instagram DM:      entry[].messaging[].message.text / .quick_reply.payload
    Instagram postback: entry[].messaging[].postback.payload
    WhatsApp:          entry[].changes[].value.messages[].text.body / interactive
    """
    olaylar: list[GelenOlay] = []
    for entry in govde.get("entry", []):
        # ── Instagram / Messenger formatı ──
        for m in entry.get("messaging", []):
            gonderen = (m.get("sender") or {}).get("id", "")
            if not gonderen:
                continue
            if "postback" in m:
                olaylar.append(GelenOlay("instagram", gonderen,
                                         (m["postback"] or {}).get("payload"), None))
            elif "message" in m:
                msg = m["message"] or {}
                if msg.get("is_echo"):  # botun kendi mesajının yankısı — işleme
                    continue
                qr = (msg.get("quick_reply") or {}).get("payload")
                ses = None
                gorsel = None
                for ek in (msg.get("attachments") or []):
                    url = (ek.get("payload") or {}).get("url")
                    if not url:
                        continue
                    if ek.get("type") == "audio" and ses is None:
                        ses = {"tip": "ig", "url": url}
                    elif ek.get("type") == "image" and gorsel is None:
                        gorsel = {"tip": "ig", "url": url}
                # Story'ye verilen yanıt: story görselinin CDN URL'i reply_to.story'de
                # gelir — müşteri "fiyat" yazsa da HANGİ ürün olduğu ancak story
                # görselinden okunabilir (bot/gorsel.py OCR'lar).
                story = (msg.get("reply_to") or {}).get("story") or {}
                if gorsel is None and story.get("url"):
                    gorsel = {"tip": "ig_story", "url": story["url"]}
                olaylar.append(GelenOlay("instagram", gonderen, qr, msg.get("text"),
                                         ses=ses, gorsel=gorsel))

        # ── WhatsApp Cloud API formatı ──
        for ch in entry.get("changes", []):
            value = ch.get("value") or {}
            # contacts[].profile.name = müşterinin WhatsApp görünen adı (pushname)
            adlar = {
                (c.get("wa_id") or ""): ((c.get("profile") or {}).get("name") or None)
                for c in value.get("contacts", [])
            }
            for msg in value.get("messages", []):
                gonderen = msg.get("from", "")
                if not gonderen:
                    continue
                secim = None
                inter = msg.get("interactive") or {}
                if inter.get("type") == "button_reply":
                    secim = (inter.get("button_reply") or {}).get("id")
                elif inter.get("type") == "list_reply":
                    secim = (inter.get("list_reply") or {}).get("id")
                audio = msg.get("audio") or {}   # sesli mesaj da type="audio" gelir
                ses = {"tip": "wa", "media_id": audio["id"]} if audio.get("id") else None
                image = msg.get("image") or {}   # resim mesajı (altyazı taşıyabilir)
                gorsel = {"tip": "wa", "media_id": image["id"]} if image.get("id") else None
                # Resimle birlikte yazılan altyazı (caption) müşteri metni sayılır.
                metin = (msg.get("text") or {}).get("body") or image.get("caption")
                olaylar.append(GelenOlay("whatsapp", gonderen, secim, metin,
                                         gonderen_ad=adlar.get(gonderen), ses=ses,
                                         gorsel=gorsel))
    return olaylar


@dataclass
class GelenYorum:
    """Bir Instagram gönderisine yapılan yorum (yorumdan-DM tetikleyicisi)."""
    yorumcu_id: str      # yorumu yapan kullanıcının IGSID (from.id)
    comment_id: str      # private reply hedefi (yorum başına yalnızca bir kez kullanılır)
    metin: str
    media_id: str = ""   # yorumun yapıldığı gönderi/reels id — "gönderi başına 1 DM" dedup'ı için
    yorumcu_ad: str | None = None


def extract_yorumlar(govde: dict) -> list[GelenYorum]:
    """Instagram yorum webhook'undan (comment-to-DM tetikleyicisi) olayları çıkar.

    Format: entry[].changes[] with field == "comments":
      value: {from: {id, username}, id: <comment_id>, text, media: {...}}
    Bot hiçbir zaman genel (public) yorum ATMAZ — yalnız private reply — bu
    yüzden botun kendi cevabının webhook'tan geri gelip döngü yaratma riski yok.
    """
    yorumlar: list[GelenYorum] = []
    for entry in govde.get("entry", []):
        for ch in entry.get("changes", []):
            if ch.get("field") != "comments":
                continue
            value = ch.get("value") or {}
            metin = (value.get("text") or "").strip()
            yorumcu = (value.get("from") or {}).get("id", "")
            comment_id = value.get("id", "")
            if not (metin and yorumcu and comment_id):
                continue
            yorumlar.append(GelenYorum(
                yorumcu_id=yorumcu,
                comment_id=comment_id,
                metin=metin,
                media_id=(value.get("media") or {}).get("id", ""),
                yorumcu_ad=(value.get("from") or {}).get("username"),
            ))
    return yorumlar


def parse_secim(tetik: str) -> tuple[str, str | None]:
    """'KAT:48' → ('KAT', '48'); 'START' → ('START', None)."""
    if ":" in tetik:
        tur, _, deger = tetik.partition(":")
        return tur.upper(), deger
    return tetik.upper(), None
