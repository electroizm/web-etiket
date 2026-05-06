-- ════════════════════════════════════════════════════════════════════
-- 0003 — urun_koleksiyon: etiket_secili
--
-- Yeni alan:
--   etiket_secili boolean default true
--     → Bu (urun, koleksiyon) eşleşmesi etikete dahil edilecek mi?
--
-- Mantık:
--   - Default TRUE → kullanıcı seçim yapmamışsa tüm ürünler etikete dahildir
--   - Kullanıcı bir ürünün checkbox'ını kaldırırsa FALSE → etikete dahil edilmez
--   - Scraper yeni satır eklerse default TRUE olarak gelir
-- ════════════════════════════════════════════════════════════════════

alter table public.urun_koleksiyon
  add column if not exists etiket_secili boolean not null default true;

-- Etiket basarken filtrelemek için index
create index if not exists ix_urun_koleksiyon_etiket_secili
  on public.urun_koleksiyon(koleksiyon_id, etiket_secili)
  where etiket_secili = true;
