-- ════════════════════════════════════════════════════════════════════
-- 0002 — Koleksiyon: takım + bayraklar (EXC, ŞUBE)
--
-- Yeni alanlar:
--   takim_adi    text NULL          → koleksiyona bağlı takım adı (sonraki adımda doldurulacak)
--   bayrak_exc   bool default false → EXC mağazada var mı
--   bayrak_sube  bool default false → ŞUBE mağazada var mı
--
-- UI mantığı:
--   - takim_adi boşsa → bayrak butonları disabled (henüz takım atanmamış)
--   - takim_adi doluysa → EXC/ŞUBE toggle edilebilir, ilerleride PDF filtresi için kullanılır
-- ════════════════════════════════════════════════════════════════════

alter table public.koleksiyonlar
  add column if not exists takim_adi    text,
  add column if not exists bayrak_exc   boolean not null default false,
  add column if not exists bayrak_sube  boolean not null default false;

-- İleride sık sorgulamak için index (filtreleme açıldığında)
create index if not exists ix_koleksiyonlar_bayrak_exc  on public.koleksiyonlar(bayrak_exc)  where bayrak_exc  = true;
create index if not exists ix_koleksiyonlar_bayrak_sube on public.koleksiyonlar(bayrak_sube) where bayrak_sube = true;
