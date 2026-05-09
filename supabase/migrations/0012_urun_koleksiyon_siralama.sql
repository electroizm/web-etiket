-- ════════════════════════════════════════════════════════════════════
-- 0012 — urun_koleksiyon: siralama (per-koleksiyon manuel sıra)
--
-- Yeni alan:
--   siralama integer not null default 0
--     → Bu (urun, koleksiyon) eşleşmesinin koleksiyon içindeki sırası.
--       Drag-and-drop ile kullanıcı manuel sıralar. Kombinasyon.sira ile
--       aynı pattern, ama burada per-koleksiyon (M2M satırı başına).
--
-- Backfill:
--   Mevcut satırlar için her koleksiyon başına 0..N atanır. İlk sıralama,
--   kullanıcının şu an gördüğü düzene yakın olsun diye:
--     etiket_secili DESC, urun_adi_tam ASC, urun.id ASC
--   ile bağlanır.
-- ════════════════════════════════════════════════════════════════════

alter table public.urun_koleksiyon
  add column if not exists siralama integer not null default 0;

with sirali as (
  select
    uk.urun_id, uk.koleksiyon_id,
    (row_number() over (
      partition by uk.koleksiyon_id
      order by uk.etiket_secili desc, u.urun_adi_tam asc, u.id asc
    ))::int - 1 as yeni_sira
  from public.urun_koleksiyon uk
  join public.urunler u on u.id = uk.urun_id
)
update public.urun_koleksiyon uk
   set siralama = sirali.yeni_sira
  from sirali
 where uk.urun_id       = sirali.urun_id
   and uk.koleksiyon_id = sirali.koleksiyon_id;

-- Listeleme query'sinin (koleksiyon filtreli) hızlı sıralı taraması için
create index if not exists ix_urun_koleksiyon_siralama
  on public.urun_koleksiyon(koleksiyon_id, siralama);
