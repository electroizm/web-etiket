-- ════════════════════════════════════════════════════════════════════
-- 0017 — teshir.fotograflar (mağazadaki gerçek malın fotoğrafları)
--
-- Sebep: teşhir ürünü katalog fotoğrafındaki fabrika çekiminden BAŞKA bir
-- şeydir — sergilenmiş, kullanılmış olabilir, kumaş/renk farklı olabilir,
-- son parçadır. Müşteri teşhir fiyatını duyunca "gerçekte nasıl görünüyor?"
-- diye soruyor; botun gönderecek bir şeyi yoktu.
--
-- Tasarım kararları:
--  * JSONB dizi — İsmail kararı 2026-08-02: kayıt başına 2-4 AÇI. Teşhir
--    malı kullanılmış olabildiği için müşteri kolu/arkası/yakın çekimi
--    görmek istiyor. Sıra korunur: ilk eleman ana fotoğraftır.
--    (JSONB projede zaten kullanılıyor: kombinasyon_kurali.patterns.)
--  * İçerik: Supabase Storage'daki PUBLIC URL'ler. Dosyanın kendisi DB'ye
--    KONMAZ — base64 gömme Supabase ücretsiz katmanını şişirir.
--    Bucket: etiket-assets (zaten vardı, public), klasör: teshir/<id>/.
--  * WhatsApp/Instagram fotoğrafı bizden dosya olarak almaz, verdiğimiz
--    LİNKTEN kendisi indirir — bu yüzden URL public olmak zorunda.
--    Fotoğraflar mağaza ürünü, gizli veri değil.
--  * NOT NULL + default '[]': okuyan kod None kontrolü yapmasın.
--
-- Geri alma:  alter table public.teshir drop column fotograflar;
-- ════════════════════════════════════════════════════════════════════

alter table public.teshir
  add column if not exists fotograflar jsonb not null default '[]'::jsonb;

comment on column public.teshir.fotograflar is
  'Mağazadaki teşhirin fotoğraf URL''leri (Supabase Storage, public). Sıralı dizi; ilk eleman ana fotoğraf. Boş dizi = fotoğraf yok.';
