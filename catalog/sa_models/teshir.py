"""Teşhir kaydı — mağazada sergilenen ürün/takımlar (bağlı + gerekirse ez modeli).

Bir kayıt bir koleksiyona (istenirse belirli bir kombinasyona) bağlanır:
- liste_fiyat / perakende_fiyat NULL ise → güncel web (scraper) fiyatı geçerli;
  dolu ise mağazanın verdiği fiyat web fiyatını EZER.
- icerik NULL ise → bağlı kombinasyonun ürün listesi gösterilir; dolu ise
  mağazadaki gerçek teşhirin içeriği (serbest metin) esas alınır.
- Koleksiyon web'de artık yoksa: koleksiyon_id NULL bırakılıp adı
  koleksiyon_adi'na ELLE yazılır (kategori_id o zaman ayrıca saklanır).
- pazarlik_payi (TL): müşteri pazarlık ederse ajan en fazla
  perakende − pay tabanına kadar inebilir; NULL = pazarlık yok.

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
    # Web'deki koleksiyona bağ — manuel kayıtlar için NULL (bkz. koleksiyon_adi).
    koleksiyon_id: Mapped[int | None] = mapped_column(
        ForeignKey("koleksiyonlar.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Manuel kayıt: koleksiyon web'de yokken elle yazılan ad + kategori bağı.
    koleksiyon_adi: Mapped[str | None] = mapped_column(Text)
    kategori_id: Mapped[int | None] = mapped_column(
        ForeignKey("kategoriler.id", ondelete="SET NULL"), nullable=True
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
    pazarlik_payi: Mapped[int | None] = mapped_column(Integer)  # TL — ajanın inebileceği pay
    notlar: Mapped[str | None] = mapped_column(Text)          # iç not — ajana/müşteriye gitmez
    guncelleme: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Teshir kol={self.koleksiyon_id} {self.baslik!r}>"
