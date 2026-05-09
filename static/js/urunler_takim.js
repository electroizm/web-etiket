/* ================================================================
   Etiket Studio · Ürünler Listesi · Takım Seçim Modalı
   - "Takım Seç" / "Değiştir" butonu → modal aç
   - Modal: aday ürünleri fetch et (SKU 1xxxxx ya da 3xxxxxxxxx)
   - Listede bir ürüne tıkla → onun adı bu koleksiyonun takım_adi olur
   - "Kaldır" butonu → takım sıfırlanır (bayraklar da resetlenir)
   ================================================================ */

(function () {
  'use strict';

  function getCsrfToken() {
    const el = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return el ? el.value : '';
  }

  const banner = document.querySelector('.takim-banner');
  if (!banner) return;
  const koleksiyonId = banner.dataset.koleksiyonId;

  // ── PDF satır limiti (sert) ─────────────────────────────────────
  const ETIKET_MAX_SATIR = 15;

  function countUrunSecili() {
    return document.querySelectorAll('.urun-card[data-secili="1"]').length;
  }
  function countKombiSecili() {
    return document.querySelectorAll('.kombi-list__item[data-etiket-secili="1"]').length;
  }
  /**
   * Yeni bir checkbox işaretlenmek üzereyken (cb.checked === true) çağır.
   * Toplam (mevcut işaretliler + bu) > 15 ise işareti geri alır,
   * uyarı gösterir ve true döner (= bloklandı). Aksi halde false döner.
   * Çıkarma (uncheck) işlemleri her zaman geçer.
   */
  function blockIfOverLimit(cb) {
    if (!cb.checked) return false;  // unchecking: serbest
    const yeniTotal = countUrunSecili() + countKombiSecili() + 1;
    if (yeniTotal > ETIKET_MAX_SATIR) {
      cb.checked = false;
      alert(
        `PDF etiketinde en fazla ${ETIKET_MAX_SATIR} satır olabilir.\n` +
        `Yeni bir tane işaretlemek için önce başka bir ürün veya ` +
        `kombinasyonun işaretini kaldır.`
      );
      return true;
    }
    return false;
  }

  const pickBtn   = document.getElementById('takim-pick-btn');
  const clearBtn  = document.getElementById('takim-clear-btn');
  const modal     = document.getElementById('takim-modal');
  const subtitle  = document.getElementById('takim-modal-subtitle');
  const loading   = document.getElementById('takim-modal-loading');
  const listEl    = document.getElementById('takim-modal-list');
  const emptyEl   = document.getElementById('takim-modal-empty');

  // ── Modal aç/kapat ──────────────────────────────────────────────
  function openModal() {
    if (!modal) return;
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
  }
  function closeModal() {
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
  }

  modal?.querySelectorAll('[data-modal-close]').forEach((el) => {
    el.addEventListener('click', closeModal);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal && !modal.hidden) closeModal();
  });

  // ── Aday ürünleri çek ──────────────────────────────────────────
  async function loadCandidates() {
    listEl.hidden = true;
    emptyEl.hidden = true;
    loading.hidden = false;
    listEl.innerHTML = '';

    try {
      const res = await fetch(`/app/koleksiyon/${koleksiyonId}/takim-candidates/`, {
        headers: { 'Accept': 'application/json' },
        credentials: 'same-origin',
      });
      const payload = await res.json().catch(() => ({}));
      loading.hidden = true;

      if (!res.ok || payload.ok === false) {
        emptyEl.hidden = false;
        emptyEl.querySelector('p strong').textContent = payload.error || 'Adaylar yüklenemedi.';
        return;
      }

      const candidates = payload.candidates || [];
      if (candidates.length === 0) {
        emptyEl.hidden = false;
        return;
      }

      // Subtitle: hangi pattern eşleşti
      const tip = payload.match_type === '1-6'
        ? 'SKU 1xxxxx (6 hane) ile eşleşen takım adayları'
        : 'SKU 3xxxxxxxxx (10 hane) ile eşleşen ürünler';
      subtitle.textContent = tip;

      // Listeyi render et — sade: sadece ürün adı
      candidates.forEach((c) => {
        const li = document.createElement('li');
        li.className = 'takim-candidates__item';
        li.dataset.ad = c.ad;
        li.dataset.urunId = c.id;
        li.innerHTML = `<div class="takim-candidates__ad">${escapeHtml(c.ad)}</div>`;
        li.addEventListener('click', () => selectTakim(c.ad, c.id, li));
        listEl.appendChild(li);
      });
      listEl.hidden = false;
    } catch (err) {
      loading.hidden = true;
      emptyEl.hidden = false;
      emptyEl.querySelector('p strong').textContent = 'Bağlantı hatası';
    }
  }

  // ── Takım atama ────────────────────────────────────────────────
  async function selectTakim(takimAdi, takimUrunId, liEl) {
    if (liEl) liEl.classList.add('is-saving');
    try {
      const res = await fetch(`/app/koleksiyon/${koleksiyonId}/takim/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken(),
          'Accept': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({ takim_adi: takimAdi, takim_urun_id: takimUrunId }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok || payload.ok === false) {
        alert(payload.error || 'Takım kaydedilemedi');
        if (liEl) liEl.classList.remove('is-saving');
        return;
      }
      // Sayfayı yenile — banner ve kategori sayfası güncel görünür
      window.location.reload();
    } catch (err) {
      alert('Bağlantı hatası');
      if (liEl) liEl.classList.remove('is-saving');
    }
  }

  // ── Takımı kaldır ──────────────────────────────────────────────
  async function clearTakim() {
    if (!confirm('Takımı kaldırmak istediğinden emin misin? EXC ve ŞUBE bayrakları da sıfırlanacak.')) return;
    try {
      const res = await fetch(`/app/koleksiyon/${koleksiyonId}/takim/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken(),
          'Accept': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({ takim_adi: '' }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok || payload.ok === false) {
        alert(payload.error || 'Takım kaldırılamadı');
        return;
      }
      window.location.reload();
    } catch (err) {
      alert('Bağlantı hatası');
    }
  }

  // ── Helpers ────────────────────────────────────────────────────
  function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s || '';
    return div.innerHTML;
  }

  // ── Wire up ────────────────────────────────────────────────────
  pickBtn?.addEventListener('click', () => {
    openModal();
    loadCandidates();
  });
  clearBtn?.addEventListener('click', clearTakim);

  // ── Ürün ızgarası — manuel sıra DB'de tutuluyor (urun_koleksiyon.siralama).
  // Drag-and-drop kullanıcı kontrollü; checkbox değişimi sırayı bozmuyor.
  const grid = document.getElementById('urun-grid');

  // ── Etiket seçim checkbox'ları (her ürün kartı) ───────────────
  document.querySelectorAll('.urun-secim-input').forEach((cb) => {
    cb.addEventListener('change', async (e) => {
      // 15 satır sert limiti — yeni işaretlemeyi engelle
      if (blockIfOverLimit(cb)) return;

      const urunId = cb.dataset.urunId;
      const kid    = cb.dataset.koleksiyonId;
      const value  = cb.checked;
      const card   = cb.closest('.urun-card');

      // Optimistic UI
      card?.classList.toggle('is-deselected', !value);
      if (card) card.dataset.secili = value ? '1' : '0';
      cb.disabled = true;

      try {
        const res = await fetch(`/app/koleksiyon/${kid}/urun/${urunId}/etiket-secimi/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
            'Accept': 'application/json',
          },
          credentials: 'same-origin',
          body: JSON.stringify({ secili: value }),
        });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok || payload.ok === false) {
          // revert
          cb.checked = !value;
          card?.classList.toggle('is-deselected', value);
          if (card) card.dataset.secili = value ? '0' : '1';
          alert(payload.error || 'Seçim kaydedilemedi');
        }
      } catch (err) {
        cb.checked = !value;
        card?.classList.toggle('is-deselected', value);
        if (card) card.dataset.secili = value ? '0' : '1';
        alert('Bağlantı hatası');
      } finally {
        cb.disabled = false;
      }
    });
  });

  // ── Ürün kaldır (X) butonu ────────────────────────────────────
  const kaldirModal      = document.getElementById('kaldir-modal');
  const kaldirAdEl       = document.getElementById('kaldir-urun-ad');
  const kaldirErrorEl    = document.getElementById('kaldir-modal-error');
  const kaldirConfirmBtn = document.getElementById('kaldir-confirm');
  let pendingKaldir = null;  // { urunId, kid, card }

  function openKaldirModal() {
    if (!kaldirModal) return;
    kaldirModal.hidden = false;
    kaldirModal.setAttribute('aria-hidden', 'false');
  }
  function closeKaldirModal() {
    if (!kaldirModal) return;
    kaldirModal.hidden = true;
    kaldirModal.setAttribute('aria-hidden', 'true');
    if (kaldirErrorEl) { kaldirErrorEl.hidden = true; kaldirErrorEl.textContent = ''; }
    pendingKaldir = null;
    if (kaldirConfirmBtn) {
      kaldirConfirmBtn.disabled = false;
      kaldirConfirmBtn.textContent = 'Kaldır';
    }
  }

  kaldirModal?.querySelectorAll('[data-modal-close]').forEach((el) => {
    el.addEventListener('click', closeKaldirModal);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && kaldirModal && !kaldirModal.hidden) closeKaldirModal();
  });

  document.querySelectorAll('.urun-kaldir-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const card = btn.closest('.urun-card');
      const cb   = card?.querySelector('.urun-secim-input');
      const ad   = card?.dataset.urunAd || 'Ürün';

      pendingKaldir = {
        urunId: btn.dataset.urunId,
        kid: btn.dataset.koleksiyonId,
        card,
      };
      if (kaldirAdEl) kaldirAdEl.textContent = ad;
      if (kaldirConfirmBtn) kaldirConfirmBtn.textContent = 'Kaldır';

      // İşaretliyse modal'ı aç ama uyar + Kaldır'ı kilitle
      if (cb && cb.checked) {
        if (kaldirErrorEl) {
          kaldirErrorEl.textContent = 'Bu ürün etiket için işaretli. Önce kart üzerindeki kutucuğun işaretini kaldırın.';
          kaldirErrorEl.hidden = false;
        }
        if (kaldirConfirmBtn) kaldirConfirmBtn.disabled = true;
      } else {
        if (kaldirErrorEl) { kaldirErrorEl.hidden = true; kaldirErrorEl.textContent = ''; }
        if (kaldirConfirmBtn) kaldirConfirmBtn.disabled = false;
      }
      openKaldirModal();
    });
  });

  kaldirConfirmBtn?.addEventListener('click', async () => {
    if (!pendingKaldir) return;
    const { urunId, kid, card } = pendingKaldir;
    kaldirConfirmBtn.disabled = true;
    kaldirConfirmBtn.textContent = 'Kaldırılıyor…';
    try {
      const res = await fetch(`/app/koleksiyon/${kid}/urun/${urunId}/kaldir/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken(),
          'Accept': 'application/json',
        },
        credentials: 'same-origin',
        body: '{}',
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok || payload.ok === false) {
        let msg = payload.error || 'Ürün kaldırılamadı.';
        if (payload.reason === 'kombinasyon' && Array.isArray(payload.kombinasyonlar)) {
          const adlar = payload.kombinasyonlar.map((k) => k.ad).join(', ');
          msg = `Bu ürün şu kombinasyon(lar)da kullanılıyor: ${adlar}. Önce kombinasyondan çıkarın.`;
        }
        if (kaldirErrorEl) {
          kaldirErrorEl.textContent = msg;
          kaldirErrorEl.hidden = false;
        } else {
          alert(msg);
        }
        kaldirConfirmBtn.disabled = false;
        kaldirConfirmBtn.textContent = 'Kaldır';
        return;
      }
      // Başarılı → kartı DOM'dan kaldır
      card?.remove();
      closeKaldirModal();
    } catch (err) {
      if (kaldirErrorEl) {
        kaldirErrorEl.textContent = 'Bağlantı hatası';
        kaldirErrorEl.hidden = false;
      }
      kaldirConfirmBtn.disabled = false;
      kaldirConfirmBtn.textContent = 'Kaldır';
    }
  });

  // ── Ürün adı inline düzenleme (kategori_detail.js ile aynı pattern) ──────
  document.querySelectorAll('.urun-title-cell').forEach((cell) => {
    const view      = cell.querySelector('.urun-title-cell__view');
    const edit      = cell.querySelector('.urun-title-cell__edit');
    const nameEl    = view.querySelector('.urun-ad-text');
    const editBtn   = view.querySelector('.urun-edit-btn');
    const input     = edit.querySelector('.urun-edit-input');
    const saveBtn   = edit.querySelector('.urun-save-btn');
    const cancelBtn = edit.querySelector('.urun-cancel-btn');
    const msg       = edit.querySelector('.urun-edit-msg');
    const urunId    = cell.dataset.urunId;

    function enterEdit(e) {
      if (e) { e.stopPropagation(); e.preventDefault(); }
      input.value = nameEl.textContent.trim();
      msg.textContent = '';
      cell.classList.add('editing');
      setTimeout(() => { input.focus(); input.select(); }, 10);
    }

    function exitEdit() {
      cell.classList.remove('editing');
      msg.textContent = '';
    }

    async function save() {
      const yeniAd = input.value.trim();
      if (!yeniAd) { msg.textContent = 'Boş olamaz'; input.focus(); return; }
      if (yeniAd === nameEl.textContent.trim()) { exitEdit(); return; }

      saveBtn.disabled = true;
      cancelBtn.disabled = true;
      msg.textContent = '';
      try {
        const res = await fetch(`/app/urun/${urunId}/rename/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
            'Accept': 'application/json',
          },
          credentials: 'same-origin',
          body: JSON.stringify({ ad: yeniAd }),
        });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok || payload.ok === false) {
          msg.textContent = payload.error || 'Kaydedilemedi';
          input.focus();
          return;
        }

        nameEl.textContent = payload.ad;
        nameEl.setAttribute('title', payload.ad);
        // Kart üzerindeki data-urun-ad da güncellensin (sort + diğer handler'lar kullanıyor)
        const card = cell.closest('.urun-card');
        if (card) card.dataset.urunAd = payload.ad;
        exitEdit();
      } catch (err) {
        msg.textContent = 'Bağlantı hatası';
      } finally {
        saveBtn.disabled = false;
        cancelBtn.disabled = false;
      }
    }

    editBtn?.addEventListener('click', enterEdit);
    saveBtn?.addEventListener('click', (e) => { e.stopPropagation(); save(); });
    cancelBtn?.addEventListener('click', (e) => { e.stopPropagation(); exitEdit(); });
    input?.addEventListener('click', (e) => e.stopPropagation());
    input?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter')        { e.preventDefault(); save(); }
      else if (e.key === 'Escape')  { e.preventDefault(); exitEdit(); }
    });
  });

  // ── Kombinasyon: PDF etiket checkbox + ↑↓ sıralama ───────────────────────
  const kombiList = document.getElementById('kombi-list');
  const satirSayacEl = document.getElementById('etiket-satir-deger');
  const satirSayacWrap = document.getElementById('etiket-satir-sayac');

  function urunSeciliCount() {
    return document.querySelectorAll('.urun-card[data-secili="1"]').length;
  }

  function kombiSeciliCount() {
    return document.querySelectorAll('.kombi-list__item[data-etiket-secili="1"]').length;
  }

  function refreshSatirSayac() {
    const total = urunSeciliCount() + kombiSeciliCount();
    if (satirSayacEl) satirSayacEl.textContent = total;
    if (satirSayacWrap) {
      satirSayacWrap.classList.toggle('etiket-satir-sayac--asildi', total > 15);
    }
    // PDF butonu: 0 işaret varsa disabled (anlamsız boş etiket önle)
    const pdfBtn = document.getElementById('pdf-btn');
    if (pdfBtn) {
      const disabled = total === 0;
      pdfBtn.classList.toggle('is-disabled', disabled);
      pdfBtn.setAttribute('aria-disabled', disabled ? 'true' : 'false');
      pdfBtn.title = disabled
        ? 'En az bir ürün veya kombinasyon işaretlemelisin'
        : "Bu koleksiyon için fiyat etiketi PDF'i üret";
    }
  }

  // PDF butonu disabled görünüyorsa tıklamayı engelle (a etiketi href'i bypass eder)
  document.getElementById('pdf-btn')?.addEventListener('click', (e) => {
    const btn = e.currentTarget;
    if (btn.classList.contains('is-disabled')) {
      e.preventDefault();
      alert('En az bir ürün veya kombinasyon işaretlemelisin.');
    }
  });
  // İlk yüklemede say
  refreshSatirSayac();

  // Ürün checkbox değişimlerinde de sayıyı güncelle (etiket_secili sort handler'ı zaten çalışıyor)
  document.addEventListener('change', (e) => {
    if (e.target.matches('.urun-secim-input')) {
      // urun_takim sort handler kart data-secili'yi güncelliyor → bekle ve say
      setTimeout(refreshSatirSayac, 50);
    }
  });

  if (kombiList) {
    // Kombinasyon etiket_secili toggle
    kombiList.addEventListener('change', async (e) => {
      const cb = e.target.closest('.kombi-etiket-input');
      if (!cb) return;

      // 15 satır sert limiti — yeni işaretlemeyi engelle
      if (blockIfOverLimit(cb)) return;

      const item = cb.closest('.kombi-list__item');
      const kombiId = cb.dataset.kombiId;
      const yeni = cb.checked;
      const eski = item.dataset.etiketSecili === '1';

      // Optimistik
      item.dataset.etiketSecili = yeni ? '1' : '0';
      refreshSatirSayac();

      try {
        const res = await fetch(`/app/kombinasyon/${kombiId}/etiket-toggle/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
            'Accept': 'application/json',
          },
          credentials: 'same-origin',
          body: JSON.stringify({ value: yeni }),
        });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok || payload.ok === false) {
          // Revert
          cb.checked = eski;
          item.dataset.etiketSecili = eski ? '1' : '0';
          refreshSatirSayac();
          alert(payload.error || 'Güncellenemedi');
        }
      } catch (err) {
        cb.checked = eski;
        item.dataset.etiketSecili = eski ? '1' : '0';
        refreshSatirSayac();
        alert('Bağlantı hatası');
      }
    });

    // Drag-and-drop ile sıralama (handle: ☰)
    // Strateji: row her zaman draggable=true, ama dragstart sadece handle'dan
    // başlatılırsa kabul edilir (mousedown ile target'i takip et).
    let dragSourceAllowed = false;
    let draggedItem = null;

    kombiList.addEventListener('mousedown', (e) => {
      dragSourceAllowed = !!e.target.closest('.kombi-drag-handle');
    });
    // Touch için (mobil)
    kombiList.addEventListener('touchstart', (e) => {
      dragSourceAllowed = !!e.target.closest('.kombi-drag-handle');
    }, { passive: true });

    kombiList.querySelectorAll('.kombi-list__item').forEach((it) => {
      it.setAttribute('draggable', 'true');
    });

    kombiList.addEventListener('dragstart', (e) => {
      const item = e.target.closest('.kombi-list__item');
      if (!item || !dragSourceAllowed) {
        e.preventDefault();
        return;
      }
      draggedItem = item;
      item.classList.add('is-dragging');
      // Drag image olarak satırı kullan (handle değil)
      try {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', item.dataset.kombiId);
      } catch (_) {}
    });

    kombiList.addEventListener('dragend', () => {
      if (draggedItem) draggedItem.classList.remove('is-dragging');
      kombiList.querySelectorAll('.is-drag-over').forEach(el => el.classList.remove('is-drag-over'));
      draggedItem = null;
      dragSourceAllowed = false;
    });

    kombiList.addEventListener('dragover', (e) => {
      if (!draggedItem) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      const over = e.target.closest('.kombi-list__item');
      if (!over || over === draggedItem) return;

      // Hover satırını işaretle (görsel feedback)
      kombiList.querySelectorAll('.is-drag-over').forEach(el => el.classList.remove('is-drag-over'));
      over.classList.add('is-drag-over');

      // İmleç satırın üst yarısındaysa öncesine, alt yarısındaysa sonrasına yerleştir
      const rect = over.getBoundingClientRect();
      const before = (e.clientY - rect.top) < rect.height / 2;
      if (before) over.parentNode.insertBefore(draggedItem, over);
      else over.parentNode.insertBefore(draggedItem, over.nextSibling);
    });

    kombiList.addEventListener('drop', async (e) => {
      e.preventDefault();
      if (!draggedItem) return;

      kombiList.querySelectorAll('.is-drag-over').forEach(el => el.classList.remove('is-drag-over'));
      draggedItem.classList.remove('is-dragging');
      const movedItem = draggedItem;
      draggedItem = null;
      dragSourceAllowed = false;

      const koleksiyonId = kombiList.dataset.koleksiyonId;
      const ids = Array.from(kombiList.querySelectorAll('.kombi-list__item'))
        .map(it => parseInt(it.dataset.kombiId, 10));

      try {
        const res = await fetch(`/app/koleksiyon/${koleksiyonId}/kombinasyon-sira/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
            'Accept': 'application/json',
          },
          credentials: 'same-origin',
          body: JSON.stringify({ ids }),
        });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok || payload.ok === false) {
          alert(payload.error || 'Sıralama kaydedilemedi');
          // Sayfayı yenile — DB ile UI uyumsuzluğunu yansıt
          window.location.reload();
        }
      } catch (err) {
        alert('Bağlantı hatası');
        window.location.reload();
      }
    });
  }

  // ── Ürün ızgarası: drag-and-drop sıralama (handle: ≡) ────────────────────
  // Pattern: .kombi-list ile aynı (mousedown handle takibi → dragstart koşullu).
  // Fark: grid 2D olduğu için before/after kararı X+Y'ye göre verilir.
  if (grid) {
    let urunDragAllowed = false;
    let urunDragged = null;

    grid.addEventListener('mousedown', (e) => {
      urunDragAllowed = !!e.target.closest('.urun-drag-handle');
    });
    grid.addEventListener('touchstart', (e) => {
      urunDragAllowed = !!e.target.closest('.urun-drag-handle');
    }, { passive: true });

    grid.querySelectorAll('.urun-card').forEach((card) => {
      card.setAttribute('draggable', 'true');
    });

    grid.addEventListener('dragstart', (e) => {
      const card = e.target.closest('.urun-card');
      if (!card || !urunDragAllowed) {
        e.preventDefault();
        return;
      }
      urunDragged = card;
      card.classList.add('is-dragging');
      try {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', card.dataset.urunId);
      } catch (_) {}
    });

    grid.addEventListener('dragend', () => {
      if (urunDragged) urunDragged.classList.remove('is-dragging');
      grid.querySelectorAll('.is-drag-over').forEach(el => el.classList.remove('is-drag-over'));
      urunDragged = null;
      urunDragAllowed = false;
    });

    grid.addEventListener('dragover', (e) => {
      if (!urunDragged) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      const over = e.target.closest('.urun-card');
      if (!over || over === urunDragged) return;

      grid.querySelectorAll('.is-drag-over').forEach(el => el.classList.remove('is-drag-over'));
      over.classList.add('is-drag-over');

      // 2D grid: aynı satırdaysa X karar verir, değilse Y.
      // Aynı satır = imleç Y'si over kartının dikey aralığında.
      const rect = over.getBoundingClientRect();
      const sameRow = e.clientY >= rect.top && e.clientY <= rect.bottom;
      const before = sameRow
        ? e.clientX < rect.left + rect.width / 2
        : e.clientY < rect.top  + rect.height / 2;
      if (before) over.parentNode.insertBefore(urunDragged, over);
      else        over.parentNode.insertBefore(urunDragged, over.nextSibling);
    });

    grid.addEventListener('drop', async (e) => {
      e.preventDefault();
      if (!urunDragged) return;

      grid.querySelectorAll('.is-drag-over').forEach(el => el.classList.remove('is-drag-over'));
      urunDragged.classList.remove('is-dragging');
      urunDragged = null;
      urunDragAllowed = false;

      const koleksiyonId = grid.dataset.koleksiyonId;
      const ids = Array.from(grid.querySelectorAll('.urun-card'))
        .map(c => parseInt(c.dataset.urunId, 10));

      try {
        const res = await fetch(`/app/koleksiyon/${koleksiyonId}/urun-sira/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
            'Accept': 'application/json',
          },
          credentials: 'same-origin',
          body: JSON.stringify({ ids }),
        });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok || payload.ok === false) {
          alert(payload.error || 'Sıralama kaydedilemedi');
          window.location.reload();
        }
      } catch (err) {
        alert('Bağlantı hatası');
        window.location.reload();
      }
    });
  }
})();
