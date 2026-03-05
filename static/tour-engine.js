/**
 * tour-engine.js — Sahyog Sutra Shared Tour Engine
 * ─────────────────────────────────────────────────
 * One reusable class that powers the guided tour on every page.
 * Each page creates a single instance and provides only its own
 * step definitions (and an optional dynamic step-builder for pages
 * that resolve elements at run-time, e.g. campaigns).
 *
 * Standard DOM IDs used by every page (must be present in HTML):
 *   sstOverlay  sstSpotlight  sstTooltip
 *   sstTitle    sstPill       sstText
 *   sstLegend   sstDots       sstPrev    sstNext
 *
 * Standard CSS classes (from tour-engine.css):
 *   sst-arrow  sst-dot  sst-lg-item  sst-lg-icon  sst-lg-info
 *   sst-lg-label  sst-lg-desc
 *
 * @param {Object}   cfg
 * @param {Array}   [cfg.steps]            Static step definitions
 * @param {Function}[cfg.stepBuilder]      Optional: fn() → step array
 *                                          (used when elements must be resolved at tour-start)
 * @param {string}   cfg.highlightClass    CSS class to lift the target above the overlay
 * @param {Object}  [cfg.i18n]             Localised button labels
 * @param {string}  [cfg.i18n.finish]      e.g. 'Finish ✓'
 * @param {string}  [cfg.i18n.next]        e.g. 'Next →'
 */
