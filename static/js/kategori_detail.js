/* ================================================================
   Etiket Studio · Kategori Detail
   - Satır tıklama → koleksiyondaki ürünlere git
   - Koleksiyon adı düzenleme (kalem → input → kaydet/iptal → DB)
   - Aynı isimde koleksiyon varsa: merge confirm modal
   - EXC / ŞUBE bayrak toggle (takım yokken disabled)
   ================================================================ */

(function () {
  'use strict';

  function getCsrfToken() {
    const el = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return el ? el.value : '';
  }

  // ── 1) Satır tıklama → navigate ─────────────────────────────────────────
  document.querySelectorAll('tr.kol-row').forEach((tr) => {
    tr.addEventListener('click', (e) => {
      // Edit modunda veya bayrak/edit kontrollerine tıklanmışsa nav etme
      if (e.target.closest('.kol-cell.editing')) return;
      if (e.target.closest('.edit-btn')) return;
      if (e.target.closest('.kol-cell__edit')) return;
      if (e.target.closest('.bayrak-btn')) return;
      const href = tr.dataset.href;
      if (href) window.location.href = href;
    });
  });

  // ── 2) Inline edit ──────────────────────────────────────────────────────
  document.querySelectorAll('.kol-cell').forEach((cell) => {
    const view      = cell.querySelector('.kol-cell__view');
    const edit      = cell.querySelector('.kol-cell__edit');
    const nameSpan  = view.querySelector('.koleksiyon-ad');
    const editBtn   = view.querySelector('.edit-btn');
    const input     = edit.querySelector('.kol-edit-input');
    const saveBtn   = edit.querySelector('.kol-save-btn');
    const cancelBtn = edit.querySelector('.kol-cancel-btn');
    const msg       = edit.querySelector('.kol-edit-msg');
    const id        = cell.dataset.id;

    function enterEdit(e) {
      if (e) { e.stopPropagation(); e.preventDefault(); }
      input.value = nameSpan.textContent.trim();
      msg.textContent = '';
      cell.classList.add('editing');
      setTimeout(() => { input.focus(); input.select(); }, 10);
    }

    function exitEdit() {
      cell.classList.remove('editing');
      msg.textContent = '';
    }

    async function save({ confirmMerge = false } = {}) {
      const yeniAd = input.value.trim();
      if (!yeniAd) { msg.textContent = 'Boş olamaz'; input.focus(); return; }
      if (yeniAd === nameSpan.textContent.trim()) { exitEdit(); return; }

      saveBtn.disabled = true; cancelBtn.disabled = true;
      msg.textContent = '';
      try {
        const res = await fetch(`/app/koleksiyon/${id}/rename/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
            'Accept': 'application/json',
          },
          credentials: 'same-origin',
          body: JSON.stringify({ ad: yeniAd, confirm_merge: confirmMerge }),
        });
        const payload = await res.json().catch(() => ({}));

        // Çakışma → merge onayı iste
        if (res.status === 409 && payload.requires_merge) {
          openMergeModal(payload, async () => {
            // tekrar dene confirm_merge=true ile
            await save({ confirmMerge: true });
          });
          return;
        }

        if (!res.ok || payload.ok === false) {
          msg.textContent = payload.error || 'Kaydedilemedi';
          input.focus();
          return;
        }

        if (payload.merged) {
          // Kaynak koleksiyon silindi → satırı DOM'dan kaldır + sayfayı yenile (sayım güncellensin)
          window.location.reload();
          return;
        }

        nameSpan.textContent = payload.ad;
        exitEdit();
      } catch (err) {
        msg.textContent = 'Bağlantı hatası';
      } finally {
        saveBtn.disabled = false; cancelBtn.disabled = false;
      }
    }

    editBtn?.addEventListener('click', enterEdit);
    saveBtn?.addEventListener('click', (e) => { e.stopPropagation(); save(); });
    cancelBtn?.addEventListener('click', (e) => { e.stopPropagation(); exitEdit(); });
    input?.addEventListener('click', (e) => e.stopPropagation());
    input?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter')   { e.preventDefault(); save(); }
      else if (e.key === 'Escape') { e.preventDefault(); exitEdit(); }
    });
  });

  // ── 3) Merge modal ──────────────────────────────────────────────────────
  const modal = document.getElementById('merge-modal');
  const modalSourceName  = document.getElementById('merge-source-name');
  const modalSourceName2 = document.getElementById('merge-source-name2');
  const modalSourceCount = document.getElementById('merge-source-count');
  const modalTargetName  = document.getElementById('merge-target-name');
  const modalConfirmBtn  = document.getElementById('merge-confirm');
  let pendingMergeConfirm = null;

  function openMergeModal(payload, onConfirm) {
    if (!modal) return;
    modalSourceName.textContent  = payload.source?.ad ?? '—';
    modalSourceName2.textContent = payload.source?.ad ?? '—';
    modalSourceCount.textContent = payload.source?.urun_sayisi ?? 0;
    modalTargetName.textContent  = payload.target?.ad ?? '—';
    pendingMergeConfirm = onConfirm;
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
    setTimeout(() => modalConfirmBtn?.focus(), 50);
  }

  function closeMergeModal() {
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
    pendingMergeConfirm = null;
  }

  modalConfirmBtn?.addEventListener('click', () => {
    const cb = pendingMergeConfirm;
    closeMergeModal();
    if (cb) cb();
  });

  modal?.querySelectorAll('[data-modal-close]').forEach((el) => {
    el.addEventListener('click', closeMergeModal);
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal && !modal.hidden) closeMergeModal();
  });

  // ── 4) Bayrak (EXC / ŞUBE) toggle ───────────────────────────────────────
  document.querySelectorAll('.bayrak-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (btn.disabled) return;

      const group = btn.closest('.bayrak-group');
      const koleksiyonId = group?.dataset.id;
      const bayrak = btn.dataset.bayrak;
      const wasActive = btn.classList.contains('is-active');
      const newValue  = !wasActive;

      // Optimistic UI
      btn.classList.toggle('is-active', newValue);
      btn.setAttribute('aria-pressed', newValue ? 'true' : 'false');
      btn.disabled = true;

      try {
        const res = await fetch(`/app/koleksiyon/${koleksiyonId}/bayrak/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
            'Accept': 'application/json',
          },
          credentials: 'same-origin',
          body: JSON.stringify({ bayrak, value: newValue }),
        });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok || payload.ok === false) {
          // revert
          btn.classList.toggle('is-active', wasActive);
          btn.setAttribute('aria-pressed', wasActive ? 'true' : 'false');
          alert(payload.error || 'Bayrak güncellenemedi');
        }
      } catch (err) {
        btn.classList.toggle('is-active', wasActive);
        btn.setAttribute('aria-pressed', wasActive ? 'true' : 'false');
        alert('Bağlantı hatası');
      } finally {
        btn.disabled = false;
      }
    });
  });
})();
