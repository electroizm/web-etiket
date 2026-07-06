"""Teşhir kaydı — mağazada sergilenen ürün/takımlar (bağlı + gerekirse ez modeli).

Bir kayıt bir koleksiyona (istenirse belirli bir kombinasyona) bağlanır:
- liste_fiyat / perakende_fiyat NULL ise → güncel web (scraper) fiyatı geçerli;
  dolu ise mağazanın verdiği fiyat web fiyatını EZER.
- icerik NULL ise → bağlı kombinasyonun ürün listesi gösterilir; dolu ise
  mağazadaki gerçek teşhirin içeriği (serbest metin) esas alınır.

AI ajan teşhir fiyatını YALNIZCA müşteri özellikle mağazadaki/teşhirdeki
üründen bahsederse söyler (2026-07-06 kararı: "sadece sorana").
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from catalog.database import Base


class Teshir(Base):
    __tablename__ = "teshir"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    koleksiyon_id: Mapped[int] = mapped_column(
        ForeignKey("koleksiyonlar.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Belirli bir kombinasyona bağlanabilir; koleksiyon geneli için NULL.
    kombinasyon_id: Mapped[int | None] = mapped_column(
        ForeignKey("kombinasyonlar.id", ondelete="SET NULL"), nullable=True
    )
    # Boş bırakılan alanlar web verisine düşer (bkz. modül docstring'i).
    baslik: Mapped[str | None] = mapped_column(Text)          # görünen ad (boş → koleksiyon adı)
    icerik: Mapped[str | None] = mapped_column(Text)          # teşhirin içeriği (serbest metin)
    liste_fiyat: Mapped[int | None] = mapped_column(Integer)
    perakende_fiyat: Mapped[int | None] = mapped_column(Integer)
    notlar: Mapped[str | None] = mapped_column(Text)          # iç not — ajana/müşteriye gitmez
    guncelleme: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Teshir kol={self.koleksiyon_id} {self.baslik!r}>"
