"""Uygulama geneli ayarlar (key-value)."""
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from catalog.database import Base


class AppAyari(Base):
    __tablename__ = "app_ayarlari"

    anahtar: Mapped[str] = mapped_column(String, primary_key=True)
    deger: Mapped[str | None] = mapped_column(String)
    guncellenme_tarihi: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<AppAyari {self.anahtar}={self.deger!r}>"
