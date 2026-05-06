-- ════════════════════════════════════════════════════════════════════
-- 0009 — etiket_secili defaults: TRUE → FALSE
--
-- Sebep: PDF etiketinde 15 satır limiti var. Yeni eklenen ürün veya
-- yeni yaratılan kombinasyon otomatik işaretli gelirse, kullanıcının
-- haberi olmadan limit aşılabiliyor.
--
-- Çözüm: yeni eklenenler default FALSE → kullanıcı isteyerek seçer.
-- Mevcut kayıtlar dokunulmuyor (TRUE'lar TRUE kalır).
-- ════════════════════════════════════════════════════════════════════

alter table public.urun_koleksiyon
  alter column etiket_secili set default false;

alter table public.kombinasyonlar
  alter column etiket_secili set default false;
