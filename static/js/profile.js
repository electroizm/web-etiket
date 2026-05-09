/* ================================================================
   Profile · İsim ve şifre güncelleme.

   Tüm Auth çağrıları SERVER-SIDE Django endpoint'leri üzerinden:
   /accounts/api/profile/update-name/
   /accounts/api/profile/change-password/

   Bu sayede browser'daki Supabase JS session'ına bağımlı değiliz
   (Django session yeterli). Şifre değişiminde mevcut şifre
   server'da Supabase /auth/v1/token ile doğrulanır.
   ================================================================ */
(function () {
  'use strict';
  const A = window.EtiketAuth;

  const userEl = document.getElementById('topbar-user');

  // Logout
  document.getElementById('logout-btn')?.addEventListener('click', () => A.logout());

  // Toggle-eye butonları
  document.querySelectorAll('.toggle-eye[data-target]').forEach((btn) => {
    const input = document.getElementById(btn.dataset.target);
    if (input) A.bindPasswordToggle(btn, input);
  });

  // Status helpers (her form için ayrı kutu)
  function showLocalStatus(boxId, message, type) {
    const box = document.getElementById(boxId);
    if (!box) return;
    box.textContent = message;
    box.dataset.type = type || 'info';
    box.hidden = false;
  }
  function hideLocalStatus(boxId) {
    const box = document.getElementById(boxId);
    if (!box) return;
    box.hidden = true;
    box.textContent = '';
    delete box.dataset.type;
  }

  function setBtnLoading(btn, loading, label) {
    if (!btn) return;
    btn.disabled = loading;
    const lbl = btn.querySelector('.btn-label');
    if (lbl && label) lbl.textContent = label;
  }

  async function postJson(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': A.getCsrfToken(),
        'Accept': 'application/json',
      },
      credentials: 'same-origin',
      body: JSON.stringify(body),
    });
    const payload = await res.json().catch(() => ({}));
    return { ok: res.ok && payload.ok !== false, status: res.status, payload };
  }

  // ── İsim güncelleme ────────────────────────────────────────────────
  const adForm  = document.getElementById('ad-form');
  const adInput = document.getElementById('full_name');
  const adBtn   = document.getElementById('ad-submit');

  adForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideLocalStatus('ad-status');

    const yeniAd = (adInput?.value || '').trim();
    if (!yeniAd) {
      showLocalStatus('ad-status', 'Ad Soyad boş olamaz.', 'error');
      adInput?.focus();
      return;
    }
    if (yeniAd.length > 120) {
      showLocalStatus('ad-status', 'Ad Soyad en fazla 120 karakter olabilir.', 'error');
      return;
    }

    setBtnLoading(adBtn, true, 'Güncelleniyor…');
    try {
      const { ok, payload } = await postJson(
        '/accounts/api/profile/update-name/',
        { full_name: yeniAd },
      );
      if (!ok) {
        showLocalStatus('ad-status', payload.error || 'Güncelleme başarısız.', 'error');
        return;
      }
      showLocalStatus('ad-status', 'Ad başarıyla güncellendi.', 'success');
      if (userEl) userEl.textContent = yeniAd;  // topbar anlık
    } catch (err) {
      showLocalStatus('ad-status', 'Bağlantı hatası.', 'error');
    } finally {
      setBtnLoading(adBtn, false, 'Adı Soyadı Güncelle');
    }
  });

  // ── Şifre değiştirme ───────────────────────────────────────────────
  const sifreForm = document.getElementById('sifre-form');
  const mevcutEl  = document.getElementById('mevcut_sifre');
  const yeniEl    = document.getElementById('yeni_sifre');
  const tekrarEl  = document.getElementById('yeni_sifre_tekrar');
  const sifreBtn  = document.getElementById('sifre-submit');

  sifreForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideLocalStatus('sifre-status');

    const mevcut = mevcutEl?.value || '';
    const yeni   = yeniEl?.value   || '';
    const tekrar = tekrarEl?.value || '';

    if (!mevcut) {
      showLocalStatus('sifre-status', 'Mevcut şifreyi gir.', 'error');
      mevcutEl?.focus(); return;
    }
    if (yeni.length < 8) {
      showLocalStatus('sifre-status', 'Yeni şifre en az 8 karakter olmalı.', 'error');
      yeniEl?.focus(); return;
    }
    if (yeni !== tekrar) {
      showLocalStatus('sifre-status', 'Yeni şifreler eşleşmiyor.', 'error');
      tekrarEl?.focus(); return;
    }
    if (yeni === mevcut) {
      showLocalStatus('sifre-status', 'Yeni şifre eskisi ile aynı olamaz.', 'error');
      yeniEl?.focus(); return;
    }

    setBtnLoading(sifreBtn, true, 'Şifre değiştiriliyor…');
    try {
      const { ok, payload } = await postJson(
        '/accounts/api/profile/change-password/',
        { current_password: mevcut, new_password: yeni },
      );
      if (!ok) {
        showLocalStatus('sifre-status', payload.error || 'Şifre güncellenemedi.', 'error');
        return;
      }
      showLocalStatus('sifre-status', 'Şifre başarıyla güncellendi.', 'success');
      sifreForm.reset();
    } catch (err) {
      showLocalStatus('sifre-status', 'Bağlantı hatası.', 'error');
    } finally {
      setBtnLoading(sifreBtn, false, 'Şifreyi Güncelle');
    }
  });
})();
