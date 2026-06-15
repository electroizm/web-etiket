"""
Django management command — DATABASE_URL teşhis + bağlantı testi.

Kullanım:
    python manage.py db_check

DATABASE_URL'i parse eder (username/host/port göster, password maskele),
ardından SQLAlchemy ile bağlanmaya dener ve tabloları sayar.
"""
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "DATABASE_URL'i parse eder ve Supabase Postgres bağlantısını test eder."

    def handle(self, *args, **opts):
        url = settings.DATABASE_URL or ""
        if not url:
            self.stderr.write(self.style.ERROR("HATA: settings.DATABASE_URL boş. .env'i kontrol et."))
            return

        # ── 1) URL parse ─────────────────────────────────────────────────
        u = urlparse(url)
        pw = u.password or ""
        masked = (pw[:2] + "*" * max(0, len(pw) - 2)) if pw else None

        self.stdout.write(self.style.NOTICE("═══ DATABASE_URL parse ═══"))
        self.stdout.write(f"  scheme  : {u.scheme!r}")
        self.stdout.write(f"  username: {u.username!r}")
        self.stdout.write(f"  password: {masked!r}  (uzunluk={len(pw)})")
        self.stdout.write(f"  host    : {u.hostname!r}")
        self.stdout.write(f"  port    : {u.port}")
        self.stdout.write(f"  database: {u.path.lstrip('/')!r}")
        self.stdout.write("")

        # ── 2) Doğrulama hints ───────────────────────────────────────────
        self.stdout.write(self.style.NOTICE("═══ Beklenen değerler ═══"))
        ok = True

        if u.scheme not in ("postgresql+psycopg2", "postgresql"):
            self.stderr.write(self.style.ERROR(
                f"  ✗ scheme {u.scheme!r} olmamalı — 'postgresql+psycopg2' bekleniyor."
            ))
            ok = False
        else:
            self.stdout.write(self.style.SUCCESS(f"  ✓ scheme: {u.scheme}"))

        if u.hostname and "pooler.supabase.com" in u.hostname:
            self.stdout.write(self.style.SUCCESS(f"  ✓ host: pooler kullanılıyor"))
        elif u.hostname and ".supabase.co" in (u.hostname or ""):
            self.stderr.write(self.style.ERROR(
                f"  ✗ host: direct connection ({u.hostname}) — IPv4 ev internetinde çalışmaz.\n"
                "    Supabase → Database → Session pooler URL'i kullan."
            ))
            ok = False

        if u.username and "." in (u.username or ""):
            self.stdout.write(self.style.SUCCESS(
                f"  ✓ username: pooler formatında ({u.username})"
            ))
        else:
            self.stderr.write(self.style.ERROR(
                f"  ✗ username: {u.username!r} — pooler için 'postgres.<project_ref>' olmalı.\n"
                "    Örnek: postgres.pogmresaofixmdnatxzp"
            ))
            ok = False

        if u.port == 5432:
            self.stdout.write(self.style.SUCCESS(f"  ✓ port: 5432 (Session pooler)"))
        elif u.port == 6543:
            self.stdout.write(self.style.WARNING(
                f"  ! port: 6543 (Transaction pooler). Session pooler 5432 önerilir."
            ))
        else:
            self.stderr.write(self.style.ERROR(f"  ✗ port: {u.port} — 5432 (session) veya 6543 (transaction) olmalı."))
            ok = False

        if not pw:
            self.stderr.write(self.style.ERROR("  ✗ password: boş!"))
            ok = False
        else:
            problemli = set("@:/?#%& ")
            kotu = sorted(set(pw) & problemli)
            if kotu:
                self.stderr.write(self.style.WARNING(
                    f"  ! password: özel karakter içeriyor ({''.join(kotu)}) — URL'yi bozabilir.\n"
                    "    Çözüm: Supabase → Database → Reset password → 'Generate' ile sade üret."
                ))
            else:
                self.stdout.write(self.style.SUCCESS(f"  ✓ password: {len(pw)} karakter, özel karakter yok"))

        self.stdout.write("")

        if not ok:
            self.stdout.write(self.style.ERROR("═══ Yukarıdakileri düzeltmeden bağlantı denemesi yapmıyorum ═══"))
            return

        # ── 3) Gerçek bağlantı denemesi ──────────────────────────────────
        self.stdout.write(self.style.NOTICE("═══ Bağlantı testi ═══"))
        try:
            from sqlalchemy import select
            from catalog.database import SessionLocal
            from catalog.sa_models import Fiyat, Kategori, Koleksiyon, Urun

            session = SessionLocal()
            try:
                # Sayım
                from sqlalchemy import func
                stats = {
                    "kategoriler":   session.scalar(select(func.count()).select_from(Kategori)) or 0,
                    "koleksiyonlar": session.scalar(select(func.count()).select_from(Koleksiyon)) or 0,
                    "urunler":       session.scalar(select(func.count()).select_from(Urun)) or 0,
                    "fiyatlar":      session.scalar(select(func.count()).select_from(Fiyat)) or 0,
                }
                self.stdout.write(self.style.SUCCESS("  ✓ Bağlantı başarılı, tablolar erişilebilir."))
                for k, v in stats.items():
                    self.stdout.write(f"    {k:14}: {v}")
            finally:
                session.close()
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"  ✗ Bağlantı / sorgu hatası:"))
            self.stderr.write(f"    {type(e).__name__}: {e}")
