/**
 * SahyogSutra Unified Motion, 3D Engine & SVG Icon Helper
 * Lightweight, dependency-free, GPU-accelerated micro-interactions & continuous motion.
 * Memory & Bandwidth: ~7.5 KB, 0 external libraries, auto-cleanup on all temporary elements.
 */
(function () {
    'use strict';

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const isFinePointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches;

    // 0. Accessible SVG Icon Helper
    window.getSvgIcon = function (name, extraClass = '') {
        return `<svg class="ss-icon ss-icon-${name} ${extraClass}" aria-hidden="true"><use href="#icon-${name}"></use></svg>`;
    };

    // 1. Delegated Tactile Ripple Effect
    function initRippleSystem() {
        if (prefersReducedMotion) return;

        document.addEventListener('pointerdown', function (e) {
            const host = e.target.closest('.cta, .submit-btn, .reset-btn, .action-btn, .filter-btn, .navlink, .pressable, .lang-option, .view-events-btn, .campaign-tag, .like-btn, .share-btn');
            if (!host) return;

            if (getComputedStyle(host).position === 'static') {
                host.style.position = 'relative';
            }
            host.classList.add('ripple-host');

            const rect = host.getBoundingClientRect();
            const size = Math.max(rect.width, rect.height);
            const x = e.clientX - rect.left - size / 2;
            const y = e.clientY - rect.top - size / 2;

            const wave = document.createElement('span');
            wave.className = 'ripple-wave';
            wave.style.width = wave.style.height = `${size}px`;
            wave.style.left = `${x}px`;
            wave.style.top = `${y}px`;

            host.appendChild(wave);
            setTimeout(() => wave.remove(), 450);
        }, { passive: true });
    }

    // 2. Delegated 3D Card & Hero Monolith Perspective Tilt (Desktop pointer only)
    function initCard3DTilt() {
        if (prefersReducedMotion || !isFinePointer) return;

        let activeCard = null;
        let rafId = null;
        let targetRotX = 0;
        let targetRotY = 0;

        function updateTilt() {
            if (!activeCard || document.hidden) return;
            if (activeCard.classList.contains('hero-3d-monolith')) {
                activeCard.style.transform = `perspective(1000px) rotateX(${targetRotX * 0.75}deg) rotateY(${targetRotY * 0.75}deg) translateZ(10px)`;
            } else {
                activeCard.style.transform = `perspective(1000px) rotateX(${targetRotX}deg) rotateY(${targetRotY}deg) scale3d(1.02, 1.02, 1.02)`;
            }
            rafId = null;
        }

        document.addEventListener('pointermove', function (e) {
            const card = e.target.closest('.campaign-card, .hero-3d-monolith');
            if (!card) {
                if (activeCard) {
                    activeCard.style.transform = '';
                    activeCard = null;
                }
                return;
            }

            activeCard = card;
            const rect = card.getBoundingClientRect();
            const centerX = rect.left + rect.width / 2;
            const centerY = rect.top + rect.height / 2;

            const normX = (e.clientX - centerX) / (rect.width / 2);
            const normY = (e.clientY - centerY) / (rect.height / 2);

            targetRotX = Math.max(-6, Math.min(6, -normY * 5));
            targetRotY = Math.max(-6, Math.min(6, normX * 5));

            if (!rafId) {
                rafId = requestAnimationFrame(updateTilt);
            }
        }, { passive: true });

        document.addEventListener('pointerleave', function () {
            if (activeCard) {
                activeCard.style.transform = '';
                activeCard = null;
            }
            if (rafId) {
                cancelAnimationFrame(rafId);
                rafId = null;
            }
        });
    }

    // 3. Scroll Reveal via IntersectionObserver
    let revealObserver = null;
    function initScrollReveals() {
        if (revealObserver) revealObserver.disconnect();

        if (prefersReducedMotion) {
            document.querySelectorAll('.reveal').forEach(el => el.classList.add('is-revealed'));
            return;
        }

        revealObserver = new IntersectionObserver((entries, obs) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('is-revealed');
                    obs.unobserve(entry.target);
                }
            });
        }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });

        document.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el));
    }

    // 4. Like Button Particle Burst & Bounce (Radial SVG sparks)
    window.triggerLikeEffect = function (btnElement) {
        if (!btnElement) return;
        btnElement.classList.add('animating');

        if (!prefersReducedMotion) {
            const count = 6;
            const colors = ['#ef4444', '#f59e0b', '#ec4899', '#f97316', '#fbbf24', '#f43f5e'];

            for (let i = 0; i < count; i++) {
                const angle = (i * (360 / count) + Math.random() * 15) * (Math.PI / 180);
                const distance = 22 + Math.random() * 14;
                const tx = Math.cos(angle) * distance;
                const ty = Math.sin(angle) * distance;

                const particle = document.createElement('div');
                particle.className = 'like-particle';
                particle.style.background = colors[i % colors.length];
                particle.style.setProperty('--tx', `${tx}px`);
                particle.style.setProperty('--ty', `${ty}px`);
                particle.style.left = '50%';
                particle.style.top = '50%';

                btnElement.appendChild(particle);
                setTimeout(() => particle.remove(), 450);
            }
        }

        setTimeout(() => btnElement.classList.remove('animating'), 400);
    };

    // 5. Stat Counter Animation (.count-up)
    function initCountUp() {
        const counterObserver = new IntersectionObserver((entries, obs) => {
            entries.forEach(entry => {
                if (!entry.isIntersecting) return;
                const el = entry.target;
                obs.unobserve(el);

                const target = parseInt(el.dataset.countTo || el.textContent, 10);
                if (isNaN(target) || target <= 0) return;

                if (prefersReducedMotion) {
                    el.textContent = target;
                    return;
                }

                const duration = 750;
                const start = performance.now();

                function step(now) {
                    const elapsed = now - start;
                    const progress = Math.min(1, elapsed / duration);
                    const ease = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress);
                    el.textContent = Math.floor(ease * target);
                    if (progress < 1) requestAnimationFrame(step);
                    else el.textContent = target;
                }
                requestAnimationFrame(step);
            });
        }, { threshold: 0.2 });

        document.querySelectorAll('.count-up').forEach(el => counterObserver.observe(el));
    }

    // 6. Full-Page & Hero Ambient Floating Particles Generator
    function initHeroParticles() {
        if (prefersReducedMotion) return;

        const containers = document.querySelectorAll('.ambient-particles-field, .hero-particles-field');
        containers.forEach(container => {
            if (!container || container.children.length > 0) return;

            const isFullPage = container.classList.contains('ambient-particles-field');
            const isMobile = window.innerWidth < 768;
            const count = isFullPage ? (isMobile ? 28 : 52) : 16;
            const fragment = document.createDocumentFragment();
            const animTypes = ['float-a', 'float-b', 'float-c'];

            for (let i = 0; i < count; i++) {
                const p = document.createElement('div');
                p.className = isFullPage ? 'ambient-particle' : 'hero-particle';

                // Size variation: mostly 2-4px, occasionally 5-6px
                const rand = Math.random();
                const size = rand > 0.88 ? Math.floor(Math.random() * 2) + 5 : (rand > 0.4 ? Math.floor(Math.random() * 2) + 3 : 2);

                const left = (Math.random() * 100).toFixed(2);
                const top = (Math.random() * 100).toFixed(2);
                const delay = (Math.random() * 10).toFixed(2);
                const duration = (Math.random() * 6 + 7).toFixed(2);

                p.style.width = `${size}px`;
                p.style.height = `${size}px`;
                p.style.left = `${left}%`;
                p.style.top = `${top}%`;
                p.style.animationDelay = `${delay}s`;
                p.style.animationDuration = `${duration}s`;

                if (isFullPage) {
                    const animClass = animTypes[i % animTypes.length];
                    p.classList.add(animClass);

                    // Color palette diversity: warm gold, glowing ember, soft diamond
                    if (rand > 0.65) {
                        p.style.background = 'radial-gradient(circle, #ffffff 0%, #fde68a 50%, #f59e0b 100%)';
                        p.style.boxShadow = '0 0 7px rgba(253, 230, 138, 0.8), 0 0 14px rgba(245, 158, 11, 0.45)';
                    } else if (rand < 0.25) {
                        p.style.background = 'radial-gradient(circle, #ffffff 0%, #fb923c 60%, #ea580c 100%)';
                        p.style.boxShadow = '0 0 7px rgba(251, 146, 60, 0.8), 0 0 14px rgba(234, 88, 12, 0.45)';
                    }
                }

                fragment.appendChild(p);
            }
            container.appendChild(fragment);
        });
    }

    // 7. Scroll Parallax
    function initScrollParallax() {
        if (prefersReducedMotion) return;
        let ticking = false;

        window.addEventListener('scroll', function () {
            if (!ticking) {
                requestAnimationFrame(() => {
                    const scrollY = window.pageYOffset || document.documentElement.scrollTop;
                    const stage = document.querySelector('.hero-stage-container');
                    if (stage && scrollY < 800) {
                        stage.style.transform = `translateY(${scrollY * 0.12}px)`;
                    }
                    ticking = false;
                });
                ticking = true;
            }
        }, { passive: true });
    }

    // 8. Localized Form Input Error Shake
    window.shakeInput = function (inputSelectorOrEl) {
        const el = typeof inputSelectorOrEl === 'string' ? document.querySelector(inputSelectorOrEl) : inputSelectorOrEl;
        if (!el) return;
        el.classList.remove('input-error-shake');
        void el.offsetWidth;
        el.classList.add('input-error-shake');
        setTimeout(() => el.classList.remove('input-error-shake'), 400);
    };

    // Initialize on DOM Ready
    function initAll() {
        // Critical micro-interactions initialized immediately
        initRippleSystem();
        initCard3DTilt();
        initScrollReveals();
        initCountUp();

        // Non-critical decorative motion deferred until after first paint
        const runNonCritical = window.requestIdleCallback || function (cb) { setTimeout(cb, 60); };
        runNonCritical(function () {
            initHeroParticles();
            initScrollParallax();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }

    // Expose for dynamic section loads
    window.reinitMotion = function () {
        initScrollReveals();
        initCountUp();
        initHeroParticles();
    };
})();
