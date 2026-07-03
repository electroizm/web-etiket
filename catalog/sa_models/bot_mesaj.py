"""WhatsApp/Instagram bot konuşma kaydı.

0488 Cloud API numarasının bir uygulama gelen kutusu yok (mesajlar webhook'a
düşüyor). İsmail'in ne konuşulduğunu görebilmesi için gelen/giden her mesaj
buraya yazılır ve dashboard'da 'Bot Konuşmaları' sayfasında gösterilir.
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from catalog.database import Base


class BotMesaj(Base):
    __tablename__ = "bot_mesaj"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(20))    # whatsapp | instagram
    kullanici: Mapped[str] = mapped_column(String(64))   # gönderen id (WA: telefon, IG: igsid)
    yon: Mapped[str] = mapped_column(String(5))          # gelen | giden
    metin: Mapped[str | None] = mapped_column(Text)
    olusturma: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<BotMesaj {self.platform}:{self.kullanici} {self.yon}>"
