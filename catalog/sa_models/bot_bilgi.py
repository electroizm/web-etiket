"""Bot bilgi tabanı — mağaza bilgileri + cevapsız müşteri soruları.

BotBilgi: adres, mesai, kargo, iade, taksit gibi operasyonel bilgiler.
AI ajan bu bilgileri YALNIZCA buradan okur (magaza_bilgi tool'u) — modelin
kendi bilgisinden mağaza bilgisi uydurması yasak (bkz. 2026-07-06 "Antalya
adresi" halüsinasyonu).

BotSoru: DB'de karşılığı bulunamayan müşteri soruları. İsmail /app/bot/bilgi
sayfasında görür, cevabı ekler → aynı soru bir daha cevapsız kalmaz.
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from catalog.database import Base


class BotBilgi(Base):
    __tablename__ = "bot_bilgi"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    baslik: Mapped[str] = mapped_column(Text)     # konu: "Adres", "Mesai saatleri"
    anahtar: Mapped[str] = mapped_column(Text)    # virgüllü arama kelimeleri
    cevap: Mapped[str] = mapped_column(Text)      # botun söyleyeceği metin
    guncelleme: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<BotBilgi {self.baslik!r}>"


class BotSoru(Base):
    __tablename__ = "bot_soru"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(20))
    kullanici: Mapped[str] = mapped_column(String(64))
    soru: Mapped[str] = mapped_column(Text)
    durum: Mapped[str] = mapped_column(String(12), default="acik",
                                       server_default="acik")  # acik | cevaplandi
    olusturma: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<BotSoru {self.soru[:30]!r} {self.durum}>"
