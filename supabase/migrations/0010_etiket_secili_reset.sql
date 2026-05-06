-- ════════════════════════════════════════════════════════════════════
-- 0010 — etiket_secili: tüm mevcut TRUE'ları FALSE'a çek (tek seferlik)
--
-- Sebep: 0008'de varsayılan TRUE ile yaratılmış olan kayıtlar var.
-- 0009 default'u FALSE yaptı ama mevcut TRUE'lar dokunulmadı.
-- Kullanıcı her koleksiyonu temiz başlatmak istiyor: PDF için ürün
-- ve kombinasyon seçimleri sıfırdan, ihtiyaç oldukça eklenecek.
--
-- DİKKAT: Bu migration yıkıcıdır. Daha önce manuel olarak işaretlenmiş
-- ürün/kombinasyonlar (49 koleksiyondaki tüm seçimler) sıfırlanır.
-- Tek tek koleksiyona girip yeniden seçim yapman gerekir.
-- ════════════════════════════════════════════════════════════════════

update public.urun_koleksiyon set etiket_secili = false where etiket_secili = true;
update public.kombinasyonlar    set etiket_secili = false where etiket_secili = true;
