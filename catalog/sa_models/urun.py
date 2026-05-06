"""Ürün, fiyat ve ürün-koleksiyon many-to-many ilişkisi.

Önemli:
- Aynı SKU birden fazla koleksiyonda görünebilir → Urun ↔ Koleksiyon M2M.
- Fiyatlar TL cinsinden tam sayı (integer; kuruş kullanılmıyor).
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from catalog.database import Base


# ─── Ara tablo: urun ↔ koleksiyon ─────────────────────────────────────────────
urun_koleksiyon = Table(
    "urun_koleksiyon",
    Base.metadata,
    Column(
        "urun_id",
        ForeignKey("urunler.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "koleksiyon_id",
        ForeignKey("koleksiyonlar.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # Bu (urun, koleksiyon) çiftinin PDF etiketine dahil edilip edilmeyeceği.
    # Default FALSE — kullanıcı manuel olarak işaretler (15 satır limiti var).
    Column(
        "etiket_secili",
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
    ),
)


class Urun(Base):
    __tablename__ = "urunler"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    urun_adi_tam: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str | None] = mapped_column(String(500))   # Doğtaş.com ürün sayfası

    # Hızlı erişim için son fiyat denormalize (tarihçe fiyatlar tablosunda)
    # TL cinsinden tam sayı
    son_liste_fiyat: Mapped[int | None] = mapped_column(Integer)
    son_perakende_fiyat: Mapped[int | None] = mapped_column(Integer)

    # Son güncelleme: insert'te NOW(), scraper fiyat değişimi (≥70 TL) tespit
    # ettiğinde de NOW() ile yenilenir. Yeni ürün de güncelleme de aynı kolonu kullanır.
    son_guncelleme: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    koleksiyonlar: Mapped[list["Koleksiyon"]] = relationship(  # noqa: F821
        secondary=urun_koleksiyon,
        back_populates="urunler",
    )
    fiyatlar: Mapped[list["Fiyat"]] = relationship(
        back_populates="urun",
        cascade="all, delete-orphan",
        order_by="Fiyat.kayit_tarihi.desc()",
    )

    def __repr__(self) -> str:
        return f"<Urun {self.sku} {self.urun_adi_tam!r}>"


class Fiyat(Base):
    __tablename__ = "fiyatlar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    urun_id: Mapped[int] = mapped_column(
        ForeignKey("urunler.id", ondelete="CASCADE"), nullable=False, index=True
    )
    liste_fiyat: Mapped[int | None] = mapped_column(Integer)
    perakende_fiyat: Mapped[int | None] = mapped_column(Integer)
    kaynak: Mapped[str] = mapped_column(String(30), default="manual", nullable=False)
    # ör. "manual" | "dogtas_com" | "sheets" | "import"
    kayit_tarihi: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    urun: Mapped["Urun"] = relationship(back_populates="fiyatlar")
