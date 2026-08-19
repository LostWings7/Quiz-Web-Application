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
            const navRect = nav.getBoundingClientRect();
            const linkRect = link.getBoundingClientRect();
            return {
                top: linkRect.top - navRect.top + nav.scrollTop,
                left: linkRect.left - navRect.left,
                width: linkRect.width,
                height: linkRect.height
            };
        },

        animateBlob(pill, startCoords, endCoords, duration = 380, onComplete = null) {
            if (!pill || !startCoords || !endCoords) return;

            if (this.activeAnimation) {
                cancelAnimationFrame(this.activeAnimation);
                this.activeAnimation = null;
            }

            // Immediately position at start point
            pill.style.transform = `translate3d(${startCoords.left}px, ${startCoords.top}px, 0)`;
            pill.style.width = `${startCoords.width}px`;
            pill.style.height = `${startCoords.height}px`;
            pill.style.opacity = '1';

            const startTime = performance.now();

            const step = (now) => {
                let t = (now - startTime) / duration;
                if (t > 1) t = 1;

                // Custom cubic spring-like easing from reference
                const ease = 1 + 1.5 * Math.pow(t - 1, 3) + 0.5 * Math.pow(t - 1, 2);

                const currentTop = startCoords.top + (endCoords.top - startCoords.top) * ease;
                const currentLeft = startCoords.left + (endCoords.left - startCoords.left) * ease;
                const currentWidth = startCoords.width + (endCoords.width - startCoords.width) * ease;
                const currentHeight = startCoords.height + (endCoords.height - startCoords.height) * ease;

                pill.style.transform = `translate3d(${currentLeft}px, ${currentTop}px, 0)`;
                pill.style.width = `${currentWidth}px`;
                pill.style.height = `${currentHeight}px`;

                if (t < 1) {
                    this.activeAnimation = requestAnimationFrame(step);
                } else {
                    pill.style.transform = `translate3d(${endCoords.left}px, ${endCoords.top}px, 0)`;
                    pill.style.width = `${endCoords.width}px`;
                    pill.style.height = `${endCoords.height}px`;
                    this.activeAnimation = null;
                    if (typeof onComplete === 'function') onComplete();
                }
            };

            this.activeAnimation = requestAnimationFrame(step);
        },

        updatePillPosition(pill, targetLink) {
            const nav = targetLink.closest('.app-sidebar-nav, .dashboard-nav');
            if (!nav || !pill) return;

            if (this.activeAnimation) {
                cancelAnimationFrame(this.activeAnimation);
                this.activeAnimation = null;
            }

            const coords = this.getCoords(targetLink, nav);
            pill.style.transform = `translate3d(${coords.left}px, ${coords.top}px, 0)`;
            pill.style.width = `${coords.width}px`;
            pill.style.height = `${coords.height}px`;
            pill.style.opacity = '1';
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
                        localStorage.setItem('quizx_sidebar_collapsed', isCollapsed ? '1' : '0');

                        // Animate pill smoothly during the sidebar width CSS transition (280ms)
                        const pill = nav ? nav.querySelector('.nav-active-pill') : null;
                        const activeItem = nav ? nav.querySelector('.app-nav-item.active') : null;
                        if (pill && activeItem) {
                            if (this.activeAnimation) cancelAnimationFrame(this.activeAnimation);
                            const start = performance.now();
                            const duration = 280; // matches sidebar CSS transition duration
                            const tick = (now) => {
                                const elapsed = now - start;
                                this.updatePillPosition(pill, activeItem);
                                if (elapsed < duration) {
                                    this.activeAnimation = requestAnimationFrame(tick);
                                } else {
                                    this.updatePillPosition(pill, activeItem);
                                    this.activeAnimation = null;
                                }
                            };
                            this.activeAnimation = requestAnimationFrame(tick);
                        }
                    });
                });

                if (localStorage.getItem('quizx_sidebar_collapsed') === '1' && window.innerWidth > 992) {
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
                    nav.appendChild(pill);
                }

                const normalizePath = (p) => {
                    if (!p) return '/';
                    let s = p.trim();
                    if (!s.startsWith('/')) s = '/' + s;
                    if (s.length > 1 && s.endsWith('/')) s = s.slice(0, -1);
                    return s;
                };

                const currentNorm = normalizePath(window.location.pathname);
                const links = Array.from(nav.querySelectorAll('a[href]'));

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

                    // Check for previous sidebar navigation path from sessionStorage
                    let previousPath = null;
                    try {
                        previousPath = sessionStorage.getItem('quizx_previous_sidebar_path');
                    } catch (e) {}

                    let previousLink = null;
                    if (previousPath) {
                        const prevNorm = normalizePath(previousPath);
                        previousLink = links.find(l => {
                            const linkNorm = normalizePath(new URL(l.href, window.location.origin).pathname);
                            return linkNorm === prevNorm;
                        });
                    }

                    if (previousLink && previousLink !== activeLink) {
                        // Animate blob smoothly across page load from previous position to active position
                        const startCoords = this.getCoords(previousLink, nav);
                        const endCoords = this.getCoords(activeLink, nav);
                        this.animateBlob(pill, startCoords, endCoords, 380, () => {
                            try { sessionStorage.removeItem('quizx_previous_sidebar_path'); } catch (e) {}
                        });
                    } else {
                        // Position instantly on page load without animation (no flash)
                        this.updatePillPosition(pill, activeLink);
                        try { sessionStorage.removeItem('quizx_previous_sidebar_path'); } catch (e) {}
                    }
                } else {
                    pill.style.opacity = '0';
                    try { sessionStorage.removeItem('quizx_previous_sidebar_path'); } catch (e) {}
                }

                // Record clicked path and animate on click
                links.forEach(link => {
                    link.addEventListener('click', () => {
                        try {
                            sessionStorage.setItem('quizx_previous_sidebar_path', window.location.pathname);
                        } catch (e) {}

                        const currentActive = nav.querySelector('.app-nav-item.active');
                        if (currentActive && currentActive !== link) {
                            links.forEach(l => l.classList.remove('active'));
                            link.classList.add('active');
                            const startCoords = this.getCoords(currentActive, nav);
                            const endCoords = this.getCoords(link, nav);
                            this.animateBlob(pill, startCoords, endCoords, 380);
                        } else {
                            links.forEach(l => l.classList.remove('active'));
                            link.classList.add('active');
                            this.updatePillPosition(pill, link);
                        }
                    });
                });

                // Also record previous path for general internal link navigation
                document.addEventListener('click', (e) => {
                    const link = e.target.closest('a');
                    if (!link || !link.href) return;
                    try {
                        const url = new URL(link.href, window.location.origin);
                        if (url.origin === window.location.origin) {
                            sessionStorage.setItem('quizx_previous_sidebar_path', window.location.pathname);
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
            // Check prefers-reduced-motion
            if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
                return;
            }

            const elements = document.querySelectorAll('[data-count-to]');
            elements.forEach(el => {
                const targetStr = el.getAttribute('data-count-to');
                const target = parseFloat(targetStr);
                if (isNaN(target)) return;

                const decimals = (targetStr.split('.')[1] || '').length;
                const duration = parseInt(el.getAttribute('data-duration') || '750', 10);
                const prefix = el.getAttribute('data-prefix') || '';
                const suffix = el.getAttribute('data-suffix') || '';

                let startTime = null;

                function easeOutExpo(t) {
                    return t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
                }

                function step(timestamp) {
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
                }

                requestAnimationFrame(step);
            });
        }
    };

    // --------------------------------------------------------------------------
    // 4. Global Modal System
    // --------------------------------------------------------------------------
    window.showModal = function (modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
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
            const openModal = document.querySelector('.modal-overlay.show');
            if (openModal) {
                window.hideModal(openModal);
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
            if (chevron) chevron.style.transform = 'rotate(0deg)';
        } else {
            content.classList.add('expanded');
            if (chevron) chevron.style.transform = 'rotate(180deg)';
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
    // 7. Scroll State Retention
    // --------------------------------------------------------------------------
    const ScrollState = {
        init() {
            // Restore and save sidebar scroll
            const sidebars = document.querySelectorAll('.app-sidebar-nav, .dashboard-nav');
            sidebars.forEach(sidebar => {
                const sidebarKey = 'scroll_sidebar';
                const savedScroll = sessionStorage.getItem(sidebarKey);
                if (savedScroll) {
                    // Slight delay to override native browser restoration sometimes
                    setTimeout(() => {
                        sidebar.scrollTop = parseInt(savedScroll, 10);
                    }, 10);
                }
                sidebar.addEventListener('scroll', () => {
                    sessionStorage.setItem(sidebarKey, sidebar.scrollTop);
                }, { passive: true });
            });

            // Restore and save page scroll
            const pageKey = 'scroll_page_' + window.location.pathname;
            
            // Check window scroll
            const savedWindowScroll = sessionStorage.getItem(pageKey + '_win');
            if (savedWindowScroll) {
                setTimeout(() => {
                    window.scrollTo(0, parseInt(savedWindowScroll, 10));
                }, 50);
            }
            window.addEventListener('scroll', () => {
                sessionStorage.setItem(pageKey + '_win', window.scrollY);
            }, { passive: true });

            // Check main container scroll (if layout uses overflow-y on .app-main-layout)
            const mainLayout = document.querySelector('.app-main-layout');
            if (mainLayout) {
                const savedMainScroll = sessionStorage.getItem(pageKey + '_main');
                if (savedMainScroll) {
                    setTimeout(() => {
                        mainLayout.scrollTop = parseInt(savedMainScroll, 10);
                    }, 50);
                }
                mainLayout.addEventListener('scroll', () => {
                    sessionStorage.setItem(pageKey + '_main', mainLayout.scrollTop);
                }, { passive: true });
            }
        }
    };

    // --------------------------------------------------------------------------
    // Initialize Everything on DOM Ready
    // --------------------------------------------------------------------------
    document.addEventListener('DOMContentLoaded', () => {
        ProgressBar.init();
        ScrollState.init();
        Navigation.init();
        StatCounters.init();
        CommandPalette.init();
        Lightbox.init();
    });

    window.ProgressBar = ProgressBar;
})();
