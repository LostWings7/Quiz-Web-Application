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

        animateBlob(pill, startCoords, endCoords, duration = 330, onComplete = null) {
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

            // Distance intensity scaling
            const distRatio = Math.min(1.0, Math.max(0.2, Math.abs(deltaY) / 180));
            const maxStretchY = (isCollapsed ? 0.12 : 0.09) * distRatio;
            const maxSqueezeX = (isCollapsed ? 0.06 : 0.04) * distRatio;

            // Analytical damped spring parameters (zeta = 0.78 for gentle natural settle, omega = 9.8)
            const zeta = 0.78;
            const omega = 9.8;
            const wd = omega * Math.sqrt(1.0 - zeta * zeta);
            const zetaCoeff = (zeta * omega) / wd;

            // Ensure transitions on transform are disabled during rAF animation
            pill.style.transition = 'none';

            // Immediately position at start point
            pill.style.transform = `translate3d(0, ${startCoords.top.toFixed(2)}px, 0) scale(1, 1)`;
            pill.style.height = `${startCoords.height.toFixed(2)}px`;
            pill.style.opacity = '1';

            // Force reflow
            void pill.offsetHeight;

            let startTime = null;

            const step = (now) => {
                if (!startTime) {
                    startTime = now;
                }
                let t = (now - startTime) / duration;
                if (t < 0) t = 0;
                if (t > 1) t = 1;

                // Unified continuous harmonic spring trajectory
                let ease = 1.0;
                if (t < 1.0) {
                    const envelope = Math.exp(-zeta * omega * t);
                    ease = 1.0 - envelope * (Math.cos(wd * t) + zetaCoeff * Math.sin(wd * t));
                }

                // Smooth coupled stretch & micro-squish
                let scaleY = 1.0;
                let scaleX = 1.0;

                if (Math.abs(deltaY) > 8) {
                    if (t < 0.40) {
                        const stretchPhase = Math.sin((t / 0.40) * Math.PI);
                        scaleY = 1.0 + maxStretchY * stretchPhase;
                        scaleX = 1.0 - maxSqueezeX * stretchPhase;
                    } else {
                        const overshoot = ease - 1.0;
                        scaleY = 1.0 - overshoot * 0.9;
                        scaleX = 1.0 + overshoot * 0.45;
                    }
                }

                const currentTop = startCoords.top + (endCoords.top - startCoords.top) * ease;
                const currentHeight = startCoords.height + (endCoords.height - startCoords.height) * ease;

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

                    let fromTop = null;
                    try {
                        const raw = sessionStorage.getItem('quizx_sidebar_from_top');
                        if (raw !== null) {
                            fromTop = parseFloat(raw);
                            sessionStorage.removeItem('quizx_sidebar_from_top');
                        }
                    } catch (e) {}

                    const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
                    const endCoords = this.getCoords(activeLink, nav);

                    if (fromTop !== null && !isNaN(fromTop) && Math.abs(fromTop - endCoords.top) >= 4 && !prefersReducedMotion) {
                        const startCoords = {
                            top: fromTop,
                            height: endCoords.height
                        };
                        // Execute the full animation in one uninterrupted go on the freshly loaded page
                        this.animateBlob(pill, startCoords, endCoords, 330);
                    } else {
                        this.updatePillPosition(pill, activeLink);
                    }
                } else {
                    pill.style.opacity = '0';
                    try { sessionStorage.removeItem('quizx_sidebar_from_top'); } catch (e) {}
                }

                // Record previous position on link click so the new page animates smoothly in one go
                links.forEach(link => {
                    link.addEventListener('click', () => {
                        const currentActive = nav.querySelector('.app-nav-item.active');
                        if (currentActive) {
                            const startCoords = this.getCurrentPillCoords(pill, currentActive, nav);
                            try {
                                sessionStorage.setItem('quizx_sidebar_from_top', String(startCoords.top));
                            } catch (err) {}
                        }
                    });
                });

                // Also record previous position for general internal navigation links
                document.addEventListener('click', (e) => {
                    const link = e.target.closest('a');
                    if (!link || !link.href || link.closest('.app-sidebar-nav, .dashboard-nav')) return;
                    try {
                        const url = new URL(link.href, window.location.origin);
                        if (url.origin === window.location.origin && url.pathname !== window.location.pathname) {
                            const currentActive = nav.querySelector('.app-nav-item.active');
                            if (currentActive) {
                                const startCoords = this.getCurrentPillCoords(pill, currentActive, nav);
                                sessionStorage.setItem('quizx_sidebar_from_top', String(startCoords.top));
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
    // 7. Theme Manager (Dark Mode & Light Mode Architecture)
    // --------------------------------------------------------------------------
    const ThemeManager = {
        STORAGE_KEY: 'quizx-theme',

        getTheme() {
            try {
                return localStorage.getItem(this.STORAGE_KEY) || document.documentElement.dataset.theme || 'light';
            } catch (e) {
                return document.documentElement.dataset.theme || 'light';
            }
        },

        getChartTokens(theme) {
            const currentTheme = theme || this.getTheme();
            const isDark = currentTheme === 'dark';
            return {
                isDark,
                gridColor: isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(24, 24, 27, 0.06)',
                borderColor: isDark ? 'rgba(255, 255, 255, 0.12)' : 'rgba(24, 24, 27, 0.1)',
                tickColor: isDark ? '#9FA4B4' : '#71717A',
                legendColor: isDark ? '#F4F4F6' : '#18181B',
                tooltipBg: isDark ? '#181A22' : '#FFFFFF',
                tooltipTitle: isDark ? '#F4F4F6' : '#18181B',
                tooltipBody: isDark ? '#9FA4B4' : '#71717A',
                tooltipBorder: isDark ? 'rgba(255, 255, 255, 0.15)' : 'rgba(24, 24, 27, 0.12)',
                sliceBorder: isDark ? '#181A22' : '#000000',
                gaugeEmptySlice: isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(24, 24, 27, 0.06)',
            };
        },

        setTheme(theme, save = true) {
            const nextTheme = (theme === 'dark') ? 'dark' : 'light';
            const prevTheme = document.documentElement.dataset.theme;

            // Apply to document root (data-theme attribute on <html>)
            document.documentElement.dataset.theme = nextTheme;

            if (save) {
                try {
                    localStorage.setItem(this.STORAGE_KEY, nextTheme);
                } catch (e) {}
            }

            // Update UI State on all toggle buttons
            this.updateButtons(nextTheme);

            // Synchronize chart defaults and instances
            ChartThemeSync.applyTheme(nextTheme);

            // Dispatch custom event for charts and decoupled listeners
            if (prevTheme !== nextTheme) {
                document.dispatchEvent(new CustomEvent('quizx:themechange', {
                    detail: { theme: nextTheme, prevTheme }
                }));
            }
        },

        toggleTheme() {
            const current = this.getTheme();
            const next = current === 'dark' ? 'light' : 'dark';
            this.setTheme(next, true);
        },

        updateButtons(theme) {
            const isDark = theme === 'dark';
            const toggleBtns = document.querySelectorAll('.theme-toggle-btn');
            toggleBtns.forEach(btn => {
                btn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
                btn.setAttribute('aria-label', isDark ? 'Switch to light theme' : 'Switch to dark theme');
                btn.setAttribute('title', isDark ? 'Switch to Light Theme (Ctrl+Shift+D)' : 'Switch to Dark Theme (Ctrl+Shift+D)');
            });
        },

        init() {
            // Synchronize current active theme from storage or DOM
            const currentTheme = this.getTheme();
            this.setTheme(currentTheme, false);

            // Bind click handler on existing and dynamically inserted toggle buttons
            document.addEventListener('click', (e) => {
                const btn = e.target.closest('.theme-toggle-btn');
                if (btn) {
                    e.preventDefault();
                    this.toggleTheme();
                }
            });

            // Cross-tab synchronization via storage event
            window.addEventListener('storage', (e) => {
                if (e.key === this.STORAGE_KEY && e.newValue) {
                    this.setTheme(e.newValue, false);
                }
            });

            // Keyboard shortcut: Ctrl + Shift + D
            document.addEventListener('keydown', (e) => {
                if (e.ctrlKey && e.shiftKey && (e.key === 'D' || e.key === 'd')) {
                    const target = e.target;
                    const isInput = target && (
                        ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) ||
                        target.isContentEditable
                    );
                    if (!isInput) {
                        e.preventDefault();
                        this.toggleTheme();
                    }
                }
            });
        }
    };

    // --------------------------------------------------------------------------
    // 8. Chart.js Theme Sync Listener
    // --------------------------------------------------------------------------
    const ChartThemeSync = {
        applyTheme(theme) {
            const currentTheme = theme || ThemeManager.getTheme();
            const tokens = ThemeManager.getChartTokens(currentTheme);

            if (window.Chart) {
                try {
                    window.Chart.defaults.color = tokens.tickColor;
                    window.Chart.defaults.borderColor = tokens.gridColor;
                    if (window.Chart.defaults.plugins) {
                        if (window.Chart.defaults.plugins.legend && window.Chart.defaults.plugins.legend.labels) {
                            window.Chart.defaults.plugins.legend.labels.color = tokens.legendColor;
                        }
                        if (window.Chart.defaults.plugins.tooltip) {
                            window.Chart.defaults.plugins.tooltip.backgroundColor = tokens.tooltipBg;
                            window.Chart.defaults.plugins.tooltip.titleColor = tokens.tooltipTitle;
                            window.Chart.defaults.plugins.tooltip.bodyColor = tokens.tooltipBody;
                            window.Chart.defaults.plugins.tooltip.borderColor = tokens.tooltipBorder;
                        }
                    }
                } catch (e) {}

                if (window.Chart.instances) {
                    Object.values(window.Chart.instances).forEach(chart => {
                        if (!chart || !chart.options) return;

                        // Scales update
                        if (chart.options.scales) {
                            ['x', 'y', 'r'].forEach(axisKey => {
                                if (chart.options.scales[axisKey]) {
                                    const scale = chart.options.scales[axisKey];
                                    if (scale.grid) {
                                        scale.grid.color = tokens.gridColor;
                                        scale.grid.borderColor = tokens.borderColor;
                                    }
                                    if (scale.ticks) {
                                        scale.ticks.color = tokens.tickColor;
                                    }
                                    if (scale.pointLabels) {
                                        scale.pointLabels.color = tokens.tickColor;
                                    }
                                    if (scale.angleLines) {
                                        scale.angleLines.color = tokens.gridColor;
                                    }
                                }
                            });
                        }

                        // Legend & Tooltips
                        if (chart.options.plugins) {
                            if (chart.options.plugins.legend && chart.options.plugins.legend.labels) {
                                chart.options.plugins.legend.labels.color = tokens.legendColor;
                            }
                            if (chart.options.plugins.tooltip) {
                                chart.options.plugins.tooltip.backgroundColor = tokens.tooltipBg;
                                chart.options.plugins.tooltip.titleColor = tokens.tooltipTitle;
                                chart.options.plugins.tooltip.bodyColor = tokens.tooltipBody;
                                chart.options.plugins.tooltip.borderColor = tokens.tooltipBorder;
                            }
                        }

                        // Speed dial gauge empty slice color update (only for 2-slice semi-circle gauges)
                        const isSpeedDial = (chart.config?.options?.plugins?.speedDialNumberPlugin || chart.options?.plugins?.speedDialNumberPlugin) || (chart.canvas && chart.canvas.id === 'overallChart');
                        if (isSpeedDial && chart.data && chart.data.datasets && chart.data.datasets[0]) {
                            if (Array.isArray(chart.data.datasets[0].backgroundColor) && chart.data.datasets[0].backgroundColor.length === 2) {
                                chart.data.datasets[0].backgroundColor[1] = tokens.gaugeEmptySlice;
                            }
                        }

                        chart.update('none');
                    });
                }
            }
        },

        init() {
            // Apply theme colors to chart defaults and any early rendered charts
            this.applyTheme();

            // Listen for theme change events
            document.addEventListener('quizx:themechange', (e) => {
                this.applyTheme(e.detail?.theme);
            });

            // Also re-check once page finishes loading
            window.addEventListener('load', () => {
                this.applyTheme();
            });

            // Fallback intervals for charts rendered with requestAnimationFrame or setTimeout
            setTimeout(() => this.applyTheme(), 150);
            setTimeout(() => this.applyTheme(), 600);
        }
    };

    // --------------------------------------------------------------------------
    // Initialize Everything on DOM Ready
    // --------------------------------------------------------------------------
    document.addEventListener('DOMContentLoaded', () => {
        ThemeManager.init();
        ChartThemeSync.init();
        ProgressBar.init();
        StateMemory.init();
        Navigation.init();
        StatCounters.init();
        CommandPalette.init();
        Lightbox.init();
    });

    window.ThemeManager = ThemeManager;
    window.ProgressBar = ProgressBar;
    window.StatCounter = StatCounters;
    window.Navigation = Navigation;
    window.StateMemory = StateMemory;
})();

