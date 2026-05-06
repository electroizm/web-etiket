"""SQLAlchemy 2.0 — engine, session factory, declarative base.

Bu modül, scraper'ın Supabase Postgres'e direct connection ile
yazabilmesi için SQLAlchemy katmanını kurar. Django'nun ORM'i ile
paralel çalışır (Django'nun kendi DB'si ayrı; SQLite varsayılanı).

DATABASE_URL Django settings'ten okunur (settings.DATABASE_URL).
"""
from collections.abc import Generator

from django.conf import settings
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def _make_engine():
    if not settings.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL .env içinde tanımlı değil. "
            "Supabase Project Settings → Database → Connection string (URI, Session mode) "
            "değerini al, başına 'postgresql+psycopg2://' ekle, .env'ye DATABASE_URL=... olarak yapıştır."
        )
    return create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False,
    )


# Lazy-init: settings.DATABASE_URL boşsa import-time'da hata vermesin
_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = _make_engine()
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _SessionLocal


def SessionLocal() -> Session:
    """Yeni bir SQLAlchemy session aç. Kullanan kapatmaktan sorumlu."""
    return get_session_factory()()


class Base(DeclarativeBase):
    """Tüm SQLAlchemy modellerinin temeli."""
    pass


def get_db() -> Generator[Session, None, None]:
    """Context manager / dependency tarzı kullanım için."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
