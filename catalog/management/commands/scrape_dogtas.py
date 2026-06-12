"""
Django management command — Doğtaş katalog scraper.

Kullanım:
    python manage.py scrape_dogtas                        # tüm katalog
    python manage.py scrape_dogtas --max-pages 1 --dry-run   # ilk 1 sayfa, DB'ye yazma
    python manage.py scrape_dogtas --max-pages 3              # ilk 3 sayfa
    python manage.py scrape_dogtas --start-page 5             # 5. sayfadan devam
"""
import asyncio
import logging
import sys
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Doğtaş kataloğunu tarar ve Supabase'e yazar."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-pages", type=int, default=None,
            help="İlk N sayfa (test için). Belirtilmezse tüm katalog.",
        )
        parser.add_argument(
            "--start-page", type=int, default=1,
            help="Hangi sayfadan başla (kalınan yerden devam için).",
        )
        parser.add_argument(
            "--concurrency", type=int, default=None,
            help="Eşzamanlı istek sayısı. Default: settings.SCRAPER_CONCURRENCY",
        )
        parser.add_argument(
            "--delay-min", type=float, default=None,
            help="İstekler arası min bekleme (sn). Default: settings.SCRAPER_RATE_DELAY_MIN",
        )
        parser.add_argument(
            "--delay-max", type=float, default=None,
            help="İstekler arası max bekleme (sn). Default: settings.SCRAPER_RATE_DELAY_MAX",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="DB'ye yazma, sadece raporla (transaction ROLLBACK).",
        )

    def handle(self, *args, **opts):
        # UTF-8 stdout (Windows konsolu cp1254 olabilir)
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")

        # Logging — INFO seviyesi, düz format
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
            force=True,
        )

        # DATABASE_URL kontrolü erken
        if not settings.DATABASE_URL:
            self.stderr.write(self.style.ERROR(
                "HATA: DATABASE_URL .env içinde tanımlı değil.\n"
                "  Supabase Dashboard → Project Settings → Database → Connection string (URI, Session mode)\n"
                "  Aldığın URL'in başına 'postgresql+psycopg2://' ekle (yoksa).\n"
                "  Örnek: postgresql+psycopg2://postgres:SIFREN@db.<ref>.supabase.co:5432/postgres"
            ))
            sys.exit(1)

        # Geç import — Django settings yüklenmeden SQLAlchemy modelleri açılmasın
        from catalog.services.bildirim import scrape_raporu_mesaji, telegram_gonder
        from catalog.services.scraper import DogtasScraper, db_upsert

        scraper = DogtasScraper(
            concurrency=opts["concurrency"] or settings.SCRAPER_CONCURRENCY,
            delay_min=opts["delay_min"] if opts["delay_min"] is not None else settings.SCRAPER_RATE_DELAY_MIN,
            delay_max=opts["delay_max"] if opts["delay_max"] is not None else settings.SCRAPER_RATE_DELAY_MAX,
        )

        baslangic = datetime.now()
        self.stdout.write(self.style.NOTICE(
            f"Doğtaş katalog tarama başlıyor "
            f"(max_pages={opts['max_pages']}, start_page={opts['start_page']}, dry_run={opts['dry_run']})"
        ))

        try:
            sonuclar = asyncio.run(scraper.tarama_yap(
                max_pages=opts["max_pages"],
                start_page=opts["start_page"],
            ))

            sure = (datetime.now() - baslangic).total_seconds()
            basarili = sum(1 for s in sonuclar if s.basarili)
            self.stdout.write(self.style.SUCCESS(
                f"Scrape tamam ({sure:.0f}s) — {basarili}/{len(sonuclar)} başarılı"
            ))

            rapor = db_upsert(sonuclar, dry_run=opts["dry_run"])
        except Exception as e:
            # Hata bildirimi — sonra yine de yükselt ki exit code ≠ 0 olsun
            telegram_gonder(f"❌ Doğtaş taraması HATA ile durdu:\n{type(e).__name__}: {e}")
            raise

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== DB RAPORU ==="))
        for k, v in rapor.items():
            self.stdout.write(f"  {k:20} : {v}")

        if not opts["dry_run"]:
            telegram_gonder(scrape_raporu_mesaji(
                rapor, sure_sn=sure, basarili=basarili, toplam=len(sonuclar),
            ))
