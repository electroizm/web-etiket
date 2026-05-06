-- ════════════════════════════════════════════════════════════════════
-- 0006 — Ürün adı yaklaşık arama (trigram + TR karakter normalizasyon)
--
-- Amaç: Koleksiyona ürün eklerken kullanıcı tam ad/SKU bilmeden
-- yazdığı parçalara göre eşleşmeli.
--   "ber iera"  → "KIERA Berjer"
--   "kira"      → "KIERA Berjer"  (typo tolere)
--   "BERJER"    → "BEND Berjer"   (case + TR karakter farketmez)
--
-- pg_trgm: trigram bazlı similarity. % operatörü ve similarity()
-- fonksiyonunu sağlar. GIN index ile hızlı.
--
-- tr_norm(): hem 'ı/i, ş/s, ğ/g, ü/u, ö/o, ç/c' eşitliği hem lower()
-- yapar. Türkçe lower() bazı locale'lerde 'İ' → 'i̇' (combining dot)
-- ürettiği için önce translate, sonra lower.
-- ════════════════════════════════════════════════════════════════════

create extension if not exists pg_trgm;

create or replace function public.tr_norm(s text) returns text
language sql
immutable
parallel safe
as $$
  select lower(translate(coalesce(s, ''), 'IİŞĞÜÖÇışğüöç', 'iisguocisguoc'));
$$;

-- GIN trigram index: tr_norm(urun_adi_tam) üzerinde fuzzy/ILIKE arama hızlı
create index if not exists ix_urunler_adi_trgm
  on public.urunler using gin (public.tr_norm(urun_adi_tam) gin_trgm_ops);
