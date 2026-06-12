"""Kategori → Koleksiyon hiyerarşisi + KategoriKurali (filtre/duplikasyon)."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from catalog.database import Base


class Kategori(Base):
    __tablename__ = "kategoriler"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ad: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    sira: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    koleksiyonlar: Mapped[list["Koleksiyon"]] = relationship(
        back_populates="kategori",
        cascade="all, delete-orphan",
        order_by="Koleksiyon.ad",
    )

    def __repr__(self) -> str:
        return f"<Kategori {self.ad!r}>"


class Koleksiyon(Base):
    __tablename__ = "koleksiyonlar"
    __table_args__ = (
        UniqueConstraint("kategori_id", "ad", name="uq_koleksiyon_kategori_ad"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kategori_id: Mapped[int] = mapped_column(
        ForeignKey("kategoriler.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ad: Mapped[str] = mapped_column(String(200), nullable=False)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Takım + mağaza bayrakları (0002 migration)
    takim_adi: Mapped[str | None] = mapped_column(String(200))
    # Atanan takım ürününün id'si (etiket PDF'i bu ürünün url'inden QR üretir)
    takim_urun_id: Mapped[int | None] = mapped_column(
        ForeignKey("urunler.id", ondelete="SET NULL"), index=True
    )
    bayrak_exc: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    bayrak_sube: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Mağaza bazlı son etiket yazdırma zamanı (0013 migration).
    # NULL = bu mağaza için hiç yazdırılmadı. Etiket Yazdır ekranının
    # "son basımdan beri değişenler" varsayılan filtresi bunlara dayanır.
    son_yazdirma_exc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    son_yazdirma_sube: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    kategori: Mapped["Kategori"] = relationship(back_populates="koleksiyonlar")
    urunler: Mapped[list["Urun"]] = relationship(  # noqa: F821
        secondary="urun_koleksiyon",
        back_populates="koleksiyonlar",
    )
    takim_urun: Mapped["Urun | None"] = relationship(  # noqa: F821
        foreign_keys=[takim_urun_id], lazy="joined"
    )

    def __repr__(self) -> str:
        return f"<Koleksiyon {self.ad!r}>"


class KategoriKurali(Base):
    """
    Scraper iş kuralları:
    - tur='filtre'      → eşleşen ürünleri DB'ye yazma (atla)
    - tur='duplikasyon' → ürünü hedef_kategori altında da koleksiyona bağla

    Kullanım örnekleri:
      filtre,    kaynak='Doğtaş Home', kelimeler=NULL → kategoriyi tamamen atla
      filtre,    kaynak=NULL,          kelimeler='Abajur' → boş kategori + ürün adında kelime
      duplikasyon, kaynak='Yemek Odası', hedef='Yatak Odası', kelimeler='ayakucu,ayna'
    """
    __tablename__ = "kategori_kurallari"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tur: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    kaynak_kategori: Mapped[str | None] = mapped_column(String(120))
    hedef_kategori: Mapped[str | None] = mapped_column(String(120))
    kelimeler: Mapped[str | None] = mapped_column(String(500))
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def kelime_listesi(self) -> list[str]:
        """CSV → küçük harfli kelime listesi."""
        if not self.kelimeler:
            return []
        return [k.strip().lower() for k in self.kelimeler.split(",") if k.strip()]

    def __repr__(self) -> str:
        return f"<KategoriKurali {self.tur} {self.kaynak_kategori}→{self.hedef_kategori}>"
