-- ════════════════════════════════════════════════════════════════════
-- 0011 — app_ayarlari (uygulama genel ayar key-value)
--
-- İlk kullanım: PDF etiketinde başlıkta gösterilen "Doğtaş'ta Bahar
-- Fırsatları" slogan görselinin Supabase Storage URL'i.
--
-- Anahtar örnekleri:
--   'etiket_slogan_url'    → https://...storage/.../slogan/aktif.png?v=...
--
-- İleride dipnot, varsayılan kdv oranı vs. eklenebilir.
-- ════════════════════════════════════════════════════════════════════

create table if not exists public.app_ayarlari (
  anahtar             text primary key,
  deger               text,
  guncellenme_tarihi  timestamptz not null default now()
);

-- RLS — authenticated kullanıcılar okuyabilir/yazabilir
alter table public.app_ayarlari enable row level security;

drop policy if exists "ayarlar_select" on public.app_ayarlari;
create policy "ayarlar_select" on public.app_ayarlari
  for select to authenticated using (true);

drop policy if exists "ayarlar_write" on public.app_ayarlari;
create policy "ayarlar_write" on public.app_ayarlari
  for all to authenticated using (true) with check (true);
