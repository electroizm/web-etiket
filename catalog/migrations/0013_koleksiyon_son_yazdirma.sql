-- 0013: Koleksiyon başına "son etiket yazdırma" zaman damgaları (mağaza bazlı).
-- Etiket Yazdır ekranı, tarih elle seçilmediğinde "fiyatı son basımdan sonra
-- değişen" koleksiyonları bu kolonlarla bulur. NULL = hiç yazdırılmamış.

ALTER TABLE koleksiyonlar
    ADD COLUMN IF NOT EXISTS son_yazdirma_exc  timestamptz NULL,
    ADD COLUMN IF NOT EXISTS son_yazdirma_sube timestamptz NULL;
