-- ════════════════════════════════════════════════════════════════════
-- 0016 — urunler.son_toptan_fiyat + toplu güncelleme RPC'si
--
-- Sebep: 10 haneli, '3' ile başlayan SAP kodlu ürünlerin bayi alış
-- (toptan) fiyatı. Kaynak: PRG Fiyat Robotu'nun SAP CRM'den hesaplattığı
-- "Tutar" değeri (PRG Supabase raporlar/fiyat). Robot koşusunun sonunda
-- urun_toptan_guncelle RPC'si ile buraya itilir.
--
-- Tasarım kararları:
--  * Değer TAM SAYI TL (kuruş yuvarlanır) — projedeki fiyat konvansiyonu.
--  * son_guncelleme'ye DOKUNULMAZ: o kolon etiket yazdırma filtresini
--    sürer; toptan değişimi etiket basımını tetiklememeli (etikette
--    toptan fiyat yoktur). Tazelik takibi için ayrı kolon:
--    son_toptan_guncelleme = bu SKU'nun toptanı en son ne zaman sync'lendi.
--  * UI'da HİÇBİR yerde gösterilmez (kullanıcı kararı 2026-07-11);
--    veri instALL botu / iç hesaplar içindir.
--  * RPC'nin EXECUTE yetkisi anon/authenticated'dan alınır — yalnız
--    service_role (PRG robotu) çağırabilir.
-- ════════════════════════════════════════════════════════════════════

alter table public.urunler
  add column if not exists son_toptan_fiyat integer,
  add column if not exists son_toptan_guncelleme timestamptz;

comment on column public.urunler.son_toptan_fiyat is
  'Bayi alış (toptan) fiyatı, tam TL. Kaynak: PRG Fiyat Robotu (SAP Tutar). UI''da gösterilmez.';
comment on column public.urunler.son_toptan_guncelleme is
  'son_toptan_fiyat en son ne zaman sync''lendi (PRG robot koşusu).';

-- Toplu güncelleme: [{"sku": "3200422655", "toptan": 4293}, ...] alır,
-- SKU eşleşen satırları günceller, güncellenen satır sayısını döner.
-- Eşleşmeyen SKU'lar (Mikro'ya özel, urunler'de olmayan) sessizce atlanır.
create or replace function public.urun_toptan_guncelle(p_fiyatlar jsonb)
returns integer
language sql
security definer
set search_path = public
as $$
  with gelen as (
    select distinct on (e->>'sku')
           e->>'sku'            as sku,
           (e->>'toptan')::int  as toptan
    from jsonb_array_elements(p_fiyatlar) e
    where coalesce(e->>'sku', '') <> ''
      and (e->>'toptan')::int > 0
  ),
  guncellenen as (
    update public.urunler u
       set son_toptan_fiyat      = g.toptan,
           son_toptan_guncelleme = now()
      from gelen g
     where u.sku = g.sku
    returning u.id
  )
  select count(*)::int from guncellenen;
$$;

revoke execute on function public.urun_toptan_guncelle(jsonb)
  from public, anon, authenticated;
