-- ════════════════════════════════════════════════════════════════════
-- 0008 — kombinasyonlar.etiket_secili
--
-- Yeni alan: etiket_secili boolean default true
--   → Bu kombinasyon PDF etiketinde gösterilsin mi?
--
-- Mantık (urun_koleksiyon.etiket_secili ile uyumlu):
--   - Default TRUE → kullanıcı çıkarmadıysa etikettedir
--   - Kullanıcı checkbox'ı kaldırırsa FALSE → PDF'e gitmez
--
-- 15 satır limiti UI tarafında: işaretli kombinasyonlar + etiket_secili=true
-- ürünler toplamı 15'i geçerse PDF üretilemez.
-- ════════════════════════════════════════════════════════════════════

alter table public.kombinasyonlar
  add column if not exists etiket_secili boolean not null default true;
