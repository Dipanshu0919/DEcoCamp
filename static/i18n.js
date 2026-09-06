/**
 * SahyogSutra i18n — lightweight client-side translation runtime.
 * - Loads only the selected language bundle (one <script> tag).
 * - Applies translations via data-i18n, data-i18n-placeholder,
 *   data-i18n-title, data-i18n-aria-label attributes.
 * - English = zero work (HTML source text is already English).
 * - Uses textContent, never innerHTML (XSS-safe).
 * - Exposes window.SahyogI18n.t(key, fallback) and window.SahyogI18n.apply(root).
 * - Lightweight MutationObserver handles dynamic HTML insertions.
 * ~2KB minified. No dependencies.
 */
(function () {
  'use strict';

  function getLang() {
    // 1. Authoritative source: server-provided html[lang], html[data-lang], or meta[name="ss-lang"]
    var html = document.documentElement;
    var serverLang = html ? (html.getAttribute('lang') || html.getAttribute('data-lang')) : null;
    if (!serverLang || serverLang === 'auto') {
      var meta = document.querySelector('meta[name="ss-lang"]');
      serverLang = meta ? meta.getAttribute('content') : null;
    }

    if (serverLang && serverLang !== 'auto' && serverLang !== '') {
      var cleanServer = serverLang.toLowerCase().trim();
      // Sync authoritative server language to client-side localStorage optimization
      try {
        localStorage.setItem('language', cleanServer);
      } catch (e) {}
      return cleanServer;
    }

    // 2. Client-side optimization fallback: localStorage['language']
    try {
      var localLang = localStorage.getItem('language') || localStorage.getItem('selectedLanguage');
      if (localLang && typeof localLang === 'string') {
        return localLang.toLowerCase().trim();
      }
    } catch (e) {}

    return 'en';
  }

  var lang = getLang();
  var SUPPORTED = ['hi', 'mr', 'gu', 'te', 'kn', 'ml', 'bn', 'pa', 'or'];

  var isApplying = false;

  function applyToElement(el, d) {
    if (!el || !d || el.nodeType !== 1) return;
    var key, val;

    key = el.getAttribute('data-i18n');
    if (key) {
      val = d[key];
      if (val && el.textContent !== val) el.textContent = val;
    }

    key = el.getAttribute('data-i18n-placeholder');
    if (key) {
      val = d[key];
      if (val && el.getAttribute('placeholder') !== val) el.setAttribute('placeholder', val);
    }

    key = el.getAttribute('data-i18n-title');
    if (key) {
      val = d[key];
      if (val && el.getAttribute('title') !== val) el.setAttribute('title', val);
    }

    key = el.getAttribute('data-i18n-aria-label');
    if (key) {
      val = d[key];
      if (val && el.getAttribute('aria-label') !== val) el.setAttribute('aria-label', val);
    }
  }

  function applyToRoot(root, d) {
    if (!root || !d || isApplying) return;
    isApplying = true;
    try {
      var els = root.querySelectorAll('[data-i18n],[data-i18n-placeholder],[data-i18n-title],[data-i18n-aria-label]');
      for (var i = 0; i < els.length; i++) applyToElement(els[i], d);
      if (root !== document && root.nodeType === 1) applyToElement(root, d);
    } finally {
      isApplying = false;
    }
  }

  /* Public API available immediately */
  window.SahyogI18n = {
    lang: lang,
    apply: function (root) {
      if (!window.SS_I18N || lang === 'en') return;
      applyToRoot(root || document, window.SS_I18N.data);
    },
    t: function (key, fallback) {
      if (window.SS_I18N && window.SS_I18N.data) {
        var val = window.SS_I18N.data[key];
        if (val) return val;
      }
      return fallback !== undefined ? fallback : key;
    }
  };

  /* English = zero bundle download, zero DOM translation */
  if (lang === 'en' || SUPPORTED.indexOf(lang) === -1) return;

  /* Setup MutationObserver for dynamically added nodes (with loop guard) */
  if (typeof MutationObserver !== 'undefined') {
    var observer = new MutationObserver(function (mutations) {
      if (isApplying || !window.SS_I18N) return;
      var d = window.SS_I18N.data;
      for (var i = 0; i < mutations.length; i++) {
        var m = mutations[i];
        for (var j = 0; j < m.addedNodes.length; j++) {
          var node = m.addedNodes[j];
          if (node.nodeType === 1) {
            // Ignore internal overlay / animation nodes
            if (node.id === 'sstOverlay' || node.id === 'sstTooltip' || node.classList.contains('hero-particle')) continue;
            applyToRoot(node, d);
          }
        }
      }
    });

    var startObserver = function () {
      if (document.body) {
        observer.observe(document.body, { childList: true, subtree: true });
      }
    };

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', startObserver);
    } else {
      startObserver();
    }
  }

  /* If bundle was already loaded via head <script>, apply as soon as DOM is ready */
  if (window.SS_I18N && window.SS_I18N.data) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () {
        applyToRoot(document, window.SS_I18N.data);
      });
    } else {
      applyToRoot(document, window.SS_I18N.data);
    }
    return;
  }

  /* Fallback dynamic script load if not preloaded in <head> */
  var v = document.querySelector('meta[name="ss-static-v"]');
  var ver = v ? '?v=' + v.getAttribute('content') : '';
  var script = document.createElement('script');
  script.src = '/static/i18n/' + lang + '.js' + ver;
  script.async = false;

  script.onload = function () {
    if (!window.SS_I18N) return;
    var d = window.SS_I18N.data;
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () {
        applyToRoot(document, d);
      });
    } else {
      applyToRoot(document, d);
    }
  };

  script.onerror = function () {
    console.warn('[SahyogI18n] Failed to load bundle for:', lang);
  };

  (document.head || document.documentElement).appendChild(script);

}());
