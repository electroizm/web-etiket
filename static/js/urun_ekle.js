/* ================================================================
   Etiket Studio · Koleksiyona ürün ekle
   - Input'a yazıldıkça (debounce 300ms) JSON search endpoint'ini çağır
   - 3 karakter altında: liste boş, hint göster
   - Sonuç satırında + butonu → POST → koleksiyon sayfasına dön
   ================================================================ */

(function () {
  'use strict';

  const MIN_LEN = 3;
  const DEBOUNCE_MS = 300;

  function getCsrfToken() {
    const el = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return el ? el.value : '';
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function fmtFiyat(perakende, liste) {
    const v = perakende || liste;
    if (!v) return '<span class="cell-empty">—</span>';
    return `${Math.round(v).toLocaleString('tr-TR')} ₺`;
  }

  const filters = document.querySelector('.urun-ekle-filters');
  if (!filters) return;

  const searchUrl     = filters.dataset.searchUrl;
  const addUrl        = filters.dataset.addUrl;
  const koleksiyonHref = filters.dataset.koleksiyonHref;
  const input         = document.getElementById('urun-ekle-q');
  const statusEl      = document.getElementById('urun-ekle-status');
  const listEl        = document.getElementById('urun-ekle-results');

  // ── Render helpers ──────────────────────────────────────────────────
  function showStatus(html) {
    statusEl.innerHTML = html;
    statusEl.hidden = false;
    listEl.hidden = true;
    listEl.innerHTML = '';
  }

  function showResults(items) {
    if (!items.length) {
      showStatus('<p class="urun-ekle-status__msg">Eşleşen ürün yok. Aramayı değiştirip dene.</p>');
      return;
    }
    statusEl.innerHTML = '';
    statusEl.hidden = true;
    listEl.innerHTML = items.map(u => `
      <li class="urun-ekle-row">
        <button type="button" class="urun-ekle-row__btn" data-urun-id="${u.id}"
                title="Bu ürünü koleksiyona ekle">
          <span class="urun-ekle-row__sku">${escapeHtml(u.sku)}</span>
          <span class="urun-ekle-row__ad">${escapeHtml(u.urun_adi_tam)}</span>
          <span class="urun-ekle-row__fiyat">${fmtFiyat(u.son_perakende_fiyat, u.son_liste_fiyat)}</span>
          <span class="urun-ekle-row__add" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 5v14"/><path d="M5 12h14"/>
            </svg>
          </span>
        </button>
      </li>
    `).join('');
    listEl.hidden = false;
  }

  // ── Search (debounced) ──────────────────────────────────────────────
  let searchTimer = null;
  let activeController = null;

  function scheduleSearch() {
    const q = input.value.trim();

    if (q.length === 0) {
      showStatus('<p class="urun-ekle-status__msg">En az 3 karakter yazarak aramaya başla.</p>');
      return;
    }
    if (q.length < MIN_LEN) {
      showStatus(`<p class="urun-ekle-status__msg">${MIN_LEN - q.length} karakter daha…</p>`);
      return;
    }

    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => runSearch(q), DEBOUNCE_MS);
  }

  async function runSearch(q) {
    if (activeController) activeController.abort();
    activeController = new AbortController();

    showStatus('<p class="urun-ekle-status__msg">Aranıyor…</p>');
    try {
      const url = `${searchUrl}?q=${encodeURIComponent(q)}`;
      const res = await fetch(url, {
        signal: activeController.signal,
        headers: { 'Accept': 'application/json' },
        credentials: 'same-origin',
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok || data.ok === false) {
        showStatus(`<p class="urun-ekle-status__msg" style="color:#ffb4b4;">${escapeHtml(data.error || 'Arama başarısız')}</p>`);
        return;
      }

      // Yarış durumu: kullanıcı son sorguyu değiştirmiş olabilir
      if (input.value.trim() !== q) return;
      showResults(data.results || []);
    } catch (err) {
      if (err.name === 'AbortError') return;
      showStatus('<p class="urun-ekle-status__msg" style="color:#ffb4b4;">Bağlantı hatası.</p>');
    }
  }

  input.addEventListener('input', scheduleSearch);
  // İlk yüklemede hint
  scheduleSearch();

  // ── Add handler (event delegation) ──────────────────────────────────
  listEl.addEventListener('click', async (e) => {
    const btn = e.target.closest('.urun-ekle-row__btn');
    if (!btn) return;
    const urunId = btn.dataset.urunId;
    if (!urunId) return;

    btn.disabled = true;
    btn.style.opacity = '0.5';

    const fd = new FormData();
    fd.append('urun_id', urunId);
    fd.append('csrfmiddlewaretoken', getCsrfToken());

    try {
      const res = await fetch(addUrl, {
        method: 'POST',
        body: fd,
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': getCsrfToken() },
      });
      // Backend redirect yapıyor — fetch redirect'i takip eder.
      // res.ok true olur; biz her durumda koleksiyon sayfasına döneriz.
      if (res.ok || res.redirected) {
        window.location.href = koleksiyonHref;
        return;
      }
      btn.disabled = false;
      btn.style.opacity = '';
      showStatus('<p class="urun-ekle-status__msg" style="color:#ffb4b4;">Ekleme başarısız oldu.</p>');
    } catch (err) {
      btn.disabled = false;
      btn.style.opacity = '';
      showStatus('<p class="urun-ekle-status__msg" style="color:#ffb4b4;">Bağlantı hatası.</p>');
    }
  });
})();
