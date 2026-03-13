/**
 * 3D Print Shop - Main JavaScript
 */

document.addEventListener('DOMContentLoaded', () => {

  // ── Mobile Nav Toggle ──────────────────────────────────
  const hamburger = document.querySelector('.hamburger');
  const navMenu = document.querySelector('.navbar-nav');
  const navActions = document.querySelector('.navbar-actions');

  if (hamburger) {
    hamburger.addEventListener('click', () => {
      navMenu?.classList.toggle('open');
      navActions?.classList.toggle('open');
    });
  }

  // ── Auto-dismiss Flash Messages ────────────────────────
  const flashes = document.querySelectorAll('.flash');
  flashes.forEach(flash => {
    setTimeout(() => {
      flash.style.transition = 'all .3s ease';
      flash.style.opacity = '0';
      flash.style.transform = 'translateX(120%)';
      setTimeout(() => flash.remove(), 300);
    }, 4000);
    flash.addEventListener('click', () => flash.remove());
  });

  // ── Quantity Selectors ─────────────────────────────────
  document.querySelectorAll('.qty-selector').forEach(selector => {
    const input = selector.querySelector('.qty-input');
    const minusBtn = selector.querySelector('[data-action="minus"]');
    const plusBtn = selector.querySelector('[data-action="plus"]');

    if (minusBtn) {
      minusBtn.addEventListener('click', () => {
        const val = parseInt(input.value) || 1;
        if (val > 1) input.value = val - 1;
      });
    }
    if (plusBtn) {
      plusBtn.addEventListener('click', () => {
        const val = parseInt(input.value) || 1;
        input.value = val + 1;
      });
    }
  });

  // ── Cart Quantity Controls ─────────────────────────────
  document.querySelectorAll('.cart-qty-form').forEach(form => {
    const input = form.querySelector('.cart-qty-input');
    const minusBtn = form.querySelector('[data-action="minus"]');
    const plusBtn = form.querySelector('[data-action="plus"]');

    if (minusBtn) {
      minusBtn.addEventListener('click', () => {
        const val = parseInt(input.value) || 1;
        input.value = Math.max(0, val - 1);
        form.closest('form')?.submit();
      });
    }
    if (plusBtn) {
      plusBtn.addEventListener('click', () => {
        const val = parseInt(input.value) || 0;
        input.value = val + 1;
        form.closest('form')?.submit();
      });
    }
  });

  // ── File Upload Drag & Drop ────────────────────────────
  document.querySelectorAll('.file-upload').forEach(zone => {
    const input = zone.querySelector('input[type="file"]');
    const textEl = zone.querySelector('.file-upload-text');

    zone.addEventListener('dragover', e => {
      e.preventDefault();
      zone.classList.add('dragover');
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', e => {
      e.preventDefault();
      zone.classList.remove('dragover');
      if (e.dataTransfer.files.length && input) {
        input.files = e.dataTransfer.files;
        updateFileName(e.dataTransfer.files[0].name, textEl);
      }
    });

    if (input) {
      input.addEventListener('change', () => {
        if (input.files.length) updateFileName(input.files[0].name, textEl);
      });
    }
  });

  function updateFileName(name, el) {
    if (el) {
      el.textContent = `✓ ${name}`;
      el.style.color = 'var(--success)';
    }
  }

  // ── Scroll Animations ──────────────────────────────────
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.style.opacity = '1';
        entry.target.style.transform = 'translateY(0)';
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1 });

  document.querySelectorAll('.product-card, .category-card, .stat-card').forEach(el => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(20px)';
    el.style.transition = 'opacity .4s ease, transform .4s ease';
    observer.observe(el);
  });

  // ── Confirm Delete ─────────────────────────────────────
  document.querySelectorAll('[data-confirm]').forEach(btn => {
    btn.addEventListener('click', e => {
      if (!confirm(btn.dataset.confirm || 'Are you sure?')) {
        e.preventDefault();
      }
    });
  });

  // ── Active Nav Link ────────────────────────────────────
  const currentPath = window.location.pathname;
  document.querySelectorAll('.nav-link').forEach(link => {
    if (link.getAttribute('href') === currentPath) {
      link.classList.add('active');
    }
  });

  document.querySelectorAll('.admin-nav-item').forEach(link => {
    if (link.getAttribute('href') === currentPath) {
      link.classList.add('active');
    }
  });

});
