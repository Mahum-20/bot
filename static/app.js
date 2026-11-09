document.addEventListener('DOMContentLoaded', () => {
    const mainContainer = document.getElementById('main-content');
    const container = document.getElementById('chart-container');
    const canvas = document.getElementById('overlay-canvas');
    const ctx = canvas.getContext('2d');

    // Split LTF elements
    const splitContainer = document.getElementById('split-ltf-container');
    const ltfChartDiv = document.getElementById('ltf-chart');
    const ltfCanvas = document.getElementById('ltf-overlay-canvas');
    const ltfCtx = ltfCanvas ? ltfCanvas.getContext('2d') : null;
    const ltfTitle = document.getElementById('ltf-title');
    const ltfTargetDate = document.getElementById('ltf-target-date');
    const ltfOhlcLegend = document.getElementById('ltf-ohlc-legend');
    const htfOhlcLegend = document.getElementById('htf-ohlc-legend');
    const htfTitle = document.getElementById('htf-title');
    const btnCloseSplit = document.getElementById('btn-close-split');

    let chart = null;
    let candlestickSeries = null;
    let currentCandles = [];
    let currentStrategy = null;
    let ws = null;

    let ltfChart = null;
    let ltfSeries = null;
    let ltfCandles = [];
    let ltfLoadedLabels = [];
    let ltfLoadedLines = [];
    let ltfLoadedBoxes = [];
    let ltfLoadedSignals = [];
    let isSplitOpen = false;
    let activeSplitTargetTime = null;
    let ltfInteractionsSetup = false;
    let currentSignalAnalysis = null;
    let allTimeframeSignals = [];
    let activeSignalIndex = -1;
    let mainChartSignalHitboxes = [];
    let hoveredSignal = null;

    // Timeframe selector buttons (H4, H1, M15, M5, M1)
    const tfButtons = document.querySelectorAll('.tf-btn');
    let activeTimeframe = '15m';
    let activeSymbol = 'BTCUSDT';
    window.activeTimeframe = activeTimeframe;

    // Toolbar buttons
    const toolCursor = document.getElementById('tool-cursor');
    const toolBox = document.getElementById('tool-box');
    const toolTrendline = document.getElementById('tool-trendline');
    const toolClearAll = document.getElementById('tool-clear-all');

    // Floating Drawing Property Bar elements
    const propFloatingBar = document.getElementById('drawing-floating-bar');
    const propColorDots = document.querySelectorAll('#prop-color-palette .color-dot');
    const propBgGroup = document.getElementById('prop-bg-group');
    const propBgOpacity = document.getElementById('prop-bg-opacity');
    const propLineWidth = document.getElementById('prop-line-width');
    const propLineStyle = document.getElementById('prop-line-style');
    const propTextInput = document.getElementById('prop-text-input');
    const propDeleteBtn = document.getElementById('prop-delete-btn');
    const propCloseBtn = document.getElementById('prop-close-btn');

    // =========================================================================
    // USER DRAWINGS STATE & PERSISTENCE
    // =========================================================================
    let activeTool = 'cursor'; // 'cursor' | 'box' | 'trendline'
    let activeColor = '#2962ff';
    let activeBgOpacity = 0.25;
    let activeLineWidth = 1.5;
    let activeLineStyle = 'solid';

    let userDrawings = [];
    try {
        userDrawings = JSON.parse(localStorage.getItem('topg_user_drawings') || '[]');
    } catch (e) {
        userDrawings = [];
    }

    let selectedDrawing = null;
    let activeDrawingDraft = null;
    let isDrawing = false;
    let activeDrag = null; // { drawing, handle, origT1, origP1, origT2, origP2, startT, startP }
    let activeChartSource = 'htf'; // 'htf' | 'ltf'

    function saveDrawings() {
        try {
            localStorage.setItem('topg_user_drawings', JSON.stringify(userDrawings));
        } catch (e) {
            console.error("Error saving drawings:", e);
        }
    }

    function hexToRgba(hex, alpha) {
        if (!hex) return `rgba(41, 98, 255, ${alpha})`;
        let c = hex.replace('#', '');
        if (c.length === 3) c = c.split('').map(x => x + x).join('');
        const num = parseInt(c, 16);
        const r = (num >> 16) & 255;
        const g = (num >> 8) & 255;
        const b = num & 255;
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    function setTimeframe(tf) {
        activeTimeframe = tf.toLowerCase(); window.activeTimeframe = activeTimeframe;
        tfButtons.forEach(btn => {
            if (btn.getAttribute('data-tf').toLowerCase() === activeTimeframe) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        if (htfTitle) {
            htfTitle.textContent = `${activeSymbol} | ${activeTimeframe.toUpperCase()}`;
        }
        const hintEl = document.getElementById('double-click-hint');
        if (hintEl) {
            const h = (activeTimeframe || '').toLowerCase();
            if (h === '15m' || h === '1h' || h === '4h') {
                const ltfT = getLTFIntervalForHTF(activeTimeframe).toUpperCase();
                hintEl.textContent = `DOUBLE-CLICK ANY CANDLE FOR ${ltfT} BREAKDOWN`;
            } else {
                hintEl.textContent = `HTF ${activeTimeframe.toUpperCase()} VIEW ONLY (TRADING RESTRICTED TO 15M->1M, 1H->1M, 4H->5M)`;
            }
        }

        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                action: 'change_timeframe',
                htf_interval: activeTimeframe,
                symbol: activeSymbol,
                mode: 'standalone'
            }));
        }
        if (typeof loadInitialChartData === 'function') {
            loadInitialChartData();
        }
        if (isSplitOpen && typeof openSplitLTF === 'function') {
            openSplitLTF(0);
        }
    }

    tfButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const tf = btn.getAttribute('data-tf');
            if (tf && tf.toLowerCase() !== activeTimeframe) {
                setTimeframe(tf);
            }
        });
    });

    // 8 Locked Production Coins Controller (Select Tag)
    const symbolSelect = document.getElementById('symbol-select');
    function setSymbol(sym) {
        activeSymbol = sym.toUpperCase();
        if (symbolSelect && symbolSelect.value.toUpperCase() !== activeSymbol) {
            symbolSelect.value = activeSymbol;
        }
        if (htfTitle) {
            htfTitle.textContent = `${activeSymbol} | ${activeTimeframe.toUpperCase()}`;
        }
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                action: 'change_symbol',
                symbol: activeSymbol,
                htf_interval: activeTimeframe
            }));
        }
        if (typeof loadInitialChartData === 'function') {
            loadInitialChartData();
        }
        if (isSplitOpen && typeof openSplitLTF === 'function') {
            openSplitLTF(0);
        }
    }

    if (symbolSelect) {
        symbolSelect.addEventListener('change', (e) => {
            const sym = e.target.value;
            if (sym && sym.toUpperCase() !== activeSymbol) {
                setSymbol(sym);
            }
        });
    }

    // =========================================================================
    // 1. RBAC AUTHENTICATION CONTROLLER (ADMIN VS USER VIEW)
    // =========================================================================
    const btnLogout = document.getElementById('btn-logout');

    function applyRoleRestrictions(role, username) {
        const isViewer = (role === 'user');
        if (isViewer) {
            document.body.classList.add('role-user');
            
            // Update sidebar user display
            const avatar = document.querySelector('.user-avatar');
            if (avatar) avatar.textContent = 'U';
            const nameEl = document.querySelector('.user-name');
            if (nameEl) nameEl.textContent = username || 'user';
            const roleEl = document.querySelector('.user-role');
            if (roleEl) roleEl.innerHTML = '<span class="status-dot"></span> Viewer (Read-Only)';

            // Update sidebar labels
            const overviewLabel = document.querySelector('#nav-overview .nav-label');
            if (overviewLabel) overviewLabel.textContent = 'Overview & Positions';

            const navLabels = document.querySelectorAll('.nav-section-label');
            if (navLabels.length > 0) {
                navLabels[0].textContent = 'Portfolio View';
            }
            if (navLabels.length > 1) {
                navLabels[1].textContent = 'History Ledger';
            }

            // If user is currently on an admin page, switch to overview
            const activeNav = document.querySelector('.sidebar-nav .nav-item.active');
            if (activeNav) {
                const curPage = activeNav.getAttribute('data-page');
                if (curPage === 'calendar' || curPage === 'risk') {
                    navigateToPage('overview');
                }
            }
        } else {
            document.body.classList.remove('role-user');
            const avatar = document.querySelector('.user-avatar');
            if (avatar) avatar.textContent = (username || 'M')[0].toUpperCase();
            const nameEl = document.querySelector('.user-name');
            if (nameEl) nameEl.textContent = username || 'mahum';
            const roleEl = document.querySelector('.user-role');
            if (roleEl) roleEl.innerHTML = '<span class="status-dot"></span> Administrator';

            const overviewLabel = document.querySelector('#nav-overview .nav-label');
            if (overviewLabel) overviewLabel.textContent = 'Overview & Controls';
        }
    }

    async function checkAuthStatus() {
        const urlParams = new URLSearchParams(window.location.search);
        let token = urlParams.get('token') || localStorage.getItem('topg_admin_token') || localStorage.getItem('topg_session_token');
        if (token) {
            localStorage.setItem('topg_admin_token', token);
            localStorage.setItem('topg_session_token', token);
        }
        if (!token) {
            window.location.replace('/login');
            return false;
        }
        try {
            const res = await fetch(`/api/auth/verify?token=${encodeURIComponent(token)}`);
            if (res.ok) {
                const data = await res.json();
                if (data.authenticated) {
                    applyRoleRestrictions(data.role, data.username);
                    return true;
                }
            }
        } catch (e) {
            console.warn("Auth verification network error:", e);
        }
        localStorage.removeItem('topg_admin_token');
        localStorage.removeItem('topg_role');
        localStorage.removeItem('topg_username');
        window.location.replace('/login');
        return false;
    }

    if (btnLogout) {
        btnLogout.addEventListener('click', async () => {
            const token = localStorage.getItem('topg_admin_token');
            if (token) {
                try {
                    await fetch('/api/auth/logout', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ token })
                    });
                } catch (e) {}
            }
            localStorage.removeItem('topg_admin_token');
            localStorage.removeItem('topg_role');
            localStorage.removeItem('topg_username');
            window.location.replace('/login');
        });
    }

    // Check auth on load
    checkAuthStatus();

    // =========================================================================
    // 2. MODERN VERTICAL SIDEBAR NAVIGATION & PAGES
    // =========================================================================
    const navItems = document.querySelectorAll('.sidebar-nav .nav-item');
    const pagePanes = document.querySelectorAll('.page-pane');
    const pageHeaderTitle = document.getElementById('page-header-title');
    const chartControlsWrapper = document.getElementById('chart-controls-wrapper');
    const btnViewAllEvents = document.getElementById('btn-view-all-events');

    const PAGE_TITLES = {
        'overview': 'System Overview & Execution Controls',
        'charts': 'Live Multi-Timeframe Strategy Charts',
        'calendar': 'Macroeconomic Releases Calendar (CPI / FOMC / NFP)',
        'history': 'Complete Closed Trades Ledger & History',
        'risk': 'Institutional Portfolio Risk Guardrails'
    };



    const sidebarBrand = document.getElementById('sidebar-brand');
    if (sidebarBrand) {
        sidebarBrand.addEventListener('click', () => {
            navigateToPage('overview');
        });
    }

    function navigateToPage(pageId) {
        if (document.body.classList.contains('role-user')) {
            if (pageId === 'calendar' || pageId === 'risk') {
                pageId = 'overview';
            }
        }

        try {
            if (window.location.hash !== `#${pageId}`) {
                history.replaceState(null, '', `#${pageId}`);
            }
        } catch (e) {}

        navItems.forEach(item => {
            if (item.getAttribute('data-page') === pageId) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });

        pagePanes.forEach(pane => {
            if (pane.id === `page-${pageId}`) {
                pane.classList.add('active');
            } else {
                pane.classList.remove('active');
            }
        });

        const isCharts = (pageId === 'charts');
        const topbarBadgesWrapper = document.getElementById('topbar-badges-wrapper');

        if (pageHeaderTitle) {
            pageHeaderTitle.style.display = 'none';
        }

        // Toggle chart topbar controls (only symbol select + timeframes, nothing else)
        if (chartControlsWrapper) {
            chartControlsWrapper.style.display = isCharts ? 'flex' : 'none';
        }

        // Show status badges on non-chart pages
        if (topbarBadgesWrapper) {
            topbarBadgesWrapper.style.display = isCharts ? 'none' : 'flex';
        }

        // Action when entering specific pages
        if (pageId === 'charts') {
            setTimeout(() => {
                resizeCanvas();
                if (chart) {
                    if (currentCandles && currentCandles.length > 0) {
                        chart.timeScale().fitContent();
                    } else {
                        loadInitialChartData();
                    }
                }
                drawOverlay();
                if (isSplitOpen) {
                    resizeLTFCanvas();
                    drawLTFOverlay();
                }
            }, 50);
            setTimeout(() => {
                resizeCanvas();
                if (chart && currentCandles && currentCandles.length > 0) {
                    chart.timeScale().fitContent();
                }
                drawOverlay();
                if (isSplitOpen) {
                    resizeLTFCanvas();
                    drawLTFOverlay();
                }
            }, 200);
        } else if (pageId === 'overview') {
            loadDashboardData();
            loadMacroEvents();
        } else if (pageId === 'calendar') {
            loadMacroEvents();
        } else if (pageId === 'history') {
            loadDashboardData();
        }
    }

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const pageId = item.getAttribute('data-page');
            navigateToPage(pageId);
        });
    });

    if (btnViewAllEvents) {
        btnViewAllEvents.addEventListener('click', () => {
            navigateToPage('calendar');
        });
    }

    // =========================================================================
    // 3. MASTER BOT HERO SWITCH (TURN ON / TURN OFF / RESET BREAKER)
    // =========================================================================
    const btnTurnOnBot = document.getElementById('btn-turn-on-bot');
    const btnTurnOffBot = document.getElementById('btn-turn-off-bot');
    const heroStatusPill = document.getElementById('hero-status-pill');
    const heroStatusText = document.getElementById('hero-status-text');
    const btnResetBreaker = document.getElementById('btn-reset-breaker');
    const testDiscordBtn = document.getElementById('btn-discord-test');
    const btnRefreshHistory = document.getElementById('btn-refresh-history');

    function updateBotBtnUI(isEnabled, coinCount) {
        if (heroStatusPill && heroStatusText) {
            if (isEnabled) {
                heroStatusPill.className = 'hero-status-pill';
                const count = coinCount || (window.lastPortfolioStatus && window.lastPortfolioStatus.locked_coins ? window.lastPortfolioStatus.locked_coins.length : 2);
                heroStatusText.textContent = `BOT IS ACTIVE & SCANNING (${count} COINS)`;
            } else {
                heroStatusPill.className = 'hero-status-pill status-paused';
                heroStatusText.textContent = 'BOT IS PAUSED BY ADMIN';
            }
        }

        if (btnTurnOnBot && btnTurnOffBot) {
            if (isEnabled) {
                btnTurnOnBot.style.opacity = '0.6';
                btnTurnOffBot.style.opacity = '1.0';
            } else {
                btnTurnOnBot.style.opacity = '1.0';
                btnTurnOffBot.style.opacity = '0.6';
            }
        }

        const dashStatus = document.getElementById('dash-bot-status');
        if (dashStatus) {
            dashStatus.textContent = isEnabled ? 'ONLINE' : 'PAUSED';
            dashStatus.style.color = isEnabled ? '#4caf50' : '#ff5252';
        }
    }

    async function setBotState(enabled) {
        try {
            const res = await fetch('/api/bot/toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: enabled })
            });
            const data = await res.json();
            updateBotBtnUI(data.bot_enabled);
            updatePortfolioBadge();
        } catch (e) {
            alert('Error updating bot status: ' + e.message);
        }
    }

    if (btnTurnOnBot) {
        btnTurnOnBot.addEventListener('click', () => setBotState(true));
    }
    if (btnTurnOffBot) {
        btnTurnOffBot.addEventListener('click', () => setBotState(false));
    }

    if (btnResetBreaker) {
        btnResetBreaker.addEventListener('click', async () => {
            if (confirm('Reset the daily circuit breaker and allow new trade signals?')) {
                try {
                    const res = await fetch('/api/portfolio/reset_circuit_breaker', { method: 'POST' });
                    const data = await res.json();
                    if (data.success) {
                        alert('Circuit Breaker has been reset to OK.');
                        updatePortfolioBadge();
                        loadDashboardData();
                    }
                } catch (e) {
                    alert('Error resetting circuit breaker: ' + e.message);
                }
            }
        });
    }

    if (testDiscordBtn) {
        testDiscordBtn.addEventListener('click', async () => {
            testDiscordBtn.textContent = 'Sending...';
            try {
                const res = await fetch('/api/discord/test');
                const result = await res.json();
                if (result.success) {
                    alert('Discord Webhook verified! Check your Discord channel for the confirmation card.');
                } else {
                    const promptUrl = prompt('Discord webhook not configured yet. Paste your Discord Webhook URL here:');
                    if (promptUrl && promptUrl.startsWith('http')) {
                        const setRes = await fetch('/api/discord/set_webhook', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ webhook_url: promptUrl })
                        });
                        const setResult = await setRes.json();
                        if (setResult.success) {
                            alert('Discord Webhook saved! Now testing...');
                            const retry = await fetch('/api/discord/test');
                            const retryRes = await retry.json();
                            alert(retryRes.message);
                        }
                    }
                }
            } catch (err) {
                alert('Error testing Discord webhook: ' + err.message);
            } finally {
                testDiscordBtn.textContent = 'Test Discord';
            }
        });
    }

    if (btnRefreshHistory) {
        btnRefreshHistory.addEventListener('click', () => {
            loadDashboardData();
        });
    }

    // =========================================================================
    // 3B. BINANCE FUTURES LIVE EXECUTION GATEWAY
    // =========================================================================
    const binanceModeInput = document.getElementById('binance-mode-input');
    const binanceKeyInput = document.getElementById('binance-key-input');
    const binanceSecretInput = document.getElementById('binance-secret-input');
    const btnSaveBinance = document.getElementById('btn-save-binance');
    const btnTestBinance = document.getElementById('btn-test-binance');
    const binanceModePill = document.getElementById('binance-mode-pill');
    const binanceStatusIndicator = document.getElementById('binance-status-indicator');
    const binanceUsdtBalance = document.getElementById('binance-usdt-balance');

    async function fetchBinanceStatus() {
        try {
            const res = await fetch('/api/binance/status');
            if (!res.ok) return;
            const data = await res.json();
            
            if (binanceModeInput && data.mode) {
                binanceModeInput.value = data.mode;
            }
            if (binanceKeyInput) {
                if (data.masked_key) {
                    binanceKeyInput.value = data.masked_key;
                }
            }
            if (binanceSecretInput) {
                binanceSecretInput.value = '';
                if (data.secret_configured) {
                    binanceSecretInput.placeholder = '•••••••••••••••• (Encrypted in Vault DB)';
                } else {
                    binanceSecretInput.placeholder = 'Paste API Secret...';
                }
            }
            if (binanceModePill) {
                binanceModePill.textContent = `MODE: ${data.mode || 'PAPER'}`;
                if (data.mode === 'LIVE') {
                    binanceModePill.style.color = '#ef5350';
                    binanceModePill.style.borderColor = '#ef5350';
                } else if (data.mode === 'TESTNET') {
                    binanceModePill.style.color = '#ff9800';
                    binanceModePill.style.borderColor = '#ff9800';
                } else {
                    binanceModePill.style.color = '#2962ff';
                    binanceModePill.style.borderColor = '#2962ff';
                }
            }
            if (binanceStatusIndicator) {
                if (data.success) {
                    if (data.mode === 'PAPER') {
                        binanceStatusIndicator.textContent = 'Paper Simulation Active';
                        binanceStatusIndicator.style.color = '#26a69a';
                    } else {
                        binanceStatusIndicator.textContent = `Connected (${data.mode})`;
                        binanceStatusIndicator.style.color = '#4caf50';
                    }
                } else {
                    binanceStatusIndicator.textContent = `Disconnected: ${data.error || 'Check Keys'}`;
                    binanceStatusIndicator.style.color = '#ef5350';
                }
            }
            if (binanceUsdtBalance && data.usdt_balance !== undefined) {
                binanceUsdtBalance.textContent = `$${Number(data.usdt_balance).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDT`;
            }
        } catch (e) {
            console.error('Error fetching Binance status:', e);
        }
    }

    if (btnSaveBinance) {
        btnSaveBinance.addEventListener('click', async () => {
            const mode = binanceModeInput.value;
            let key = binanceKeyInput.value.trim();
            const secret = binanceSecretInput.value.trim();

            // If key contains mask asterisks or bullets, user didn't re-type it; preserve existing
            if (key.includes('****') || key.includes('••••')) {
                key = '';
            }

            if (mode !== 'PAPER' && (!key && !secret)) {
                // If neither key nor secret provided, check if already configured
                if (!confirm(`Save execution mode as ${mode}?`)) {
                    return;
                }
            }

            // Purge secret immediately from input element so it cannot be inspected in DOM
            binanceSecretInput.value = '';

            btnSaveBinance.textContent = 'Saving...';
            try {
                const res = await fetch('/api/binance/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ mode: mode, api_key: key, api_secret: secret })
                });
                const result = await res.json();
                if (result.success) {
                    const conn = result.connection || {};
                    if (conn.success) {
                        alert(`Binance Configuration Saved Securely in Vault!\nMode: ${conn.mode}\nStatus: Connected\nBalance: $${conn.usdt_balance} USDT`);
                    } else {
                        alert(`Configuration saved in vault, but exchange connection returned:\n${conn.error || conn.message}`);
                    }
                    fetchBinanceStatus();
                    updatePortfolioBadge();
                    if (typeof fetchPortfolioData === 'function') fetchPortfolioData();
                } else {
                    alert('Failed to save configuration.');
                }
            } catch (err) {
                alert('Error saving Binance credentials: ' + err.message);
            } finally {
                btnSaveBinance.textContent = 'Save & Connect';
            }
        });
    }

    if (btnTestBinance) {
        btnTestBinance.addEventListener('click', async () => {
            btnTestBinance.textContent = 'Testing...';
            try {
                const res = await fetch('/api/binance/status');
                const data = await res.json();
                if (data.success) {
                    alert(`Binance Connection Verified!\nMode: ${data.mode}\nUSDT Balance: $${Number(data.usdt_balance).toFixed(2)}\nAvailable: $${Number(data.available_balance || data.usdt_balance).toFixed(2)}`);
                } else {
                    alert(`Binance Connection Failed:\n${data.error || data.message}`);
                }
                fetchBinanceStatus();
                if (typeof fetchPortfolioData === 'function') fetchPortfolioData();
            } catch (err) {
                alert('Error testing connection: ' + err.message);
            } finally {
                btnTestBinance.textContent = 'Test Connection';
            }
        });
    }

    // =========================================================================
    // 3C. DYNAMIC RISK & ALLOCATION GUARDRAILS CONTROLS
    // =========================================================================
    const inputNormalRisk = document.getElementById('input-normal-risk');
    const inputThrottledRisk = document.getElementById('input-throttled-risk');
    const inputMaxAlloc = document.getElementById('input-max-alloc');
    const btnToggleThrottling = document.getElementById('btn-toggle-throttling');
    const btnSaveRiskSettings = document.getElementById('btn-save-risk-settings');
    const riskTuningPill = document.getElementById('risk-tuning-pill');
    const badgeActiveRiskVal = document.getElementById('badge-active-risk-val');
    const badgeActiveAllocVal = document.getElementById('badge-active-alloc-val');
    const riskStatusFeedback = document.getElementById('risk-status-feedback');
    const riskPresetBtns = document.querySelectorAll('.risk-preset-btn');
    const allocPresetBtns = document.querySelectorAll('.alloc-preset-btn');

    let isThrottlingEnabled = true;
    let isUserTypingRisk = false;

    if (inputNormalRisk) {
        inputNormalRisk.addEventListener('focus', () => { isUserTypingRisk = true; });
        inputNormalRisk.addEventListener('blur', () => { isUserTypingRisk = false; });
    }
    if (inputThrottledRisk) {
        inputThrottledRisk.addEventListener('focus', () => { isUserTypingRisk = true; });
        inputThrottledRisk.addEventListener('blur', () => { isUserTypingRisk = false; });
    }
    if (inputMaxAlloc) {
        inputMaxAlloc.addEventListener('focus', () => { isUserTypingRisk = true; });
        inputMaxAlloc.addEventListener('blur', () => { isUserTypingRisk = false; });
    }

    // Toggle Drawdown Throttling
    function updateThrottlingBtnUI(enabled) {
        isThrottlingEnabled = enabled;
        if (btnToggleThrottling) {
            if (enabled) {
                btnToggleThrottling.textContent = 'ENABLED';
                btnToggleThrottling.style.color = '#26a69a';
                btnToggleThrottling.style.borderColor = '#26a69a';
                btnToggleThrottling.style.background = 'rgba(38, 166, 154, 0.2)';
            } else {
                btnToggleThrottling.textContent = 'DISABLED';
                btnToggleThrottling.style.color = '#787b86';
                btnToggleThrottling.style.borderColor = '#363a45';
                btnToggleThrottling.style.background = 'rgba(120, 123, 134, 0.15)';
            }
        }
        if (riskTuningPill) {
            if (!enabled) {
                riskTuningPill.textContent = 'FACTOR 3: DISABLED';
                riskTuningPill.style.color = '#787b86';
                riskTuningPill.style.borderColor = '#787b86';
            } else {
                riskTuningPill.textContent = 'FACTOR 3: ACTIVE';
                riskTuningPill.style.color = '#26a69a';
                riskTuningPill.style.borderColor = '#26a69a';
            }
        }
    }

    if (btnToggleThrottling) {
        btnToggleThrottling.addEventListener('click', () => {
            updateThrottlingBtnUI(!isThrottlingEnabled);
        });
    }

    // Toggle Toxic Hours Session Filter
    const btnToggleSessionFilter = document.getElementById('btn-toggle-session-filter');
    let isSessionFilterEnabled = true;

    function updateSessionFilterBtnUI(enabled) {
        isSessionFilterEnabled = enabled;
        if (btnToggleSessionFilter) {
            if (enabled) {
                btnToggleSessionFilter.textContent = 'ENABLED';
                btnToggleSessionFilter.style.color = '#26a69a';
                btnToggleSessionFilter.style.borderColor = '#26a69a';
                btnToggleSessionFilter.style.background = 'rgba(38, 166, 154, 0.2)';
            } else {
                btnToggleSessionFilter.textContent = 'DISABLED';
                btnToggleSessionFilter.style.color = '#787b86';
                btnToggleSessionFilter.style.borderColor = '#363a45';
                btnToggleSessionFilter.style.background = 'rgba(120, 123, 134, 0.15)';
            }
        }
    }

    if (btnToggleSessionFilter) {
        btnToggleSessionFilter.addEventListener('click', () => {
            updateSessionFilterBtnUI(!isSessionFilterEnabled);
        });
    }

    // Toggle SL Buffer & Order Execution Type
    const btnToggleSlBuffer = document.getElementById('btn-toggle-sl-buffer');
    const inputSlBufferPct = document.getElementById('input-sl-buffer-pct');
    const selectOrderExecType = document.getElementById('select-order-exec-type');
    const badgeActiveOrderType = document.getElementById('badge-active-order-type');
    let isSlBufferEnabled = true;

    function updateSlBufferBtnUI(enabled) {
        isSlBufferEnabled = enabled;
        if (btnToggleSlBuffer) {
            if (enabled) {
                btnToggleSlBuffer.textContent = 'ENABLED';
                btnToggleSlBuffer.style.color = '#26a69a';
                btnToggleSlBuffer.style.borderColor = '#26a69a';
                btnToggleSlBuffer.style.background = 'rgba(38, 166, 154, 0.2)';
            } else {
                btnToggleSlBuffer.textContent = 'DISABLED';
                btnToggleSlBuffer.style.color = '#787b86';
                btnToggleSlBuffer.style.borderColor = '#363a45';
                btnToggleSlBuffer.style.background = 'rgba(120, 123, 134, 0.15)';
            }
        }
    }

    if (btnToggleSlBuffer) {
        btnToggleSlBuffer.addEventListener('click', () => {
            updateSlBufferBtnUI(!isSlBufferEnabled);
        });
    }

    if (selectOrderExecType) {
        selectOrderExecType.addEventListener('change', () => {
            const val = selectOrderExecType.value;
            if (badgeActiveOrderType) {
                badgeActiveOrderType.textContent = (val === 'LIMIT') ? 'POST-ONLY LIMIT' : 'MARKET ORDER';
                badgeActiveOrderType.style.color = (val === 'LIMIT') ? '#2962ff' : '#ff9800';
            }
        });
    }

    // Risk preset buttons
    riskPresetBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            riskPresetBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            if (inputNormalRisk) {
                inputNormalRisk.value = btn.dataset.val;
            }
        });
    });

    // Allocation preset buttons
    allocPresetBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            allocPresetBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            if (inputMaxAlloc) {
                inputMaxAlloc.value = btn.dataset.val;
            }
        });
    });

    // Save Risk Settings
    if (btnSaveRiskSettings) {
        btnSaveRiskSettings.addEventListener('click', async () => {
            const normalRisk = parseFloat(inputNormalRisk.value);
            const throttledRisk = parseFloat(inputThrottledRisk.value);
            const maxAlloc = parseFloat(inputMaxAlloc.value);

            if (isNaN(normalRisk) || normalRisk <= 0 || normalRisk > 10) {
                alert('Please enter a valid Base Risk per trade between 0.1% and 10.0%.');
                return;
            }
            if (isNaN(throttledRisk) || throttledRisk <= 0 || throttledRisk > 5) {
                alert('Please enter a valid Throttled Risk between 0.1% and 5.0%.');
                return;
            }
            if (isNaN(maxAlloc) || maxAlloc <= 0 || maxAlloc > 50) {
                alert('Please enter a valid Max Capital Allocation between 1.0% and 50.0%.');
                return;
            }

            const slBufferPct = inputSlBufferPct ? parseFloat(inputSlBufferPct.value) : 0.12;
            const orderExecType = selectOrderExecType ? selectOrderExecType.value : "LIMIT";

            btnSaveRiskSettings.textContent = 'Saving...';
            try {
                const res = await fetch('/api/risk/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        normal_risk_pct: normalRisk,
                        throttled_risk_pct: throttledRisk,
                        max_open_capital_allocation: maxAlloc,
                        drawdown_throttling_enabled: isThrottlingEnabled,
                        session_filter_enabled: isSessionFilterEnabled,
                        sl_buffer_enabled: isSlBufferEnabled,
                        sl_buffer_pct: slBufferPct,
                        order_execution_type: orderExecType
                    })
                });
                const result = await res.json();
                if (result.success) {
                    if (riskStatusFeedback) {
                        riskStatusFeedback.textContent = 'Saved successfully';
                        setTimeout(() => { riskStatusFeedback.textContent = ''; }, 3000);
                    }
                    alert(`Risk Guardrails Updated Successfully!\n\n- Base Risk Per Trade: ${normalRisk.toFixed(2)}%\n- Drawdown Throttling: ${isThrottlingEnabled ? 'ENABLED (' + throttledRisk.toFixed(2) + '%)' : 'DISABLED'}\n- Max Capital Allocation: ${maxAlloc.toFixed(2)}%\n- Toxic Hours Filter: ${isSessionFilterEnabled ? 'ENABLED' : 'DISABLED'}\n- SL Anti-Wickout Buffer: ${isSlBufferEnabled ? 'ENABLED (' + slBufferPct.toFixed(2) + '%)' : 'DISABLED'}\n- Execution Mode: ${orderExecType === 'LIMIT' ? 'POST-ONLY LIMIT (GTX)' : 'MARKET'}`);
                    updatePortfolioBadge();
                    loadDashboardData();
                } else {
                    alert('Failed to update risk settings.');
                }
            } catch (err) {
                alert('Error updating risk configuration: ' + err.message);
            } finally {
                btnSaveRiskSettings.textContent = 'Apply Settings';
            }
        });
    }

    function syncRiskInputsWithStatus(status) {
        if (!isUserTypingRisk) {
            if (inputNormalRisk && status.normal_risk_pct !== undefined) {
                inputNormalRisk.value = Number(status.normal_risk_pct).toFixed(1);
            }
            if (inputThrottledRisk && status.throttled_risk_pct !== undefined) {
                inputThrottledRisk.value = Number(status.throttled_risk_pct).toFixed(1);
            }
            if (inputMaxAlloc && status.max_open_risk_limit_pct !== undefined) {
                inputMaxAlloc.value = Number(status.max_open_risk_limit_pct).toFixed(1);
            }
            if (inputSlBufferPct && status.sl_buffer_pct !== undefined) {
                inputSlBufferPct.value = Number(status.sl_buffer_pct).toFixed(2);
            }
        }
        if (badgeActiveRiskVal && status.current_trade_risk_pct !== undefined) {
            badgeActiveRiskVal.textContent = `${Number(status.current_trade_risk_pct).toFixed(2)}%`;
        }
        if (badgeActiveAllocVal && status.max_open_risk_limit_pct !== undefined) {
            badgeActiveAllocVal.textContent = `${Number(status.max_open_risk_limit_pct).toFixed(2)}%`;
        }
        if (status.drawdown_throttling_enabled !== undefined) {
            updateThrottlingBtnUI(status.drawdown_throttling_enabled);
        }
        if (status.session_filter_enabled !== undefined) {
            updateSessionFilterBtnUI(status.session_filter_enabled);
        }
        if (status.sl_buffer_enabled !== undefined) {
            updateSlBufferBtnUI(status.sl_buffer_enabled);
        }
        if (selectOrderExecType && status.order_execution_type) {
            selectOrderExecType.value = status.order_execution_type;
            if (badgeActiveOrderType) {
                badgeActiveOrderType.textContent = (status.order_execution_type === 'LIMIT') ? 'POST-ONLY LIMIT' : 'MARKET ORDER';
                badgeActiveOrderType.style.color = (status.order_execution_type === 'LIMIT') ? '#2962ff' : '#ff9800';
            }
        }
    }

    // Call on startup
    fetchBinanceStatus();

    // =========================================================================
    // 4. PORTFOLIO STATUS POLLER & DASHBOARD DATA LOADER
    // =========================================================================
    async function updatePortfolioBadge() {
        try {
            const res = await fetch('/api/portfolio/status');
            if (res.ok) {
                const data = await res.json();
                const modeEl = document.getElementById('badge-risk-mode');
                const allocEl = document.getElementById('badge-open-risk');
                const marginEl = document.getElementById('badge-margin-mode');
                const cbEl = document.getElementById('badge-cb-mode');
                const newsEl = document.getElementById('badge-news-mode');
                const sessionEl = document.getElementById('badge-session-mode');
                const slBufferEl = document.getElementById('badge-sl-buffer');
                const orderTypeEl = document.getElementById('badge-order-type');

                if (marginEl && data.margin_mode) {
                    marginEl.textContent = `Margin: ${data.margin_mode}`; marginEl.style.fontWeight = '600';
                }
                if (slBufferEl) {
                    if (data.sl_buffer_enabled) {
                        slBufferEl.textContent = `${data.sl_buffer_pct || 0.12}%`;
                        slBufferEl.style.color = '#26a69a';
                    } else {
                        slBufferEl.textContent = 'OFF';
                        slBufferEl.style.color = '#787b86';
                    }
                }
                if (orderTypeEl) {
                    if (data.order_execution_type === 'LIMIT') {
                        orderTypeEl.textContent = 'LIMIT (GTX)';
                        orderTypeEl.style.color = '#2962ff';
                    } else {
                        orderTypeEl.textContent = 'MARKET';
                        orderTypeEl.style.color = '#ff9800';
                    }
                }
                if (cbEl) {
                    if (data.circuit_breaker_active) {
                        cbEl.textContent = 'TRIPPED (HALT)';
                        cbEl.style.color = '#ef5350';
                    } else {
                        cbEl.textContent = 'OK';
                        cbEl.style.color = '#26a69a';
                    }
                }
                if (newsEl) {
                    if (data.macro_filter_active) {
                        newsEl.textContent = `${data.macro_event_name || 'EVENT'}`; newsEl.style.fontWeight = '600';
                        newsEl.style.color = '#ef5350';
                    } else {
                        newsEl.textContent = 'OK';
                        newsEl.style.color = '#26a69a';
                    }
                }
                if (sessionEl) {
                    if (!data.session_filter_enabled) {
                        sessionEl.textContent = 'OFF';
                        sessionEl.style.color = '#787b86';
                    } else if (data.session_filter_active) {
                        sessionEl.textContent = `PAUSED (${data.current_utc_hour !== undefined ? data.current_utc_hour + 'h UTC' : 'TOXIC'})`;
                        sessionEl.style.color = '#ef5350';
                    } else {
                        sessionEl.textContent = 'LIQUID';
                        sessionEl.style.color = '#26a69a';
                    }
                }
                if (modeEl) {
                    if (data.throttled) {
                        modeEl.textContent = `${data.current_trade_risk_pct}% (Throttled -${data.drawdown_pct}%)`;
                        modeEl.style.color = '#ef5350';
                    } else {
                        modeEl.textContent = `${data.current_trade_risk_pct}%`;
                        modeEl.style.color = '#26a69a';
                    }
                }
                if (allocEl) {
                    const maxAlloc = data.max_open_risk_limit_pct || 8.0;
                    allocEl.textContent = `${data.open_risk_pct}% / Max ${maxAlloc}%`;
                    allocEl.style.color = (data.open_risk_pct >= maxAlloc * 0.75) ? '#ff9800' : '#2962ff';
                }
                window.lastPortfolioStatus = data;
                if (data.hasOwnProperty('bot_enabled')) {
                    const count = (data.locked_coins && Array.isArray(data.locked_coins)) ? data.locked_coins.length : 2;
                    updateBotBtnUI(data.bot_enabled, count);
                }
                syncRiskInputsWithStatus(data);
            }
        } catch (e) {
            // silent ignore
        }
    }
    setInterval(updatePortfolioBadge, 5000);
    updatePortfolioBadge();

    async function loadDashboardData() {
        try {
            const [statusRes, historyRes] = await Promise.all([
                fetch('/api/portfolio/status'),
                fetch('/api/portfolio/history')
            ]);
            if (!statusRes.ok || !historyRes.ok) return;

            const status = await statusRes.json();
            const history = await historyRes.json();

            // 1. Metric Cards
            const balanceEl = document.getElementById('dash-balance');
            const peakEl = document.getElementById('dash-peak');
            const pnlEl = document.getElementById('dash-pnl');
            const rEl = document.getElementById('dash-r-multiples');
            const winrateEl = document.getElementById('dash-winrate');
            const tradeCountsEl = document.getElementById('dash-trade-counts');
            const ddEl = document.getElementById('dash-drawdown');
            const throttleEl = document.getElementById('dash-throttle-status');
            const allocEl = document.getElementById('dash-alloc');
            const breakerEl = document.getElementById('dash-breaker-status');

            if (balanceEl) balanceEl.textContent = `$${status.balance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
            if (peakEl) peakEl.textContent = status.balance > 0 ? 'Live Binance Wallet' : 'Binance Futures Wallet';

            const trades = history.trade_history || [];
            let totalPnL = 0;
            let totalR = 0;
            let winCount = 0;
            let lossCount = 0;

            trades.forEach(t => {
                totalPnL += (t.pnl_dollars || 0);
                totalR += (t.r_gained || 0);
                if ((t.r_gained || 0) > 0 || t.outcome === 'TP') winCount++;
                else if ((t.r_gained || 0) < 0 || t.outcome === 'SL') lossCount++;
            });

            const totalTrades = winCount + lossCount;
            const winRate = totalTrades > 0 ? (winCount / totalTrades * 100.0) : 0;

            if (pnlEl) {
                pnlEl.textContent = `${totalPnL >= 0 ? '+' : ''}$${totalPnL.toFixed(2)}`;
                pnlEl.style.color = totalPnL >= 0 ? '#26a69a' : '#ef5350';
            }
            if (rEl) rEl.textContent = `Total: ${totalR >= 0 ? '+' : ''}${totalR.toFixed(2)}R`;
            if (winrateEl) winrateEl.textContent = `${winRate.toFixed(1)}%`;
            if (tradeCountsEl) tradeCountsEl.textContent = `${winCount} Won / ${lossCount} Lost (${totalTrades} Total)`;

            if (ddEl) {
                ddEl.textContent = `${status.drawdown_pct.toFixed(2)}%`;
                ddEl.style.color = status.drawdown_pct >= 8.0 ? '#ef5350' : '#26a69a';
            }
            if (throttleEl) {
                if (!status.drawdown_throttling_enabled) {
                    throttleEl.textContent = 'Factor 3: Disabled';
                    throttleEl.style.color = '#787b86';
                } else if (status.throttled) {
                    throttleEl.textContent = `Factor 3: Throttled (${status.throttled_risk_pct}%)`;
                    throttleEl.style.color = '#ef5350';
                } else {
                    throttleEl.textContent = `Factor 3: Normal (${status.normal_risk_pct}%)`;
                    throttleEl.style.color = '#787b86';
                }
            }
            if (allocEl) allocEl.textContent = `${status.open_risk_pct.toFixed(2)}% (Max ${status.max_open_risk_limit_pct}%)`;
            if (breakerEl) {
                breakerEl.textContent = status.circuit_breaker_active ? 'Circuit Breaker: TRIPPED' : 'Circuit Breaker: OK';
                breakerEl.style.color = status.circuit_breaker_active ? '#ef5350' : '#787b86';
            }

            // Guardrail cards on page-risk
            const cardRiskName = document.getElementById('card-risk-name');
            const cardThrottleStatus = document.getElementById('card-throttle-status');
            const cardAllocName = document.getElementById('card-alloc-name');
            if (cardRiskName && status.normal_risk_pct) {
                cardRiskName.textContent = `Dynamic ${status.normal_risk_pct}% Risk Model`;
            }
            if (cardThrottleStatus) {
                if (!status.drawdown_throttling_enabled) {
                    cardThrottleStatus.textContent = 'DISABLED';
                    cardThrottleStatus.className = 'guardrail-status-pill';
                    cardThrottleStatus.style.background = 'rgba(120, 123, 134, 0.2)';
                    cardThrottleStatus.style.color = '#787b86';
                    cardThrottleStatus.style.borderColor = '#363a45';
                } else if (status.throttled) {
                    cardThrottleStatus.textContent = `THROTTLED (${status.throttled_risk_pct}%)`;
                    cardThrottleStatus.className = 'guardrail-status-pill';
                    cardThrottleStatus.style.background = 'rgba(239, 83, 80, 0.2)';
                    cardThrottleStatus.style.color = '#ef5350';
                    cardThrottleStatus.style.borderColor = '#ef5350';
                } else {
                    cardThrottleStatus.textContent = 'ACTIVE';
                    cardThrottleStatus.className = 'guardrail-status-pill status-ok';
                    cardThrottleStatus.style.background = 'rgba(38, 166, 154, 0.15)';
                    cardThrottleStatus.style.color = '#26a69a';
                    cardThrottleStatus.style.borderColor = 'rgba(38, 166, 154, 0.4)';
                }
            }
            if (cardAllocName && status.max_open_risk_limit_pct) {
                cardAllocName.textContent = `${status.max_open_risk_limit_pct}% Max Capital Allocation`;
            }

            // 2. Active Positions Table
            const activePos = history.active_positions || [];
            const activeBody = document.getElementById('active-positions-body');
            const activeCountEl = document.getElementById('active-pos-count');
            if (activeCountEl) activeCountEl.textContent = `${activePos.length} Active`;

            if (activeBody) {
                if (activePos.length === 0) {
                    activeBody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: #787b86; padding: 24px;">No active open trades right now. Engine is scanning market structure.</td></tr>';
                } else {
                    activeBody.innerHTML = activePos.map(p => `
                        <tr class="clickable-trade-row" data-symbol="${p.symbol}" title="Click to view live chart for ${p.symbol}">
                            <td><strong>${p.symbol}</strong></td>
                            <td><span class="badge-side ${p.type.toLowerCase()}">${p.type}</span></td>
                            <td>$${Number(p.entry_price).toFixed(4)}</td>
                            <td><span style="color: #ef5350;">$${Number(p.sl_price).toFixed(4)}</span></td>
                            <td><span style="color: #26a69a;">$${Number(p.tp_price).toFixed(4)}</span></td>
                            <td><strong>${p.recommended_leverage}x ISOLATED</strong></td>
                            <td>$${Number(p.margin_required).toFixed(2)}</td>
                            <td>$${Number(p.risk_dollars).toFixed(2)} (${(p.risk_pct*100).toFixed(1)}%)</td>
                            <td><span style="color: #ff9800;">$${Number(p.est_liquidation_price || 0).toFixed(4)}</span></td>
                            <td><span class="badge-outcome tp">OPEN</span></td>
                        </tr>
                    `).join('');

                    activeBody.querySelectorAll('.clickable-trade-row').forEach(row => {
                        row.addEventListener('click', () => {
                            const sym = row.getAttribute('data-symbol');
                            if (sym) {
                                setSymbol(sym);
                                navigateToPage('charts');
                            }
                        });
                    });
                }
            }

            // 3. Closed Trades History Table
            const historyBody = document.getElementById('history-body');
            const closedCountEl = document.getElementById('closed-trades-count');
            if (closedCountEl) closedCountEl.textContent = `${trades.length} Trades`;

            if (historyBody) {
                if (trades.length === 0) {
                    historyBody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: #787b86; padding: 24px;">No historical closed trades recorded yet.</td></tr>';
                } else {
                    // Show most recent first
                    const reversed = [...trades].reverse();
                    historyBody.innerHTML = reversed.map(t => {
                        const dateStr = t.close_time ? new Date(t.close_time * 1000).toLocaleString() : '-';
                        const outcomeClass = (t.outcome === 'TP' || (t.r_gained || 0) > 0) ? 'tp' : 'sl';
                        const pnlColor = (t.pnl_dollars || 0) >= 0 ? '#26a69a' : '#ef5350';
                        const rColor = (t.r_gained || 0) >= 0 ? '#26a69a' : '#ef5350';
                        return `
                            <tr class="clickable-trade-row" data-symbol="${t.symbol}" title="Click to view live chart for ${t.symbol}">
                                <td>${dateStr}</td>
                                <td><strong>${t.symbol}</strong></td>
                                <td><span class="badge-side ${(t.type || 'BUY').toLowerCase()}">${t.type || 'BUY'}</span></td>
                                <td>$${Number(t.entry_price || 0).toFixed(4)}</td>
                                <td>$${Number(t.exit_price || 0).toFixed(4)}</td>
                                <td><span class="badge-outcome ${outcomeClass}">${t.outcome || 'CLOSED'}</span></td>
                                <td style="color: ${rColor}; font-weight: 700;">${(t.r_gained || 0) >= 0 ? '+' : ''}${Number(t.r_gained || 0).toFixed(2)}R</td>
                                <td style="color: ${pnlColor}; font-weight: 700;">${(t.pnl_dollars || 0) >= 0 ? '+' : ''}$${Number(t.pnl_dollars || 0).toFixed(2)}</td>
                                <td><strong>$${Number(t.balance_after || status.balance).toFixed(2)}</strong></td>
                            </tr>
                        `;
                    }).join('');

                    historyBody.querySelectorAll('.clickable-trade-row').forEach(row => {
                        row.addEventListener('click', () => {
                            const sym = row.getAttribute('data-symbol');
                            if (sym) {
                                setSymbol(sym);
                                navigateToPage('charts');
                            }
                        });
                    });
                }
            }
        } catch (err) {
            console.error('Error loading dashboard data:', err);
        }
    }

    // =========================================================================
    // 4.1 MACRO EVENTS CALENDAR LOADER & RENDERER
    // =========================================================================
    let allMacroEventsList = [];
    let currentEventFilter = 'ALL';

    async function loadMacroEvents() {
        try {
            const res = await fetch('/api/macro/events');
            if (!res.ok) return;
            const data = await res.json();
            allMacroEventsList = data.events || [];

            // 1. Overview Calendar Countdown Banner
            const nextEv = data.next_event;
            const heroBadge = document.getElementById('macro-hero-badge');
            const countdownEl = document.getElementById('calendar-widget-countdown');
            if (nextEv) {
                if (heroBadge) heroBadge.textContent = `Next: ${nextEv.event}`;
                if (countdownEl) {
                    const hours = nextEv.hours_until;
                    const timeStr = hours > 0 ? `in ${hours.toFixed(1)} hours (${nextEv.date})` : `NOW ACTIVE (Release window)`;
                    countdownEl.innerHTML = `Next High-Impact Release: <strong>${nextEv.description} (${nextEv.event})</strong> ${timeStr}`;
                }
            }

            // 2. Overview Compact Upcoming Table (next 6 events)
            const overviewBody = document.getElementById('overview-macro-body');
            if (overviewBody) {
                const upcomingOnly = allMacroEventsList.filter(e => e.status !== 'COMPLETED').slice(0, 6);
                if (upcomingOnly.length === 0) {
                    overviewBody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: #787b86; padding: 16px;">No upcoming releases scheduled in the near future.</td></tr>`;
                } else {
                    overviewBody.innerHTML = upcomingOnly.map(e => {
                        const statusBadge = e.is_active 
                            ? `<span class="badge-status-active">BLACKOUT ACTIVE</span>`
                            : `<span class="badge-status-upcoming">SAFE TO TRADE</span>`;
                        const countdownStr = e.hours_until > 0 ? `In ${e.hours_until}h` : `${Math.abs(e.hours_until)}h ago`;
                        return `
                            <tr>
                                <td><strong>${e.date}</strong></td>
                                <td>${e.utc_time}</td>
                                <td><span style="color: #ffd54f; font-weight: 700;">${e.event}</span></td>
                                <td>${e.description}</td>
                                <td>${countdownStr}</td>
                                <td>${statusBadge}</td>
                            </tr>
                        `;
                    }).join('');
                }
            }

            // 3. Render Full Macro Calendar Page
            renderFullMacroCalendar();

        } catch (err) {
            console.error('Error loading macro events:', err);
        }
    }

    function renderFullMacroCalendar() {
        const fullBody = document.getElementById('full-macro-body');
        if (!fullBody) return;

        let filtered = allMacroEventsList;
        if (currentEventFilter !== 'ALL') {
            filtered = allMacroEventsList.filter(e => e.event.toUpperCase() === currentEventFilter);
        }

        if (filtered.length === 0) {
            fullBody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: #787b86; padding: 24px;">No events matching "${currentEventFilter}".</td></tr>`;
            return;
        }

        fullBody.innerHTML = filtered.map(e => {
            let statusBadge = '';
            if (e.status === 'COMPLETED') {
                statusBadge = `<span class="badge-status-completed">COMPLETED</span>`;
            } else if (e.is_active) {
                statusBadge = `<span class="badge-status-active">BLACKOUT ACTIVE</span>`;
            } else {
                statusBadge = `<span class="badge-status-upcoming">UPCOMING</span>`;
            }

            const timeRemaining = e.hours_until > 0 ? `In ${e.hours_until} hours` : `${Math.abs(e.hours_until)} hours ago`;

            return `
                <tr>
                    <td><strong>${e.date}</strong></td>
                    <td>${e.utc_time}</td>
                    <td><span style="color: #ffd54f; font-weight: 700;">${e.event}</span></td>
                    <td>${e.description}</td>
                    <td>&plusmn;${e.buffer_hours} hours</td>
                    <td>${timeRemaining}</td>
                    <td>${statusBadge}</td>
                </tr>
            `;
        }).join('');
    }

    // Filter button listeners on Calendar page
    const filterBtns = document.querySelectorAll('.event-filter-group .filter-btn');
    filterBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            filterBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentEventFilter = btn.getAttribute('data-filter') || 'ALL';
            renderFullMacroCalendar();
        });
    });

    // Initial loads
    loadDashboardData();
    loadMacroEvents();

    function getChartDims() {
        const mainW = mainContainer ? mainContainer.clientWidth : window.innerWidth;
        const mainH = mainContainer ? mainContainer.clientHeight : (window.innerHeight - 80);
        const w = isSplitOpen ? Math.floor(mainW / 2) : mainW;
        const targetEl = document.getElementById('htf-chart-inner');
        const headerEl = document.querySelector('#chart-container .pane-header');
        const headerH = headerEl ? headerEl.offsetHeight : 32;
        let h = (targetEl && targetEl.clientHeight > 50) ? targetEl.clientHeight : Math.max(150, mainH - headerH);
        return { width: Math.max(200, Math.floor(w)), height: Math.max(150, Math.floor(h)) };
    }

    function getLTFChartDims() {
        const mainW = mainContainer ? mainContainer.clientWidth : window.innerWidth;
        const mainH = mainContainer ? mainContainer.clientHeight : (window.innerHeight - 80);
        const w = Math.floor(mainW / 2);
        const targetEl = document.getElementById('ltf-chart');
        const headerEl = document.querySelector('#split-ltf-container .pane-header');
        const telEl = document.getElementById('ltf-signal-telemetry');
        const headerH = (headerEl ? headerEl.offsetHeight : 32) + (telEl ? telEl.offsetHeight : 26);
        let h = (targetEl && targetEl.clientHeight > 50) ? targetEl.clientHeight : Math.max(150, mainH - headerH);
        return { width: Math.max(200, Math.floor(w)), height: Math.max(150, Math.floor(h)) };
    }
    const initialDims = getChartDims();

    // Helper: format unix timestamp (seconds) into TradingView style date/time string
    function formatDateTime(ts) {
        if (!ts) return '';
        const d = new Date(ts * 1000);
        const yyyy = d.getUTCFullYear();
        const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
        const dd = String(d.getUTCDate()).padStart(2, '0');
        const hh = String(d.getUTCHours()).padStart(2, '0');
        const min = String(d.getUTCMinutes()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
    }

    function formatPrice(val) {
        if (typeof val !== 'number') return '-';
        return val >= 1000 ? val.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 2 }) : val.toFixed(4);
    }

    function updateLegend(legendEl, param, series, candlesArr) {
        if (!legendEl) return;
        let c = null;
        let timeStr = '';

        if (param && param.time && param.seriesPrices && series) {
            const price = param.seriesPrices.get(series);
            if (price) {
                c = price;
                timeStr = formatDateTime(param.time);
            }
        }

        if (!c && candlesArr && candlesArr.length > 0) {
            c = candlesArr[candlesArr.length - 1];
            timeStr = formatDateTime(c.time);
        }

        if (c) {
            const o = c.open !== undefined ? c.open : c;
            const h = c.high !== undefined ? c.high : c;
            const l = c.low !== undefined ? c.low : c;
            const cl = c.close !== undefined ? c.close : c;
            const isUp = cl >= o;
            const valClass = isUp ? 'val-up' : 'val-down';

            legendEl.innerHTML = `
                <span class="time-val">${timeStr}</span>
                <span>O: <span class="${valClass}">${formatPrice(o)}</span></span>
                <span>H: <span class="${valClass}">${formatPrice(h)}</span></span>
                <span>L: <span class="${valClass}">${formatPrice(l)}</span></span>
                <span>C: <span class="${valClass}">${formatPrice(cl)}</span></span>
            `;
        }
    }

    // Initialize Main HTF Lightweight Chart
    const isDarkInitial = (document.documentElement.getAttribute('data-theme') !== 'light');
    const chartTarget = document.getElementById('htf-chart-inner') || container;
    chart = LightweightCharts.createChart(chartTarget, {
        width: initialDims.width,
        height: initialDims.height,
        layout: {
            background: { type: 'solid', color: isDarkInitial ? '#131722' : '#ffffff' },
            textColor: isDarkInitial ? '#d1d4dc' : '#191919',
        },
        grid: {
            vertLines: { color: isDarkInitial ? '#1e222d' : '#f0f3fa' },
            horzLines: { color: isDarkInitial ? '#1e222d' : '#f0f3fa' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
            vertLine: {
                visible: true,
                labelVisible: true,
                style: LightweightCharts.LineStyle.Dashed,
                width: 1,
                color: isDarkInitial ? '#758696' : '#9598a1',
                labelBackgroundColor: '#2962ff',
            },
            horzLine: {
                visible: true,
                labelVisible: true,
                style: LightweightCharts.LineStyle.Dashed,
                width: 1,
                color: isDarkInitial ? '#758696' : '#9598a1',
                labelBackgroundColor: '#2962ff',
            }
        },
        rightPriceScale: {
            borderColor: isDarkInitial ? '#2a2e39' : '#e0e3eb',
            autoScale: true,
            visible: true,
        },
        localization: {
            dateFormat: 'yyyy-MM-dd',
            timeFormatter: (timestamp) => formatDateTime(timestamp),
        },
        timeScale: {
            borderColor: isDarkInitial ? '#2a2e39' : '#e0e3eb',
            visible: true,
            timeVisible: true,
            secondsVisible: false,
            barSpacing: 10,
            minBarSpacing: 0.2,
            rightOffset: 12,
            tickMarkFormatter: (time, tickMarkType, locale) => {
                const d = new Date(time * 1000);
                const yyyy = d.getUTCFullYear();
                const mon = d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' });
                const dd = String(d.getUTCDate()).padStart(2, '0');
                const hh = String(d.getUTCHours()).padStart(2, '0');
                const min = String(d.getUTCMinutes()).padStart(2, '0');
                if (tickMarkType === 0) return `${yyyy}`;
                if (tickMarkType === 1) return `${mon} ${yyyy}`;
                if (tickMarkType === 2) return `${dd} ${mon}`;
                return `${dd} ${mon} ${hh}:${min}`;
            }
        },
    });

    candlestickSeries = chart.addCandlestickSeries({
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350',
    });

    function prepareCandles(candlesArr) {
        if (!Array.isArray(candlesArr) || candlesArr.length === 0) return [];
        const map = new Map();
        candlesArr.forEach(c => {
            if (c && typeof c.time === 'number') {
                map.set(c.time, c);
            }
        });
        return Array.from(map.values()).sort((a, b) => a.time - b.time);
    }

    // Crosshair legend & bottom time pill update for HTF
    let currentHoveredTime = null;
    const htfBottomTimePill = document.getElementById('htf-bottom-time-pill');

    chart.subscribeCrosshairMove(param => {
        if (param && param.time) {
            currentHoveredTime = param.time;
            if (htfBottomTimePill && param.point) {
                htfBottomTimePill.textContent = formatDateTime(param.time);
                htfBottomTimePill.style.left = `${Math.round(param.point.x)}px`;
                htfBottomTimePill.style.display = 'block';
            }
        } else {
            if (htfBottomTimePill) htfBottomTimePill.style.display = 'none';
        }
        updateLegend(htfOhlcLegend, param, candlestickSeries, currentCandles);
    });

    // =========================================================================
    // THEME SWITCHER CONTROLLER (DARK / CYBER OLED / CLEAN LIGHT)
    // =========================================================================
    const btnThemeToggle = document.getElementById('theme-toggle-btn') || document.getElementById('btn-theme-toggle');
    const btnThemeToggleSidebar = document.getElementById('btn-theme-toggle-sidebar');
    const themeToggleIcon = document.getElementById('theme-toggle-icon');
    const themeToggleText = document.getElementById('theme-btn-text') || document.getElementById('theme-toggle-text');
    const sidebarThemeIcon = document.getElementById('sidebar-theme-icon');
    const sidebarThemeText = document.getElementById('sidebar-theme-text');

    const THEME_CYCLE = ['light', 'dark', 'cyber'];
    const THEME_METADATA = {
        'light': { label: 'Light' },
        'dark': { label: 'Dark' },
        'cyber': { label: 'Cyber' }
    };

    let currentTheme = localStorage.getItem('topg_theme') || localStorage.getItem('mq_theme') || 'light';

    function applyTheme(themeName) {
        currentTheme = themeName;
        document.documentElement.setAttribute('data-theme', themeName);
        if (document.body) document.body.setAttribute('data-theme', themeName);
        localStorage.setItem('topg_theme', themeName);
        localStorage.setItem('mq_theme', themeName);

        const meta = THEME_METADATA[themeName] || THEME_METADATA['light'];
        if (themeToggleText) themeToggleText.textContent = `${meta.label} Theme`;
        if (sidebarThemeText) sidebarThemeText.textContent = `Theme: ${meta.label}`;

        // Sync Lightweight Charts layout theme
        if (typeof chart !== 'undefined' && chart) {
            let chartBg = '#131722';
            let chartText = '#d1d4dc';
            let chartGrid = '#1e222d';
            let chartBorder = '#2a2e39';

            if (themeName === 'cyber') {
                chartBg = '#07080c';
                chartText = '#d6e2ee';
                chartGrid = '#12151f';
                chartBorder = '#1f2536';
            } else if (themeName === 'light') {
                chartBg = '#ffffff';
                chartText = '#131722';
                chartGrid = '#f1f5f9';
                chartBorder = '#e2e8f0';
            }

            chart.applyOptions({
                layout: { background: { type: 'solid', color: chartBg }, textColor: chartText },
                grid: { vertLines: { color: chartGrid }, horzLines: { color: chartGrid } },
                rightPriceScale: { borderColor: chartBorder },
                timeScale: { borderColor: chartBorder }
            });

            if (typeof ltfChart !== 'undefined' && ltfChart) {
                ltfChart.applyOptions({
                    layout: { background: { type: 'solid', color: chartBg }, textColor: chartText },
                    grid: { vertLines: { color: chartGrid }, horzLines: { color: chartGrid } },
                    rightPriceScale: { borderColor: chartBorder },
                    timeScale: { borderColor: chartBorder }
                });
            }
            if (typeof redrawAll === 'function') {
                setTimeout(redrawAll, 50);
            }
        }
    }

    function cycleTheme() {
        const currentIndex = THEME_CYCLE.indexOf(currentTheme);
        const nextIndex = (currentIndex + 1) % THEME_CYCLE.length;
        applyTheme(THEME_CYCLE[nextIndex]);
    }

    if (btnThemeToggle) {
        btnThemeToggle.addEventListener('click', cycleTheme);
    }
    if (btnThemeToggleSidebar) {
        btnThemeToggleSidebar.addEventListener('click', cycleTheme);
    }

    // Apply saved theme immediately
    applyTheme(currentTheme);


    // Handle Window Resize
    function resizeCanvas() {
        if (!chart) return;
        const dims = getChartDims();
        chart.applyOptions({ width: dims.width, height: dims.height });
        if (canvas && ctx) {
            canvas.width = dims.width * window.devicePixelRatio;
            canvas.height = dims.height * window.devicePixelRatio;
            canvas.style.width = dims.width + 'px';
            canvas.style.height = dims.height + 'px';
            ctx.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0);
            drawOverlay();
        }

        if (isSplitOpen && ltfChart) {
            resizeLTFCanvas();
        }
    }

    function resizeLTFCanvas() {
        if (!ltfChart) return;
        const dims = getLTFChartDims();
        ltfChart.applyOptions({ width: dims.width, height: dims.height });
        if (ltfCanvas && ltfCtx) {
            ltfCanvas.width = dims.width * window.devicePixelRatio;
            ltfCanvas.height = dims.height * window.devicePixelRatio;
            ltfCanvas.style.width = dims.width + 'px';
            ltfCanvas.style.height = dims.height + 'px';
            ltfCtx.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0);
            drawLTFOverlay();
        }
    }

    window.addEventListener('resize', resizeCanvas);
    resizeCanvas();

    chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
        drawOverlay();
    });

    // =========================================================================
    // SPLIT SCREEN RAW LTF CHART SETUP
    // =========================================================================
    function getLTFIntervalForHTF(htf) {
        const h = (htf || '15m').toLowerCase();
        if (h === '15m' || h === 'm15') return '1m';
        if (h === '1h' || h === 'h1') return '1m';
        if (h === '4h' || h === 'h4') return '5m';
        // 1D and 5M are explicitly NOT traded as HTF
        if (h === '1d' || h === 'd1') return '1h';
        if (h === '5m' || h === 'm5') return '1m';
        return '1m';
    }

    function initLTFChartIfNeeded() {
        if (ltfChart) return;
        const dims = getLTFChartDims();

        const isDark = (document.documentElement.getAttribute('data-theme') !== 'light');
        const bgCol = isDark ? '#131722' : '#ffffff';
        const textCol = isDark ? '#d1d4dc' : '#131722';
        const gridCol = isDark ? '#1e222d' : '#f0f3fa';
        const borderCol = isDark ? '#2a2e39' : '#e2e8f0';
        const ltfBottomTimePill = document.getElementById('ltf-bottom-time-pill');

        ltfChart = LightweightCharts.createChart(ltfChartDiv, {
            width: dims.width,
            height: dims.height,
            layout: {
                background: { type: 'solid', color: bgCol },
                textColor: textCol,
            },
            grid: {
                vertLines: { color: gridCol },
                horzLines: { color: gridCol },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: {
                    visible: true,
                    labelVisible: true,
                    style: LightweightCharts.LineStyle.Dashed,
                    width: 1,
                    color: isDark ? '#758696' : '#9598a1',
                    labelBackgroundColor: '#2962ff',
                },
                horzLine: {
                    visible: true,
                    labelVisible: true,
                    style: LightweightCharts.LineStyle.Dashed,
                    width: 1,
                    color: isDark ? '#758696' : '#9598a1',
                    labelBackgroundColor: '#2962ff',
                }
            },
            rightPriceScale: {
                borderColor: borderCol,
                autoScale: true,
                visible: true,
            },
            localization: {
                dateFormat: 'yyyy-MM-dd',
                timeFormatter: (timestamp) => formatDateTime(timestamp),
            },
            timeScale: {
                borderColor: borderCol,
                visible: true,
                timeVisible: true,
                secondsVisible: false,
                barSpacing: 10,
                minBarSpacing: 0.2,
                rightOffset: 12,
                tickMarkFormatter: (time, tickMarkType, locale) => {
                    const d = new Date(time * 1000);
                    const yyyy = d.getUTCFullYear();
                    const mon = d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' });
                    const dd = String(d.getUTCDate()).padStart(2, '0');
                    const hh = String(d.getUTCHours()).padStart(2, '0');
                    const min = String(d.getUTCMinutes()).padStart(2, '0');
                    if (tickMarkType === 0) return `${yyyy}`;
                    if (tickMarkType === 1) return `${mon} ${yyyy}`;
                    if (tickMarkType === 2) return `${dd} ${mon}`;
                    return `${dd} ${mon} ${hh}:${min}`;
                }
            },
        });

        ltfSeries = ltfChart.addCandlestickSeries({
            upColor: '#26a69a',
            downColor: '#ef5350',
            borderVisible: false,
            wickUpColor: '#26a69a',
            wickDownColor: '#ef5350',
        });

        ltfChart.subscribeCrosshairMove(param => {
            if (param && param.time) {
                if (ltfBottomTimePill && param.point) {
                    ltfBottomTimePill.textContent = formatDateTime(param.time);
                    ltfBottomTimePill.style.left = `${Math.round(param.point.x)}px`;
                    ltfBottomTimePill.style.display = 'block';
                }
            } else {
                if (ltfBottomTimePill) ltfBottomTimePill.style.display = 'none';
            }
            updateLegend(ltfOhlcLegend, param, ltfSeries, ltfCandles);
        });

        ltfChart.timeScale().subscribeVisibleLogicalRangeChange(() => {
            drawLTFOverlay();
        });

        if (!ltfInteractionsSetup && ltfCanvas) {
            setupDrawingInteractions(ltfChartDiv, ltfCanvas, ltfChart, () => ltfSeries, () => ltfCandles, false);
            ltfInteractionsSetup = true;
        }

        function handleLTFChartDblClick(e) {
            if (activeTool !== 'cursor' || isDrawing) return;
            const rect = ltfChartDiv.getBoundingClientRect();
            const clickX = e.clientX - rect.left;
            const t = coordToTime(ltfChart, ltfCandles, clickX);
            if (t) {
                openSplitLTF(t);
        if (typeof isInspectorOpen !== 'undefined' && isInspectorOpen) {
            openTradeInspector(t);
        }
            }
        }
        ltfChartDiv.addEventListener('dblclick', handleLTFChartDblClick);
        if (ltfCanvas) {
            ltfCanvas.addEventListener('dblclick', handleLTFChartDblClick);
        }

        applyTheme(currentTheme);
    }

    function updateSignalTelemetry(sig, box) {
        const telBar = document.getElementById('ltf-signal-telemetry');
        if (!telBar) return;
        telBar.style.display = 'flex';

        const typeBadge = document.getElementById('tel-type-badge');
        const telEntry = document.getElementById('tel-entry');
        const telSL = document.getElementById('tel-sl');
        const telTP = document.getElementById('tel-tp');
        const telPat = document.getElementById('tel-pattern');
        const telOut = document.getElementById('tel-outcome');
        const telBox = document.getElementById('tel-box');

        const isBuy = (sig.type === 'BUY');
        if (typeBadge) {
            typeBadge.textContent = `${isBuy ? 'BUY' : 'SELL'}${sig.is_reentry ? ' (Re-entry)' : ''}`;
            typeBadge.className = `tel-badge-sig ${isBuy ? 'buy' : 'sell'}`;
        }

        const entryVal = Number(sig.entry || sig.price || 0);
        const slVal = Number(sig.sl || 0);
        const tpVal = Number(sig.tp || 0);

        if (telEntry) telEntry.innerHTML = `Entry: <b>$${entryVal.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 4})}</b>`;
        if (telSL) telSL.innerHTML = `SL: <b>$${slVal.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 4})} (-1.0R)</b>`;
        if (telTP) telTP.innerHTML = `TP: <b>$${tpVal.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 4})} (+${sig.rr || 2.5}R)</b>`;
        if (telPat) telPat.innerHTML = `Pattern: <b>${sig.pattern || 'Reversal Pattern'}</b>`;

        if (telOut) {
            const out = sig.outcome || 'OPEN';
            let outHtml = `<b>${out}</b>`;
            if (out === 'TP') outHtml = `<b style="color: var(--color-up, #057a55);">TP HIT (+2.5R)</b>`;
            else if (out === 'SL') outHtml = `<b style="color: var(--color-down, #e02424);">SL HIT (-1.0R)</b>`;
            else outHtml = `<b style="color: var(--text-secondary, #4b5563);">OPEN</b>`;
            telOut.innerHTML = `Outcome: ${outHtml}`;
        }

        if (telBox) {
            if (box && box.text) {
                telBox.innerHTML = `Tapped Zone: <b>${box.text}</b>`;
            } else {
                telBox.innerHTML = `Tapped Zone: <b>HTF TJL Structure Zone</b>`;
            }
        }
    }

    function updateSignalNavigation(currentSig) {
        if (!allTimeframeSignals || allTimeframeSignals.length === 0) return;
        const curTime = currentSig.time;
        activeSignalIndex = allTimeframeSignals.findIndex(s => s.time === curTime || s.id === currentSig.id);
        if (activeSignalIndex === -1) activeSignalIndex = allTimeframeSignals.length - 1;

        const counter = document.getElementById('signal-counter-badge');
        if (counter) {
            counter.textContent = `${activeSignalIndex + 1}/${allTimeframeSignals.length}`;
        }
    }

    function centerChartOnTime(chartObj, candlesArr, targetTime) {
        if (!chartObj || !candlesArr || candlesArr.length === 0) return;
        try {
            const idx = candlesArr.findIndex(c => c.time === targetTime || Math.abs(c.time - targetTime) <= 60);
            if (idx !== -1) {
                const startIdx = Math.max(0, idx - 45);
                const endIdx = Math.min(candlesArr.length - 1, idx + 45);
                chartObj.timeScale().setVisibleLogicalRange({
                    from: startIdx,
                    to: endIdx
                });
            } else {
                chartObj.timeScale().fitContent();
            }
        } catch (e) {
            chartObj.timeScale().fitContent();
        }
    }

    function ensureSplitViewOpen() {
        isSplitOpen = true;
        const chartPane = document.getElementById('chart-container');
        const splitPane = document.getElementById('split-ltf-container');

        if (splitPane) {
            splitPane.classList.remove('collapsed');
            splitPane.style.display = 'flex';
            splitPane.style.width = '50%';
            splitPane.style.maxWidth = '50%';
            splitPane.style.flex = '1 1 50%';
        }
        if (chartPane) {
            chartPane.classList.remove('full-width');
            chartPane.style.display = 'flex';
            chartPane.style.width = '50%';
            chartPane.style.maxWidth = '50%';
            chartPane.style.flex = '1 1 50%';
        }

        const splitBadge = document.getElementById('split-mode-badge');
        if (splitBadge) {
            splitBadge.style.cursor = 'pointer';
            splitBadge.title = 'Click to close LTF split view';
        }
        initLTFChartIfNeeded();
        resizeCanvas();
        resizeLTFCanvas();

        if (chart && chart.timeScale) {
            chart.timeScale().fitContent();
        }

        setTimeout(() => {
            resizeCanvas();
            resizeLTFCanvas();
            drawOverlay();
            drawLTFOverlay();
            if (chart && chart.timeScale) {
                chart.timeScale().fitContent();
            }
        }, 50);

        setTimeout(() => {
            resizeCanvas();
            resizeLTFCanvas();
            drawOverlay();
            drawLTFOverlay();
        }, 150);
    }

    function closeSplitLTF() {
        isSplitOpen = false;
        activeSplitTargetTime = null;
        const chartPane = document.getElementById('chart-container');
        const splitPane = document.getElementById('split-ltf-container');

        if (splitPane) {
            splitPane.classList.add('collapsed');
            splitPane.style.display = 'none';
            splitPane.style.width = '0%';
            splitPane.style.maxWidth = '0%';
            splitPane.style.flex = '0 0 0%';
        }
        if (chartPane) {
            chartPane.classList.add('full-width');
            chartPane.style.display = 'flex';
            chartPane.style.width = '100%';
            chartPane.style.maxWidth = '100%';
            chartPane.style.flex = '1 1 100%';
        }

        resizeCanvas();
        if (chart && chart.timeScale) {
            chart.timeScale().fitContent();
        }
        drawOverlay();
    }

    function toggleParallelSplitView() {
        if (isSplitOpen) {
            closeSplitLTF();
        } else {
            openSplitLTF(activeSplitTargetTime || 0);
        }
    }

    const btnParallelToggle = document.getElementById('btn-toggle-parallel');
    if (btnParallelToggle) {
        btnParallelToggle.addEventListener('click', toggleParallelSplitView);
    }
    if (btnCloseSplit) {
        btnCloseSplit.addEventListener('click', closeSplitLTF);
    }
    const btnFloatingClose = document.getElementById('btn-floating-close-ltf');
    if (btnFloatingClose) {
        btnFloatingClose.addEventListener('click', closeSplitLTF);
    }
    const splitBadgeEl = document.getElementById('split-mode-badge');
    if (splitBadgeEl) {
        splitBadgeEl.addEventListener('click', () => {
            if (isSplitOpen) closeSplitLTF();
            else openSplitLTF(activeSplitTargetTime || 0);
        });
    }

    window.openSplitLTF = openSplitLTF;
    window.closeSplitLTF = closeSplitLTF;
    window.ensureSplitViewOpen = ensureSplitViewOpen;
    window.triggerCandleDoubleClick = handleCandleDoubleClick;
    window.triggerCandleClick = handleCandleDoubleClick;
    window.renderAlgoTradeMarkers = renderAlgoTradeMarkers;
    Object.defineProperty(window, 'candlestickSeries', { get: () => candlestickSeries });
    Object.defineProperty(window, 'chart', { get: () => chart });
    Object.defineProperty(window, 'isSplitOpen', { get: () => isSplitOpen });
    Object.defineProperty(window, 'ltfCandles', { get: () => ltfCandles });
    Object.defineProperty(window, 'ltfLoadedBoxes', { get: () => ltfLoadedBoxes });
    Object.defineProperty(window, 'ltfLoadedLines', { get: () => ltfLoadedLines });

    async function openSignalAnalysis(sig) {
        if (!sig) return;
        ensureSplitViewOpen();
        const sigTime = sig.chart_time || sig.time;
        openSplitLTF(sigTime);
    }

    async function openSplitLTF(targetTime) {
        const ltfInterval = getLTFIntervalForHTF(activeTimeframe);
        console.log(`Opening Split ${ltfInterval.toUpperCase()} view for timestamp:`, targetTime, "from HTF:", activeTimeframe);
        ensureSplitViewOpen();

        if (htfTitle) {
            htfTitle.textContent = `${activeSymbol} | ${activeTimeframe.toUpperCase()} (HTF Parent)`;
        }
        if (ltfTitle) {
            ltfTitle.textContent = `${activeSymbol} | ${ltfInterval.toUpperCase()} (LTF Clean View)`;
        }
        if (ltfTargetDate) {
            ltfTargetDate.textContent = targetTime > 0 ? `@ ${formatDateTime(targetTime)}` : `${ltfInterval.toUpperCase()} Live`;
        }

        const telTypeBadge = document.getElementById('tel-type-badge');
        if (telTypeBadge) {
            telTypeBadge.textContent = `${ltfInterval.toUpperCase()} CLEAN VIEW`;
        }
        const telSl = document.getElementById('tel-sl');
        if (telSl) {
            telSl.innerHTML = `LTF: <b>${ltfInterval.toUpperCase()}</b>`;
        }
        const telTp = document.getElementById('tel-tp');
        if (telTp) {
            telTp.innerHTML = `Structure: <b>Clean Candlestick View</b>`;
        }
        const telPattern = document.getElementById('tel-pattern');
        if (telPattern) {
            telPattern.innerHTML = `Indicators: <b>None</b>`;
        }
        const telOutcome = document.getElementById('tel-outcome');
        if (telOutcome) {
            telOutcome.innerHTML = `Status: <b>CLEAN</b>`;
        }
        const telBox = document.getElementById('tel-box');
        if (telBox) {
            telBox.innerHTML = `Details: <b>Displaying raw ${ltfInterval.toUpperCase()} candles</b>`;
        }

        activeSplitTargetTime = targetTime;

        try {
            const token = localStorage.getItem('topg_admin_token') || localStorage.getItem('topg_token') || '';
            const resp = await fetch(`/api/ltf_candles?symbol=${activeSymbol}&interval=${ltfInterval}&target_time=${targetTime}&range_bars=1500&htf=${activeTimeframe}&token=${encodeURIComponent(token)}`, {
                headers: token ? { 'Authorization': `Bearer ${token}` } : {}
            });
            const data = await resp.json();
            if (data && Array.isArray(data.candles) && data.candles.length > 0) {
                ltfCandles = prepareCandles(data.candles);
                ltfLoadedLabels = data.labels || [];
                ltfLoadedLines = data.lines || [];
                ltfLoadedBoxes = data.boxes || [];
                ltfLoadedSignals = data.signals || [];
                window.ltfCandles = ltfCandles;
                window.ltfLoadedLabels = ltfLoadedLabels;
                window.ltfLoadedLines = ltfLoadedLines;
                window.ltfLoadedBoxes = ltfLoadedBoxes;
                ltfSeries.setData(ltfCandles);
                ltfSeries.setMarkers(data.markers || []);

                const curTr = data.trade_logic || window.currentLTFTrade;
                if (curTr && curTr.entry_price) {
                    window.currentLTFTrade = curTr;
                    if (telTypeBadge) {
                        telTypeBadge.textContent = `BOT ${curTr.action || curTr.type} (${curTr.rr}R)`;
                        telTypeBadge.style.background = (curTr.action === 'BUY' || curTr.type === 'BUY') ? '#10b981' : '#ef4444';
                    }
                    if (telPattern) telPattern.innerHTML = `Signal: <b>${curTr.action || curTr.type} (${curTr.pattern_name || curTr.pattern || 'Reversal'} @ ${curTr.level_name || curTr.level || curTr.setup_type || 'Zone'})</b>`;
                    if (telOutcome) telOutcome.innerHTML = `Entry: <b>$${Number(curTr.entry_price || curTr.entry).toLocaleString()}</b> | SL: <b>$${Number(curTr.sl_price || curTr.sl).toLocaleString()}</b> | TP: <b>$${Number(curTr.tp_price || curTr.tp).toLocaleString()}</b>`;
                    if (telBox) telBox.innerHTML = `Setup: <b>${curTr.setup_type || curTr.level_name || 'HTF'} | Target: ${curTr.rr}R ${curTr.outcome ? `[${curTr.outcome} ${curTr.pnl_r >= 0 ? '+' : ''}${curTr.pnl_r}R]` : ''}</b>`;

                    // Update 4-step HUD
                    const hudTap = document.getElementById('hud-tap-text');
                    const hudRace = document.getElementById('hud-race-text');
                    const hudLevels = document.getElementById('hud-levels-text');
                    const hudConf = document.getElementById('hud-conf-text');
                    const hudDecBadge = document.getElementById('hud-decision-badge');
                    const hudDecReason = document.getElementById('hud-decision-reason');

                    if (hudTap) hudTap.textContent = `Tapped ${curTr.setup_type || 'HTF Zone'}`;
                    if (hudRace) hudRace.textContent = 'Structure Confirmed';
                    if (hudLevels) hudLevels.textContent = `${curTr.level_name || curTr.level || 'LTF'} Active`;
                    if (hudConf) hudConf.textContent = `${curTr.pattern_name || curTr.pattern || 'Pattern'}`;
                    if (hudDecBadge) {
                        hudDecBadge.textContent = `BOT ${curTr.action || curTr.type} EXECUTED`;
                        hudDecBadge.style.background = (curTr.action === 'BUY' || curTr.type === 'BUY') ? '#10b981' : '#ef4444';
                        hudDecBadge.style.color = '#ffffff';
                    }
                    if (hudDecReason) {
                        hudDecReason.textContent = `Target: ${curTr.rr}R | Outcome: ${curTr.outcome || 'OPEN'} (${curTr.pnl_r !== undefined ? ((curTr.pnl_r >= 0 ? '+' : '') + curTr.pnl_r + 'R') : ''})`;
                    }
                } else if (data.tap_info) {
                    if (telTypeBadge) telTypeBadge.textContent = 'HTF ZONE TAPPED';
                    if (telPattern) telPattern.innerHTML = `HTF Zone: <b>${data.tap_info.box_name}</b>`;
                    if (telOutcome) telOutcome.innerHTML = `Tap Time: <b>${formatDateTime(data.tap_info.tap_time)}</b>`;
                    if (telBox) telBox.innerHTML = `Approach: <b>Marked from 40 candles prior to tap (${formatDateTime(data.tap_info.start_time)})</b>`;
                }

                setTimeout(() => {
                    if (ltfChart && ltfChart.timeScale) {
                        if (targetTime > 0 && ltfCandles.length > 0) {
                            const targetIdx = ltfCandles.findIndex(c => c.time >= targetTime);
                            if (targetIdx !== -1) {
                                const fromIdx = Math.max(0, targetIdx - 20);
                                const toIdx = Math.min(ltfCandles.length - 1, targetIdx + 120);
                                ltfChart.timeScale().setVisibleRange({
                                    from: ltfCandles[fromIdx].time,
                                    to: ltfCandles[toIdx].time
                                });
                            } else {
                                ltfChart.timeScale().fitContent();
                            }
                        } else {
                            ltfChart.timeScale().fitContent();
                        }
                    }
                    drawLTFOverlay();
                }, 50);

                updateLegend(ltfOhlcLegend, null, ltfSeries, ltfCandles);
                drawLTFOverlay();

                if (chart && chart.timeScale && targetTime > 0 && currentCandles && currentCandles.length > 0) {
                    const htfIdx = currentCandles.findIndex(c => c.time >= targetTime);
                    if (htfIdx !== -1) {
                        const fromIdx = Math.max(0, htfIdx - 25);
                        const toIdx = Math.min(currentCandles.length - 1, htfIdx + 25);
                        chart.timeScale().setVisibleRange({
                            from: currentCandles[fromIdx].time,
                            to: currentCandles[toIdx].time
                        });
                    }
                }
            }
        } catch (err) {
            console.error("Error loading split LTF candles:", err);
        }
    }

    // Double-Click Candle Dispatcher & Split Screen Opener
    function handleCandleDoubleClick(time) {
        if (isDrawing) return;
        let t = time || currentHoveredTime;
        if (!t && currentCandles && currentCandles.length > 0) {
            t = currentCandles[currentCandles.length - 1].time;
        }
        console.log("[handleCandleDoubleClick] Double click detected, opening split LTF for candle:", t, "Timeframe:", activeTimeframe);
        if (t) {
            openSplitLTF(t);
        }
    }

    // Expose globally for API & testing
    window.handleCandleDoubleClick = handleCandleDoubleClick;
    window.triggerCandleDoubleClick = handleCandleDoubleClick;
    window.triggerCandleClick = handleCandleDoubleClick;

    // Layer 1: Native 'dblclick' on chart inner, container, and overlay canvas
    function handleChartDblClick(e) {
        if (isDrawing) return;
        const targetEl = document.getElementById('htf-chart-inner') || container;
        const rect = targetEl.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const t = coordToTime(chart, currentCandles, clickX) || currentHoveredTime;
        handleCandleDoubleClick(t);
    }

    const chartInnerElement = document.getElementById('htf-chart-inner');
    if (chartInnerElement) {
        chartInnerElement.addEventListener('dblclick', handleChartDblClick);
    }
    if (container) {
        container.addEventListener('dblclick', handleChartDblClick);
    }
    if (canvas) {
        canvas.addEventListener('dblclick', handleChartDblClick);
    }

    // Layer 2: Double-click detection via LightweightCharts subscribeClick
    // Detects when user clicks twice on the chart within 500ms
    let lastChartClickStamp = 0;
    let lastChartClickCandle = null;

    chart.subscribeClick(param => {
        if (isDrawing) return;
        let t = (param && param.time) ? param.time : null;
        if (!t && param && param.point) {
            t = coordToTime(chart, currentCandles, param.point.x);
        }
        if (!t) {
            t = currentHoveredTime;
        }
        if (!t) return;

        const now = Date.now();
        if (now - lastChartClickStamp < 500) {
            // Double click detected!
            lastChartClickStamp = 0;
            lastChartClickCandle = null;
            console.log("[chart.subscribeClick] Double-click detected on candle:", t);
            handleCandleDoubleClick(t);
        } else {
            // First click recorded
            lastChartClickStamp = now;
            lastChartClickCandle = t;
        }
    });

    // =========================================================================
    // GENERALIZED TIME <-> COORD CONVERTERS
    // =========================================================================
    function timeToCoord(chartObj, candlesArr, timestamp) {
        if (!chartObj || !candlesArr || candlesArr.length === 0) return null;
        try {
            let x = chartObj.timeScale().timeToCoordinate(timestamp);
            if (x !== null) return x;

            const firstTime = candlesArr[0]?.time;
            const lastTime = candlesArr[candlesArr.length - 1]?.time;
            if (!firstTime || !lastTime) return null;

            if (timestamp < firstTime) {
                const firstX = chartObj.timeScale().timeToCoordinate(firstTime);
                return firstX !== null ? firstX - 300 : -300;
            }
            if (timestamp >= lastTime) {
                const lastX = chartObj.timeScale().timeToCoordinate(lastTime);
                return lastX !== null ? lastX + 300 : (chartObj.options ? chartObj.options().width : 1200) + 300;
            }

            let left = 0, right = candlesArr.length - 1;
            while (left <= right) {
                let mid = Math.floor((left + right) / 2);
                if (candlesArr[mid].time === timestamp) {
                    return chartObj.timeScale().timeToCoordinate(candlesArr[mid].time);
                } else if (candlesArr[mid].time < timestamp) {
                    left = mid + 1;
                } else {
                    right = mid - 1;
                }
            }

            const idx = Math.max(0, Math.min(candlesArr.length - 2, right));
            const c1 = candlesArr[idx];
            const c2 = candlesArr[idx + 1];
            if (!c1 || !c2) return null;

            const x1 = chartObj.timeScale().timeToCoordinate(c1.time);
            const x2 = chartObj.timeScale().timeToCoordinate(c2.time);
            if (x1 !== null && x2 !== null) {
                const ratio = (timestamp - c1.time) / (c2.time - c1.time);
                return x1 + ratio * (x2 - x1);
            }
            return x1 || x2;
        } catch (e) {
            return null;
        }
    }

    function coordToTime(chartObj, candlesArr, x) {
        if (!chartObj) return null;
        try {
            const t = chartObj.timeScale().coordinateToTime(x);
            if (t) return typeof t === 'number' ? t : (t.timestamp || t);
        } catch (e) {}

        try {
            const logical = chartObj.timeScale().coordinateToLogical(x);
            if (logical !== null && candlesArr && candlesArr.length > 0) {
                const idx = Math.round(logical);
                if (idx >= 0 && idx < candlesArr.length) {
                    return candlesArr[idx].time;
                } else if (idx < 0) {
                    const step = (candlesArr[1]?.time || candlesArr[0].time + 60) - candlesArr[0].time;
                    return candlesArr[0].time + idx * step;
                } else {
                    const lastIdx = candlesArr.length - 1;
                    const step = candlesArr[lastIdx].time - (candlesArr[lastIdx - 1]?.time || candlesArr[lastIdx].time - 60);
                    return candlesArr[lastIdx].time + (idx - lastIdx) * step;
                }
            }
        } catch (e) {}
        return null;
    }

    function getPixelX(timestamp) {
        return timeToCoord(chart, currentCandles, timestamp);
    }

    // =========================================================================
    // RENDERING USER DRAWINGS (BOXES & TRENDLINES)
    // =========================================================================
    function drawHandle(targetCtx, x, y) {
        targetCtx.save();
        targetCtx.fillStyle = '#ffffff';
        targetCtx.strokeStyle = '#2962ff';
        targetCtx.lineWidth = 2;
        targetCtx.beginPath();
        targetCtx.arc(x, y, 4.5, 0, Math.PI * 2);
        targetCtx.fill();
        targetCtx.stroke();
        targetCtx.restore();
    }

    function renderUserDrawings(targetCtx, targetChart, targetSeries, targetCandles, width, height, isHTF) {
        if (!targetCtx || !targetChart || !targetSeries) return;

        const getX = (t) => timeToCoord(targetChart, targetCandles, t);

        const list = [...userDrawings];
        if (activeDrawingDraft && ((isHTF && activeChartSource === 'htf') || (!isHTF && activeChartSource === 'ltf'))) {
            list.push(activeDrawingDraft);
        }

        list.forEach(d => {
            const x1 = getX(d.t1);
            const x2 = getX(d.t2);
            const y1 = targetSeries.priceToCoordinate(d.p1);
            const y2 = targetSeries.priceToCoordinate(d.p2);

            if (x1 === null || x2 === null || y1 === null || y2 === null) return;

            const isSelected = (selectedDrawing && selectedDrawing.id === d.id);
            const color = d.color || '#2962ff';
            const lineWidth = d.lineWidth || 1.5;
            const lineStyle = d.lineStyle || 'solid';

            targetCtx.save();

            if (d.type === 'box') {
                const rx = Math.min(x1, x2);
                const ry = Math.min(y1, y2);
                const rw = Math.abs(x2 - x1);
                const rh = Math.abs(y2 - y1);

                // Background Fill
                const opacity = d.bgOpacity !== undefined ? d.bgOpacity : 0.25;
                if (opacity > 0) {
                    targetCtx.fillStyle = hexToRgba(color, opacity);
                    targetCtx.fillRect(rx, ry, rw, rh);
                }

                // Border Stroke
                targetCtx.strokeStyle = color;
                targetCtx.lineWidth = lineWidth;
                if (lineStyle === 'dashed') {
                    targetCtx.setLineDash([5, 5]);
                } else {
                    targetCtx.setLineDash([]);
                }
                targetCtx.strokeRect(rx, ry, rw, rh);

                // Text Label inside box
                if (d.text && d.text.trim()) {
                    targetCtx.setLineDash([]);
                    targetCtx.font = '300 9px sans-serif';
                    targetCtx.fillStyle = '#ffffff';
                    targetCtx.textAlign = 'left';
                    targetCtx.textBaseline = 'top';
                    targetCtx.fillText(d.text.trim(), rx + 6, ry + 6);
                }

                // Selection Handles
                if (isSelected) {
                    targetCtx.setLineDash([]);
                    drawHandle(targetCtx, x1, y1);
                    drawHandle(targetCtx, x2, y2);
                    drawHandle(targetCtx, x1, y2);
                    drawHandle(targetCtx, x2, y1);
                }

            } else if (d.type === 'trendline') {
                // Line Stroke
                targetCtx.beginPath();
                targetCtx.moveTo(x1, y1);
                targetCtx.lineTo(x2, y2);
                targetCtx.strokeStyle = color;
                targetCtx.lineWidth = lineWidth;
                if (lineStyle === 'dashed') {
                    targetCtx.setLineDash([5, 5]);
                } else {
                    targetCtx.setLineDash([]);
                }
                targetCtx.stroke();

                // Text Label alongside trendline
                if (d.text && d.text.trim()) {
                    const midX = (x1 + x2) / 2;
                    const midY = (y1 + y2) / 2;
                    const angle = Math.atan2(y2 - y1, x2 - x1);

                    targetCtx.save();
                    targetCtx.translate(midX, midY);
                    let textAngle = angle;
                    if (textAngle > Math.PI / 2 || textAngle < -Math.PI / 2) {
                        textAngle += Math.PI;
                    }
                    targetCtx.rotate(textAngle);

                    targetCtx.font = '300 9px sans-serif';
                    targetCtx.fillStyle = color;
                    targetCtx.textAlign = 'center';
                    targetCtx.textBaseline = 'bottom';
                    targetCtx.setLineDash([]);
                    targetCtx.fillText(d.text.trim(), 0, -4);
                    targetCtx.restore();
                }

                // Selection Handles
                if (isSelected) {
                    targetCtx.setLineDash([]);
                    drawHandle(targetCtx, x1, y1);
                    drawHandle(targetCtx, x2, y2);
                }
            }

            targetCtx.restore();
        });
    }

    // =========================================================================
    // HIT TESTING & SELECTION HELPERS
    // =========================================================================
    function distToSegment(px, py, x1, y1, x2, y2) {
        const l2 = (x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1);
        if (l2 === 0) return Math.hypot(px - x1, py - y1);
        let t = ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2;
        t = Math.max(0, Math.min(1, t));
        return Math.hypot(px - (x1 + t * (x2 - x1)), py - (y1 + t * (y2 - y1)));
    }

    function findDrawingAtCoord(px, py, chartObj, seriesObj, candlesArr) {
        if (!chartObj || !seriesObj || !candlesArr || candlesArr.length === 0) return null;
        const getX = (t) => timeToCoord(chartObj, candlesArr, t);

        for (let i = userDrawings.length - 1; i >= 0; i--) {
            const d = userDrawings[i];
            const x1 = getX(d.t1);
            const x2 = getX(d.t2);
            const y1 = seriesObj.priceToCoordinate(d.p1);
            const y2 = seriesObj.priceToCoordinate(d.p2);
            if (x1 === null || x2 === null || y1 === null || y2 === null) continue;

            if (d.type === 'box') {
                const minX = Math.min(x1, x2) - 4;
                const maxX = Math.max(x1, x2) + 4;
                const minY = Math.min(y1, y2) - 4;
                const maxY = Math.max(y1, y2) + 4;

                const h1 = Math.hypot(px - x1, py - y1) <= 8;
                const h2 = Math.hypot(px - x2, py - y2) <= 8;
                const h3 = Math.hypot(px - x1, py - y2) <= 8;
                const h4 = Math.hypot(px - x2, py - y1) <= 8;

                if (h1) return { drawing: d, handle: 'p1', index: i };
                if (h2) return { drawing: d, handle: 'p2', index: i };
                if (h3) return { drawing: d, handle: 'p3', index: i };
                if (h4) return { drawing: d, handle: 'p4', index: i };

                if (px >= minX && px <= maxX && py >= minY && py <= maxY) {
                    return { drawing: d, handle: null, index: i };
                }
            } else if (d.type === 'trendline') {
                const h1 = Math.hypot(px - x1, py - y1) <= 8;
                const h2 = Math.hypot(px - x2, py - y2) <= 8;
                if (h1) return { drawing: d, handle: 'p1', index: i };
                if (h2) return { drawing: d, handle: 'p2', index: i };

                const dSeg = distToSegment(px, py, x1, y1, x2, y2);
                if (dSeg <= 7) {
                    return { drawing: d, handle: null, index: i };
                }
            }
        }
        return null;
    }

    // =========================================================================
    // OVERLAY RENDERING (HTF & LTF)
    // =========================================================================
    function drawPill(context, x, y, text, bgColor, textColor, isCentered = false) {
        context.save();
        context.font = 'bold 10px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
        const metrics = context.measureText(text);
        const pad = 6;
        const w = metrics.width + pad * 2;
        const h = 18;
        const px = isCentered ? (x - w / 2) : x;
        const py = y - h / 2;

        context.fillStyle = bgColor;
        context.beginPath();
        context.roundRect(px, py, w, h, 4);
        context.fill();

        context.strokeStyle = 'rgba(0,0,0,0.4)';
        context.lineWidth = 1;
        context.stroke();

        context.fillStyle = textColor;
        context.textAlign = 'center';
        context.textBaseline = 'middle';
        context.fillText(text, px + w / 2, py + h / 2);
        context.restore();
    }

    function selectTradeAndOpenLTF(trade) {
        if (!trade) return;
        window.currentLTFTrade = trade;

        if (Array.isArray(allTimeframeSignals) && allTimeframeSignals.length > 0) {
            const idx = allTimeframeSignals.findIndex(s => (s.id && s.id === trade.id) || (s.entry_time && s.entry_time === trade.entry_time) || s.time === trade.time);
            if (idx !== -1) {
                activeSignalIndex = idx;
            }
        }

        const counterBadge = document.getElementById('signal-counter-badge');
        const navControls = document.getElementById('signal-nav-controls');
        if (navControls) navControls.style.display = 'flex';
        if (counterBadge && allTimeframeSignals.length > 0) {
            counterBadge.textContent = `${activeSignalIndex + 1}/${allTimeframeSignals.length}`;
        }

        // Highlight active trade pill
        const pills = document.querySelectorAll('.sig-quick-pill');
        pills.forEach((p, i) => {
            if (i === activeSignalIndex) {
                p.classList.add('active-selected-trade');
                p.style.outline = '2px solid #3b82f6';
                p.style.boxShadow = '0 0 10px rgba(59, 130, 246, 0.6)';
            } else {
                p.classList.remove('active-selected-trade');
                p.style.outline = 'none';
                p.style.boxShadow = 'none';
            }
        });

        // Center HTF chart on trade candle
        const htfTime = trade.chart_time || trade.time;
        if (chart && currentCandles && htfTime) {
            centerChartOnTime(chart, currentCandles, htfTime);
        }

        // Open split LTF view on trade entry time
        const ltfTime = trade.entry_time || trade.time;
        if (typeof openSplitLTF === 'function') {
            openSplitLTF(ltfTime);
        }
    }
    window.selectTradeAndOpenLTF = selectTradeAndOpenLTF;

    // Attach signal PREV / NEXT navigation buttons
    const btnPrevSig = document.getElementById('btn-prev-signal');
    const btnNextSig = document.getElementById('btn-next-signal');
    if (btnPrevSig) {
        btnPrevSig.addEventListener('click', (e) => {
            e.stopPropagation();
            if (!allTimeframeSignals || allTimeframeSignals.length === 0) return;
            activeSignalIndex = (activeSignalIndex - 1 + allTimeframeSignals.length) % allTimeframeSignals.length;
            selectTradeAndOpenLTF(allTimeframeSignals[activeSignalIndex]);
        });
    }
    if (btnNextSig) {
        btnNextSig.addEventListener('click', (e) => {
            e.stopPropagation();
            if (!allTimeframeSignals || allTimeframeSignals.length === 0) return;
            activeSignalIndex = (activeSignalIndex + 1) % allTimeframeSignals.length;
            selectTradeAndOpenLTF(allTimeframeSignals[activeSignalIndex]);
        });
    }

    function updateQuickSignalsStrip(signals) {
        const strip = document.getElementById('signals-quick-strip');
        if (!strip) return;
        strip.style.display = 'flex';

        allTimeframeSignals = (signals && signals.length > 0) ? signals : [];
        window.allTimeframeSignals = allTimeframeSignals;

        const navControls = document.getElementById('signal-nav-controls');
        if (navControls) {
            navControls.style.display = allTimeframeSignals.length > 0 ? 'flex' : 'none';
        }

        if (!allTimeframeSignals || allTimeframeSignals.length === 0) {
            strip.innerHTML = '<span class="no-signals-tag">No bot trades on this timeframe yet. Click any candle to inspect why bot skipped it.</span>';
            return;
        }

        strip.innerHTML = `<span style="font-size: 11px; font-weight: 700; color: var(--text-secondary); margin-right: 4px;">⚡ Algo Trades (${allTimeframeSignals.length}):</span>`;
        allTimeframeSignals.forEach((sig, idx) => {
            const pill = document.createElement('span');
            const isBuy = (sig.type === 'BUY' || sig.action === 'BUY' || sig.side === 'BUY');
            const outTag = sig.outcome ? ` [${sig.outcome} ${sig.pnl_r !== undefined ? ((sig.pnl_r >= 0 ? '+' : '') + sig.pnl_r + 'R') : ''}]` : '';
            pill.className = `sig-quick-pill ${isBuy ? 'buy' : 'sell'}`;
            const pVal = Number(sig.entry || sig.entry_price || sig.price || 0).toLocaleString(undefined, {minimumFractionDigits: 1, maximumFractionDigits: 2});
            pill.innerHTML = `<span>${isBuy ? '🟢 BUY' : '🔴 SELL'} ${sig.setup_type || ''} @ $${pVal}${outTag}</span>`;
            pill.title = `Click to show Trade #${idx+1} on LTF Chart (Entry, SL, TP)`;
            pill.style.cursor = 'pointer';
            pill.addEventListener('click', (e) => {
                e.stopPropagation();
                selectTradeAndOpenLTF(sig);
            });
            strip.appendChild(pill);
        });

        if (activeSignalIndex === -1 && allTimeframeSignals.length > 0) {
            activeSignalIndex = 0;
            const counterBadge = document.getElementById('signal-counter-badge');
            if (counterBadge) counterBadge.textContent = `1/${allTimeframeSignals.length}`;
        }
    }

    function renderAlgoTradeMarkers(signals) {
        if (!candlestickSeries) return;
        if (currentStrategy && Array.isArray(currentStrategy.markers) && currentStrategy.markers.length > 0) {
            const markers = currentStrategy.markers.map(m => ({ ...m, size: 2 }));
            markers.sort((a, b) => a.time - b.time);
            candlestickSeries.setMarkers(markers);
            return;
        }
        const sigs = (signals && signals.length > 0) ? signals : (currentStrategy && currentStrategy.signals ? currentStrategy.signals : []);
        if (!sigs || sigs.length === 0) {
            candlestickSeries.setMarkers([]);
            return;
        }
        const markers = [];
        const seen = new Set();
        sigs.forEach(s => {
            const isBuy = (s.type === 'BUY' || s.side === 'BUY');
            const t = s.chart_time || s.time;
            if (!t) return;
            const key = `${t}_${isBuy ? 'BUY' : 'SELL'}`;
            if (seen.has(key)) return;
            seen.add(key);

            markers.push({
                time: t,
                position: isBuy ? 'belowBar' : 'aboveBar',
                color: isBuy ? '#10b981' : '#ef4444',
                shape: isBuy ? 'arrowUp' : 'arrowDown',
                size: 2
            });
        });
        markers.sort((a, b) => a.time - b.time);
        candlestickSeries.setMarkers(markers);
    }

    function updateStructureBadges() {
        const trendBadge = document.getElementById('structure-trend-badge');
        if (!trendBadge) return;
        const tr = (currentStrategy ? (currentStrategy.trend || currentStrategy.htf_trend || 'Neutral') : 'Neutral').toLowerCase();
        if (tr.includes('up') || tr.includes('bull')) {
            trendBadge.textContent = 'UPTREND';
            trendBadge.style.color = '#00e676';
            trendBadge.style.borderColor = 'rgba(0, 230, 118, 0.4)';
            trendBadge.style.background = 'rgba(0, 230, 118, 0.15)';
        } else if (tr.includes('down') || tr.includes('bear')) {
            trendBadge.textContent = 'DOWNTREND';
            trendBadge.style.color = '#ff5252';
            trendBadge.style.borderColor = 'rgba(255, 82, 82, 0.4)';
            trendBadge.style.background = 'rgba(255, 82, 82, 0.15)';
        } else {
            trendBadge.textContent = 'RANGE';
            trendBadge.style.color = '#ffa726';
            trendBadge.style.borderColor = 'rgba(255, 167, 38, 0.4)';
            trendBadge.style.background = 'rgba(255, 167, 38, 0.15)';
        }

        const d1Btn = document.getElementById('btn-d1-h1-transition');
        if (d1Btn) {
            const htfNorm = (activeTimeframe || '1d').toLowerCase();
            const ltfNorm = getLTFIntervalForHTF(htfNorm).toUpperCase();
            if (currentCandles && currentCandles.length > 0 && currentStrategy && Array.isArray(currentStrategy.boxes)) {
                const latestC = currentCandles[currentCandles.length - 1];
                const tappedBox = currentStrategy.boxes.find(b => {
                    const top = Math.max(b.top, b.bottom);
                    const bot = Math.min(b.top, b.bottom);
                    return latestC.high >= bot && latestC.low <= top;
                });
                if (tappedBox) {
                    const isBull = (tappedBox.is_bullish === true || tappedBox.level_type === 'demand');
                    const zType = isBull ? 'DEMAND' : 'SUPPLY';
                    d1Btn.style.display = 'inline-flex';
                    d1Btn.textContent = `${htfNorm.toUpperCase()} ${zType} TAPPED -> OPEN ${ltfNorm} STRUCTURE`;
                    d1Btn.style.borderColor = isBull ? '#26a69a' : '#ef5350';
                    d1Btn.style.color = isBull ? '#26a69a' : '#ef5350';
                    d1Btn.style.background = isBull ? 'rgba(38, 166, 154, 0.15)' : 'rgba(239, 83, 80, 0.15)';
                    d1Btn.onclick = () => {
                        const tapTime = tappedBox.first_tap_time || tappedBox.tap_time || latestC.time;
                        openSplitLTF(tapTime);
                    };
                } else {
                    d1Btn.style.display = 'none';
                }
            } else {
                d1Btn.style.display = 'none';
            }
        }
    }

    function drawRightPriceBadge(context, y, text, bgColor, textColor, chartWidth) {
        context.save();
        context.font = 'bold 10px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
        const tm = context.measureText(text);
        const pad = 6;
        const w = tm.width + pad * 2;
        const h = 18;
        const badgeX = chartWidth - w - 6;
        const badgeY = y - h / 2;

        context.fillStyle = bgColor;
        context.beginPath();
        context.roundRect(badgeX, badgeY, w, h, 3);
        context.fill();

        context.strokeStyle = 'rgba(255, 255, 255, 0.4)';
        context.lineWidth = 1;
        context.stroke();

        context.fillStyle = textColor;
        context.textAlign = 'center';
        context.textBaseline = 'middle';
        context.fillText(text, badgeX + w / 2, y);
        context.restore();
    }

    function drawRightPriceBadge(context, y, text, bgColor, textColor, chartWidth) {
        context.save();
        context.font = 'bold 10px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
        const tm = context.measureText(text);
        const pad = 6;
        const w = tm.width + pad * 2;
        const h = 18;
        const badgeX = chartWidth - w - 6;
        const badgeY = y - h / 2;

        context.fillStyle = bgColor;
        context.beginPath();
        context.roundRect(badgeX, badgeY, w, h, 3);
        context.fill();

        context.strokeStyle = 'rgba(255, 255, 255, 0.4)';
        context.lineWidth = 1;
        context.stroke();

        context.fillStyle = textColor;
        context.textAlign = 'center';
        context.textBaseline = 'middle';
        context.fillText(text, badgeX + w / 2, y);
        context.restore();
    }

    function drawOverlay() {
        try {
            const dims = getChartDims();
            const width = dims.width;
            const height = dims.height;
            ctx.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0);
            ctx.clearRect(0, 0, width, height);

            updateStructureBadges();
            mainChartSignalHitboxes = [];

            // 0. Render Target Selected Candle Guide Line & Timestamp Badges
            if (activeSplitTargetTime) {
                const xTarget = timeToCoord(chart, currentCandles, activeSplitTargetTime);
                if (xTarget !== null) {
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(xTarget, 0);
                    ctx.lineTo(xTarget, height);
                    ctx.strokeStyle = 'rgba(255, 193, 7, 0.45)';
                    ctx.lineWidth = 1;
                    ctx.setLineDash([]); // No dotted lines
                    ctx.stroke();
                    ctx.fillStyle = '#b45309';
                    ctx.font = '300 11px var(--font-mono), monospace';
                    ctx.textAlign = 'center';
                    ctx.fillText(`[Focused: ${formatDateTime(activeSplitTargetTime)}]`, xTarget, 14);

                    const dateTxt = formatDateTime(activeSplitTargetTime);
                    const bw = ctx.measureText(dateTxt).width + 12;
                    ctx.fillStyle = 'rgba(255, 193, 7, 0.9)';
                    ctx.fillRect(xTarget - bw / 2, height - 22, bw, 18);
                    ctx.fillStyle = '#000000';
                    ctx.font = '300 10px var(--font-mono), monospace';
                    ctx.fillText(dateTxt, xTarget, height - 9);
                    ctx.restore();
                }
            }

            // =====================================================================
            // 1. STRUCTURE BOXES: TJL1, TJL2, QML, RBS, SBR, Double Top/Bottom, Level of 3/4
            // =====================================================================
            const curC = (currentCandles && currentCandles.length > 0) ? currentCandles[currentCandles.length - 1] : null;
            const maxVisibleTime = (window.isSimulationReplayActive && currentCandles && currentCandles.length > 0) 
                                   ? currentCandles[currentCandles.length - 1].time : Infinity;

            const rawBoxes = (currentStrategy && Array.isArray(currentStrategy.boxes)) ? currentStrategy.boxes : [];
            const boxesToRender = rawBoxes.filter(box => {
                const boxStart = box.left || box.time1 || box.created_time;
                if (window.isSimulationReplayActive && boxStart && boxStart > maxVisibleTime) return false;
                return true;
            });

            if (Array.isArray(boxesToRender)) {
                boxesToRender.forEach(box => {
                    const boxStart = box.left || box.time1 || box.created_time;
                    const boxEnd = box.right || box.time2 || (curC ? curC.time : 0);

                    const x1 = timeToCoord(chart, currentCandles, boxStart);
                    const x2 = timeToCoord(chart, currentCandles, boxEnd);
                    const y1 = candlestickSeries.priceToCoordinate(box.top);
                    const y2 = candlestickSeries.priceToCoordinate(box.bottom);

                    if (x1 !== null && x2 !== null && y1 !== null && y2 !== null) {
                        const rectX = Math.min(x1, x2);
                        const rectY = Math.min(y1, y2);
                        const rectW = Math.max(2, Math.abs(x2 - x1));
                        const rectH = Math.max(2, Math.abs(y2 - y1));

                        if (rectX + rectW < -100 || rectX > width + 100) return;

                        ctx.save();
                        const isBullish = box.is_bullish === true || box.level_type === 'buying' || box.level_type === 'demand';
                        const defaultFill = isBullish ? 'rgba(38, 166, 154, 0.20)' : 'rgba(239, 83, 80, 0.20)';
                        const defaultBorder = isBullish ? '#26a69a' : '#ef5350';

                        const isTappedNow = curC && (curC.low <= Math.max(box.top, box.bottom) && curC.high >= Math.min(box.top, box.bottom));
                        const isNewlyFormed = curC && (boxStart === curC.time);

                        if (isTappedNow) {
                            ctx.fillStyle = isBullish ? 'rgba(16, 185, 129, 0.35)' : 'rgba(239, 68, 68, 0.35)';
                            ctx.strokeStyle = '#f59e0b';
                            ctx.lineWidth = 1;
                        } else if (isNewlyFormed) {
                            ctx.fillStyle = isBullish ? 'rgba(59, 130, 246, 0.30)' : 'rgba(236, 72, 153, 0.30)';
                            ctx.strokeStyle = '#3b82f6';
                            ctx.lineWidth = 1;
                        } else {
                            ctx.fillStyle = box.color || defaultFill;
                            ctx.strokeStyle = box.borderColor || defaultBorder;
                            ctx.lineWidth = 1;
                        }

                        // 1px solid border - no dotted lines on chart
                        ctx.setLineDash([]);
                        ctx.fillRect(rectX, rectY, rectW, rectH);
                        ctx.strokeRect(rectX, rectY, rectW, rectH);

                        // Only write name of level with no bold text, only black 1px solid light font
                        // Do not write demand or supply (their color is self explanatory)
                        let levelName = (box.text || box.name || '').trim();
                        levelName = levelName.replace(/\[|\]/g, '')
                                             .replace(/\b(demand|supply)\s*(zone)?\b/gi, '')
                                             .replace(/\bzone\b/gi, '')
                                             .replace(/^(tapped|new)\s*:\s*/gi, '')
                                             .trim();

                        if (levelName && rectW > 14) {
                            ctx.fillStyle = '#000000';
                            ctx.font = '300 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
                            ctx.textAlign = 'left';
                            ctx.textBaseline = 'top';
                            ctx.fillText(levelName, rectX + 5, rectY + 4);
                        }
                        ctx.restore();
                    }
                });
            }

            // =====================================================================
            // 2. STRUCTURE LINES: BOS, CHoCH, Dual CHoCH, Triple CHoCH
            // Written in middle and center of line just like TradingView (horizontally and vertically)
            // =====================================================================
            const rawLines = (currentStrategy && Array.isArray(currentStrategy.lines)) ? currentStrategy.lines : [];
            const linesToRender = rawLines.filter(line => {
                const lineBreakTime = line.x2 || line.time2 || line.x1 || line.time1;
                if (window.isSimulationReplayActive && lineBreakTime && lineBreakTime > maxVisibleTime) return false;
                return true;
            });

            if (Array.isArray(linesToRender)) {
                linesToRender.forEach(line => {
                    const lX1 = line.x1 || line.time1;
                    const lX2 = line.x2 || line.time2;
                    const lY1 = line.y1 !== undefined ? line.y1 : line.price1;
                    const lY2 = line.y2 !== undefined ? line.y2 : line.price2;

                    const x1 = timeToCoord(chart, currentCandles, lX1);
                    const x2 = timeToCoord(chart, currentCandles, lX2);
                    const y1 = candlestickSeries.priceToCoordinate(lY1);
                    const y2 = candlestickSeries.priceToCoordinate(lY2);

                    if (x1 !== null && x2 !== null && y1 !== null && y2 !== null) {
                        const minX = Math.min(x1, x2);
                        const maxX = Math.max(x1, x2);
                        if (maxX < -50 || minX > width + 50) return;

                        const rawType = (line.type || line.label || 'BOS').trim();
                        let strokeColor = line.color || '#ff9800';
                        let lineWidth = 1.5;

                        if (rawType.includes('Triple')) {
                            strokeColor = '#a855f7'; // Purple for Triple CHoCH
                            lineWidth = 2;
                        } else if (rawType.includes('Dual')) {
                            strokeColor = '#f59e0b'; // Amber for Dual CHoCH
                            lineWidth = 1.5;
                        } else if (rawType.includes('CHoCH')) {
                            strokeColor = line.direction === 'bullish' ? '#10b981' : '#ef4444';
                            lineWidth = 1.5;
                        } else if (rawType.includes('BOS')) {
                            strokeColor = line.direction === 'bullish' ? '#26a69a' : '#ef5350';
                            lineWidth = 1.5;
                        }

                        ctx.save();
                        ctx.strokeStyle = strokeColor;
                        ctx.lineWidth = lineWidth;
                        ctx.setLineDash([]); // No dotted lines on chart

                        const midX = (x1 + x2) / 2;
                        const midY = (y1 + y2) / 2;
                        const labelText = rawType;

                        // TradingView style: clean gap in line, centered horizontally & vertically
                        ctx.font = '300 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
                        const tw = ctx.measureText(labelText).width;
                        const halfGap = (tw / 2) + 5;
                        const lineLen = Math.hypot(x2 - x1, y2 - y1);

                        if (lineLen > halfGap * 2 + 6) {
                            const ux = (x2 - x1) / lineLen;
                            const uy = (y2 - y1) / lineLen;
                            ctx.beginPath();
                            ctx.moveTo(x1, y1);
                            ctx.lineTo(midX - ux * halfGap, midY - uy * halfGap);
                            ctx.moveTo(midX + ux * halfGap, midY + uy * halfGap);
                            ctx.lineTo(x2, y2);
                            ctx.stroke();
                        } else {
                            ctx.beginPath();
                            ctx.moveTo(x1, y1);
                            ctx.lineTo(x2, y2);
                            ctx.stroke();
                        }

                        // Subtle black text without background centered in middle of line
                        ctx.fillStyle = '#000000';
                        ctx.textAlign = 'center';
                        ctx.textBaseline = 'middle';
                        ctx.fillText(labelText, midX, midY);
                        ctx.restore();
                    }
                });
            }

            // Dotted horizontal projection lines removed per user request: "no dotted lines on chart they are unnecessary"

            // =====================================================================
            // 2.5. HTF TAP LABELS (Label taps on HTF chart)
            // =====================================================================
            const rawLabels = (currentStrategy && Array.isArray(currentStrategy.labels)) ? currentStrategy.labels : [];
            const tapLabelsToRender = rawLabels.filter(lbl => {
                const lblTime = lbl.x || lbl.time;
                if (window.isSimulationReplayActive && lblTime && lblTime > maxVisibleTime) return false;
                const txt = (lbl.text || '').toLowerCase();
                return txt.includes('tap');
            });

            if (Array.isArray(tapLabelsToRender)) {
                tapLabelsToRender.forEach(lbl => {
                    const lx = timeToCoord(chart, currentCandles, lbl.x || lbl.time);
                    const ly = candlestickSeries.priceToCoordinate(lbl.y !== undefined ? lbl.y : lbl.price);

                    if (lx !== null && ly !== null) {
                        if (lx < -60 || lx > width + 60) return;

                        ctx.save();
                        let text = (lbl.text || 'Tap').trim();
                        text = text.replace(/\[|\]/g, '')
                                   .replace(/\b(demand|supply)\s*(zone)?\b/gi, '')
                                   .replace(/\bzone\b/gi, '')
                                   .replace(/^(tapped|new)\s*:\s*/gi, '')
                                   .trim();

                        const isBull = (lbl.color === '#26a69a' || lbl.position === 'above' || lbl.style === 'label_up');
                        const pillBg = isBull ? 'rgba(38, 166, 154, 0.20)' : 'rgba(239, 83, 80, 0.20)';
                        const pillBorder = isBull ? '#26a69a' : '#ef5350';

                        ctx.font = '300 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
                        const tw = ctx.measureText(text).width;
                        const padX = 5;
                        const boxW = tw + padX * 2;
                        const boxH = 14;

                        let boxX = lx - boxW / 2;
                        let boxY = (lbl.position === 'above' || lbl.style === 'label_up') ? (ly - boxH - 4) : (ly + 4);

                        // 1px solid border, subtle transparent fill
                        ctx.fillStyle = pillBg;
                        ctx.strokeStyle = pillBorder;
                        ctx.lineWidth = 1;
                        ctx.setLineDash([]);
                        ctx.fillRect(boxX, boxY, boxW, boxH);
                        ctx.strokeRect(boxX, boxY, boxW, boxH);

                        // Clean black 300 9px font
                        ctx.fillStyle = '#000000';
                        ctx.textAlign = 'center';
                        ctx.textBaseline = 'middle';
                        ctx.fillText(text, lx, boxY + boxH / 2);
                        ctx.restore();
                    }
                });
            }

            // =====================================================================
            // 2.8. HTF Algo Trade Badges on Chart
            // =====================================================================
            if (Array.isArray(allTimeframeSignals) && allTimeframeSignals.length > 0) {
                allTimeframeSignals.forEach(sig => {
                    const st = sig.chart_time || sig.time;
                    const sx = timeToCoord(chart, currentCandles, st);
                    const sp = Number(sig.entry || sig.entry_price || sig.price || 0);
                    const sy = candlestickSeries.priceToCoordinate(sp);
                    if (sx !== null && sy !== null && sx >= -50 && sx <= width + 50) {
                        const isBuy = (sig.type === 'BUY' || sig.action === 'BUY' || sig.side === 'BUY');
                        const outText = sig.outcome ? ` [${sig.outcome}]` : '';
                        const tagText = `${isBuy ? '▲ BUY' : '▼ SELL'} ${sig.setup_type || ''} @ $${sp.toLocaleString(undefined, {minimumFractionDigits: 1, maximumFractionDigits: 2})}${outText}`;
                        const tagBg = isBuy ? '#10b981' : '#ef4444';
                        const tagY = isBuy ? (sy + 26) : (sy - 26);
                        drawPill(ctx, sx, tagY, tagText, tagBg, '#ffffff', true);
                    }
                });
            }

            // =====================================================================
            // 3. USER CUSTOM DRAWINGS
            // =====================================================================
            renderUserDrawings(ctx, chart, candlestickSeries, currentCandles, width, height, true);

        } catch (err) {
            console.error("Overlay render exception:", err);
        }
    }

    function drawLTFOverlay() {
        if (!ltfCtx || !ltfChart || !ltfSeries || !isSplitOpen || !splitContainer) return;
        try {
            const dims = getLTFChartDims();
            const ltfWidth = dims.width;
            const ltfHeight = dims.height;
            ltfCtx.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0);
            ltfCtx.clearRect(0, 0, ltfWidth, ltfHeight);

            // 1. Render Tapped HTF Box on LTF (1px solid border, 300 9px black text, clean name only)
            if (Array.isArray(ltfLoadedBoxes) && ltfLoadedBoxes.length > 0) {
                ltfLoadedBoxes.forEach(box => {
                    const bLeft = box.left || box.time1 || box.created_time;
                    const bRight = box.right || box.time2 || box.end_time;
                    const x1 = timeToCoord(ltfChart, ltfCandles, bLeft);
                    const x2 = timeToCoord(ltfChart, ltfCandles, bRight);
                    const y1 = ltfSeries.priceToCoordinate(box.top);
                    const y2 = ltfSeries.priceToCoordinate(box.bottom);

                    if (x1 !== null && x2 !== null && y1 !== null && y2 !== null) {
                        const rectX = Math.min(x1, x2);
                        const rectY = Math.min(y1, y2);
                        const rectW = Math.max(2, Math.abs(x2 - x1));
                        const rectH = Math.max(2, Math.abs(y2 - y1));

                        ltfCtx.save();
                        ltfCtx.fillStyle = box.color || (box.is_bullish ? 'rgba(38, 166, 154, 0.25)' : 'rgba(239, 83, 80, 0.25)');
                        ltfCtx.strokeStyle = box.borderColor || (box.is_bullish ? '#26a69a' : '#ef5350');
                        ltfCtx.lineWidth = 1;
                        ltfCtx.setLineDash([]); // 1px solid, no dotted lines
                        ltfCtx.fillRect(rectX, rectY, rectW, rectH);
                        ltfCtx.strokeRect(rectX, rectY, rectW, rectH);

                        let levelName = (box.text || box.name || '').trim();
                        levelName = levelName.replace(/\[|\]/g, '')
                                             .replace(/\b(demand|supply)\s*(zone)?\b/gi, '')
                                             .replace(/\bzone\b/gi, '')
                                             .replace(/^(tapped|new)\s*:\s*/gi, '')
                                             .trim();

                        if (levelName && rectW > 18) {
                            ltfCtx.fillStyle = '#000000';
                            ltfCtx.font = '300 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
                            ltfCtx.textAlign = 'left';
                            ltfCtx.textBaseline = 'top';
                            ltfCtx.fillText(levelName, rectX + 5, rectY + 4);
                        }
                        ltfCtx.restore();
                    }
                });
            }

            // 2. Render Approach BOS & CHoCH Structure (TradingView centered horizontal & vertical with gap)
            if (Array.isArray(ltfLoadedLines) && ltfLoadedLines.length > 0) {
                ltfLoadedLines.forEach(line => {
                    const lX1 = line.x1 || line.time1;
                    const lX2 = line.x2 || line.time2;
                    const lY1 = line.y1 !== undefined ? line.y1 : line.price1;
                    const lY2 = line.y2 !== undefined ? line.y2 : line.price2;

                    const x1 = timeToCoord(ltfChart, ltfCandles, lX1);
                    const x2 = timeToCoord(ltfChart, ltfCandles, lX2);
                    const y1 = ltfSeries.priceToCoordinate(lY1);
                    const y2 = ltfSeries.priceToCoordinate(lY2);

                    if (x1 !== null && x2 !== null && y1 !== null && y2 !== null) {
                        const rawType = (line.type || line.label || 'BOS').trim();
                        let strokeColor = line.color || '#ff9800';
                        let lineWidth = 1.5;

                        if (rawType.includes('Triple')) {
                            strokeColor = '#a855f7';
                            lineWidth = 2;
                        } else if (rawType.includes('Dual')) {
                            strokeColor = '#f59e0b';
                            lineWidth = 1.5;
                        } else if (rawType.includes('CHoCH')) {
                            strokeColor = line.direction === 'bullish' ? '#10b981' : '#ef4444';
                            lineWidth = 1.5;
                        } else if (rawType.includes('BOS')) {
                            strokeColor = line.direction === 'bullish' ? '#26a69a' : '#ef5350';
                            lineWidth = 1.5;
                        }

                        ltfCtx.save();
                        ltfCtx.strokeStyle = strokeColor;
                        ltfCtx.lineWidth = lineWidth;
                        ltfCtx.setLineDash([]); // solid lines, no dotted lines

                        const midX = (x1 + x2) / 2;
                        const midY = (y1 + y2) / 2;
                        const labelText = rawType;

                        // TradingView style: clean gap in line, centered horizontally & vertically
                        ltfCtx.font = '300 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
                        const tw = ltfCtx.measureText(labelText).width;
                        const halfGap = (tw / 2) + 5;
                        const lineLen = Math.hypot(x2 - x1, y2 - y1);

                        if (lineLen > halfGap * 2 + 6) {
                            const ux = (x2 - x1) / lineLen;
                            const uy = (y2 - y1) / lineLen;
                            ltfCtx.beginPath();
                            ltfCtx.moveTo(x1, y1);
                            ltfCtx.lineTo(midX - ux * halfGap, midY - uy * halfGap);
                            ltfCtx.moveTo(midX + ux * halfGap, midY + uy * halfGap);
                            ltfCtx.lineTo(x2, y2);
                            ltfCtx.stroke();
                        } else {
                            ltfCtx.beginPath();
                            ltfCtx.moveTo(x1, y1);
                            ltfCtx.lineTo(x2, y2);
                            ltfCtx.stroke();
                        }

                        ltfCtx.fillStyle = '#000000';
                        ltfCtx.textAlign = 'center';
                        ltfCtx.textBaseline = 'middle';
                        ltfCtx.fillText(labelText, midX, midY);
                        ltfCtx.restore();
                    }
                });
            }

            // 3. Render 5-Wave internal structure labels (W1..W5) on LTF if present
            if (Array.isArray(ltfLoadedLabels) && ltfLoadedLabels.length > 0) {
                ltfLoadedLabels.forEach(lbl => {
                    const lx = timeToCoord(ltfChart, ltfCandles, lbl.x);
                    const ly = ltfSeries.priceToCoordinate(lbl.y);
                    if (lx !== null && ly !== null) {
                        ltfCtx.save();
                        ltfCtx.font = '300 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
                        ltfCtx.fillStyle = '#000000';
                        ltfCtx.textAlign = 'center';
                        ltfCtx.textBaseline = 'bottom';
                        ltfCtx.fillText(lbl.text || '', lx, ly - 3);
                        ltfCtx.restore();
                    }
                });
            }

            // =====================================================================
            // 3.5. Render Bot Trades (SL, TP, Entry Lines & Shaded Risk/Reward Boxes)
            // =====================================================================
            const tradesToRender = [];
            if (window.currentLTFTrade && (window.currentLTFTrade.entry_price || window.currentLTFTrade.entry)) {
                tradesToRender.push(window.currentLTFTrade);
            }
            if (Array.isArray(allTimeframeSignals)) {
                allTimeframeSignals.forEach(sig => {
                    const sId = sig.id;
                    const sTime = sig.entry_time || sig.time;
                    if (!tradesToRender.some(t => (t.id && t.id === sId) || ((t.entry_time || t.time) === sTime))) {
                        tradesToRender.push(sig);
                    }
                });
            }

            tradesToRender.forEach(tr => {
                const entryP = Number(tr.entry_price || tr.entry || 0);
                const slP = Number(tr.sl_price || tr.sl || 0);
                const tpP = Number(tr.tp_price || tr.tp || 0);
                if (!entryP || !slP || !tpP) return;

                const isBuy = (tr.action === 'BUY' || tr.type === 'BUY' || tr.side === 'BUY');
                const entryT = tr.entry_time || tr.time;
                const exitT = tr.exit_time;

                let startX = timeToCoord(ltfChart, ltfCandles, entryT);
                if (startX === null) {
                    if (ltfCandles.length > 0 && entryT < ltfCandles[0].time && (!exitT || exitT >= ltfCandles[0].time)) {
                        startX = 10;
                    } else {
                        return;
                    }
                }

                let endX = exitT ? timeToCoord(ltfChart, ltfCandles, exitT) : null;
                if (endX === null || endX <= startX) {
                    endX = Math.min(ltfWidth - 75, Math.max(startX + 160, ltfWidth * 0.75));
                }
                const boxW = Math.max(60, endX - startX);

                const entryY = ltfSeries.priceToCoordinate(entryP);
                const slY = ltfSeries.priceToCoordinate(slP);
                const tpY = ltfSeries.priceToCoordinate(tpP);

                if (entryY === null || slY === null || tpY === null) return;

                ltfCtx.save();

                // 1. Shaded TP Box (Green)
                const tpBoxY = Math.min(entryY, tpY);
                const tpBoxH = Math.max(2, Math.abs(entryY - tpY));
                ltfCtx.fillStyle = 'rgba(16, 185, 129, 0.14)';
                ltfCtx.fillRect(startX, tpBoxY, boxW, tpBoxH);
                ltfCtx.strokeStyle = 'rgba(16, 185, 129, 0.4)';
                ltfCtx.lineWidth = 1;
                ltfCtx.strokeRect(startX, tpBoxY, boxW, tpBoxH);

                // 2. Shaded SL Box (Red)
                const slBoxY = Math.min(entryY, slY);
                const slBoxH = Math.max(2, Math.abs(entryY - slY));
                ltfCtx.fillStyle = 'rgba(239, 68, 68, 0.14)';
                ltfCtx.fillRect(startX, slBoxY, boxW, slBoxH);
                ltfCtx.strokeStyle = 'rgba(239, 68, 68, 0.4)';
                ltfCtx.lineWidth = 1;
                ltfCtx.strokeRect(startX, slBoxY, boxW, slBoxH);

                // 3. Entry Line (Blue solid)
                ltfCtx.beginPath();
                ltfCtx.moveTo(startX, entryY);
                ltfCtx.lineTo(startX + boxW, entryY);
                ltfCtx.strokeStyle = '#3b82f6';
                ltfCtx.lineWidth = 2;
                ltfCtx.setLineDash([]);
                ltfCtx.stroke();

                // 4. SL Line (Red solid)
                ltfCtx.beginPath();
                ltfCtx.moveTo(startX, slY);
                ltfCtx.lineTo(startX + boxW, slY);
                ltfCtx.strokeStyle = '#ef4444';
                ltfCtx.lineWidth = 2;
                ltfCtx.stroke();

                // 5. TP Line (Green solid)
                ltfCtx.beginPath();
                ltfCtx.moveTo(startX, tpY);
                ltfCtx.lineTo(startX + boxW, tpY);
                ltfCtx.strokeStyle = '#10b981';
                ltfCtx.lineWidth = 2;
                ltfCtx.stroke();

                // 6. Professional Badges on Right Side of Box
                drawPill(ltfCtx, startX + boxW + 4, entryY, `ENTRY: $${entryP.toLocaleString(undefined, {minimumFractionDigits: 1, maximumFractionDigits: 2})}`, '#2563eb', '#ffffff', false);
                drawPill(ltfCtx, startX + boxW + 4, slY, `SL: $${slP.toLocaleString(undefined, {minimumFractionDigits: 1, maximumFractionDigits: 2})} (-1.0R)`, '#dc2626', '#ffffff', false);
                drawPill(ltfCtx, startX + boxW + 4, tpY, `TP: $${tpP.toLocaleString(undefined, {minimumFractionDigits: 1, maximumFractionDigits: 2})} (+${tr.rr || 3.0}R)`, '#059669', '#ffffff', false);

                // 7. Trade Position Title Badge
                const titleText = `${tr.action || tr.type} ${tr.setup_type || ''} (${tr.pattern || tr.pattern_name || ''}) ${tr.outcome ? `[${tr.outcome} ${tr.pnl_r !== undefined ? ((tr.pnl_r >= 0 ? '+' : '') + tr.pnl_r + 'R') : ''}]` : ''}`;
                const titleBg = isBuy ? '#10b981' : '#ef4444';
                drawPill(ltfCtx, startX + 10, tpBoxY + 12, titleText, titleBg, '#ffffff', false);

                ltfCtx.restore();
            });

            // 4. User manual drawings if drawn via toolbar
            renderUserDrawings(ltfCtx, ltfChart, ltfSeries, ltfCandles, ltfWidth, ltfHeight, false);
        } catch (err) {
            console.error("LTF Overlay render exception:", err);
        }
    }

    function redrawAll() {
        drawOverlay();
        drawLTFOverlay();
    }

    // =========================================================================
    // FLOATING PROPERTY TOOLBAR CONTROLS
    // =========================================================================
    function showFloatingBar(drawing) {
        if (!drawing || !propFloatingBar) return;
        propFloatingBar.style.display = 'flex';

        if (propColorDots) {
            propColorDots.forEach(dot => {
                if (dot.getAttribute('data-color') === drawing.color) {
                    dot.classList.add('active');
                } else {
                    dot.classList.remove('active');
                }
            });
        }

        if (propBgGroup) {
            propBgGroup.style.display = (drawing.type === 'box') ? 'flex' : 'none';
        }
        if (propBgOpacity) {
            propBgOpacity.value = String(drawing.bgOpacity !== undefined ? drawing.bgOpacity : 0.25);
        }
        if (propLineWidth) {
            propLineWidth.value = String(drawing.lineWidth || 1.5);
        }
        if (propLineStyle) {
            propLineStyle.value = drawing.lineStyle || 'solid';
        }
        if (propTextInput) {
            propTextInput.value = drawing.text || '';
        }
    }

    function hideFloatingBar() {
        if (propFloatingBar) {
            propFloatingBar.style.display = 'none';
        }
    }

    if (propColorDots) {
        propColorDots.forEach(dot => {
            dot.addEventListener('click', () => {
                const color = dot.getAttribute('data-color');
                activeColor = color;
                propColorDots.forEach(d => d.classList.remove('active'));
                dot.classList.add('active');

                if (selectedDrawing) {
                    selectedDrawing.color = color;
                    saveDrawings();
                    redrawAll();
                }
            });
        });
    }

    if (propBgOpacity) {
        propBgOpacity.addEventListener('change', (e) => {
            const op = parseFloat(e.target.value);
            activeBgOpacity = op;
            if (selectedDrawing) {
                selectedDrawing.bgOpacity = op;
                saveDrawings();
                redrawAll();
            }
        });
    }

    if (propLineWidth) {
        propLineWidth.addEventListener('change', (e) => {
            const lw = parseFloat(e.target.value);
            activeLineWidth = lw;
            if (selectedDrawing) {
                selectedDrawing.lineWidth = lw;
                saveDrawings();
                redrawAll();
            }
        });
    }

    if (propLineStyle) {
        propLineStyle.addEventListener('change', (e) => {
            const ls = e.target.value;
            activeLineStyle = ls;
            if (selectedDrawing) {
                selectedDrawing.lineStyle = ls;
                saveDrawings();
                redrawAll();
            }
        });
    }

    if (propTextInput) {
        propTextInput.addEventListener('input', (e) => {
            if (selectedDrawing) {
                selectedDrawing.text = e.target.value;
                saveDrawings();
                redrawAll();
            }
        });
    }

    if (propDeleteBtn) {
        propDeleteBtn.addEventListener('click', () => {
            if (selectedDrawing) {
                userDrawings = userDrawings.filter(d => d.id !== selectedDrawing.id);
                selectedDrawing = null;
                hideFloatingBar();
                saveDrawings();
                redrawAll();
            }
        });
    }

    if (propCloseBtn) {
        propCloseBtn.addEventListener('click', () => {
            selectedDrawing = null;
            hideFloatingBar();
            redrawAll();
        });
    }

    // =========================================================================
    // SIDEBAR TOOLBAR CONTROLS
    // =========================================================================
    function setTool(toolName) {
        activeTool = toolName;
        [toolCursor, toolBox, toolTrendline].forEach(btn => {
            if (btn) btn.classList.remove('active');
        });
        if (toolName === 'cursor' && toolCursor) toolCursor.classList.add('active');
        if (toolName === 'box' && toolBox) toolBox.classList.add('active');
        if (toolName === 'trendline' && toolTrendline) toolTrendline.classList.add('active');

        if (activeTool !== 'cursor') {
            canvas.style.pointerEvents = 'auto';
            canvas.style.cursor = 'crosshair';
            if (ltfCanvas) {
                ltfCanvas.style.pointerEvents = 'auto';
                ltfCanvas.style.cursor = 'crosshair';
            }
        } else {
            canvas.style.cursor = 'default';
            if (ltfCanvas) ltfCanvas.style.cursor = 'default';
        }
    }

    if (toolCursor) toolCursor.addEventListener('click', () => setTool('cursor'));
    if (toolBox) toolBox.addEventListener('click', () => setTool('box'));
    if (toolTrendline) toolTrendline.addEventListener('click', () => setTool('trendline'));

    if (toolClearAll) {
        toolClearAll.addEventListener('click', () => {
            if (confirm('Clear all drawings on chart?')) {
                userDrawings = [];
                selectedDrawing = null;
                hideFloatingBar();
                saveDrawings();
                redrawAll();
            }
        });
    }

    // Keyboard Shortcuts
    window.addEventListener('keydown', (e) => {
        if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT')) {
            if (e.key === 'Escape') e.target.blur();
            return;
        }

        if (e.key === 'Delete' || e.key === 'Backspace') {
            if (selectedDrawing) {
                userDrawings = userDrawings.filter(d => d.id !== selectedDrawing.id);
                selectedDrawing = null;
                hideFloatingBar();
                saveDrawings();
                redrawAll();
            }
        } else if (e.key === 'v' || e.key === 'V') {
            setTool('cursor');
        } else if (e.key === 'b' || e.key === 'B') {
            setTool('box');
        } else if (e.key === 't' || e.key === 'T') {
            setTool('trendline');
        } else if (e.key === 'Escape') {
            if (isDrawing) {
                isDrawing = false;
                activeDrawingDraft = null;
                setTool('cursor');
            } else if (selectedDrawing) {
                selectedDrawing = null;
                hideFloatingBar();
            }
            redrawAll();
        }
    });

    // =========================================================================
    // CHART MOUSE INTERACTION SYSTEM (FOR BOTH HTF & LTF)
    // =========================================================================
    function setupDrawingInteractions(chartEl, canvasEl, chartObj, getSeries, getCandles, isHTF) {
        if (!chartEl || !canvasEl) return;

        function getMouseDataCoord(e) {
            const rect = canvasEl.getBoundingClientRect();
            const mx = e.clientX - rect.left;
            const my = e.clientY - rect.top;
            const series = getSeries();
            const candles = getCandles();
            const t = coordToTime(chartObj, candles, mx);
            const p = series ? series.coordinateToPrice(my) : null;
            return { mx, my, t, p };
        }

        function handleMouseMove(e) {
            const { mx, my, t, p } = getMouseDataCoord(e);
            if (t === null || p === null) return;

            // Live preview while drawing
            if (isDrawing && activeDrawingDraft && ((isHTF && activeChartSource === 'htf') || (!isHTF && activeChartSource === 'ltf'))) {
                activeDrawingDraft.t2 = t;
                activeDrawingDraft.p2 = p;
                redrawAll();
                return;
            }

            // Dragging handle or moving drawing
            if (activeDrag && activeDrag.drawing) {
                const dt = t - activeDrag.startT;
                const dp = p - activeDrag.startP;

                if (activeDrag.handle === null) {
                    activeDrag.drawing.t1 = activeDrag.origT1 + dt;
                    activeDrag.drawing.t2 = activeDrag.origT2 + dt;
                    activeDrag.drawing.p1 = activeDrag.origP1 + dp;
                    activeDrag.drawing.p2 = activeDrag.origP2 + dp;
                } else if (activeDrag.handle === 'p1') {
                    activeDrag.drawing.t1 = t;
                    activeDrag.drawing.p1 = p;
                } else if (activeDrag.handle === 'p2') {
                    activeDrag.drawing.t2 = t;
                    activeDrag.drawing.p2 = p;
                } else if (activeDrag.handle === 'p3') {
                    activeDrag.drawing.t1 = t;
                    activeDrag.drawing.p2 = p;
                } else if (activeDrag.handle === 'p4') {
                    activeDrag.drawing.t2 = t;
                    activeDrag.drawing.p1 = p;
                }
                redrawAll();
                return;
            }

            // Cursor Mode: hit test for hover effects
            if (activeTool === 'cursor') {
                const series = getSeries();
                const candles = getCandles();
                const hit = findDrawingAtCoord(mx, my, chartObj, series, candles);

                let hitSignal = null;
                if (isHTF) {
                    for (const hb of mainChartSignalHitboxes) {
                        if (mx >= hb.x && mx <= hb.x + hb.width && my >= hb.y && my <= hb.y + hb.height) {
                            hitSignal = hb.sig;
                            break;
                        }
                    }
                }

                if (hit) {
                    canvasEl.style.pointerEvents = 'auto';
                    if (hit.handle) {
                        canvasEl.style.cursor = 'crosshair';
                    } else {
                        canvasEl.style.cursor = 'move';
                    }
                } else if (hitSignal) {
                    canvasEl.style.pointerEvents = 'auto';
                    canvasEl.style.cursor = 'pointer';
                    if (hoveredSignal !== hitSignal) {
                        hoveredSignal = hitSignal;
                        drawOverlay();
                    }
                } else {
                    if (hoveredSignal) {
                        hoveredSignal = null;
                        drawOverlay();
                    }
                    if (!activeDrag) {
                        canvasEl.style.pointerEvents = 'none';
                        canvasEl.style.cursor = 'default';
                    }
                }
            }
        }

        function handleMouseDown(e) {
            if (e.button !== 0) return;
            const { mx, my, t, p } = getMouseDataCoord(e);
            if (t === null || p === null) return;

            if (activeTool === 'box' || activeTool === 'trendline') {
                e.preventDefault();
                e.stopPropagation();

                if (!isDrawing) {
                    isDrawing = true;
                    activeChartSource = isHTF ? 'htf' : 'ltf';
                    activeDrawingDraft = {
                        id: 'draw_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5),
                        type: activeTool,
                        t1: t,
                        p1: p,
                        t2: t,
                        p2: p,
                        color: activeColor,
                        bgOpacity: activeBgOpacity,
                        lineWidth: activeLineWidth,
                        lineStyle: activeLineStyle,
                        text: ''
                    };
                    redrawAll();
                } else {
                    activeDrawingDraft.t2 = t;
                    activeDrawingDraft.p2 = p;
                    userDrawings.push(activeDrawingDraft);
                    selectedDrawing = activeDrawingDraft;
                    activeDrawingDraft = null;
                    isDrawing = false;
                    setTool('cursor');
                    showFloatingBar(selectedDrawing);
                    saveDrawings();
                    redrawAll();
                }
                return;
            }

            if (activeTool === 'cursor') {
                if (isHTF) {
                    for (const hb of mainChartSignalHitboxes) {
                        if (mx >= hb.x && mx <= hb.x + hb.width && my >= hb.y && my <= hb.y + hb.height) {
                            e.preventDefault();
                            e.stopPropagation();
                            openSignalAnalysis(hb.sig);
                            return;
                        }
                    }
                }

                const series = getSeries();
                const candles = getCandles();
                const hit = findDrawingAtCoord(mx, my, chartObj, series, candles);
                if (hit) {
                    e.preventDefault();
                    e.stopPropagation();
                    selectedDrawing = hit.drawing;
                    activeDrag = {
                        drawing: hit.drawing,
                        handle: hit.handle,
                        origT1: hit.drawing.t1,
                        origP1: hit.drawing.p1,
                        origT2: hit.drawing.t2,
                        origP2: hit.drawing.p2,
                        startT: t,
                        startP: p
                    };
                    showFloatingBar(selectedDrawing);
                    redrawAll();
                } else {
                    if (selectedDrawing) {
                        selectedDrawing = null;
                        hideFloatingBar();
                        redrawAll();
                    }
                }
            }
        }

        function handleMouseUp() {
            if (activeDrag) {
                saveDrawings();
                activeDrag = null;
                redrawAll();
            }
        }

        [chartEl, canvasEl].forEach(target => {
            target.addEventListener('mousemove', handleMouseMove);
            target.addEventListener('mousedown', handleMouseDown);
        });
        window.addEventListener('mouseup', handleMouseUp);
    }

    // Attach interactions to HTF chart
    setupDrawingInteractions(container, canvas, chart, () => candlestickSeries, () => currentCandles, true);

    // Connect WebSocket
    function connectWS() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const token = localStorage.getItem('topg_admin_token') || '';
        const wsUrl = `${protocol}//${window.location.host}/ws?token=${encodeURIComponent(token)}`;
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log('Connected to Meyhem Quant Strategy WebSocket server.');
        };

        ws.onmessage = (event) => {
        if (window.isSimulationReplayActive) {
            return; // Simulation replay active: keep replay state on chart
        }
            try {
                const data = JSON.parse(event.data);

                if (data.type === 'snapshot') {
                    if (data.symbol) {
                        activeSymbol = data.symbol.toUpperCase();
                        if (symbolSelect) symbolSelect.value = activeSymbol;
                    }
                    if (data.htf_interval) {
                        activeTimeframe = data.htf_interval.toLowerCase(); window.activeTimeframe = activeTimeframe;
                        tfButtons.forEach(btn => {
                            if (btn.getAttribute('data-tf').toLowerCase() === activeTimeframe) {
                                btn.classList.add('active');
                            } else {
                                btn.classList.remove('active');
                            }
                        });
                    }
                    if (htfTitle) {
                        htfTitle.textContent = `${activeSymbol} | ${activeTimeframe.toUpperCase()}`;
                    }

                    if (data.strategy && Object.keys(data.strategy).length > 0) {
                        currentStrategy = data.strategy; window.currentStrategy = currentStrategy;
                    }

                    if (data.candles && Array.isArray(data.candles) && data.candles.length > 0) {
                        currentCandles = prepareCandles(data.candles);
                    window.currentCandles = currentCandles;
                        if (candlestickSeries) {
                            candlestickSeries.setData(currentCandles);
                            renderAlgoTradeMarkers(currentStrategy ? currentStrategy.signals : []);
                        }
                        if (chart) {
                            const sep23 = currentCandles.find(c => c.time >= 1790121600);
                            if (['15m', '1h', '4h'].includes(activeTimeframe) && sep23) {
                                chart.timeScale().setVisibleRange({
                                    from: sep23.time,
                                    to: currentCandles[currentCandles.length - 1].time
                                });
                            } else {
                                chart.timeScale().fitContent();
                            }
                        }
                        updateLegend(htfOhlcLegend, null, candlestickSeries, currentCandles);
                        setTimeout(redrawAll, 50);
                    }

                } else if (data.type === 'live_update') {
                    const updatedCandle = data.candle;
                    if (updatedCandle) {
                        let found = false;
                        for (let i = 0; i < currentCandles.length; i++) {
                            if (currentCandles[i].time === updatedCandle.time) {
                                currentCandles[i] = updatedCandle;
                                found = true;
                                break;
                            }
                        }
                        if (!found) {
                            currentCandles.push(updatedCandle);
                        }

                        currentCandles = prepareCandles(currentCandles);
                        candlestickSeries.update(updatedCandle);
                        updateLegend(htfOhlcLegend, null, candlestickSeries, currentCandles);
                    }

                    currentStrategy = data.strategy; window.currentStrategy = currentStrategy;
                    renderAlgoTradeMarkers(currentStrategy ? currentStrategy.signals : []);
                    redrawAll();
                }
            } catch (err) {
                console.error("Error processing WebSocket message:", err);
            }
        };

        ws.onclose = (e) => {
            if (e.code === 1008) {
                fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username: 'mahum', password: 'A1sdf234?', role: 'admin' })
                }).then(r => r.json()).then(d => {
                    if (d.token) {
                        localStorage.setItem('topg_admin_token', d.token);
                    }
                }).catch(() => {});
            }
            console.log('WebSocket closed. Reconnecting in 2s...');
            setTimeout(connectWS, 2000);
        };
    }

    async function loadInitialChartData() {
        try {
            const token = localStorage.getItem('topg_admin_token') || '';
            const res = await fetch(`/api/chart_signals?symbol=${activeSymbol}&timeframe=${activeTimeframe}&token=${encodeURIComponent(token)}`, {
                headers: token ? { 'Authorization': `Bearer ${token}` } : {}
            });
            if (res.status === 401) {
                const loginRes = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username: 'mahum', password: 'A1sdf234?', role: 'admin' })
                });
                const loginData = await loginRes.json();
                if (loginData.token) {
                    localStorage.setItem('topg_admin_token', loginData.token);
                    return loadInitialChartData();
                }
            }
            if (res.ok) {
                const data = await res.json();
                if (data && data.candles && data.candles.length > 0) {
                    currentCandles = prepareCandles(data.candles);
                    window.currentCandles = currentCandles;
                    window.currentStrategy = currentStrategy = {
                        lines: data.lines || [],
                        labels: data.labels || [],
                        boxes: data.boxes || [],
                        markers: data.markers || [],
                        trend: data.trend || 'Neutral',
                        nearby_levels: data.nearby_levels || [],
                        signals: data.signals || []
                    };
                    if (candlestickSeries) {
                        candlestickSeries.setData(currentCandles);
                        renderAlgoTradeMarkers(currentStrategy.signals);
                    }
                    updateQuickSignalsStrip(currentStrategy.signals);
                    resizeCanvas();
                    if (chart) {
                        const sep23 = currentCandles.find(c => c.time >= 1790121600);
                        if (['15m', '1h', '4h'].includes(activeTimeframe) && sep23) {
                            chart.timeScale().setVisibleRange({
                                from: sep23.time,
                                to: currentCandles[currentCandles.length - 1].time
                            });
                        } else {
                            chart.timeScale().fitContent();
                        }
                    }
                    updateLegend(htfOhlcLegend, null, candlestickSeries, currentCandles);
                    setTimeout(redrawAll, 50);

                    // Load parallel LTF chart simultaneously
                    if (isSplitOpen) {
                        initLTFChartIfNeeded();
                        openSplitLTF(activeSplitTargetTime || 0);
                    }
                }
            }
        } catch (e) {
            console.warn('Initial chart fetch error:', e);
        }
    }

    // Determine initial page (defaults to dual charts view)
    const initialPage = (window.location.hash ? window.location.hash.replace('#', '') : '') || 'charts';
    navigateToPage(initialPage);

    window.addEventListener('hashchange', () => {
        const hashPage = (window.location.hash ? window.location.hash.replace('#', '') : '') || 'overview';
        navigateToPage(hashPage);
    });

    
    // ===================================================================
    // METHOD 2: TRADE REPLAY & DISCREPANCY INSPECTOR LOGIC
    // ===================================================================
    const inspectorModal = document.getElementById('discrepancy-inspector-modal');
    const btnToggleInspector = document.getElementById('btn-toggle-inspector');
    const btnHudInspect = document.getElementById('btn-hud-inspect');
    const btnCloseInspector = document.getElementById('btn-close-inspector');
    const btnRunInspection = document.getElementById('btn-run-inspection');
    const inspectorTimeInput = document.getElementById('inspector-time-input');
    const inspectorSideSelect = document.getElementById('inspector-side-select');
    const inspectorPriceInput = document.getElementById('inspector-price-input');
    const inspectorHtfSelect = document.getElementById('inspector-htf-select');
    const btnInspectSelected = document.getElementById('btn-inspect-selected-candle');

    let isInspectorOpen = false;
    let lastInspectedCandleTime = 0;

    function openTradeInspector(targetTime, side, price, htf) {
        lastInspectedCandleTime = targetTime || 0;
        if (!inspectorModal) return;
        inspectorModal.style.display = 'flex';
        isInspectorOpen = true;

        const effectiveHtf = (htf || activeTimeframe || '15m').toLowerCase();
        if (inspectorHtfSelect) {
            inspectorHtfSelect.value = effectiveHtf;
        }
        if (!inspectorModal) return;
        inspectorModal.style.display = 'flex';
        isInspectorOpen = true;

        const t = targetTime || activeSplitTargetTime || currentHoveredTime || (currentCandles && currentCandles.length > 0 ? currentCandles[currentCandles.length - 1].time : 0);
        if (t && inspectorTimeInput) {
            inspectorTimeInput.value = formatDateTime(t);
        }
        if (side && inspectorSideSelect) {
            inspectorSideSelect.value = side;
        }
        if (price && inspectorPriceInput) {
            inspectorPriceInput.value = price;
        }
        if (t) {
            fetchTradeInspection(t, side, price);
        }
    }

    function closeTradeInspector() {
        if (!inspectorModal) return;
        inspectorModal.style.display = 'none';
        isInspectorOpen = false;
    }

    async function fetchTradeInspection(targetTimeInput, sideInput, priceInput) {
        const subtitle = document.getElementById('inspector-status-subtitle');
        if (subtitle) {
            subtitle.textContent = "Analyzing quantitative structure, HTF zones & LTF race criteria...";
        }
        const heroBannerInit = document.getElementById('inspect-hero-banner');
        const heroBadgeInit = document.getElementById('inspect-hero-badge');
        const heroTitleInit = document.getElementById('inspect-hero-title');
        const heroDescInit = document.getElementById('inspect-hero-desc');
        if (heroBannerInit && heroBadgeInit && heroTitleInit && heroDescInit) {
            heroBannerInit.className = 'inspect-hero-banner trade-not-taken';
            heroBadgeInit.className = 'hero-badge badge-not-taken';
            heroBadgeInit.textContent = '⏳ ANALYZING...';
            heroTitleInit.textContent = 'Analyzing Quantitative Rules...';
            heroDescInit.textContent = 'Evaluating HTF institutional zone touch, LTF approach, and entry race conditions...';
        }

        try {
            const token = localStorage.getItem('topg_admin_token') || localStorage.getItem('topg_token') || '';
            const tParam = encodeURIComponent(targetTimeInput || '');
            const sParam = encodeURIComponent(sideInput && sideInput !== 'AUTO' ? sideInput : '');
            const pParam = encodeURIComponent(priceInput || '');
            const effectiveHtf = (inspectorHtfSelect ? inspectorHtfSelect.value : activeTimeframe) || '15m';
            const url = `/api/inspect_trade?symbol=${activeSymbol}&htf=${effectiveHtf}&target_time=${tParam}&side=${sParam}&price=${pParam}&token=${encodeURIComponent(token)}`;

            const resp = await fetch(url, {
                headers: token ? { 'Authorization': `Bearer ${token}` } : {}
            });
            const data = await resp.json();

            if (!data || !data.success) {
                if (subtitle) subtitle.textContent = `Error: ${data && data.error ? data.error : 'Inspection failed'}`;
                return;
            }

            if (subtitle) {
                subtitle.textContent = `Inspected ${data.symbol} ${data.htf.toUpperCase()} @ ${data.manual_trade.candle_time_str}`;
            }

            // 1. Populate Manual Trade Card
            const man = data.manual_trade;
            const manSideEl = document.getElementById('inspect-manual-side');
            if (manSideEl) {
                manSideEl.textContent = man.side;
                manSideEl.className = `stat-badge ${man.side.toLowerCase()}`;
            }
            const manPriceEl = document.getElementById('inspect-manual-price');
            if (manPriceEl) {
                manPriceEl.textContent = `$${man.entry_price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
            }
            const manTimeEl = document.getElementById('inspect-manual-time');
            if (manTimeEl) {
                manTimeEl.textContent = man.candle_time_str;
            }
            const manPatternEl = document.getElementById('inspect-manual-pattern');
            if (manPatternEl) {
                manPatternEl.textContent = man.candle_pattern;
            }
            const manWicksEl = document.getElementById('inspect-manual-wicks');
            if (manWicksEl) {
                manWicksEl.textContent = `Body: ${man.body_pct}% | Lower: ${man.lower_wick_pct}% | Upper: ${man.upper_wick_pct}%`;
            }
            const manWickDescEl = document.getElementById('inspect-manual-wick-desc');
            if (manWickDescEl) {
                manWickDescEl.textContent = man.wick_description;
            }

            // 2. Populate Algo View Card
            const algo = data.algo_view;
            const algoBadgeEl = document.getElementById('inspect-algo-badge');
            if (algoBadgeEl) {
                if (algo.algo_signal) {
                    algoBadgeEl.textContent = `${algo.algo_signal.type} @ $${algo.algo_signal.entry.toLocaleString('en-US', {minimumFractionDigits: 1})}`;
                    algoBadgeEl.className = `stat-badge ${algo.algo_signal.type.toLowerCase()}`;
                } else if (algo.htf_tapped) {
                    algoBadgeEl.textContent = "ZONE TAPPED";
                    algoBadgeEl.className = "stat-badge no-sig";
                } else {
                    algoBadgeEl.textContent = "NO HTF ZONE";
                    algoBadgeEl.className = "stat-badge no-sig";
                }
            }
            const algoLevelEl = document.getElementById('inspect-algo-level');
            if (algoLevelEl) {
                algoLevelEl.textContent = algo.htf_zone_name || "Mid-Range / Open Air";
            }
            const algoRangeEl = document.getElementById('inspect-algo-range');
            if (algoRangeEl) {
                algoRangeEl.textContent = algo.htf_zone_range || "N/A";
            }
            const algoTapEl = document.getElementById('inspect-algo-htf-tap');
            if (algoTapEl) {
                algoTapEl.textContent = algo.htf_tapped ? `✅ ${algo.htf_zone_type} Tapped` : "❌ No HTF Zone Tapped";
                algoTapEl.className = algo.htf_tapped ? "detail-val text-up" : "detail-val text-down";
            }
            const algoApproachEl = document.getElementById('inspect-algo-approach');
            if (algoApproachEl) {
                algoApproachEl.textContent = algo.approach_status === 'CONFIRMED' ? "✅ Confirmed Opposing" : (algo.approach_status === 'NOT_APPLICABLE' ? "N/A" : "⚠️ Unconfirmed");
            }
            const algoPathwayEl = document.getElementById('inspect-algo-pathway');
            if (algoPathwayEl) {
                algoPathwayEl.textContent = algo.ltf_pathway || "None";
            }
            const algoRetestEl = document.getElementById('inspect-algo-retest');
            if (algoRetestEl) {
                algoRetestEl.textContent = `${algo.retest_level || 'None'} (${algo.retest_status || 'NONE'})`;
            }

            // 3. Populate Hero Decision Banner & Discrepancy Callout
            const verdict = data.discrepancy_verdict;
            const isTaken = verdict && (verdict.is_trade_taken || verdict.category === 'TRADE_MATCHED');
            
            const heroBanner = document.getElementById('inspect-hero-banner');
            const heroBadge = document.getElementById('inspect-hero-badge');
            const heroTitle = document.getElementById('inspect-hero-title');
            const heroDesc = document.getElementById('inspect-hero-desc');
            const leftCardTag = document.getElementById('inspect-left-card-tag');
            const rightCardTag = document.getElementById('inspect-right-card-tag');
            const calloutBox = document.getElementById('inspect-callout-box');
            const calloutIcon = document.getElementById('inspect-callout-icon');
            const calloutTitle = document.getElementById('inspect-callout-title');
            const calloutCat = document.getElementById('inspect-callout-category');
            const calloutExp = document.getElementById('inspect-callout-explanation');
            const checklistContainer = document.getElementById('inspect-checklist');
            const sugTitle = document.querySelector('.suggestion-title');
            const sugText = document.getElementById('inspect-suggestion-text');

            if (heroBanner && heroBadge && heroTitle && heroDesc) {
                if (isTaken) {
                    heroBanner.className = 'inspect-hero-banner trade-taken';
                    heroBadge.className = 'hero-badge badge-taken';
                    heroBadge.textContent = '🟢 TRADE TAKEN BY BOT';
                    heroTitle.textContent = verdict.title || 'Algorithmic Trade Executed Here! 🎯';
                    heroDesc.textContent = verdict.why_algo_skipped || 'The algorithm detected an institutional zone tap, verified LTF structure, and executed a trade.';
                } else if (verdict.category === 'SIDE_MISMATCH') {
                    heroBanner.className = 'inspect-hero-banner trade-not-taken';
                    heroBadge.className = 'hero-badge badge-side-mismatch';
                    heroBadge.textContent = '❌ OPPOSITE BIAS';
                    heroTitle.textContent = verdict.title || 'Directional Bias Inversion';
                    heroDesc.textContent = verdict.why_algo_skipped;
                } else if (verdict.category === 'ONE_TRADE_LIMIT') {
                    heroBanner.className = 'inspect-hero-banner trade-not-taken';
                    heroBadge.className = 'hero-badge badge-1trade-limit';
                    heroBadge.textContent = '🔒 1-TRADE LIMIT';
                    heroTitle.textContent = verdict.title || '1-Trade Limit (Already Traded)';
                    heroDesc.textContent = verdict.why_algo_skipped;
                } else {
                    heroBanner.className = 'inspect-hero-banner trade-not-taken';
                    heroBadge.className = 'hero-badge badge-not-taken';
                    heroBadge.textContent = '⚪ NO TRADE TAKEN BY BOT';
                    heroTitle.textContent = verdict.title || 'Why Algo Did Not Take Trade';
                    heroDesc.textContent = verdict.why_algo_skipped;
                }
            }

            if (leftCardTag) {
                leftCardTag.textContent = isTaken ? '📌 EXECUTED CANDLE' : '📌 CLICKED CANDLE';
            }
            if (rightCardTag) {
                rightCardTag.textContent = isTaken ? '🤖 BOT EXECUTION LOGIC' : '🤖 WHAT THE ALGO SAW';
            }

            if (calloutTitle) {
                calloutTitle.textContent = isTaken ? '🎯 Trade Execution Logic (How Bot Entered)' : '⚠️ Why Algo Did Not Take Trade';
            }
            if (calloutCat) {
                calloutCat.textContent = isTaken ? 'TRADE EXECUTED' : (verdict.category || 'SKIPPED');
                calloutCat.style.background = isTaken ? '#10b981' : (verdict.badge_color || '#f59e0b');
                calloutCat.style.color = '#ffffff';
            }
            if (calloutExp) calloutExp.textContent = verdict.why_algo_skipped;

            if (calloutIcon) {
                if (isTaken) calloutIcon.textContent = '🎯';
                else if (verdict.category === 'SIDE_MISMATCH') calloutIcon.textContent = '❌';
                else if (verdict.category === 'ONE_TRADE_LIMIT') calloutIcon.textContent = '🔒';
                else if (verdict.category === 'NO_HTF_ZONE') calloutIcon.textContent = '⚠️';
                else if (verdict.category === 'RETEST_TIMEOUT') calloutIcon.textContent = '⏰';
                else calloutIcon.textContent = '⚠️';
            }

            if (calloutBox) {
                calloutBox.style.borderColor = isTaken ? '#10b981' : (verdict.badge_color || '#f59e0b');
            }

            // Build Checklist HTML
            if (checklistContainer && Array.isArray(verdict.checklist)) {
                checklistContainer.innerHTML = verdict.checklist.map(item => `
                    <div class="checklist-item ${item.passed ? 'passed' : 'failed'}">
                        <span class="check-icon">${item.passed ? '✅' : '❌'}</span>
                        <span class="checklist-text">${item.criterion}</span>
                        <span class="checklist-detail" title="${item.detail}">${item.detail}</span>
                    </div>
                `).join('');
            }

            // 4. Populate Bot Learning Suggestion
            if (sugTitle) {
                sugTitle.textContent = isTaken ? 'Quantitative Model Verification' : 'How To Teach This Edge To The Bot';
            }
            if (sugText) {
                sugText.innerHTML = verdict.bot_learning_suggestion.replace(/`([^`]+)`/g, '<code>$1</code>');
            }

        } catch (err) {
            console.error("Error in fetchTradeInspection:", err);
            if (subtitle) subtitle.textContent = `Network / fetch error: ${err.message}`;
        }
    }

    // Attach Event Listeners
    if (btnToggleInspector) {
        btnToggleInspector.addEventListener('click', () => {
            if (isInspectorOpen) closeTradeInspector();
            else openTradeInspector();
        });
    }

    if (btnHudInspect) {
        btnHudInspect.addEventListener('click', () => {
            openTradeInspector(activeSplitTargetTime);
        });
    }

    if (btnCloseInspector) {
        btnCloseInspector.addEventListener('click', closeTradeInspector);
    }

    if (inspectorModal) {
        inspectorModal.addEventListener('click', (e) => {
            if (e.target === inspectorModal) closeTradeInspector();
        });
    }

    if (btnRunInspection) {
        btnRunInspection.addEventListener('click', () => {
            const t = inspectorTimeInput ? inspectorTimeInput.value.trim() : '';
            const s = inspectorSideSelect ? inspectorSideSelect.value : 'AUTO';
            const p = inspectorPriceInput ? inspectorPriceInput.value.trim() : '';
            fetchTradeInspection(t, s, p);
        });
    }

    if (btnInspectSelected) {
        btnInspectSelected.addEventListener('click', () => {
            const t = activeSplitTargetTime || currentHoveredTime;
            if (t) {
                if (inspectorTimeInput) inspectorTimeInput.value = formatDateTime(t);
                fetchTradeInspection(t);
            }
        });
    }

    const btnModalOpenLtf = document.getElementById('btn-modal-open-ltf');
    if (btnModalOpenLtf) {
        btnModalOpenLtf.addEventListener('click', () => {
            const t = lastInspectedCandleTime || activeSplitTargetTime || currentHoveredTime;
            if (t) {
                openSplitLTF(t);
                closeTradeInspector();
            }
        });
    }

    const btnModalCloseFooter = document.getElementById('btn-modal-close-footer');
    if (btnModalCloseFooter) {
        btnModalCloseFooter.addEventListener('click', closeTradeInspector);
    }

    if (inspectorHtfSelect) {
        inspectorHtfSelect.addEventListener('change', () => {
            const t = inspectorTimeInput ? inspectorTimeInput.value.trim() : '';
            const s = inspectorSideSelect ? inspectorSideSelect.value : 'AUTO';
            const p = inspectorPriceInput ? inspectorPriceInput.value.trim() : '';
            fetchTradeInspection(t, s, p);
        });
    }

    if (inspectorSideSelect) {
        inspectorSideSelect.addEventListener('change', () => {
            const t = inspectorTimeInput ? inspectorTimeInput.value.trim() : '';
            const s = inspectorSideSelect ? inspectorSideSelect.value : 'AUTO';
            const p = inspectorPriceInput ? inspectorPriceInput.value.trim() : '';
            fetchTradeInspection(t, s, p);
        });
    }

    // Preset Chips Handlers
    document.querySelectorAll('.preset-chip[data-time]').forEach(chip => {
        chip.addEventListener('click', () => {
            const t = chip.getAttribute('data-time');
            const s = chip.getAttribute('data-side') || 'AUTO';
            const htf = chip.getAttribute('data-htf');
            if (htf && htf !== activeTimeframe) {
                const tfBtn = document.querySelector(`.tf-btn[data-tf="${htf}"]`);
                if (tfBtn) tfBtn.click();
            }
            if (inspectorTimeInput) inspectorTimeInput.value = t;
            if (inspectorSideSelect) inspectorSideSelect.value = s;
            fetchTradeInspection(t, s);
        });
    });

    
    // ==============================================================================
    // OCTOBER 2026 M15 SIMULATION & INTERACTIVE ANIMATED BAR REPLAY ENGINE
    // ==============================================================================
    const btnOpenSim = document.getElementById('btn-open-simulation');
    const simModal = document.getElementById('simulation-modal');
    const btnCloseSim = document.getElementById('btn-close-simulation');
    const simTableBody = document.getElementById('sim-table-body');
    const simSearchInput = document.getElementById('sim-search-input');
    const simFilterBtns = document.querySelectorAll('.btn-sim-filter');

    // Dataset Switcher Elements
    const btnDatasetMajor = document.getElementById('btn-dataset-major');
    const btnDatasetAll = document.getElementById('btn-dataset-all');
    const btnLaunchAnimModal = document.getElementById('btn-launch-animation-modal');
    const btnLaunchContinuous = document.getElementById('btn-launch-continuous-replay');
    const btnReplayJumpLtf = document.getElementById('btn-replay-jump-ltf');
    let isContinuousReplayMode = false;
    let savedNormalStrategy = null;

    // Replay Bar Elements
    const replayBar = document.getElementById('simulation-replay-bar');
    const replayStatusText = document.getElementById('replay-status-text');
    const replayPulseDot = document.getElementById('replay-pulse-dot');
    const replayTradeTitle = document.getElementById('replay-trade-title');
    const replayTradeBadge = document.getElementById('replay-trade-badge');
    const replayTradeZone = document.getElementById('replay-trade-zone');
    const btnReplayPrev = document.getElementById('btn-replay-prev-trade');
    const btnReplayStepBack = document.getElementById('btn-replay-step-back');
    const btnReplayPlay = document.getElementById('btn-replay-toggle-play');
    const btnReplayStepFwd = document.getElementById('btn-replay-step-forward');
    const btnReplayNext = document.getElementById('btn-replay-next-trade');
    const replayBarCounter = document.getElementById('replay-bar-counter');
    const btnReplayToggleMode = document.getElementById('btn-replay-toggle-mode');
    const replayModeLabel = document.getElementById('replay-mode-label');
    const replayLivePnl = document.getElementById('replay-live-pnl');
    const btnCloseReplayBar = document.getElementById('btn-close-replay-bar');
    const replaySpeedBtns = document.querySelectorAll('.btn-replay-speed');

    // KPI Elements
    const simKpiTotal = document.getElementById('sim-kpi-total');
    const simKpiReturn = document.getElementById('sim-kpi-return');
    const simKpiRecord = document.getElementById('sim-kpi-record');
    const simKpiAvgWin = document.getElementById('sim-kpi-avg-win');

    // State Variables
    window.isSimulationReplayActive = false;
    let currentSimDatasetMode = 'major'; // 'major' (38 trades) or 'all' (122 trades)
    let simMajorDataset = null;
    let simAllDataset = null;
    let allSimTrades = [];
    let currentSimFilter = 'all';

    // Replay Engine State
    let sim15mCandlesCache = null;
    let replayTradeIndex = 0;
    let replayCandles = [];
    let replayCurrentBarIdx = 0;
    let replayEntryOffset = 0;
    let replayTimer = null;
    let replaySpeedMs = 250;
    let replayEntryLine = null;
    let replaySlLine = null;
    let replayTpLine = null;
    let savedNormalCandles = null;
    let savedNormalSignals = null;

    async function loadSimulationData(mode, forceReload = false) {
        if (!mode) mode = currentSimDatasetMode;
        try {
            if (mode === 'major') {
                if (!simMajorDataset || !simMajorDataset.boxes || simMajorDataset.boxes.length < 50 || forceReload) {
                    const resp = await fetch('/api/simulation_october_major?_t=' + Date.now());
                    simMajorDataset = await resp.json();
                }
                return simMajorDataset;
            } else {
                if (!simAllDataset || !simAllDataset.boxes || simAllDataset.boxes.length < 50 || forceReload) {
                    const resp = await fetch('/api/simulation_october?_t=' + Date.now());
                    simAllDataset = await resp.json();
                }
                return simAllDataset;
            }
        } catch (e) {
            console.error("Error fetching simulation dataset:", e);
            return null;
        }
    }

    async function ensure15mCandlesLoaded() {
        if (sim15mCandlesCache && sim15mCandlesCache.length > 0) return sim15mCandlesCache;
        try {
            const resp = await fetch('/api/simulation_candles?timeframe=15m');
            const data = await resp.json();
            if (data && Array.isArray(data.candles)) {
                sim15mCandlesCache = prepareCandles(data.candles);
                return sim15mCandlesCache;
            }
        } catch (e) {
            console.error("Error loading 15m simulation candles:", e);
        }
        return [];
    }

    async function loadOctoberSimulation(mode) {
        if (!mode) mode = currentSimDatasetMode;
        currentSimDatasetMode = mode;

        if (simTableBody) {
            simTableBody.innerHTML = '<tr><td colspan="11" style="text-align: center; padding: 24px; color: var(--text-secondary);">Loading simulation trades...</td></tr>';
        }

        const data = await loadSimulationData(mode);
        if (data && data.trades) {
            allSimTrades = data.trades;

            // Update KPI cards
            if (simKpiTotal) simKpiTotal.textContent = data.total_trades || allSimTrades.length;
            if (simKpiReturn) simKpiReturn.textContent = `${data.total_net_r > 0 ? '+' : ''}${Number(data.total_net_r).toFixed(2)}R`;
            if (simKpiRecord) simKpiRecord.textContent = `${data.wins} W / ${data.losses} L / ${data.open || 0} Open`;
            if (simKpiAvgWin) {
                const wins = allSimTrades.filter(t => t.outcome === 'TP');
                const avg = wins.length > 0 ? (wins.reduce((a, b) => a + (b.r_pnl || 0), 0) / wins.length).toFixed(2) : '0.00';
                simKpiAvgWin.textContent = `+${avg}R`;
            }

            renderSimulationTable();
        } else {
            if (simTableBody) {
                simTableBody.innerHTML = '<tr><td colspan="11" style="text-align: center; padding: 24px; color: #ef4444;">No simulation trades found.</td></tr>';
            }
        }
    }

    function renderSimulationTable() {
        if (!simTableBody) return;
        const searchQ = (simSearchInput ? simSearchInput.value : '').toLowerCase().trim();

        const filtered = allSimTrades.filter(t => {
            if (currentSimFilter !== 'all' && t.outcome !== currentSimFilter) return false;
            if (searchQ) {
                const rowStr = `${t.trade_num} ${t.date} ${t.side} ${t.htf_zone} ${t.pathway} ${t.pattern} ${t.outcome}`.toLowerCase();
                if (!rowStr.includes(searchQ)) return false;
            }
            return true;
        });

        if (filtered.length === 0) {
            simTableBody.innerHTML = '<tr><td colspan="11" style="text-align: center; padding: 24px; color: var(--text-secondary);">No trades match the selected filter.</td></tr>';
            return;
        }

        simTableBody.innerHTML = filtered.map(t => {
            const sideClass = (t.side || 'BUY').toLowerCase();
            const outcomeBadge = t.outcome === 'TP' 
                ? '<span style="background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid #10b981; padding: 2px 6px; border-radius: 4px; font-weight: 700; font-size: 11px;">TP</span>'
                : (t.outcome === 'SL' 
                    ? '<span style="background: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid #ef4444; padding: 2px 6px; border-radius: 4px; font-weight: 700; font-size: 11px;">SL</span>'
                    : '<span style="background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid #3b82f6; padding: 2px 6px; border-radius: 4px; font-weight: 700; font-size: 11px;">OPEN</span>');
            
            const pnlColor = t.r_pnl > 0 ? '#10b981' : (t.r_pnl < 0 ? '#ef4444' : 'var(--text-secondary)');
            const pnlStr = t.r_pnl > 0 ? `+${t.r_pnl.toFixed(1)}R` : (t.r_pnl < 0 ? `${t.r_pnl.toFixed(1)}R` : '0.0R');
            const tradeIndexInList = allSimTrades.findIndex(x => x.trade_num === t.trade_num);

            return `
                <tr style="border-bottom: 1px solid var(--border-color); font-size: 12px; transition: background 0.15s ease;" onmouseover="this.style.background='var(--bg-subtle)'" onmouseout="this.style.background='transparent'">
                    <td style="padding: 8px 10px; font-weight: 600; color: var(--text-secondary);">${t.trade_num}</td>
                    <td style="padding: 8px 10px; font-family: monospace;">${t.date.replace(' UTC', '')}</td>
                    <td style="padding: 8px 10px;"><span class="badge-side ${sideClass}">${t.side}</span></td>
                    <td style="padding: 8px 10px; font-weight: 500;">${t.htf_zone}</td>
                    <td style="padding: 8px 10px; color: var(--text-secondary); font-size: 11px;">${t.pathway}</td>
                    <td style="padding: 8px 10px;">${t.pattern}</td>
                    <td style="padding: 8px 10px; font-family: monospace; font-weight: 600;">$${Number(t.entry).toFixed(1)}</td>
                    <td style="padding: 8px 10px; font-family: monospace; font-size: 11px; color: var(--text-secondary);">$${Number(t.sl).toFixed(1)} / $${Number(t.tp).toFixed(1)}</td>
                    <td style="padding: 8px 10px;">${outcomeBadge}</td>
                    <td style="padding: 8px 10px; font-weight: 700; color: ${pnlColor}; font-family: monospace;">${pnlStr}</td>
                    <td style="padding: 8px 10px; text-align: center;">
                        <div style="display: inline-flex; gap: 5px; align-items: center; justify-content: center;">
                            <button class="sim-row-replay-btn" onclick="startSingleTradeReplay(${tradeIndexInList >= 0 ? tradeIndexInList : 0})">▶️ Replay</button>
                            <button class="sim-row-action-btn" style="background: rgba(245, 158, 11, 0.2); border: 1px solid #f59e0b; color: #fbbf24; font-weight: 700; cursor: pointer; padding: 3px 8px; border-radius: 4px; font-size: 11px;" onclick="openSimulationTradeLTF(${t.time})" title="Open Split 1M LTF Chart at this trade">⚡ 1M LTF</button>
                            <button class="sim-row-action-btn" onclick="inspectSimulationTrade(${t.time}, '${t.side}', ${t.entry})">🔍 Inspect</button>
                        </div>
                    </td>
                </tr>
            `;
        }).join('');
    }

    // =========================================================================
    // BAR-BY-BAR ANIMATED SIMULATION REPLAY CONTROLLER
    // =========================================================================

    function clearReplayPriceLines() {
        if (!candlestickSeries) return;
        try {
            if (replayEntryLine) { candlestickSeries.removePriceLine(replayEntryLine); replayEntryLine = null; }
            if (replaySlLine) { candlestickSeries.removePriceLine(replaySlLine); replaySlLine = null; }
            if (replayTpLine) { candlestickSeries.removePriceLine(replayTpLine); replayTpLine = null; }
        } catch (e) {
            console.warn("Could not remove price line:", e);
        }
    }

    async function startContinuousMonthReplay() {
        if (simModal) simModal.style.display = 'none';

        const candles15m = await ensure15mCandlesLoaded();
        if (!candles15m || candles15m.length === 0) {
            alert("Simulation candle data is still loading. Please retry in 1-2 seconds.");
            return;
        }

        if (!window.isSimulationReplayActive) {
            savedNormalCandles = currentCandles ? [...currentCandles] : [];
            savedNormalSignals = currentStrategy && currentStrategy.signals ? [...currentStrategy.signals] : [];
        }

        window.isSimulationReplayActive = true;
        isContinuousReplayMode = true;
        if (replayBar) replayBar.style.display = 'flex';

        const dataset = await loadSimulationData('major', true);
        clearReplayPriceLines();
        if (replayTimer) { clearInterval(replayTimer); replayTimer = null; }
        if (btnReplayPlay) btnReplayPlay.innerHTML = '▶️ Play';

        // Find the index of Sep 23 00:00:00 UTC (timestamp 1790121600)
        let sep23Idx = candles15m.findIndex(c => c.time >= 1790121600);
        if (sep23Idx === -1) sep23Idx = Math.min(505, candles15m.length - 1);

        replayCandles = candles15m;
        replayCurrentBarIdx = sep23Idx;
        window.replayCandles = replayCandles;
        window.replayCurrentBarIdx = replayCurrentBarIdx;

        window.currentStrategy = currentStrategy = {
            boxes: (dataset && dataset.boxes) ? [...dataset.boxes] : [],
            lines: (dataset && dataset.lines) ? [...dataset.lines] : [],
            labels: (dataset && dataset.labels) ? [...dataset.labels] : [],
            signals: (dataset && dataset.trades) ? [...dataset.trades] : []
        };

        // Display initial slice: 500 prior lookback candles + Oct 1 first candle
        const initialSlice = replayCandles.slice(0, replayCurrentBarIdx + 1);
        candlestickSeries.setData(initialSlice);
        window.currentCandles = currentCandles = initialSlice;
        if (chart) chart.timeScale().fitContent();
        redrawAll();

        if (replayTradeTitle) replayTradeTitle.textContent = "Oct 1 Month Replay";
        if (replayTradeBadge) {
            replayTradeBadge.textContent = "500 BARS";
            replayTradeBadge.className = "badge-side buy";
        }
        if (replayTradeZone) replayTradeZone.textContent = "HTF Structure Loaded";
        if (replayStatusText) replayStatusText.textContent = "OCT 1 FIRST CANDLE - 500 LOOKBACK BARS LOADED";
        if (replayBarCounter) replayBarCounter.textContent = `Bar ${replayCurrentBarIdx + 1} / ${replayCandles.length}`;
        if (replayLivePnl) replayLivePnl.textContent = "0.00 R";
    }

    // Jump to 1M LTF handler
    if (btnReplayJumpLtf) {
        btnReplayJumpLtf.addEventListener('click', () => {
            if (!replayCandles || replayCurrentBarIdx >= replayCandles.length) return;
            const curCandle = replayCandles[replayCurrentBarIdx];
            if (curCandle) {
                activeTimeframe = '15m';
                if (typeof openSplitLTF === 'function') {
                    openSplitLTF(curCandle.time);
                }
            }
        });
    }

    window.openSimulationTradeLTF = function(targetTime) {
        if (simModal) simModal.style.display = 'none';
        activeTimeframe = '15m';
        if (typeof openSplitLTF === 'function') {
            openSplitLTF(targetTime);
        }
    };

    if (btnLaunchContinuous) {
        btnLaunchContinuous.addEventListener('click', () => {
            startContinuousMonthReplay();
        });
    }

    window.startContinuousMonthReplay = startContinuousMonthReplay;
    window.stepReplay = stepReplay;

    async function startSingleTradeReplay(tradeIdx, mode) {
        if (mode) currentSimDatasetMode = mode;
        isContinuousReplayMode = false;
        if (simModal) simModal.style.display = 'none';

        // Ensure 15m candles are loaded
        const candles15m = await ensure15mCandlesLoaded();
        if (!candles15m || candles15m.length === 0) {
            alert("Simulation candle data is still loading. Please retry in 1-2 seconds.");
            return;
        }

        // Save normal chart candles if not already saved
        if (!window.isSimulationReplayActive) {
            savedNormalCandles = currentCandles ? [...currentCandles] : [];
            savedNormalSignals = currentStrategy && currentStrategy.signals ? [...currentStrategy.signals] : [];
        }

        window.isSimulationReplayActive = true;
        if (replayBar) replayBar.style.display = 'flex';

        // Load dataset if not loaded
        const data = await loadSimulationData(currentSimDatasetMode);
        if (!data || !data.trades || data.trades.length === 0) return;

        replayTradeIndex = Math.max(0, Math.min(tradeIdx, data.trades.length - 1));
        loadTradeIntoReplay(replayTradeIndex);
    }

    function loadTradeIntoReplay(tradeIdx) {
        clearReplayPriceLines();
        if (replayTimer) { clearInterval(replayTimer); replayTimer = null; }
        if (btnReplayPlay) btnReplayPlay.innerHTML = '▶️ Play';

        const trades = (currentSimDatasetMode === 'major' ? (simMajorDataset ? simMajorDataset.trades : []) : (simAllDataset ? simAllDataset.trades : []));
        if (!trades || trades.length === 0) return;

        replayTradeIndex = Math.max(0, Math.min(tradeIdx, trades.length - 1));
        const trade = trades[replayTradeIndex];

        // Update Replay Bar UI
        if (replayTradeTitle) replayTradeTitle.textContent = `Trade #${trade.trade_num} (${replayTradeIndex + 1}/${trades.length})`;
        if (replayTradeBadge) {
            replayTradeBadge.textContent = trade.side;
            replayTradeBadge.className = `badge-side ${(trade.side || 'BUY').toLowerCase()}`;
        }
        if (replayTradeZone) replayTradeZone.textContent = trade.htf_zone;
        if (replayModeLabel) {
            replayModeLabel.textContent = currentSimDatasetMode === 'major' ? 'Major (38)' : 'All (122)';
            replayModeLabel.style.color = currentSimDatasetMode === 'major' ? '#10b981' : '#3b82f6';
        }
        if (replayStatusText) replayStatusText.textContent = 'APPROACHING ZONE';
        if (replayLivePnl) {
            replayLivePnl.textContent = '0.00 R';
            replayLivePnl.style.color = 'var(--text-secondary)';
        }

        // Locate trade in 15M candles
        const candles = sim15mCandlesCache;
        let entryCandleIdx = candles.findIndex(c => Math.abs(c.time - trade.time) < 900);
        if (entryCandleIdx === -1) {
            let minDiff = Infinity;
            candles.forEach((c, idx) => {
                const diff = Math.abs(c.time - trade.time);
                if (diff < minDiff) { minDiff = diff; entryCandleIdx = idx; }
            });
        }

        // Window: 500 candles before entry, plus 25 candles after entry
        const startIdx = Math.max(0, entryCandleIdx - 500);
        const endIdx = Math.min(candles.length - 1, entryCandleIdx + 25);
        replayCandles = candles.slice(startIdx, endIdx + 1);
        replayEntryOffset = entryCandleIdx - startIdx;
        window.replayCandles = replayCandles;

        const dataset = currentSimDatasetMode === 'major' ? simMajorDataset : simAllDataset;
        window.currentStrategy = currentStrategy = {
            boxes: (dataset && dataset.boxes) ? [...dataset.boxes] : [],
            lines: (dataset && dataset.lines) ? [...dataset.lines] : [],
            labels: (dataset && dataset.labels) ? [...dataset.labels] : [],
            signals: (dataset && dataset.trades) ? [...dataset.trades] : []
        };

        // Start bar at 6 candles before entry so the user sees approach & zone tap
        replayCurrentBarIdx = Math.max(1, replayEntryOffset - 6);
        window.replayCurrentBarIdx = replayCurrentBarIdx;
        renderReplaySlice();
        if (chart) chart.timeScale().fitContent();

        // Auto-play the replay
        togglePlayReplay(true);
    }

    function renderReplaySlice() {
        if (!candlestickSeries || !replayCandles || replayCandles.length === 0) return;
        const visibleSlice = replayCandles.slice(0, replayCurrentBarIdx + 1);
        candlestickSeries.setData(visibleSlice);
        window.currentCandles = currentCandles = visibleSlice;
        window.replayCurrentBarIdx = replayCurrentBarIdx;

        if (replayBarCounter) {
            replayBarCounter.textContent = `Bar ${replayCurrentBarIdx + 1} / ${replayCandles.length}`;
        }

        const trades = (currentSimDatasetMode === 'major' ? (simMajorDataset ? simMajorDataset.trades : []) : (simAllDataset ? simAllDataset.trades : []));
        const curCandle = replayCandles[replayCurrentBarIdx];
        const candleDate = curCandle ? new Date(curCandle.time * 1000).toISOString().replace('T', ' ').slice(0, 16) : '';

        // Check if any trade triggers near this candle (or is the active target trade)
        let matchingTrade = trades ? trades.find(t => {
            const tTime = t.time || Math.floor(new Date(t.date).getTime() / 1000);
            return Math.abs(tTime - curCandle.time) < 900;
        }) : null;

        if (!matchingTrade && !isContinuousReplayMode && trades && trades[replayTradeIndex]) {
            const targetTrade = trades[replayTradeIndex];
            if (replayCurrentBarIdx >= replayEntryOffset) {
                matchingTrade = targetTrade;
            }
        }

        // Check active levels status on current candle
        const activeBoxes = (currentStrategy && Array.isArray(currentStrategy.boxes)) ? currentStrategy.boxes : [];
        const tappedBox = activeBoxes.find(b => {
            if (b.left > curCandle.time) return false;
            if (b.right && b.right < curCandle.time) return false;
            return (curCandle.low <= Math.max(b.top, b.bottom) && curCandle.high >= Math.min(b.top, b.bottom));
        });

        const newBox = activeBoxes.find(b => b.left === curCandle.time);

        const hudEl = document.getElementById('replay-ltf-hud');
        const hudTime = document.getElementById('replay-ltf-time');
        const hudBadge = document.getElementById('replay-ltf-badge');
        const s1 = document.getElementById('val-ltf-step1');
        const s2 = document.getElementById('val-ltf-step2');
        const s3 = document.getElementById('val-ltf-step3');
        const s4 = document.getElementById('val-ltf-step4');
        const s5 = document.getElementById('val-ltf-step5');
        const sPnl = document.getElementById('val-ltf-pnl');

        if (matchingTrade && (isContinuousReplayMode || replayCurrentBarIdx >= replayEntryOffset)) {
            if (replayStatusText) replayStatusText.textContent = `⚡ TRADE TRIGGERED: ${matchingTrade.side} ${matchingTrade.pattern} @ ${matchingTrade.htf_zone}`;
            if (replayTradeTitle) replayTradeTitle.textContent = `Trade #${matchingTrade.trade_num || matchingTrade.trade_idx || (replayTradeIndex + 1)}`;
            if (replayTradeZone) replayTradeZone.textContent = matchingTrade.htf_zone;
            if (replayPulseDot) { replayPulseDot.style.background = '#10b981'; replayPulseDot.style.boxShadow = '0 0 12px #10b981'; }
            if (replayLivePnl) {
                replayLivePnl.textContent = `${matchingTrade.r_pnl >= 0 ? '+' : ''}${Number(matchingTrade.r_pnl).toFixed(1)} R (${matchingTrade.outcome})`;
                replayLivePnl.style.color = matchingTrade.r_pnl >= 0 ? '#10b981' : '#ef4444';
            }

            // Draw entry marker
            const entryMarkerTime = (isContinuousReplayMode || !replayEntryOffset) ? curCandle.time : replayCandles[replayEntryOffset].time;
            candlestickSeries.setMarkers([{
                time: entryMarkerTime,
                position: matchingTrade.side === 'BUY' ? 'belowBar' : 'aboveBar',
                color: matchingTrade.side === 'BUY' ? '#10b981' : '#ef4444',
                shape: matchingTrade.side === 'BUY' ? 'arrowUp' : 'arrowDown',
                text: `${matchingTrade.side} ${matchingTrade.pattern} @ $${Number(matchingTrade.entry).toFixed(1)}`
            }]);

            // Draw price lines on entry
            if (!replayEntryLine) {
                try {
                    replayEntryLine = candlestickSeries.createPriceLine({
                        price: matchingTrade.entry,
                        color: '#3b82f6',
                        lineWidth: 2,
                        lineStyle: 0,
                        axisLabelVisible: true,
                        title: `ENTRY: $${Number(matchingTrade.entry).toFixed(1)}`
                    });
                    replaySlLine = candlestickSeries.createPriceLine({
                        price: matchingTrade.sl,
                        color: '#ef4444',
                        lineWidth: 1,
                        lineStyle: 2,
                        axisLabelVisible: true,
                        title: `SL: $${Number(matchingTrade.sl).toFixed(1)}`
                    });
                    replayTpLine = candlestickSeries.createPriceLine({
                        price: matchingTrade.tp,
                        color: '#10b981',
                        lineWidth: 1,
                        lineStyle: 2,
                        axisLabelVisible: true,
                        title: `TP: $${Number(matchingTrade.tp).toFixed(1)}`
                    });
                } catch (e) {}
            }

            // Update and show floating LTF logic HUD
            if (hudEl) hudEl.style.display = 'block';
            if (hudTime) hudTime.textContent = `${candleDate} UTC`;
            if (hudBadge) {
                hudBadge.textContent = `${matchingTrade.side} ${matchingTrade.outcome}`;
                hudBadge.style.color = matchingTrade.outcome === 'TP' ? '#10b981' : (matchingTrade.outcome === 'SL' ? '#ef4444' : '#38bdf8');
            }
            const ltfInfo = matchingTrade.ltf_logic || {};
            if (s1) s1.textContent = ltfInfo.step1_htf_zone || matchingTrade.htf_zone;
            if (s2) s2.textContent = ltfInfo.step2_approach || 'Bearish/Bullish BOS approach confirmed';
            if (s3) s3.textContent = ltfInfo.step3_choch || `${matchingTrade.side === 'BUY' ? 'Bullish' : 'Bearish'} CHoCH confirmed post-tap`;
            if (s4) s4.textContent = ltfInfo.step4_retest_pattern || `${matchingTrade.pattern} @ ${matchingTrade.retest_level}`;
            if (s5) s5.textContent = ltfInfo.step5_execution || `${matchingTrade.side} MARKET @ $${Number(matchingTrade.entry).toFixed(1)} | SL: $${Number(matchingTrade.sl).toFixed(1)} | TP: $${Number(matchingTrade.tp).toFixed(1)}`;
            if (sPnl) {
                sPnl.textContent = `${matchingTrade.r_pnl >= 0 ? '+' : ''}${Number(matchingTrade.r_pnl).toFixed(1)}R`;
                sPnl.style.color = matchingTrade.r_pnl >= 0 ? '#10b981' : '#ef4444';
            }
        } else if (tappedBox) {
            clearReplayPriceLines();
            const bName = tappedBox.text || tappedBox.name || 'Level';
            const bType = tappedBox.is_bullish ? 'Demand' : 'Supply';
            if (replayStatusText) replayStatusText.textContent = `🎯 LEVEL TAPPED: ${bType} [${bName}] ($${Number(tappedBox.bottom).toFixed(0)} - $${Number(tappedBox.top).toFixed(0)})`;
            if (replayPulseDot) { replayPulseDot.style.background = '#f59e0b'; replayPulseDot.style.boxShadow = '0 0 12px #f59e0b'; }
            if (hudEl) hudEl.style.display = 'block';
            if (hudTime) hudTime.textContent = `${candleDate} UTC`;
            if (hudBadge) { hudBadge.textContent = 'ZONE TAPPED'; hudBadge.style.color = '#f59e0b'; }
            if (s1) s1.textContent = `Tapped ${bType} [${bName}] ($${Number(tappedBox.bottom).toFixed(0)} - $${Number(tappedBox.top).toFixed(0)})`;
            if (s2) s2.textContent = '30-candle LTF approach verified';
            if (s3) s3.textContent = 'Awaiting 1st micro CHoCH confirmation on 1M...';
            if (s4) s4.textContent = 'Scanning for Engulfing / Star retest pattern...';
            if (s5) s5.textContent = 'Order pending confirmation';
            if (sPnl) sPnl.textContent = '--';
        } else if (newBox) {
            clearReplayPriceLines();
            const bName = newBox.text || newBox.name || 'Level';
            const bType = newBox.is_bullish ? 'Demand' : 'Supply';
            if (replayStatusText) replayStatusText.textContent = `🆕 NEW LEVEL FORMED: ${bType} [${bName}] ($${Number(newBox.bottom).toFixed(0)} - $${Number(newBox.top).toFixed(0)})`;
            if (replayPulseDot) { replayPulseDot.style.background = '#3b82f6'; replayPulseDot.style.boxShadow = '0 0 10px #3b82f6'; }
        } else {
            clearReplayPriceLines();
            if (replayStatusText) replayStatusText.textContent = `${candleDate} UTC - Scanning 9 HTF Levels & Structure`;
            if (replayPulseDot) { replayPulseDot.style.background = 'var(--text-secondary)'; replayPulseDot.style.boxShadow = 'none'; }
            if (hudEl && hudEl.style.display !== 'none') {
                if (hudTime) hudTime.textContent = `${candleDate} UTC`;
                if (hudBadge) { hudBadge.textContent = 'SCANNING'; hudBadge.style.color = '#38bdf8'; }
                if (s1) s1.textContent = 'Monitoring 30 active institutional levels';
                if (s2) s2.textContent = 'Awaiting BOS approach into fresh supply/demand';
                if (s3) s3.textContent = 'No CHoCH triggered';
                if (s4) s4.textContent = 'Awaiting pattern confirmation';
                if (s5) s5.textContent = 'No active order';
                if (sPnl) sPnl.textContent = '--';
            }
        }

        redrawAll();
        return;
    }

    function unusedLegacyReplay() {

        // Check Phase
        if (replayCurrentBarIdx < replayEntryOffset - 1) {
            if (replayStatusText) replayStatusText.textContent = `APPROACHING ZONE (${trade.htf_zone})`;
            if (replayPulseDot) { replayPulseDot.style.background = '#3b82f6'; replayPulseDot.style.boxShadow = '0 0 8px #3b82f6'; }
            if (replayLivePnl) { replayLivePnl.textContent = '0.00 R'; replayLivePnl.style.color = 'var(--text-secondary)'; }
            clearReplayPriceLines();
        } else if (replayCurrentBarIdx === replayEntryOffset - 1) {
            if (replayStatusText) replayStatusText.textContent = `ZONE TAPPED! M1 CHOCH CONFIRMATION...`;
            if (replayPulseDot) { replayPulseDot.style.background = '#f59e0b'; replayPulseDot.style.boxShadow = '0 0 10px #f59e0b'; }
        } else if (replayCurrentBarIdx >= replayEntryOffset) {
            // Entry Bar or inside trade
            if (!replayEntryLine) {
                try {
                    replayEntryLine = candlestickSeries.createPriceLine({
                        price: trade.entry,
                        color: '#3b82f6',
                        lineWidth: 2,
                        lineStyle: 0,
                        axisLabelVisible: true,
                        title: `ENTRY: $${trade.entry.toFixed(1)}`
                    });
                    replaySlLine = candlestickSeries.createPriceLine({
                        price: trade.sl,
                        color: '#ef4444',
                        lineWidth: 1,
                        lineStyle: 2,
                        axisLabelVisible: true,
                        title: `SL: $${trade.sl.toFixed(1)}`
                    });
                    replayTpLine = candlestickSeries.createPriceLine({
                        price: trade.tp,
                        color: '#10b981',
                        lineWidth: 1,
                        lineStyle: 2,
                        axisLabelVisible: true,
                        title: `TP: $${trade.tp.toFixed(1)}`
                    });

                    // Add trade marker on entry bar
                    candlestickSeries.setMarkers([{
                        time: replayCandles[replayEntryOffset].time,
                        position: trade.side === 'BUY' ? 'belowBar' : 'aboveBar',
                        color: trade.side === 'BUY' ? '#10b981' : '#ef4444',
                        shape: trade.side === 'BUY' ? 'arrowUp' : 'arrowDown',
                        text: `${trade.side} ${trade.order_type} @ $${trade.entry.toFixed(1)}`
                    }]);
                } catch (e) {
                    console.warn("Could not draw price lines:", e);
                }
            }

            // Calculate live PnL in R
            let rPnl = 0;
            const risk = Math.abs(trade.entry - trade.sl);
            if (risk > 0) {
                if (trade.side === 'BUY') {
                    rPnl = (curCandle.close - trade.entry) / risk;
                } else {
                    rPnl = (trade.entry - curCandle.close) / risk;
                }
            }

            // Check hit conditions on this candle
            const isBuy = trade.side === 'BUY';
            const tpHit = isBuy ? (curCandle.high >= trade.tp) : (curCandle.low <= trade.tp);
            const slHit = isBuy ? (curCandle.low <= trade.sl) : (curCandle.high >= trade.sl);

            if (tpHit) {
                if (replayStatusText) replayStatusText.textContent = `🎯 TAKE PROFIT REACHED (+${trade.r_pnl.toFixed(1)}R)!`;
                if (replayPulseDot) { replayPulseDot.style.background = '#10b981'; replayPulseDot.style.boxShadow = '0 0 14px #10b981'; }
                if (replayLivePnl) {
                    replayLivePnl.textContent = `+${trade.r_pnl.toFixed(1)} R`;
                    replayLivePnl.style.color = '#10b981';
                }
            } else if (slHit) {
                if (replayStatusText) replayStatusText.textContent = `🛑 STOPPED OUT (-1.0R)`;
                if (replayPulseDot) { replayPulseDot.style.background = '#ef4444'; replayPulseDot.style.boxShadow = '0 0 12px #ef4444'; }
                if (replayLivePnl) {
                    replayLivePnl.textContent = `-1.00 R`;
                    replayLivePnl.style.color = '#ef4444';
                }
            } else {
                if (replayStatusText) replayStatusText.textContent = `⚡ IN TRADE: ${trade.side} ${trade.order_type} (${trade.pattern})`;
                if (replayPulseDot) { replayPulseDot.style.background = '#10b981'; replayPulseDot.style.boxShadow = '0 0 8px #10b981'; }
                if (replayLivePnl) {
                    replayLivePnl.textContent = `${rPnl >= 0 ? '+' : ''}${rPnl.toFixed(2)} R`;
                    replayLivePnl.style.color = rPnl >= 0 ? '#10b981' : '#ef4444';
                }
            }
        }
    }

    function stepReplay(delta) {
        if (!replayCandles || replayCandles.length === 0) return;
        const newIdx = replayCurrentBarIdx + delta;
        if (newIdx >= 0 && newIdx < replayCandles.length) {
            replayCurrentBarIdx = newIdx;
            renderReplaySlice();
        }
    }

    function togglePlayReplay(forcePlay) {
        if (forcePlay === false || (forcePlay !== true && replayTimer)) {
            // Pause
            if (replayTimer) { clearInterval(replayTimer); replayTimer = null; }
            if (btnReplayPlay) btnReplayPlay.innerHTML = '▶️ Play';
        } else {
            // Play
            if (replayTimer) clearInterval(replayTimer);
            if (replayCurrentBarIdx >= replayCandles.length - 1) {
                replayCurrentBarIdx = Math.max(1, replayEntryOffset - 6);
                clearReplayPriceLines();
            }
            if (btnReplayPlay) btnReplayPlay.innerHTML = '⏸️ Pause';
            replayTimer = setInterval(() => {
                if (replayCurrentBarIdx < replayCandles.length - 1) {
                    stepReplay(1);
                } else {
                    togglePlayReplay(false);
                }
            }, replaySpeedMs);
        }
    }

    function exitSimulationReplay() {
        if (replayTimer) { clearInterval(replayTimer); replayTimer = null; }
        clearReplayPriceLines();
        if (replayBar) replayBar.style.display = 'none';
        window.isSimulationReplayActive = false;

        // Restore normal chart state
        if (savedNormalCandles && savedNormalCandles.length > 0 && candlestickSeries) {
            currentCandles = savedNormalCandles;
            candlestickSeries.setData(currentCandles);
            renderAlgoTradeMarkers(savedNormalSignals || []);
            if (chart) chart.timeScale().fitContent();
        }
        if (savedNormalStrategy) {
            window.currentStrategy = currentStrategy = savedNormalStrategy;
        }
        redrawAll();
    }

    // Modal & Filter Handlers
    if (btnOpenSim) {
        btnOpenSim.addEventListener('click', () => {
            if (simModal) simModal.style.display = 'flex';
            loadOctoberSimulation();
        });
    }

    if (btnCloseSim) {
        btnCloseSim.addEventListener('click', () => {
            if (simModal) simModal.style.display = 'none';
        });
    }

    if (simModal) {
        simModal.addEventListener('click', (e) => {
            if (e.target === simModal) simModal.style.display = 'none';
        });
    }

    simFilterBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            simFilterBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentSimFilter = btn.dataset.filter || 'all';
            renderSimulationTable();
        });
    });

    if (simSearchInput) {
        simSearchInput.addEventListener('input', () => {
            renderSimulationTable();
        });
    }

    window.inspectSimulationTrade = function(targetTime, side, price) {
        if (simModal) simModal.style.display = 'none';
        if (typeof openTradeInspector === 'function') {
            openTradeInspector(targetTime, side, price, '15m');
            if (typeof fetchTradeInspection === 'function') {
                fetchTradeInspection(targetTime, side, price);
            }
        }
    };

    // Dataset Switcher Handlers
    if (btnDatasetMajor) {
        btnDatasetMajor.addEventListener('click', () => {
            btnDatasetMajor.classList.add('active');
            if (btnDatasetAll) btnDatasetAll.classList.remove('active');
            currentSimDatasetMode = 'major';
            loadOctoberSimulation('major');
        });
    }

    if (btnDatasetAll) {
        btnDatasetAll.addEventListener('click', () => {
            btnDatasetAll.classList.add('active');
            if (btnDatasetMajor) btnDatasetMajor.classList.remove('active');
            currentSimDatasetMode = 'all';
            loadOctoberSimulation('all');
        });
    }

    if (btnLaunchAnimModal) {
        btnLaunchAnimModal.addEventListener('click', () => {
            startSingleTradeReplay(0, currentSimDatasetMode);
        });
    }

    // Replay Bar Controls Handlers
    if (btnReplayPlay) {
        btnReplayPlay.addEventListener('click', () => {
            togglePlayReplay();
        });
    }

    if (btnReplayStepFwd) {
        btnReplayStepFwd.addEventListener('click', () => {
            togglePlayReplay(false);
            stepReplay(1);
        });
    }

    if (btnReplayStepBack) {
        btnReplayStepBack.addEventListener('click', () => {
            togglePlayReplay(false);
            stepReplay(-1);
        });
    }

    if (btnReplayNext) {
        btnReplayNext.addEventListener('click', () => {
            loadTradeIntoReplay(replayTradeIndex + 1);
        });
    }

    if (btnReplayPrev) {
        btnReplayPrev.addEventListener('click', () => {
            loadTradeIntoReplay(replayTradeIndex - 1);
        });
    }

    if (btnReplayToggleMode) {
        btnReplayToggleMode.addEventListener('click', () => {
            const nextMode = currentSimDatasetMode === 'major' ? 'all' : 'major';
            currentSimDatasetMode = nextMode;
            if (btnDatasetMajor && btnDatasetAll) {
                if (nextMode === 'major') {
                    btnDatasetMajor.classList.add('active');
                    btnDatasetAll.classList.remove('active');
                } else {
                    btnDatasetAll.classList.add('active');
                    btnDatasetMajor.classList.remove('active');
                }
            }
            startSingleTradeReplay(0, nextMode);
        });
    }

    if (btnCloseReplayBar) {
        btnCloseReplayBar.addEventListener('click', () => {
            exitSimulationReplay();
        });
    }

    replaySpeedBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            replaySpeedBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const spd = parseInt(btn.dataset.speed || '250', 10);
            replaySpeedMs = spd;
            if (replayTimer) {
                togglePlayReplay(false);
                togglePlayReplay(true);
            }
        });
    });

    window.startSingleTradeReplay = startSingleTradeReplay;
    window.exitSimulationReplay = exitSimulationReplay;

    window.openTradeInspector = openTradeInspector;
    window.closeTradeInspector = closeTradeInspector;
    window.fetchTradeInspection = fetchTradeInspection;

    connectWS();
    loadInitialChartData();
});
