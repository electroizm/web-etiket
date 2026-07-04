-- ════════════════════════════════════════════════════════════════════
-- 0014 — bot_kisi (bot müşterilerinin profil bilgisi)
--
-- /app/bot gelen kutusunda çıplak id yerine isim/foto göstermek için:
--   WhatsApp : ad webhook'un contacts[].profile.name alanından gelir
--              (Meta, müşteri fotoğrafını Cloud API'ye vermez — foto yok).
--   Instagram: ad + kullanıcı adı + profil fotoğrafı Graph API'den çekilir
--              (GET /{igsid}?fields=name,username,profile_pic).
-- ════════════════════════════════════════════════════════════════════

create table if not exists public.bot_kisi (
  id             bigserial primary key,
  platform       text not null,            -- whatsapp | instagram
  kullanici      text not null,            -- WA: telefon, IG: igsid
  ad             text,                     -- görünen ad (WA pushname / IG name)
  kullanici_adi  text,                     -- IG username (osm_gns gibi); WA'da null
  foto_url       text,                     -- IG profil foto CDN URL (süreli); WA'da null
  guncelleme     timestamptz not null default now(),
  unique (platform, kullanici)
);

alter table public.bot_kisi enable row level security;

drop policy if exists "bot_kisi_all" on public.bot_kisi;
create policy "bot_kisi_all" on public.bot_kisi
  for all to authenticated using (true) with check (true);
