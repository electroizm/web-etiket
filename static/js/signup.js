/* ================================================================
   Etiket Studio · Signup JS
   ================================================================ */
(function () {
  'use strict';
  const A = window.EtiketAuth;

  const form          = document.getElementById('signup-form');
  const fullNameInput = document.getElementById('full_name');
  const emailInput    = document.getElementById('email');
  const passInput     = document.getElementById('password');
  const pass2Input    = document.getElementById('password2');
  const submitBtn     = document.getElementById('submit-btn');
  const togglePass    = document.getElementById('toggle-password');
  const strengthFill  = document.getElementById('strength-fill');

  if (!form) return;

  A.bindPasswordToggle(togglePass, passInput);

  // Password strength meter
  passInput?.addEventListener('input', () => {
    const score = A.passwordScore(passInput.value);
    if (strengthFill) {
      strengthFill.style.width = (score * 25) + '%';
      strengthFill.dataset.level = String(score);
    }
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    A.hideStatus();

    const fullName = (fullNameInput?.value || '').trim();
    const email    = (emailInput?.value || '').trim();
    const password = passInput?.value || '';
    const password2 = pass2Input?.value || '';

    if (!A.isValidEmail(email)) {
      A.showStatus('Lütfen geçerli bir e-posta adresi girin.', 'error');
      emailInput?.focus(); return;
    }
    if (password.length < 8) {
      A.showStatus('Şifre en az 8 karakter olmalıdır.', 'error');
      passInput?.focus(); return;
    }
    if (password !== password2) {
      A.showStatus('Şifreler eşleşmiyor.', 'error');
      pass2Input?.focus(); return;
    }

    A.setLoading(submitBtn, true);
    try {
      const supabase = await A.waitForSupabase();
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: {
          data: { full_name: fullName || null },
          emailRedirectTo: window.location.origin + '/accounts/login/',
        },
      });
      if (error) throw new Error(translateAuthError(error.message));

      // İki olası akış:
      //   (a) E-posta onayı KAPALI → session anında gelir, doğrudan giriş yap.
      //   (b) E-posta onayı AÇIK   → session yok, kullanıcıya onay maili göndermesini söyle.
      if (data?.session?.access_token) {
        await A.syncSessionWithDjango(data.session.access_token);
        A.showStatus('Hesap oluşturuldu, yönlendiriliyorsunuz...', 'success');
        window.location.href = '/app/';
      } else {
        A.showStatus(
          'Hesabınız oluşturuldu. E-postanıza gönderilen onay bağlantısına tıklayıp giriş yapabilirsiniz.',
          'success'
        );
        form.reset();
        if (strengthFill) { strengthFill.style.width = '0%'; strengthFill.dataset.level = '0'; }
      }
    } catch (err) {
      A.showStatus(err?.message || 'Kayıt sırasında bir hata oluştu.', 'error');
    } finally {
      A.setLoading(submitBtn, false);
    }
  });

  function translateAuthError(msg) {
    if (!msg) return 'Kayıt başarısız.';
    const m = msg.toLowerCase();
    if (m.includes('user already registered')) return 'Bu e-posta zaten kayıtlı. Giriş yapmayı deneyin.';
    if (m.includes('password should be at least')) return 'Şifre çok kısa. En az 8 karakter olmalı.';
    if (m.includes('rate limit')) return 'Çok fazla deneme yapıldı, lütfen biraz bekleyin.';
    return msg;
  }
})();