if (!window.SahyogTour) {
  window.SahyogTour = class SahyogTour {

    constructor(cfg) {
      this._cfg = cfg;
      this._step = 0;
      this._open = false;
      this._steps = [];           // resolved at tour start
      this._resizeTimer = null;

      // Bound handlers (needed so we can removeEventListener later)
      this._keyFn = this._onKey.bind(this);
      this._resizeFn = this._onResize.bind(this);

      document.addEventListener('keydown', this._keyFn);
      window.addEventListener('resize', this._resizeFn);
    }

    /* ── DOM helpers ──────────────────────────────────────────── */

    _el(id) { return document.getElementById(id); }
    _tt() { return this._el('sstTooltip'); }
    _sp() { return this._el('sstSpotlight'); }
    _ov() { return this._el('sstOverlay'); }

    /* ── Step resolution ──────────────────────────────────────── */

    /**
     * Normalises this._steps into objects of the form:
     *   { el, title, text, legend, preferAbove, scrollBlock,
     *     highlightParent, highlightParentSel }
     */
    _resolveSteps() {
      if (this._cfg.stepBuilder) {
        // Campaigns uses a custom builder that resolves DOM elements at start-time
        this._steps = this._cfg.stepBuilder();
      } else {
        this._steps = (this._cfg.steps || [])
          .map(s => ({
            el: document.getElementById(s.targetId),
            title: s.title,
            text: s.text,
            legend: s.legend || null,
            preferAbove: s.preferAbove || false,
            scrollBlock: s.scrollBlock || 'center',
            highlightParent: s.highlightParent || false,
            highlightParentSel: s.highlightParentSel || null,
          }))
          .filter(s => s.el);   // skip steps whose target is not in the DOM
      }
    }

    /* ── Highlight helpers ────────────────────────────────────── */

    _clearHL() {
      document.querySelectorAll('.' + this._cfg.highlightClass)
        .forEach(el => el.classList.remove(this._cfg.highlightClass));
    }

    /* ── Progress dots ────────────────────────────────────────── */

    _buildDots() {
      const c = this._el('sstDots');
      c.innerHTML = '';
      this._steps.forEach((_, i) => {
        const d = document.createElement('div');
        d.className = 'sst-dot' + (i === this._step ? ' active' : '');
        d.onclick = () => this.show(i);
        c.appendChild(d);
      });
    }

    /* ── Spotlight positioning ────────────────────────────────── */

    _spotPos(rect, pad = 10) {
      const sp = this._sp();
      sp.style.top = (rect.top - pad) + 'px';
      sp.style.left = (rect.left - pad) + 'px';
      sp.style.width = (rect.width + pad * 2) + 'px';
      sp.style.height = (rect.height + pad * 2) + 'px';
    }

    /* ── Tooltip positioning ──────────────────────────────────── */

    _ttPos(rect, pad = 10, preferAbove = false) {
      const tt = this._tt();
      const TW = tt.offsetWidth, TH = tt.offsetHeight;
      const VW = window.innerWidth, VH = window.innerHeight, M = 12;

      const below = rect.bottom + pad + M;
      const above = rect.top - pad - TH - M;
      const fitsBelow = below + TH <= VH - 10;
      const fitsAbove = above >= 10;

      let top, cls;

      if (preferAbove) {
        if (fitsAbove) { top = above; cls = 'arrow-bottom'; }
        else if (fitsBelow) { top = below; cls = 'arrow-top'; }
        else { top = Math.max(10, above); cls = 'arrow-bottom'; }
      } else {
        if (fitsBelow) { top = below; cls = 'arrow-top'; }
        else if (fitsAbove) { top = above; cls = 'arrow-bottom'; }
        else {
          // Not enough room above or below — place away from the element's midpoint
          const viewMid = (VH - TH) / 2;
          const spotMid = (rect.top + rect.bottom) / 2;
          top = viewMid < spotMid
            ? Math.max(10, rect.top - pad - TH - M)
            : Math.min(VH - TH - 10, rect.bottom + pad + M);
          cls = viewMid < spotMid ? 'arrow-bottom' : 'arrow-top';
        }
      }

      // Centre tooltip horizontally over the target, clamped to viewport
      const cx = rect.left + rect.width / 2;
      const left = Math.max(12, Math.min(Math.round(cx - TW / 2), VW - TW - 12));

      tt.style.top = top + 'px';
      tt.style.left = left + 'px';
      tt.classList.remove('arrow-top', 'arrow-bottom');

      if (cls) {
        tt.classList.add(cls);
        const arrow = tt.querySelector('.sst-arrow');
        if (arrow) {
          // Nudge arrow so it physically points at the highlighted element
          arrow.style.left = Math.max(12, Math.min(Math.round(cx - left - 9), TW - 30)) + 'px';
          arrow.style.transform = 'none';
        }
      }
    }

    /* ── Show a specific step ─────────────────────────────────── */

    show(i) {
      this._step = i;
      const step = this._steps[i];
      if (!step) { this.end(); return; }

      // Lift target above the overlay
      this._clearHL();
      step.el.classList.add(this._cfg.highlightClass);

      // Some steps also need the parent card highlighted (e.g. campaigns card footer)
      if (step.highlightParent) {
        const parent = step.el.closest(step.highlightParentSel || '.campaign-card');
        if (parent) parent.classList.add(this._cfg.highlightClass);
      }

      // Use 'instant' so getBoundingClientRect() reads the post-scroll position —
      // smooth scroll is async and would return wrong coordinates on mobile.
      step.el.scrollIntoView({ behavior: 'instant', block: step.scrollBlock || 'center' });

      // Fill tooltip content
      this._el('sstTitle').textContent = step.title;
      this._el('sstText').textContent = step.text;
      this._el('sstPill').textContent = `${i + 1} / ${this._steps.length}`;

      // Legend (optional icon/label grid)
      const lg = this._el('sstLegend');
      if (step.legend && step.legend.length) {
        lg.style.display = 'grid';
        lg.innerHTML = step.legend.map(x =>
          `<div class="sst-lg-item">` +
          `<div class="sst-lg-icon">${x.icon}</div>` +
          `<div class="sst-lg-info">` +
          `<div class="sst-lg-label">${x.label}</div>` +
          `<div class="sst-lg-desc">${x.desc}</div>` +
          `</div>` +
          `</div>`
        ).join('');
      } else {
        lg.style.display = 'none';
        lg.innerHTML = '';
      }

      // Navigation button states
      this._el('sstPrev').style.visibility = i === 0 ? 'hidden' : 'visible';
      this._el('sstNext').textContent = i === this._steps.length - 1
        ? (this._cfg.i18n && this._cfg.i18n.finish || 'Finish ✓')
        : (this._cfg.i18n && this._cfg.i18n.next || 'Next →');

      this._buildDots();

      // Double rAF: first frame paints the updated tooltip content,
      // second frame measures real offsetWidth/Height before positioning.
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          const rect = step.el.getBoundingClientRect();
          this._spotPos(rect);
          this._sp().classList.add('visible');

          const tt = this._tt();
          tt.style.display = 'block';
          tt.style.visibility = 'hidden';   // hide while measuring
          tt.classList.remove('visible');

          requestAnimationFrame(() => {
            this._ttPos(rect, 10, step.preferAbove || false);
            tt.style.visibility = 'visible';
            tt.classList.add('visible');
          });
        });
      });
    }

    /* ── Lifecycle ────────────────────────────────────────────── */

    start() {
      if (this._open) return;
      this._resolveSteps();
      if (!this._steps.length) return;

      this._open = true;
      this._step = 0;

      const ov = this._ov();
      ov.style.display = 'block';
      requestAnimationFrame(() => ov.classList.add('active', 'visible'));
      document.body.style.overflow = 'hidden';
      this.show(0);
    }

    end() {
      if (!this._open) return;
      this._open = false;

      const ov = this._ov();
      ov.classList.remove('visible');
      setTimeout(() => { ov.classList.remove('active'); ov.style.display = 'none'; }, 350);

      this._sp().classList.remove('visible');

      const tt = this._tt();
      tt.classList.remove('visible');
      setTimeout(() => { tt.style.display = 'none'; }, 300);

      document.body.style.overflow = '';
      setTimeout(() => this._clearHL(), 300);  // wipe highlights after overlay fades
    }

    next() {
      if (this._step < this._steps.length - 1) {
        this._tt().classList.remove('visible');
        this._sp().classList.remove('visible');
        setTimeout(() => this.show(this._step + 1), 180);
      } else {
        this.end();
      }
    }

    prev() {
      if (this._step > 0) {
        this._tt().classList.remove('visible');
        this._sp().classList.remove('visible');
        setTimeout(() => this.show(this._step - 1), 180);
      }
    }

    /* ── Event handlers ───────────────────────────────────────── */

    _onKey(e) {
      if (!this._open) return;
      if (e.key === 'Escape') this.end();
      if (e.key === 'ArrowRight') this.next();
      if (e.key === 'ArrowLeft') this.prev();
    }

    _onResize() {
      if (!this._open) return;
      clearTimeout(this._resizeTimer);
      this._resizeTimer = setTimeout(() => {
        const step = this._steps[this._step];
        if (!step) return;
        const rect = step.el.getBoundingClientRect();
        this._spotPos(rect);
        this._ttPos(rect, 10, step.preferAbove || false);
      }, 150);
    }

    /* ── Cleanup (call if the tour element is removed from DOM) ── */

    destroy() {
      document.removeEventListener('keydown', this._keyFn);
      window.removeEventListener('resize', this._resizeFn);
    }
  }
}
