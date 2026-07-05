-- ════════════════════════════════════════════════════════════════════
-- 0015 — Bot bilgi tabanı + konuşma durumu
--
-- bot_bilgi : mağaza bilgi kayıtları (adres, mesai, kargo, iade, taksit…).
--             AI ajan operasyonel soruları YALNIZCA buradan cevaplar —
--             uydurma yasak (Antalya adresi halüsinasyonu, 2026-07-06).
-- bot_soru  : DB'de karşılığı olmayan müşteri soruları. İsmail /app/bot/bilgi
--             sayfasından görüp cevaplar → bot ertesi mesajda artık biliyor.
-- bot_kisi  : okundu/çözüldü durumu (panel: okunmamış rozeti, ✓ çözüldü,
--             7 günden eski okunmuş/çözülmüş konuşmaların oto temizliği).
-- ════════════════════════════════════════════════════════════════════

create table if not exists public.bot_bilgi (
  id         bigserial primary key,
  baslik     text not null,              -- konu: "Adres", "Mesai saatleri"
  anahtar    text not null,              -- virgüllü arama kelimeleri: "adres, konum, nerede"
  cevap      text not null,              -- botun müşteriye söyleyeceği metin
  guncelleme timestamptz not null default now()
);

alter table public.bot_bilgi enable row level security;
drop policy if exists "bot_bilgi_all" on public.bot_bilgi;
create policy "bot_bilgi_all" on public.bot_bilgi
  for all to authenticated using (true) with check (true);

create table if not exists public.bot_soru (
  id        bigserial primary key,
  platform  text not null,               -- whatsapp | instagram
  kullanici text not null,               -- soran müşteri (WA: telefon, IG: igsid)
  soru      text not null,
  durum     text not null default 'acik',  -- acik | cevaplandi
  olusturma timestamptz not null default now()
);

alter table public.bot_soru enable row level security;
drop policy if exists "bot_soru_all" on public.bot_soru;
create policy "bot_soru_all" on public.bot_soru
  for all to authenticated using (true) with check (true);

-- Konuşma durumu: son_okunan_id'ye kadarki mesajlar okunmuş sayılır.
alter table public.bot_kisi add column if not exists son_okunan_id bigint;
alter table public.bot_kisi add column if not exists cozuldu boolean not null default false;
