-- ════════════════════════════════════════════════════════════════════
-- 0013 — bot_mesaj (WhatsApp/Instagram bot konuşma kaydı)
--
-- 0488 Cloud API numarasının uygulama gelen kutusu yok; gelen/giden her
-- mesaj buraya yazılır, dashboard 'Bot Konuşmaları' sayfasında gösterilir.
-- yon: 'gelen' (müşteri) | 'giden' (bot).
-- ════════════════════════════════════════════════════════════════════

create table if not exists public.bot_mesaj (
  id         bigserial primary key,
  platform   text not null,          -- whatsapp | instagram
  kullanici  text not null,          -- gönderen id (WA: telefon, IG: igsid)
  yon        text not null,          -- gelen | giden
  metin      text,
  olusturma  timestamptz not null default now()
);

create index if not exists bot_mesaj_kullanici_idx on public.bot_mesaj (kullanici, olusturma desc);
create index if not exists bot_mesaj_olusturma_idx on public.bot_mesaj (olusturma desc);

-- RLS — authenticated kullanıcılar okuyabilir/yazabilir (direct connection zaten bypass eder)
alter table public.bot_mesaj enable row level security;

drop policy if exists "bot_mesaj_all" on public.bot_mesaj;
create policy "bot_mesaj_all" on public.bot_mesaj
  for all to authenticated using (true) with check (true);
