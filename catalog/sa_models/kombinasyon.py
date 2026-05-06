"""Kombinasyon modelleri (eski projedeki TakimKombinasyonu/TakimUrunu port'u).

- Kombinasyon: bir koleksiyona bağlı adlandırılmış set ("6 Kapaklı, Karyola")
- KombinasyonUrun: M2M with miktar — her kombinasyondaki ürünler ve adetleri
- KategoriKombinasyonKurali: otomatik bul için regex pattern'leri
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from catalog.database import Base


class Kombinasyon(Base):
    """'6 Kapaklı, Karyola' gibi adlandırılmış ürün setleri (koleksiyon başına)."""
    __tablename__ = "kombinasyonlar"
    __table_args__ = (
        UniqueConstraint("koleksiyon_id", "ad", name="uq_kombinasyon_kol_ad"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    koleksiyon_id: Mapped[int] = mapped_column(
        ForeignKey("koleksiyonlar.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ad: Mapped[str] = mapped_column(String(200), nullable=False)
    sira: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # PDF etiketinde gösterilsin mi? (default FALSE → kullanıcı manuel işaretler;
    # 15 satır limiti aşılmasın diye)
    etiket_secili: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    urunler: Mapped[list["KombinasyonUrun"]] = relationship(
        back_populates="kombinasyon",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Kombinasyon {self.ad!r} (kol={self.koleksiyon_id})>"


class KombinasyonUrun(Base):
    """Kombinasyon × Ürün ara tablosu (miktar bilgisiyle)."""
    __tablename__ = "kombinasyon_urunleri"
    __table_args__ = (
        UniqueConstraint("kombinasyon_id", "urun_id", name="uq_kombinasyon_urun"),
        CheckConstraint("miktar >= 1", name="ck_kombinasyon_urun_miktar"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kombinasyon_id: Mapped[int] = mapped_column(
        ForeignKey("kombinasyonlar.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    urun_id: Mapped[int] = mapped_column(
        ForeignKey("urunler.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    miktar: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    kombinasyon: Mapped["Kombinasyon"] = relationship(back_populates="urunler")
    # urun ilişkisini selectinload ile yükleriz; back_populates yok
    urun: Mapped["Urun"] = relationship()  # noqa: F821


class KategoriKombinasyonKurali(Base):
    """Bir kategori için otomatik kombinasyon bulma kuralı.

    patterns: regex pattern listesi (her bir pattern bir 'slot' — set'in bir parçası)
    adet_overrides: {pattern: adet_int} — bazı slot'lar için adet override
                    (ör. komodin 2 adet, sandalye 6 adet)
    """
    __tablename__ = "kategori_kombinasyon_kurallari"
    __table_args__ = (
        UniqueConstraint("kategori_id", "kombinasyon_adi", name="uq_kkk_kategori_ad"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kategori_id: Mapped[int] = mapped_column(
        ForeignKey("kategoriler.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kombinasyon_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    patterns: Mapped[list] = mapped_column(JSONB, nullable=False)
    adet_overrides: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    sira: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<KKK kat={self.kategori_id} {self.kombinasyon_adi!r}>"
