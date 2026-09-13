/**
 * QuizX / Modern Academic Interface - Application Core Controller
 * Handles Navigation Pill Motion, Top Progress Bar, Stat Count-Up,
 * Global Modals, Global Toasts, Lightbox, and Command Palette.
 */

(function () {
    'use strict';

    // --------------------------------------------------------------------------
    // 1. Top Route Progress Bar
    // --------------------------------------------------------------------------
    const ProgressBar = {
        bar: null,
        init() {
            let el = document.getElementById('topProgressBar');
            if (!el) {
                el = document.createElement('div');
                el.id = 'topProgressBar';
                el.className = 'top-route-progress';
                document.body.appendChild(el);
            }
            this.bar = el;

            // Intercept internal link clicks to trigger quick visual feedback
            document.addEventListener('click', (e) => {
                const link = e.target.closest('a');
                if (!link || !link.href) return;
                const url = new URL(link.href, window.location.origin);

                // Ignore external links, hash anchors, downloads, JS voids, new tabs
                if (url.origin !== window.location.origin) return;
                if (link.target === '_blank' || link.hasAttribute('download')) return;
                if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) return;
                if (link.href.startsWith('javascript:')) return;

                ProgressBar.start();
            });
        },
        start() {
            if (!this.bar) return;
            this.bar.style.transition = 'none';
            this.bar.style.width = '0%';
            this.bar.style.opacity = '1';

            // Force reflow
            this.bar.offsetWidth;

            this.bar.style.transition = 'width 250ms cubic-bezier(0.22, 1, 0.36, 1)';
            this.bar.style.width = '65%';

            setTimeout(() => {
                if (this.bar.style.opacity === '1') {
                    this.bar.style.width = '90%';
                }
            }, 250);
        },
        complete() {
            if (!this.bar) return;
            this.bar.style.transition = 'width 150ms ease, opacity 200ms ease';
            this.bar.style.width = '100%';
            setTimeout(() => {
                this.bar.style.opacity = '0';
                setTimeout(() => {
                    this.bar.style.width = '0%';
                }, 200);
            }, 150);
        }
    };

    // --------------------------------------------------------------------------
    // 2. Sidebar Navigation & Sliding Blob Indicator
    // --------------------------------------------------------------------------
    const Navigation = {
        activeAnimation: null,

        getCoords(link, nav) {
            if (!link) return { top: 0, height: 44 };
            return {
                top: link.offsetTop,
                height: link.offsetHeight || 44
            };
        },

        getCurrentPillCoords(pill, defaultLink, nav) {
            if (pill && pill.style.transform) {
                const match = pill.style.transform.match(/translate3d\(0(?:px)?,\s*([\d.-]+)px/);
                if (match) {
                    const currentY = parseFloat(match[1]);
                    const currentHeight = parseFloat(pill.style.height) || (defaultLink ? defaultLink.offsetHeight : 44);
                    if (!isNaN(currentY)) {
                        return { top: currentY, height: currentHeight };
                    }
                }
            }
            return this.getCoords(defaultLink, nav);
        },

        animateBlob(pill, startCoords, endCoords, duration = 380, onComplete = null) {
            if (!pill || !startCoords || !endCoords) return;

            if (this.activeAnimation) {
                cancelAnimationFrame(this.activeAnimation);
                this.activeAnimation = null;
            }

            const deltaY = endCoords.top - startCoords.top;
            if (Math.abs(deltaY) < 1) {
                this.updatePillPosition(pill, null, endCoords);
                if (typeof onComplete === 'function') onComplete();
                return;
            }

            const shell = document.getElementById('appShell') || document.getElementById('dashboardShell');
            const isCollapsed = shell ? shell.classList.contains('sidebar-collapsed') : false;

            // Distance intensity ratio (0.2 to 1.0)
            const distRatio = Math.min(1.0, Math.max(0.2, Math.abs(deltaY) / 180));
            const maxStretchY = (isCollapsed ? 0.18 : 0.14) * distRatio;
            const maxSqueezeX = (isCollapsed ? 0.10 : 0.06) * distRatio;

            // Ensure transitions on transform are disabled during rAF animation
            pill.style.transition = 'none';

            // Immediately position at start point
            pill.style.transform = `translate3d(0, ${startCoords.top.toFixed(2)}px, 0) scale(1, 1)`;
            pill.style.height = `${startCoords.height.toFixed(2)}px`;
            pill.style.opacity = '1';

            // Force reflow to guarantee the browser commits the start position BEFORE stepping
            void pill.offsetHeight;

            let startTime = null;

            const step = (now) => {
                if (!startTime) {
                    startTime = now;
                }
                let t = (now - startTime) / duration;
                if (t < 0) t = 0;
                if (t > 1) t = 1;

                // Motion translation curve (cubic spring ease)
                const ease = 1 + 1.5 * Math.pow(t - 1, 3) + 0.5 * Math.pow(t - 1, 2);
                const currentTop = startCoords.top + (endCoords.top - startCoords.top) * ease;
                const currentHeight = startCoords.height + (endCoords.height - startCoords.height) * ease;

                let scaleY = 1.0;
                let scaleX = 1.0;

                if (Math.abs(deltaY) > 8) {
                    if (t < 0.72) {
                        const morphPhase = Math.sin((t / 0.72) * Math.PI);
                        scaleY = 1.0 + maxStretchY * morphPhase;
                        scaleX = 1.0 - maxSqueezeX * morphPhase;
                    } else {
                        const reboundT = (t - 0.72) / 0.28;
                        const reboundPhase = Math.sin(reboundT * Math.PI) * Math.exp(-2.2 * reboundT);
                        scaleY = 1.0 - (maxStretchY * 0.25) * reboundPhase;
                        scaleX = 1.0 + (maxSqueezeX * 0.25) * reboundPhase;
                    }
                }

                pill.style.transform = `translate3d(0, ${currentTop.toFixed(2)}px, 0) scale(${scaleX.toFixed(4)}, ${scaleY.toFixed(4)})`;
                pill.style.height = `${currentHeight.toFixed(2)}px`;

                if (t < 1) {
                    this.activeAnimation = requestAnimationFrame(step);
                } else {
                    pill.style.transform = `translate3d(0, ${endCoords.top.toFixed(2)}px, 0) scale(1, 1)`;
                    pill.style.height = `${endCoords.height.toFixed(2)}px`;
                    pill.style.transition = '';
                    this.activeAnimation = null;
                    if (typeof onComplete === 'function') onComplete();
                }
            };

            this.activeAnimation = requestAnimationFrame(step);
        },

        updatePillPosition(pill, targetLink, coords = null) {
            if (!pill) return;
            const targetCoords = coords || (targetLink ? this.getCoords(targetLink) : null);
            if (!targetCoords) return;

            if (this.activeAnimation) {
                cancelAnimationFrame(this.activeAnimation);
                this.activeAnimation = null;
            }

            pill.style.transition = 'none';
            pill.style.transform = `translate3d(0, ${targetCoords.top}px, 0) scale(1, 1)`;
            pill.style.height = `${targetCoords.height}px`;
            pill.style.opacity = '1';
            void pill.offsetHeight;
            pill.style.transition = '';
        },

        init() {
            const shell = document.getElementById('appShell') || document.getElementById('dashboardShell');
            const toggleBtns = document.querySelectorAll('#sidebarToggle, #sidebarExpandTab, #collapseSidebar');
            const nav = document.querySelector('.app-sidebar-nav, .dashboard-nav');

            if (toggleBtns.length && shell) {
                toggleBtns.forEach(btn => {
                    btn.addEventListener('click', () => {
                        shell.classList.toggle('sidebar-collapsed');
                        const isCollapsed = shell.classList.contains('sidebar-collapsed');
                        sessionStorage.setItem('quizx_sidebar_collapsed', isCollapsed ? '1' : '0');

                        const pill = nav ? nav.querySelector('.nav-active-pill') : null;
                        const activeItem = nav ? nav.querySelector('.app-nav-item.active') : null;
                        if (pill && activeItem) {
                            this.updatePillPosition(pill, activeItem);
                        }
                    });
                });

                if (sessionStorage.getItem('quizx_sidebar_collapsed') === '1' && window.innerWidth > 992) {
                    shell.classList.add('sidebar-collapsed');
                }
            }

            // Clean up zero-flash preload class after initial layout
            requestAnimationFrame(() => {
                document.documentElement.classList.remove('sidebar-collapsed-preload');
            });

            // Setup moving active indicator
            if (nav) {
                let pill = nav.querySelector('.nav-active-pill');
                if (!pill) {
                    pill = document.createElement('div');
                    pill.className = 'nav-active-pill';
                    nav.insertBefore(pill, nav.firstChild);
                }

                const normalizePath = (p) => {
                    if (!p) return '/';
                    let s = p.trim();
                    if (!s.startsWith('/')) s = '/' + s;
                    if (s.length > 1 && s.endsWith('/')) s = s.slice(0, -1);
                    return s;
                };

                const currentNorm = normalizePath(window.location.pathname);
                const links = Array.from(nav.querySelectorAll('a.app-nav-item[href]'));

                // 1. Exact match with path normalization (e.g. /home/ matches /home)
                let activeLink = links.find(l => {
                    const linkNorm = normalizePath(new URL(l.href, window.location.origin).pathname);
                    return linkNorm === currentNorm;
                });

                // 2. Longest prefix match (e.g. /dashboard/quizzes/create matches /dashboard/quizzes rather than /dashboard)
                if (!activeLink && currentNorm !== '/' && currentNorm !== '') {
                    const matchingLinks = links.filter(l => {
                        const linkNorm = normalizePath(new URL(l.href, window.location.origin).pathname);
                        if (linkNorm === '/' || linkNorm === '') return false;
                        return currentNorm.startsWith(linkNorm + '/');
                    });
                    if (matchingLinks.length > 0) {
                        matchingLinks.sort((a, b) => {
                            const lenA = normalizePath(new URL(a.href, window.location.origin).pathname).length;
                            const lenB = normalizePath(new URL(b.href, window.location.origin).pathname).length;
                            return lenB - lenA;
                        });
                        activeLink = matchingLinks[0];
                    }
                }

                if (activeLink) {
                    activeLink.classList.add('active');

                    // Check for previous navigation state from sessionStorage
                    let navState = null;
                    try {
                        const raw = sessionStorage.getItem('quizx_sidebar_nav_state');
                        if (raw) navState = JSON.parse(raw);
                    } catch (e) {}

                    const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
                    const endCoords = this.getCoords(activeLink, nav);

                    if (navState && typeof navState.fromTop === 'number' && !prefersReducedMotion) {
                        const elapsed = Date.now() - (navState.timestamp || 0);
                        // If navigation occurred within the last 450ms and start was at a different position
                        if (elapsed < 450 && Math.abs(navState.fromTop - endCoords.top) >= 2) {
                            const startCoords = {
                                top: navState.fromTop,
                                height: navState.fromHeight || endCoords.height
                            };
                            this.animateBlob(pill, startCoords, endCoords, 380, () => {
                                try { sessionStorage.removeItem('quizx_sidebar_nav_state'); } catch (e) {}
                            });
                        } else {
                            this.updatePillPosition(pill, activeLink);
                            try { sessionStorage.removeItem('quizx_sidebar_nav_state'); } catch (e) {}
                        }
                    } else {
                        // Position instantly on page load without animation (no flash)
                        this.updatePillPosition(pill, activeLink);
                        try { sessionStorage.removeItem('quizx_sidebar_nav_state'); } catch (e) {}
                    }
                } else {
                    pill.style.opacity = '0';
                    try { sessionStorage.removeItem('quizx_sidebar_nav_state'); } catch (e) {}
                }

                // Record clicked path and animate optimistically on sidebar link click
                links.forEach(link => {
                    link.addEventListener('click', () => {
                        const currentActive = nav.querySelector('.app-nav-item.active');
                        if (currentActive) {
                            const startCoords = this.getCurrentPillCoords(pill, currentActive, nav);
                            const endCoords = this.getCoords(link, nav);

                            try {
                                const targetUrl = new URL(link.href, window.location.origin);
                                sessionStorage.setItem('quizx_sidebar_nav_state', JSON.stringify({
                                    fromTop: startCoords.top,
                                    fromHeight: startCoords.height,
                                    targetPath: targetUrl.pathname,
                                    targetTop: endCoords.top,
                                    targetHeight: endCoords.height,
                                    timestamp: Date.now()
                                }));
                            } catch (err) {}

                            if (currentActive !== link) {
                                links.forEach(l => l.classList.remove('active'));
                                link.classList.add('active');
                                this.animateBlob(pill, startCoords, endCoords, 380);
                            }
                        }
                    });
                });

                // Also record previous path for general internal link navigation (e.g. from page content)
                document.addEventListener('click', (e) => {
                    const link = e.target.closest('a');
                    if (!link || !link.href || link.closest('.app-sidebar-nav, .dashboard-nav')) return;
                    try {
                        const url = new URL(link.href, window.location.origin);
                        if (url.origin === window.location.origin && url.pathname !== window.location.pathname) {
                            const currentActive = nav.querySelector('.app-nav-item.active');
                            if (currentActive) {
                                const startCoords = this.getCurrentPillCoords(pill, currentActive, nav);
                                sessionStorage.setItem('quizx_sidebar_nav_state', JSON.stringify({
                                    fromTop: startCoords.top,
                                    fromHeight: startCoords.height,
                                    targetPath: url.pathname,
                                    timestamp: Date.now()
                                }));
                            }
                        }
                    } catch (err) {}
                });

                // Recalculate on window resize
                window.addEventListener('resize', () => {
                    const currentActive = nav.querySelector('.app-nav-item.active');
                    if (currentActive) this.updatePillPosition(pill, currentActive);
                });
            }
        },
    };

    // --------------------------------------------------------------------------
    // 3. Stat Numbers Count-Up Animation
    // --------------------------------------------------------------------------
    const StatCounters = {
        init() {
            if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
                return;
            }

            const elements = document.querySelectorAll('[data-count-to]');
            elements.forEach(el => {
                const targetStr = el.getAttribute('data-count-to');
                const target = parseFloat(targetStr);
                if (isNaN(target)) return;

                if (target === 0) {
                    const prefix = el.getAttribute('data-prefix') || '';
                    const suffix = el.getAttribute('data-suffix') || '';
                    el.textContent = `${prefix}0${suffix}`;
                    return;
                }

                const decimals = (targetStr.split('.')[1] || '').length;
                const duration = parseInt(el.getAttribute('data-duration') || '600', 10);
                const prefix = el.getAttribute('data-prefix') || '';
                const suffix = el.getAttribute('data-suffix') || '';

                let startTime = null;
                const easeOutExpo = (t) => t === 1 ? 1 : 1 - Math.pow(2, -10 * t);

                const step = (timestamp) => {
                    if (!startTime) startTime = timestamp;
                    const elapsed = timestamp - startTime;
                    const progress = Math.min(elapsed / duration, 1);
                    const current = easeOutExpo(progress) * target;

                    el.textContent = `${prefix}${current.toFixed(decimals)}${suffix}`;

                    if (progress < 1) {
                        requestAnimationFrame(step);
                    } else {
                        el.textContent = `${prefix}${target.toFixed(decimals)}${suffix}`;
                    }
                };

                requestAnimationFrame(step);
            });
        }
    };

    // --------------------------------------------------------------------------
    // 4. Global Modal System
    // --------------------------------------------------------------------------
    window.showModal = function (modalId) {
        const modal = typeof modalId === 'string' ? document.getElementById(modalId) : modalId;
        if (modal) {
            // Teleport to document.body if nested inside a transformed or animated container
            // (e.g. .panel-card-fade-in, animated cards) to ensure position: fixed is strictly
            // anchored to the viewport rather than trapped off-screen.
            if (modal.parentElement !== document.body) {
                if (modal.id) {
                    const stale = document.body.querySelector(`:scope > #${modal.id}`);
                    if (stale && stale !== modal) {
                        stale.remove();
                    }
                }
                document.body.appendChild(modal);
            }
            modal.classList.add('show');
            document.body.classList.add('modal-open');
            const focusInput = modal.querySelector('input:not([type="hidden"]), select, textarea, button.primary');
            if (focusInput) setTimeout(() => focusInput.focus(), 80);
        }
    };

    window.hideModal = function (modalId) {
        const modal = typeof modalId === 'string' ? document.getElementById(modalId) : modalId;
        if (modal) {
            modal.classList.remove('show');
            if (!document.querySelector('.modal-overlay.show')) {
                document.body.classList.remove('modal-open');
            }
        }
    };

    // Backdrop click & Escape listener
    document.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal-overlay')) {
            window.hideModal(e.target);
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const openModals = document.querySelectorAll('.modal-overlay.show');
            if (openModals.length > 0) {
                window.hideModal(openModals[openModals.length - 1]);
            }
        }
    });

    // --------------------------------------------------------------------------
    // 5. Global Toast Notification System
    // --------------------------------------------------------------------------
    window.showToast = function (message, type = 'info', duration = 3000) {
        let container = document.getElementById('globalToastContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'globalToastContainer';
            container.className = 'global-toast-container';
            document.body.appendChild(container);
        }

        const icons = {
            success: 'fa-check',
            error: 'fa-triangle-exclamation',
            warning: 'fa-circle-exclamation',
            info: 'fa-circle-info'
        };

        const toast = document.createElement('div');
        toast.className = `global-toast ${type}`;
        toast.innerHTML = `
            <div class="toast-icon"><i class="fa-solid ${icons[type] || 'fa-circle-info'}"></i></div>
            <div class="toast-message">${message}</div>
            <button class="toast-close" type="button" aria-label="Close">&times;</button>
        `;

        container.appendChild(toast);

        // Force reflow and show
        toast.offsetWidth;
        toast.classList.add('visible');

        const dismiss = () => {
            toast.classList.remove('visible');
            setTimeout(() => {
                if (toast.parentNode) toast.remove();
            }, 250);
        };

        const timer = setTimeout(dismiss, duration);

        toast.querySelector('.toast-close').addEventListener('click', () => {
            clearTimeout(timer);
            dismiss();
        });
    };

    // --------------------------------------------------------------------------
    // 6. Accordions
    // --------------------------------------------------------------------------
    window.toggleAccordion = function (contentId, triggerElement) {
        const content = document.getElementById(contentId);
        if (!content) return;

        const isExpanded = content.classList.contains('expanded');
        const chevron = triggerElement ? triggerElement.querySelector('.fa-chevron-down, .chevron-icon') : null;

        if (isExpanded) {
            content.classList.remove('expanded');
            if (triggerElement) {
                triggerElement.setAttribute('aria-expanded', 'false');
                triggerElement.classList.remove('is-open');
            }
            if (chevron) chevron.style.transform = 'rotate(0deg)';
        } else {
            content.classList.add('expanded');
            if (triggerElement) {
                triggerElement.setAttribute('aria-expanded', 'true');
                triggerElement.classList.add('is-open');
            }
            if (chevron) chevron.style.transform = 'rotate(180deg)';

            if (window.MathJax && window.MathJax.typesetPromise) {
                window.MathJax.typesetPromise([content]).catch(function () {});
            }
        }
    };

    window.toggleQuestionOptions = function (cardIdOrQid) {
        let card = document.getElementById('bloom-q-card-' + cardIdOrQid);
        if (!card) {
            card = document.getElementById(cardIdOrQid);
        }
        if (!card) return;

        const isOpen = card.classList.contains('is-open');
        const header = card.querySelector('.bloom-question-card-header');
        const toggleBtn = card.querySelector('.bloom-options-toggle-btn');

        if (isOpen) {
            card.classList.remove('is-open');
            if (header) header.setAttribute('aria-expanded', 'false');
            if (toggleBtn) toggleBtn.setAttribute('aria-expanded', 'false');
        } else {
            card.classList.add('is-open');
            if (header) header.setAttribute('aria-expanded', 'true');
            if (toggleBtn) toggleBtn.setAttribute('aria-expanded', 'true');

            const accordionGrid = card.querySelector('.accordion-grid');
            if (accordionGrid && window.MathJax && window.MathJax.typesetPromise) {
                window.MathJax.typesetPromise([accordionGrid]).catch(function () {});
            }
        }
    };


    // --------------------------------------------------------------------------
    // 7. Command Palette (Ctrl+K / Cmd+K) - Progressive Enhancement
    // --------------------------------------------------------------------------
    const CommandPalette = {
        modal: null,
        input: null,
        list: null,
        items: [],
        focusedIndex: 0,

        init() {
            this.modal = document.getElementById('commandPaletteModal');
            if (!this.modal) return;

            this.input = document.getElementById('commandPaletteInput');
            this.list = document.getElementById('commandPaletteList');
            if (!this.input || !this.list) return;

            document.addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
                    e.preventDefault();
                    if (this.modal.classList.contains('show')) {
                        window.hideModal(this.modal);
                    } else {
                        window.showModal('commandPaletteModal');
                        this.input.value = '';
                        this.filter('');
                    }
                }
            });

            this.input.addEventListener('input', (e) => {
                this.filter(e.target.value);
            });

            this.input.addEventListener('keydown', (e) => {
                const visible = Array.from(this.list.querySelectorAll('.command-item:not([style*="display: none"])'));
                if (!visible.length) return;

                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    this.focusedIndex = (this.focusedIndex + 1) % visible.length;
                    this.updateFocus(visible);
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    this.focusedIndex = (this.focusedIndex - 1 + visible.length) % visible.length;
                    this.updateFocus(visible);
                } else if (e.key === 'Enter') {
                    e.preventDefault();
                    if (visible[this.focusedIndex]) {
                        visible[this.focusedIndex].click();
                    }
                }
            });
        },

        filter(query) {
            const q = query.trim().toLowerCase();
            const items = this.list.querySelectorAll('.command-item');
            let hasVisible = false;

            items.forEach(item => {
                const text = item.textContent.toLowerCase();
                const match = !q || text.includes(q);
                item.style.display = match ? 'flex' : 'none';
                if (match) hasVisible = true;
            });

            const emptyMsg = this.list.querySelector('.command-empty');
            if (emptyMsg) {
                emptyMsg.style.display = hasVisible ? 'none' : 'block';
            }

            this.focusedIndex = 0;
            const visible = Array.from(this.list.querySelectorAll('.command-item:not([style*="display: none"])'));
            this.updateFocus(visible);
        },

        updateFocus(visible) {
            visible.forEach((el, idx) => {
                el.classList.toggle('focused', idx === this.focusedIndex);
                if (idx === this.focusedIndex) {
                    el.scrollIntoView({ block: 'nearest' });
                }
            });
        }
    };

    // --------------------------------------------------------------------------
    // 8. Image Lightbox
    // --------------------------------------------------------------------------
    const Lightbox = {
        init() {
            document.addEventListener('click', (e) => {
                const target = e.target;
                if (target.tagName === 'IMG' &&
                    !target.closest('button') &&
                    !target.closest('.logo') &&
                    !target.closest('.brand-mark') &&
                    !target.classList.contains('no-lightbox') &&
                    !target.closest('.exam-header')) {

                    const overlay = document.createElement('div');
                    overlay.className = 'lightbox-overlay';

                    const img = document.createElement('img');
                    img.src = target.src;
                    img.className = 'lightbox-image';

                    overlay.appendChild(img);
                    document.body.appendChild(overlay);

                    setTimeout(() => {
                        overlay.classList.add('visible');
                    }, 10);

                    const close = () => {
                        overlay.classList.remove('visible');
                        setTimeout(() => overlay.remove(), 220);
                        document.removeEventListener('keydown', keyHandler);
                    };

                    const keyHandler = (evt) => {
                        if (evt.key === 'Escape') close();
                    };

                    overlay.onclick = close;
                    document.addEventListener('keydown', keyHandler);
                }
            });
        }
    };

    // --------------------------------------------------------------------------
    // 7. Universal Scroll & State Memory
    // --------------------------------------------------------------------------
    const StateMemory = {
        init() {
            // 1. Restore & track sidebar scroll
            const sidebars = document.querySelectorAll('.app-sidebar-nav, .dashboard-nav');
            sidebars.forEach(sidebar => {
                const sidebarKey = 'quizx_scroll_sidebar';
                const savedScroll = sessionStorage.getItem(sidebarKey);
                if (savedScroll) {
                    sidebar.scrollTop = parseInt(savedScroll, 10);
                }
                sidebar.addEventListener('scroll', () => {
                    sessionStorage.setItem(sidebarKey, sidebar.scrollTop);
                }, { passive: true });
            });

            // 2. Track & restore window scroll position (unified across analytics tabs, per-path for other pages)
            const isAnalyticsPage = () => window.location.pathname.includes('/analytics') || window.location.pathname.includes('/bloom-analytics');

            const restorePageScroll = () => {
                if (window.location.hash) return;
                const scrollKey = isAnalyticsPage() ? 'quizx_analytics_scroll' : ('quizx_scroll_page_' + window.location.pathname);
                const savedPageScroll = sessionStorage.getItem(scrollKey);
                if (savedPageScroll !== null) {
                    const top = parseInt(savedPageScroll, 10);
                    requestAnimationFrame(() => {
                        window.scrollTo({ top, behavior: 'instant' });
                    });
                    setTimeout(() => {
                        window.scrollTo({ top, behavior: 'instant' });
                    }, 80);
                }
            };
            restorePageScroll();

            window.addEventListener('scroll', () => {
                if (window._isSwappingPanel) return;
                if (isAnalyticsPage()) {
                    sessionStorage.setItem('quizx_analytics_scroll', window.scrollY);
                } else {
                    const pathKey = 'quizx_scroll_page_' + window.location.pathname;
                    sessionStorage.setItem(pathKey, window.scrollY);
                }
            }, { passive: true });

            // 3. Track & restore table-wrapper scroll position (e.g. Scorecard, student roster, results)
            const restoreTableScroll = () => {
                const tables = document.querySelectorAll('.table-wrapper');
                tables.forEach((tw, idx) => {
                    const tableKey = 'quizx_scroll_table_' + window.location.pathname + '_' + idx;
                    const savedTableScroll = sessionStorage.getItem(tableKey);
                    if (savedTableScroll) {
                        const sLeft = parseInt(savedTableScroll, 10);
                        tw.scrollLeft = sLeft;
                        setTimeout(() => { tw.scrollLeft = sLeft; }, 80);
                    }
                    if (!tw._hasScrollTracker) {
                        tw._hasScrollTracker = true;
                        tw.addEventListener('scroll', () => {
                            if (window._isSwappingPanel) return;
                            sessionStorage.setItem(tableKey, tw.scrollLeft);
                        }, { passive: true });
                    }
                });
            };
            restoreTableScroll();

            window.restorePageAndTableScroll = () => {
                restorePageScroll();
                restoreTableScroll();
                setTimeout(() => {
                    restorePageScroll();
                    restoreTableScroll();
                    window._isSwappingPanel = false;
                }, 120);
            };

            window.addEventListener('load', () => {
                restorePageScroll();
                restoreTableScroll();
            });

            // 3. Track active quiz ID in sessionStorage for easy lookup
            const urlParams = new URLSearchParams(window.location.search);
            const quizParam = urlParams.get('quiz');
            if (quizParam) {
                sessionStorage.setItem('quizx_active_quiz_id', quizParam);
            }
        }
    };

    // --------------------------------------------------------------------------
    // Initialize Everything on DOM Ready
    // --------------------------------------------------------------------------
    document.addEventListener('DOMContentLoaded', () => {
        ProgressBar.init();
        StateMemory.init();
        Navigation.init();
        StatCounters.init();
        CommandPalette.init();
        Lightbox.init();
    });

    window.ProgressBar = ProgressBar;
    window.StatCounter = StatCounters;
    window.Navigation = Navigation;
    window.StateMemory = StateMemory;
})();
