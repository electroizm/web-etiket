-- ════════════════════════════════════════════════════════════════════
-- 0018 — koleksiyonlar.video_url + teshir.video_url (YouTube tanıtım videosu)
--
-- Sebep: İsmail'in kendi YouTube kanalında koleksiyon videoları var
-- ("Doğtaş Bend Yemek Odası Takımı" — Güneşler Doğtaş Mobilya). Fotoğraf
-- ürünü gösteriyor, video ölçeği/kumaş hareketini/gerçek hâlini gösteriyor.
--
-- Tasarım kararları:
--  * VİDEO DOSYASI DEĞİL, YouTube LİNKİ (İsmail kararı 2026-08-02).
--    Alternatif (mp4'ü Supabase Storage'a koyup sohbet içinde oynatmak)
--    tartışıldı ve elendi: WhatsApp linkten çektiği videoda 16 MB sınırı
--    var, Render ücretsiz katmanında video sıkıştıracak araç YOK, dolayısıyla
--    telefonla çekilen 1080p+ video reddedilmek zorunda kalırdı.
--    Link yolunda boyut sınırı yok ve bant genişliğini YouTube karşılıyor.
--    Bedeli: müşteri videoyu izlemek için WhatsApp'tan çıkıyor.
--  * Tek metin kolonu — kayıt başına BİR video yeter (fotoğrafta 4 açı
--    gerekiyordu çünkü teşhir malının hâli parça parça görülür; video zaten
--    her açıyı tek seferde gösterir).
--  * KANONİK biçimde saklanır (https://www.youtube.com/watch?v=<id>).
--    Panel 'shorts/', 'youtu.be/', 'embed/' ve '?feature=share' gibi
--    biçimleri kabul edip bu hâle çevirir; WhatsApp önizleme kartını
--    kanonik adreste daha güvenilir üretiyor.
--  * İKİ TABLO: koleksiyonlar (262 kayıt — katalog sorana ulaşır) ve
--    teshir (15 kayıt). İsmail kararı: ikisi de olsun.
--
-- Geri alma:
--   alter table public.koleksiyonlar drop column video_url;
--   alter table public.teshir        drop column video_url;
-- ════════════════════════════════════════════════════════════════════

alter table public.koleksiyonlar
  add column if not exists video_url text;

alter table public.teshir
  add column if not exists video_url text;

comment on column public.koleksiyonlar.video_url is
  'Koleksiyonun YouTube tanıtım videosu, kanonik biçim (watch?v=<id>). NULL = video yok, bot videodan hiç bahsetmez.';
comment on column public.teshir.video_url is
  'Teşhir kaydının YouTube videosu, kanonik biçim. NULL = video yok.';
