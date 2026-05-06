/* ================================================================
   Etiket Studio · Auth Common Helpers
   login.js / signup.js / forgot_password.js içinden kullanılır.
   ================================================================ */

window.EtiketAuth = (function () {
  'use strict';

  function getCsrfToken() {
    const el = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return el ? el.value : '';
  }

  function isValidEmail(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  }

  function showStatus(message, type) {
    const box = document.getElementById('status');
    if (!box) return;
    box.textContent = message;
    box.dataset.type = type || 'info';
    box.hidden = false;
  }

  function hideStatus() {
    const box = document.getElementById('status');
    if (!box) return;
    box.hidden = true;
    box.textContent = '';
    delete box.dataset.type;
  }

  function setLoading(btn, loading) {
    if (!btn) return;
    btn.dataset.loading = loading ? 'true' : 'false';
    btn.disabled = loading;
  }

  /** Şifre alanı için göz simgesi toggle */
  function bindPasswordToggle(toggleBtn, input) {
    if (!toggleBtn || !input) return;
    const eyeOn  = toggleBtn.querySelector('.eye-on');
    const eyeOff = toggleBtn.querySelector('.eye-off');
    toggleBtn.addEventListener('click', () => {
      const isHidden = input.type === 'password';
      input.type = isHidden ? 'text' : 'password';
      toggleBtn.setAttribute('aria-label', isHidden ? 'Şifreyi gizle' : 'Şifreyi göster');
      if (eyeOn && eyeOff) { eyeOn.hidden = isHidden; eyeOff.hidden = !isHidden; }
      input.focus({ preventScroll: true });
    });
  }

  /** Şifre gücü 0–4 arası bir skor döner */
  function passwordScore(pw) {
    let score = 0;
    if (!pw) return 0;
    if (pw.length >= 8) score++;
    if (pw.length >= 12) score++;
    if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) score++;
    if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) score++;
    return Math.min(score, 4);
  }

  /** Supabase JS client hazır olana kadar bekler (max 3sn) */
  function waitForSupabase(timeoutMs = 3000) {
    return new Promise((resolve, reject) => {
      if (window.supabase) return resolve(window.supabase);
      const t = setTimeout(() => {
        window.removeEventListener('supabase:ready', onReady);
        reject(new Error('Supabase istemcisi yüklenemedi. .env yapılandırmasını kontrol edin.'));
      }, timeoutMs);
      function onReady() {
        clearTimeout(t);
        window.removeEventListener('supabase:ready', onReady);
        resolve(window.supabase);
      }
      window.addEventListener('supabase:ready', onReady);
    });
  }

  /** Supabase access_token'ı Django'ya gönderir, session kurulur. */
  async function syncSessionWithDjango(accessToken) {
    const res = await fetch('/accounts/api/session/sync/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
        'Accept': 'application/json',
      },
      credentials: 'same-origin',
      body: JSON.stringify({ access_token: accessToken }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) {
      throw new Error(payload.error || 'Sunucu oturumu kurulamadı.');
    }
    return payload;
  }

  /** Logout: hem Supabase JS hem Django session temizlenir. */
  async function logout() {
    try {
      if (window.supabase) await window.supabase.auth.signOut();
    } catch (e) { /* ignore */ }
    try {
      const res = await fetch('/accounts/api/session/clear/', {
        method: 'POST',
        headers: { 'X-CSRFToken': getCsrfToken(), 'Accept': 'application/json' },
        credentials: 'same-origin',
      });
      const payload = await res.json().catch(() => ({}));
      window.location.href = payload.redirect || '/accounts/login/';
    } catch (e) {
      window.location.href = '/accounts/login/';
    }
  }

  return {
    getCsrfToken,
    isValidEmail,
    showStatus,
    hideStatus,
    setLoading,
    bindPasswordToggle,
    passwordScore,
    waitForSupabase,
    syncSessionWithDjango,
    logout,
  };
})();
