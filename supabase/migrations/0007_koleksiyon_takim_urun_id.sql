-- ════════════════════════════════════════════════════════════════════
-- 0007 — koleksiyonlar.takim_urun_id
--
-- Sebep: Etiket PDF'inde QR kodun URL'i, koleksiyona atanan "takım
-- ürününün" url alanından gelir. Şimdiye kadar sadece takim_adi
-- (string) saklanıyordu, hangi SKU/ürün olduğu kayıtlı değildi.
--
-- Yeni alan: takim_urun_id → urunler.id (nullable, ON DELETE SET NULL).
-- Ürün silindiğinde koleksiyon kayıtlarını silmeyelim.
-- ════════════════════════════════════════════════════════════════════

alter table public.koleksiyonlar
  add column if not exists takim_urun_id integer
    references public.urunler(id) on delete set null;

create index if not exists ix_koleksiyonlar_takim_urun_id
  on public.koleksiyonlar(takim_urun_id);
