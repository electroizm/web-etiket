/* ================================================================
   Etiket Studio · Login JS
   ================================================================ */
(function () {
  'use strict';
  const A = window.EtiketAuth;

  const form       = document.getElementById('login-form');
  const emailInput = document.getElementById('email');
  const passInput  = document.getElementById('password');
  const remember   = document.getElementById('remember');
  const submitBtn  = document.getElementById('submit-btn');
  const togglePass = document.getElementById('toggle-password');

  if (!form) return;

  A.bindPasswordToggle(togglePass, passInput);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    A.hideStatus();

    const email    = (emailInput?.value || '').trim();
    const password = passInput?.value || '';

    if (!A.isValidEmail(email)) {
      A.showStatus('Lütfen geçerli bir e-posta adresi girin.', 'error');
      emailInput?.focus(); return;
    }
    if (password.length < 6) {
      A.showStatus('Şifre en az 6 karakter olmalıdır.', 'error');
      passInput?.focus(); return;
    }

    A.setLoading(submitBtn, true);
    try {
      const supabase = await A.waitForSupabase();
      const { data, error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw new Error(translateAuthError(error.message));

      const accessToken = data?.session?.access_token;
      if (!accessToken) throw new Error('Oturum bilgisi alınamadı.');

      const sync = await A.syncSessionWithDjango(accessToken);

      A.showStatus('Giriş başarılı, yönlendiriliyorsunuz...', 'success');
      const next = form.dataset.next || sync.redirect || '/app/';
      window.location.href = next;
    } catch (err) {
      A.showStatus(err?.message || 'Beklenmeyen bir hata oluştu.', 'error');
    } finally {
      A.setLoading(submitBtn, false);
    }
  });

  // Caps Lock uyarısı
  passInput?.addEventListener('keyup', (e) => {
    const box = document.getElementById('status');
    if (e.getModifierState && e.getModifierState('CapsLock')) {
      A.showStatus('Caps Lock açık görünüyor.', 'info');
    } else if (box?.dataset.type === 'info' && box.textContent.includes('Caps Lock')) {
      A.hideStatus();
    }
  });

  function translateAuthError(msg) {
    if (!msg) return 'Giriş başarısız.';
    const m = msg.toLowerCase();
    if (m.includes('invalid login credentials')) return 'E-posta veya şifre hatalı.';
    if (m.includes('email not confirmed'))      return 'E-posta adresiniz henüz onaylanmamış.';
    if (m.includes('rate limit'))                return 'Çok fazla deneme yapıldı, lütfen biraz bekleyin.';
    return msg;
  }
})();
