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

  /** Şifre alanı için göz simgesi toggle — tek SVG, .is-revealed class'ı ile
      slash çizgisi gösterilir/gizlenir. */
  function bindPasswordToggle(toggleBtn, input) {
    if (!toggleBtn || !input) return;
    toggleBtn.addEventListener('click', () => {
      const isHidden = input.type === 'password';
      input.type = isHidden ? 'text' : 'password';
      toggleBtn.classList.toggle('is-revealed', isHidden);
      toggleBtn.setAttribute('aria-pressed', isHidden ? 'true' : 'false');
      toggleBtn.setAttribute('aria-label', isHidden ? 'Şifreyi gizle' : 'Şifreyi göster');
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

  /** Logout: hem Supabase JS (localStorage) hem Django session temizlenir.
      /accounts/logout/ endpoint'i GET ile çalışır (CSRF gerektirmez), session
      flush edip login'e yönlendirir. Önceki fetch tabanlı yaklaşım CSRF
      eksikse Django session'ı temizleyemiyordu. */
  async function logout() {
    try {
      if (window.supabase) await window.supabase.auth.signOut();
    } catch (e) { /* yoksay */ }
    window.location.href = '/accounts/logout/';
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
