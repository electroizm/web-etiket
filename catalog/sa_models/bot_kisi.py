"""Bot müşterilerinin profil bilgisi (/app/bot'ta id yerine isim/foto göstermek için).

WhatsApp: ad, gelen webhook'un contacts[].profile.name alanından yakalanır;
Meta müşteri fotoğrafını Cloud API'ye vermez (gizlilik) → foto_url hep None.
Instagram: ad + kullanıcı adı + profil fotoğrafı Graph API'den çekilir
(bot/kisi.py). Foto URL'si CDN imzalı olduğundan süreli → periyodik tazelenir.
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from catalog.database import Base


class BotKisi(Base):
    __tablename__ = "bot_kisi"
    __table_args__ = (UniqueConstraint("platform", "kullanici"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(20))     # whatsapp | instagram
    kullanici: Mapped[str] = mapped_column(String(64))    # WA: telefon, IG: igsid
    ad: Mapped[str | None] = mapped_column(String(128))
    kullanici_adi: Mapped[str | None] = mapped_column(String(64))   # IG username
    foto_url: Mapped[str | None] = mapped_column(Text)
    guncelleme: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<BotKisi {self.platform}:{self.kullanici} {self.ad!r}>"
