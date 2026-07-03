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
                olaylar.append(GelenOlay("instagram", gonderen, qr, msg.get("text")))

        # ── WhatsApp Cloud API formatı ──
        for ch in entry.get("changes", []):
            value = ch.get("value") or {}
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
                metin = (msg.get("text") or {}).get("body")
                olaylar.append(GelenOlay("whatsapp", gonderen, secim, metin))
    return olaylar


def parse_secim(tetik: str) -> tuple[str, str | None]:
    """'KAT:48' → ('KAT', '48'); 'START' → ('START', None)."""
    if ":" in tetik:
        tur, _, deger = tetik.partition(":")
        return tur.upper(), deger
    return tetik.upper(), None
