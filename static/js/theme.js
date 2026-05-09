/* ================================================================
   Tema yönetimi — light/dark toggle.

   Dosya iki şey yapar:
   1) localStorage'tan temayı oku ve <html data-theme="..."> set et.
      (FOUC önleme için inline script base.html <head>'inde de var;
       bu dosya zaten geç yüklendiğinde tekrar onaylar.)
   2) Topbar'da varsa (.topbar__user içine) bir tema değişim butonu
      yerleştirir; tıklayınca tema değiştirilip kaydedilir.

   Tema değişimi tüm sayfalarda anında geçerli — sayfa yenilenmez.
   ================================================================ */
(function () {
  'use strict';

  const STORAGE_KEY = 'theme';
  const root = document.documentElement;

  function getTheme() {
    try {
      return localStorage.getItem(STORAGE_KEY) || 'dark';
    } catch (_) {
      return 'dark';
    }
  }

  function applyTheme(theme) {
    if (theme === 'light') {
      root.setAttribute('data-theme', 'light');
    } else {
      root.removeAttribute('data-theme');
    }
  }

  function saveTheme(theme) {
    try { localStorage.setItem(STORAGE_KEY, theme); } catch (_) {}
  }

  function toggleTheme() {
    const next = getTheme() === 'light' ? 'dark' : 'light';
    saveTheme(next);
    applyTheme(next);
    updateButton();
  }

  // İlk anda tema uygula (inline script kaçırırsa diye)
  applyTheme(getTheme());

  function buildButton() {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'theme-toggle';
    btn.className = 'btn-ghost theme-toggle';
    btn.setAttribute('aria-label', 'Temayı değiştir');
    btn.title = 'Temayı değiştir';
    btn.innerHTML = `
      <svg class="theme-icon theme-icon--moon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
      </svg>
      <svg class="theme-icon theme-icon--sun" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="4"/>
        <line x1="12" y1="2" x2="12" y2="4"/>
        <line x1="12" y1="20" x2="12" y2="22"/>
        <line x1="4.93" y1="4.93" x2="6.34" y2="6.34"/>
        <line x1="17.66" y1="17.66" x2="19.07" y2="19.07"/>
        <line x1="2" y1="12" x2="4" y2="12"/>
        <line x1="20" y1="12" x2="22" y2="12"/>
        <line x1="4.93" y1="19.07" x2="6.34" y2="17.66"/>
        <line x1="17.66" y1="6.34" x2="19.07" y2="4.93"/>
      </svg>
      <span class="theme-toggle__label">Tema</span>
    `;
    btn.addEventListener('click', toggleTheme);
    return btn;
  }

  function updateButton() {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    btn.setAttribute(
      'aria-label',
      getTheme() === 'light' ? 'Karanlık temaya geç' : 'Aydınlık temaya geç',
    );
  }

  function inject() {
    // Çıkış butonunun bulunduğu container'ı yakala — onun hemen öncesine ekle.
    const logoutBtn = document.getElementById('logout-btn');
    if (!logoutBtn) return;
    if (document.getElementById('theme-toggle')) return; // zaten ekli
    const btn = buildButton();
    logoutBtn.parentNode.insertBefore(btn, logoutBtn);
    updateButton();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inject);
  } else {
    inject();
  }
})();
