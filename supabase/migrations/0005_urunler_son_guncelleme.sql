-- ════════════════════════════════════════════════════════════════════
-- 0005 — urunler.olusturma_tarihi → urunler.son_guncelleme
--
-- Sebep: Scraper artık fiyat değişimini (≥70 TL fark) bu kolona
-- yazıyor. "Olusturma" semantik olarak yanıltıcıydı; gerçek anlamı
-- "son güncelleme" — hem yaratma hem fiyat değişimini kapsar.
--
-- Sadece urunler tablosu etkilenir. Diğer tablolardaki
-- olusturma_tarihi (kategoriler, koleksiyonlar, kombinasyonlar,
-- kategori_kurali) dokunulmaz.
-- ════════════════════════════════════════════════════════════════════

alter table public.urunler
  rename column olusturma_tarihi to son_guncelleme;
