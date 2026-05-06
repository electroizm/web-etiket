/* ================================================================
   Etiket Studio · Forgot Password JS
   ================================================================ */
(function () {
  'use strict';
  const A = window.EtiketAuth;

  const form       = document.getElementById('forgot-form');
  const emailInput = document.getElementById('email');
  const submitBtn  = document.getElementById('submit-btn');

  if (!form) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    A.hideStatus();

    const email = (emailInput?.value || '').trim();
    if (!A.isValidEmail(email)) {
      A.showStatus('Lütfen geçerli bir e-posta adresi girin.', 'error');
      emailInput?.focus(); return;
    }

    A.setLoading(submitBtn, true);
    try {
      const supabase = await A.waitForSupabase();
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: window.location.origin + '/accounts/login/',
      });
      if (error) throw new Error(error.message);

      A.showStatus(
        'Bağlantı gönderildi. Gelen kutunu (ve spam klasörünü) kontrol et.',
        'success'
      );
      form.reset();
    } catch (err) {
      A.showStatus(err?.message || 'İstek gönderilemedi.', 'error');
    } finally {
      A.setLoading(submitBtn, false);
    }
  });
})();
