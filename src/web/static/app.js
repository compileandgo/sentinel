// ─── Sentinel Deep Research UI Controller ─────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {

    // ── DOM refs ───────────────────────────────────────────────────────────────
    const researchForm = document.getElementById("research-form");
    const topicInput = document.getElementById("topic-input");
    const sendQueryBtn = document.getElementById("send-query-btn");
    const stopResearchBtn = document.getElementById("stop-research-btn");
    const deepResearchBtn = document.getElementById("deep-research-btn");

    const chatMessages = document.getElementById("chat-messages");
    const idleWelcome = document.getElementById("idle-welcome");
    const activeChatContent = document.getElementById("active-chat-content");
    const userQueryBubble = document.getElementById("user-query-bubble");

    // Plan card
    const planTitle = document.getElementById("plan-title");
    const planBullets = document.getElementById("plan-bullets");
    const bulletsMoreBtn = document.getElementById("bullets-more-btn");
    const startResearchBtn = document.getElementById("start-research-btn");
    const editPlanBtn = document.getElementById("edit-plan-btn");

    // Research viewer (right panel)
    const researchViewer = document.getElementById("research-viewer");
    const viewerTitle = document.getElementById("viewer-research-title");
    const closeViewerBtn = document.getElementById("close-viewer-btn");
    const toggleThinkingBtn = document.getElementById("thinking-dropdown-btn");
    const thinkingArea = document.getElementById("thinking-area");
    const thinkingSkeleton = document.getElementById("thinking-skeleton");
    const thinkingLogs = document.getElementById("thinking-logs");

    const sourcesPanel = document.getElementById("sources-panel");
    const sourcesGrid = document.getElementById("sources-grid");
    const reportContent = document.getElementById("report-content");

    // Outline dropdown
    const contentsWrapper = document.getElementById("contents-dropdown-wrapper");
    const contentsBtn = document.getElementById("contents-dropdown-btn");
    const contentsMenu = document.getElementById("contents-menu");

    // Sidebar
    const recentBriefsList = document.getElementById("recent-briefs-list");
    const newResearchNav = document.getElementById("new-research-nav");
    const sidebarToggleBtn = document.getElementById("sidebar-toggle-btn");
    const sidebarElement = document.querySelector(".sidebar");
    const settingsBtn = document.getElementById("settings-btn");
    const tryAdvancedBtn = document.getElementById("try-advanced-btn");

    // Search view elements
    const searchView = document.getElementById("search-view");
    const chatSearchInput = document.getElementById("chat-search-input");
    const clearSearchBtn = document.getElementById("clear-search-btn");
    const searchResultsList = document.getElementById("search-results-list");
    const searchChatsBtn = document.getElementById("search-chats-btn");

    // ── State ──────────────────────────────────────────────────────────────────
    let currentRunId = null;
    let eventSource = null;
    let currentTopic = "";
    let isThinkingHidden = false;
    let planTasks = [];
    let seenUrls = new Set();
    let maxIterationsSetting = 1;
    let maxSubagentsSetting = 3;
    let currentReportMarkdown = "";
    let isLightTheme = localStorage.getItem("theme") === "light";
    let currentBriefFilename = "";
    let recentBriefs = [];
    let isDeepResearchEnabled = true;
    let activeRunId = null;
    let activeRunTopic = "";
    let activeRunStatus = "idle";
    let activeChatAbortController = null;
    let searchDebounceTimeout = null;
    let isSearchViewActive = false;
    let lastSearchedQuery = "";

    // Apply persistent theme on load
    if (isLightTheme) {
        document.body.classList.add("light-theme");
    } else {
        document.body.classList.remove("light-theme");
    }

    // ── Markdown parser ────────────────────────────────────────────────────────
    if (typeof marked !== "undefined") {
        const customRenderer = {
            link(hrefOrToken, title, text) {
                let href = "";
                let linkText = "";

                if (hrefOrToken && typeof hrefOrToken === 'object') {
                    href = hrefOrToken.href || "";
                    linkText = hrefOrToken.text || hrefOrToken.raw || "";
                } else {
                    href = hrefOrToken || "";
                    linkText = text || hrefOrToken || "";
                }

                href = String(href).trim();
                linkText = String(linkText).trim();
                if (!linkText) linkText = href;

                try {
                    const url = new URL(href);
                    const faviconUrl = `https://www.google.com/s2/favicons?domain=${url.hostname}&sz=32`;
                    return `<a href="${href}" target="_blank" rel="noopener noreferrer" class="chat-link"><img src="${faviconUrl}" class="link-favicon" onerror="this.style.display='none'"> ${linkText}</a>`;
                } catch {
                    return `<a href="${href}" target="_blank" rel="noopener noreferrer" class="chat-link">${linkText}</a>`;
                }
            },
            code(codeOrToken, language, escaped) {
                let codeText = "";
                let lang = "";

                if (codeOrToken && typeof codeOrToken === 'object') {
                    codeText = codeOrToken.text;
                    if (codeText === undefined) codeText = codeOrToken.raw || "";
                    lang = codeOrToken.lang || "";
                } else {
                    codeText = codeOrToken || "";
                    lang = language || "";
                }

                codeText = String(codeText);
                lang = String(lang).trim();

                const validLang = (typeof hljs !== "undefined" && hljs.getLanguage(lang)) ? lang : 'plaintext';
                let highlighted = codeText;
                if (typeof hljs !== "undefined") {
                    try {
                        highlighted = hljs.highlight(codeText, { language: validLang }).value;
                    } catch (e) {
                        // Silent fallback
                    }
                }

                return `
                    <div class="code-block-container">
                        <div class="code-block-header">
                            <span class="code-block-lang">${validLang}</span>
                            <button class="copy-code-btn" onclick="navigator.clipboard.writeText(this.closest('.code-block-container').querySelector('code').innerText).then(() => { this.innerText = 'Copied!'; setTimeout(() => this.innerText = 'Copy', 2000); })">Copy</button>
                        </div>
                        <pre><code class="hljs ${validLang}">${highlighted}</code></pre>
                    </div>
                `;
            }
        };

        marked.use({ renderer: customRenderer });
        marked.setOptions({ gfm: true, breaks: true });
    }

    // ── Authentication Bootstrap ──────────────────────────────────────────────
    let supabase = null;
    let session = null;
    let uiInitialized = false;

    // Define authFetch wrapper
    async function authFetch(url, options = {}) {
        if (!session) {
            throw new Error("User is not authenticated");
        }
        options.headers = options.headers || {};
        options.headers["Authorization"] = `Bearer ${session.access_token}`;
        return fetch(url, options);
    }

    function showUpdatePasswordForm() {
        const authContainer = document.getElementById("auth-container");
        const appContainer = document.querySelector(".app-container");
        const authTabsContainer = document.getElementById("auth-tabs-container");
        const loginForm = document.getElementById("login-form");
        const signupForm = document.getElementById("signup-form");
        const resetPasswordForm = document.getElementById("reset-password-form");
        const updatePasswordForm = document.getElementById("update-password-form");

        authContainer.classList.remove("hidden");
        appContainer.classList.add("hidden");
        if (authTabsContainer) authTabsContainer.classList.add("hidden");
        if (loginForm) loginForm.classList.add("hidden");
        if (signupForm) signupForm.classList.add("hidden");
        if (resetPasswordForm) resetPasswordForm.classList.add("hidden");
        if (updatePasswordForm) updatePasswordForm.classList.remove("hidden");

        authFeedback.textContent = "Please set a new password.";
        authFeedback.className = "auth-feedback info";
    }

    async function initAuth() {
        try {
            const res = await fetch("/api/config");
            const config = await res.json();
            if (config.supabaseUrl && config.supabaseAnonKey) {
                // Initialize Supabase client
                const { createClient } = window.supabase;
                supabase = createClient(config.supabaseUrl, config.supabaseAnonKey);

                // Get current session
                const { data: { session: currentSession } } = await supabase.auth.getSession();
                session = currentSession;

                supabase.auth.onAuthStateChange((event, newSession) => {
                    const sessionChanged = (session?.user?.id !== newSession?.user?.id);
                    session = newSession;
                    if (event === "PASSWORD_RECOVERY") {
                        showUpdatePasswordForm();
                    } else {
                        if (!newSession) {
                            uiInitialized = false;
                            resetState(false);
                            updateUIForAuth();
                        } else if (!uiInitialized || sessionChanged) {
                            uiInitialized = true;
                            if (sessionChanged) {
                                resetState(false);
                            }
                            updateUIForAuth();
                        }
                    }
                });

                // Check if current URL contains recovery parameters
                if (window.location.hash && window.location.hash.includes("type=recovery")) {
                    showUpdatePasswordForm();
                } else {
                    if (session) {
                        uiInitialized = true;
                    }
                    updateUIForAuth();
                }
            }
        } catch (err) {
            // Silent catch
        }
    }

    function updateUIForAuth() {
        const authContainer = document.getElementById("auth-container");
        const appContainer = document.querySelector(".app-container");

        if (session) {
            authContainer.classList.add("hidden");
            appContainer.classList.remove("hidden");

            // Set user profile in sidebar footer
            const email = session.user.email;
            const metadata = session.user.user_metadata || {};
            const username = metadata.username || email;
            const userAvatar = document.getElementById("user-avatar");
            const usernameDisplay = document.getElementById("username-display");

            if (userAvatar) {
                userAvatar.textContent = username.substring(0, 2).toUpperCase();
            }
            if (usernameDisplay) {
                usernameDisplay.textContent = username;
            }

            // Load history and open active chat if saved
            loadBriefHistory().then(briefs => {
                const activeChatKey = session ? `sentinel_active_chat_${session.user.id}` : "sentinel_active_chat";
                let activeChat = localStorage.getItem(activeChatKey);

                // Migrate legacy key if exists
                if (!activeChat && session) {
                    const legacyChat = localStorage.getItem("sentinel_active_chat");
                    if (legacyChat) {
                        activeChat = legacyChat;
                        localStorage.setItem(activeChatKey, legacyChat);
                        localStorage.removeItem("sentinel_active_chat");
                    }
                }

                if (activeChat && briefs && briefs.some(b => b.filename === activeChat)) {
                    loadBriefContent(activeChat);
                } else {
                    resetState(true);
                }
            });
        } else {
            authContainer.classList.remove("hidden");
            appContainer.classList.add("hidden");

            // Reset to default SignIn tab state
            const loginForm = document.getElementById("login-form");
            const signupForm = document.getElementById("signup-form");
            const resetPasswordForm = document.getElementById("reset-password-form");
            const updatePasswordForm = document.getElementById("update-password-form");
            const authTabsContainer = document.getElementById("auth-tabs-container");
            const tabLogin = document.getElementById("tab-login");
            const tabSignup = document.getElementById("tab-signup");

            if (authTabsContainer) authTabsContainer.classList.remove("hidden");
            if (tabLogin) tabLogin.classList.add("active");
            if (tabSignup) tabSignup.classList.remove("active");
            if (loginForm) loginForm.classList.remove("hidden");
            if (signupForm) signupForm.classList.add("hidden");
            if (resetPasswordForm) resetPasswordForm.classList.add("hidden");
            if (updatePasswordForm) updatePasswordForm.classList.add("hidden");
        }
    }

    // Set up auth forms
    const loginForm = document.getElementById("login-form");
    const signupForm = document.getElementById("signup-form");
    const tabLogin = document.getElementById("tab-login");
    const tabSignup = document.getElementById("tab-signup");
    const authFeedback = document.getElementById("auth-feedback");

    // Forgot/Reset elements
    const forgotPasswordLink = document.getElementById("forgot-password-link");
    const backToLoginLink = document.getElementById("back-to-login-link");
    const resetPasswordForm = document.getElementById("reset-password-form");
    const updatePasswordForm = document.getElementById("update-password-form");
    const authTabsContainer = document.getElementById("auth-tabs-container");

    if (forgotPasswordLink && backToLoginLink && resetPasswordForm && authTabsContainer) {
        forgotPasswordLink.addEventListener("click", (e) => {
            e.preventDefault();
            if (loginForm) loginForm.classList.add("hidden");
            if (signupForm) signupForm.classList.add("hidden");
            resetPasswordForm.classList.remove("hidden");
            authTabsContainer.classList.add("hidden");
            authFeedback.textContent = "";
        });

        backToLoginLink.addEventListener("click", (e) => {
            e.preventDefault();
            resetPasswordForm.classList.add("hidden");
            if (loginForm) loginForm.classList.remove("hidden");
            authTabsContainer.classList.remove("hidden");
            authFeedback.textContent = "";
        });
    }

    if (resetPasswordForm) {
        resetPasswordForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            authFeedback.textContent = "Sending reset link...";
            authFeedback.className = "auth-feedback";
            const email = document.getElementById("reset-email").value.trim();

            try {
                const { error } = await supabase.auth.resetPasswordForEmail(email, {
                    redirectTo: window.location.origin
                });
                if (error) throw error;

                authFeedback.textContent = "Password reset link sent to your email!";
                authFeedback.className = "auth-feedback success";
            } catch (err) {
                authFeedback.textContent = err.message;
                authFeedback.className = "auth-feedback error";
            }
        });
    }

    if (updatePasswordForm) {
        updatePasswordForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            authFeedback.textContent = "Updating password...";
            authFeedback.className = "auth-feedback";
            const newPassword = document.getElementById("update-password").value;

            try {
                const { error } = await supabase.auth.updateUser({ password: newPassword });
                if (error) throw error;

                authFeedback.textContent = "Password updated successfully! Loading workspace...";
                authFeedback.className = "auth-feedback success";

                setTimeout(() => {
                    updatePasswordForm.classList.add("hidden");
                    // Clear the URL fragment to clean up hash params
                    window.history.replaceState({}, document.title, window.location.pathname);
                    updateUIForAuth();
                }, 2000);
            } catch (err) {
                authFeedback.textContent = err.message;
                authFeedback.className = "auth-feedback error";
            }
        });
    }

    if (tabLogin && tabSignup && loginForm && signupForm) {
        tabLogin.addEventListener("click", () => {
            tabLogin.classList.add("active");
            tabSignup.classList.remove("active");
            loginForm.classList.remove("hidden");
            signupForm.classList.add("hidden");
            authFeedback.textContent = "";
        });

        tabSignup.addEventListener("click", () => {
            tabSignup.classList.add("active");
            tabLogin.classList.remove("active");
            signupForm.classList.remove("hidden");
            loginForm.classList.add("hidden");
            authFeedback.textContent = "";
        });

        loginForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            authFeedback.textContent = "Signing in...";
            authFeedback.className = "auth-feedback";

            const email = document.getElementById("login-email").value.trim();
            const password = document.getElementById("login-password").value;

            const { error } = await supabase.auth.signInWithPassword({ email, password });
            if (error) {
                authFeedback.textContent = error.message;
                authFeedback.className = "auth-feedback error";
            } else {
                authFeedback.textContent = "Success!";
                authFeedback.className = "auth-feedback success";
            }
        });

        signupForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            authFeedback.textContent = "Creating account...";
            authFeedback.className = "auth-feedback";

            const username = document.getElementById("signup-username").value.trim();
            const email = document.getElementById("signup-email").value.trim();
            const password = document.getElementById("signup-password").value;

            if (!username) {
                authFeedback.textContent = "Username is required.";
                authFeedback.className = "auth-feedback error";
                return;
            }

            try {
                // First check email uniqueness to prevent duplicate signup or silent failure
                const checkRes = await fetch(`/api/auth/check-email?email=${encodeURIComponent(email)}`);
                if (checkRes.ok) {
                    const checkData = await checkRes.json();
                    if (checkData.exists) {
                        authFeedback.textContent = "Email is already registered. Please sign in instead.";
                        authFeedback.className = "auth-feedback error";
                        return;
                    }
                }

                const { data, error } = await supabase.auth.signUp({
                    email,
                    password,
                    options: {
                        data: {
                            username: username
                        }
                    }
                });

                if (error) throw error;

                if (data.user && data.session === null) {
                    authFeedback.textContent = "Confirmation email sent! Please check your inbox.";
                    authFeedback.className = "auth-feedback success";
                } else {
                    authFeedback.textContent = "Account created and logged in!";
                    authFeedback.className = "auth-feedback success";
                }
            } catch (err) {
                authFeedback.textContent = err.message;
                authFeedback.className = "auth-feedback error";
            }
        });
    }

    const plusBtn = document.getElementById("plus-dropdown-btn");
    const plusMenu = document.getElementById("plus-dropdown-menu");
    if (plusBtn && plusMenu) {
        plusBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            plusMenu.classList.toggle("hidden");
        });

        document.addEventListener("click", () => {
            plusMenu.classList.add("hidden");
        });

        const optSources = document.getElementById("plus-opt-sources");
        const optFiles = document.getElementById("plus-opt-files");

        if (optSources) {
            optSources.addEventListener("click", (e) => {
                e.stopPropagation();
                plusMenu.classList.add("hidden");
                showToast("Enterprise Feature", '"Sources" integration is an enterprise-only feature.');
            });
        }

        if (optFiles) {
            optFiles.addEventListener("click", (e) => {
                e.stopPropagation();
                plusMenu.classList.add("hidden");
                showToast("Enterprise Feature", '"Files" upload is an enterprise-only feature.');
            });
        }
    }

    // Call authentication initializer
    initAuth();

    // ── Textarea auto-grow ────────────────────────────────────────────────────
    topicInput.addEventListener("input", function () {
        this.style.height = "auto";
        const newHeight = Math.min(this.scrollHeight, 160);
        this.style.height = newHeight + "px";
        this.style.overflowY = this.scrollHeight > 160 ? "auto" : "hidden";
    });

    // ── Toggle Deep Research / Normal QA Mode ─────────────────────────────────
    if (deepResearchBtn) {
        deepResearchBtn.addEventListener("click", () => {
            isDeepResearchEnabled = !isDeepResearchEnabled;
            deepResearchBtn.classList.toggle("active", isDeepResearchEnabled);
            if (isDeepResearchEnabled) {
                topicInput.placeholder = "Ask Sentinel to research...";
            } else {
                topicInput.placeholder = "Ask a question...";
            }
        });
    }

    // ── Enter key submits (Shift+Enter = newline) ─────────────────────────────
    topicInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendQueryBtn.click();
        }
    });

    // ── New Research button ───────────────────────────────────────────────────
    newResearchNav.addEventListener("click", () => {
        resetState();
        topicInput.value = "";
        topicInput.style.height = "auto";
        if (window.innerWidth <= 768 && sidebarElement) {
            sidebarElement.classList.add("collapsed");
        }
    });

    // ── Sidebar Nav Buttons Click Handler ──────────────────────────────────────
    const navButtons = document.querySelectorAll(".sidebar-nav .nav-btn");
    navButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            if (window.innerWidth <= 768 && sidebarElement) {
                sidebarElement.classList.add("collapsed");
            }
            if (btn.id === "search-chats-btn") {
                openSearchView();
            } else {
                closeSearchView();

                // Set active class on non-search buttons
                navButtons.forEach(b => b.classList.remove("active"));
                btn.classList.add("active");

                // If it's not the new chat button, show toast
                if (btn.id !== "new-research-nav") {
                    showToast("Enterprise Feature", `"${btn.querySelector('span').textContent}" is an enterprise-only feature.`);
                }
            }
        });
    });

    // ── Chat Search View Functions ─────────────────────────────────────────────
    function openSearchView() {
        isSearchViewActive = true;

        // Show search view popup overlay
        searchView.classList.remove("hidden");

        // Update sidebar nav state
        navButtons.forEach(b => {
            if (b.id === "search-chats-btn") {
                b.classList.add("active");
            } else {
                b.classList.remove("active");
            }
        });

        chatSearchInput.focus();

        // If there's already text, trigger search immediately
        if (chatSearchInput.value.trim()) {
            performSearch(chatSearchInput.value.trim());
        } else {
            renderEmptySearchState("Type a keyword to search across chats, briefs, and messages.");
        }
    }

    function closeSearchView() {
        if (!isSearchViewActive) return;
        isSearchViewActive = false;

        searchView.classList.add("hidden");

        const searchBtn = document.getElementById("search-chats-btn");
        if (searchBtn) searchBtn.classList.remove("active");

        // Restore active navigation button state
        if (currentBriefFilename) {
            const items = recentBriefsList.querySelectorAll(".recent-item");
            items.forEach(item => {
                if (item.dataset.filename === currentBriefFilename) {
                    item.classList.add("active");
                } else {
                    item.classList.remove("active");
                }
            });
            newResearchNav.classList.remove("active");
        } else {
            newResearchNav.classList.add("active");
        }
    }

    async function performSearch(query) {
        const trimmed = query.trim();
        if (trimmed === lastSearchedQuery) {
            return;
        }
        lastSearchedQuery = trimmed;

        if (!trimmed) {
            clearSearchBtn.classList.add("hidden");
            renderEmptySearchState("Type a keyword to search across chats, briefs, and messages.");
            return;
        }

        clearSearchBtn.classList.remove("hidden");
        searchResultsList.innerHTML = `<div class="search-empty-state">Searching...</div>`;

        try {
            const res = await authFetch(`/api/search?q=${encodeURIComponent(trimmed)}`);
            if (!res.ok) throw new Error("Search request failed");
            const results = await res.json();

            renderSearchResults(results, trimmed);
        } catch (e) {
            searchResultsList.innerHTML = `<div class="search-empty-state" style="color: var(--text-error);">Search failed. Please try again.</div>`;
        }
    }

    function formatDate(dateStr) {
        if (!dateStr) return "";
        try {
            const date = new Date(dateStr);
            if (isNaN(date.getTime())) {
                return dateStr.split(" ")[0];
            }
            const options = { day: 'numeric', month: 'short' };
            return date.toLocaleDateString('en-US', options);
        } catch (e) {
            return dateStr;
        }
    }

    function renderSearchResults(results, query) {
        searchResultsList.innerHTML = "";

        if (!results || results.length === 0) {
            searchResultsList.innerHTML = `<div class="search-empty-state">No results found for "${escHtml(query)}"</div>`;
            return;
        }

        results.forEach(res => {
            const item = document.createElement("div");
            item.className = "search-result-item";

            let snippetHtml = escHtml(res.snippet || "No snippet available.");
            if (query) {
                const regex = new RegExp(`(${escapeRegExp(query)})`, "gi");
                snippetHtml = snippetHtml.replace(regex, `<mark style="background-color: rgba(78,136,245,0.25); color: inherit; padding: 0 2px; border-radius: 2px;">$1</mark>`);
            }

            const displayDate = formatDate(res.date);

            item.innerHTML = `
                <div class="search-result-left">
                    <span class="search-result-title">${escHtml(res.title)}</span>
                    <span class="search-result-snippet">${snippetHtml}</span>
                </div>
                <span class="search-result-date">${displayDate}</span>
            `;

            item.onclick = () => {
                loadBriefContent(res.filename);
            };

            searchResultsList.appendChild(item);
        });
    }

    function renderEmptySearchState(message) {
        searchResultsList.innerHTML = `
            <div class="search-empty-state">
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="color: var(--text-muted); margin-bottom: 12px;">
                    <circle cx="11" cy="11" r="8"></circle>
                    <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                </svg>
                <div>${escHtml(message)}</div>
            </div>
        `;
    }

    function escapeRegExp(string) {
        return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    // Debounced search input handler
    chatSearchInput.addEventListener("input", () => {
        const query = chatSearchInput.value;

        if (searchDebounceTimeout) {
            clearTimeout(searchDebounceTimeout);
        }

        searchDebounceTimeout = setTimeout(() => {
            performSearch(query);
        }, 400);
    });

    // Enter key immediate search execution
    chatSearchInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            if (searchDebounceTimeout) {
                clearTimeout(searchDebounceTimeout);
            }
            performSearch(chatSearchInput.value);
        }
    });

    // Clear search button handler
    clearSearchBtn.addEventListener("click", () => {
        chatSearchInput.value = "";
        clearSearchBtn.classList.add("hidden");
        chatSearchInput.focus();
        renderEmptySearchState("Type a keyword to search across chats, briefs, and messages.");
        performSearch("");
    });

    // Close search popup if clicked outside container
    searchView.addEventListener("click", (e) => {
        if (e.target === searchView) {
            closeSearchView();
        }
    });

    // Escape key listener to close search popup
    window.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && isSearchViewActive) {
            closeSearchView();
        }
    });

    // ── Toggle Sidebar ────────────────────────────────────────────────────────
    const logoToggleBtn = document.getElementById("sidebar-logo-toggle");
    const closeBtn = document.getElementById("sidebar-close-btn");
    if (sidebarElement) {
        if (logoToggleBtn) {
            logoToggleBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                sidebarElement.classList.toggle("collapsed");
            });
        }
        if (closeBtn) {
            closeBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                sidebarElement.classList.add("collapsed");
            });
        }

        // Mobile menu toggle button
        const mobileMenuBtn = document.getElementById("mobile-menu-btn");
        if (mobileMenuBtn) {
            mobileMenuBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                sidebarElement.classList.toggle("collapsed");
            });
        }

        // Mobile new chat button
        const mobileNewChatBtn = document.getElementById("mobile-new-chat-btn");
        if (mobileNewChatBtn) {
            mobileNewChatBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                resetState();
                topicInput.value = "";
                topicInput.style.height = "auto";
                sidebarElement.classList.add("collapsed");
            });
        }

        // Click outside sidebar to close it on mobile
        document.addEventListener("click", (e) => {
            if (window.innerWidth <= 768 && !sidebarElement.classList.contains("collapsed")) {
                const isClickInside = sidebarElement.contains(e.target);
                const isClickOnMenuBtn = mobileMenuBtn && mobileMenuBtn.contains(e.target);
                if (!isClickInside && !isClickOnMenuBtn) {
                    sidebarElement.classList.add("collapsed");
                }
            }
        });
    }

    // ── Form submit → start research ──────────────────────────────────────────
    researchForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const topic = topicInput.value.trim();
        if (!topic || sendQueryBtn.disabled) return;

        if (window.innerWidth <= 768 && sidebarElement) {
            sidebarElement.classList.add("collapsed");
        }

        if (!isDeepResearchEnabled) {
            // Normal Chat QA Mode
            const query = topic;
            topicInput.value = "";
            topicInput.style.height = "auto";

            // Append user message
            appendChatMessage("user", query);

            // Disable send button while answering
            activeChatAbortController = new AbortController();
            sendQueryBtn.classList.add("hidden");
            stopResearchBtn.classList.remove("hidden");

            // Append loading bubble
            appendChatMessage("assistant", "", true);

            const tempId = "temp-" + Date.now();
            let activeItem = null;
            if (!currentBriefFilename) {
                // Prepend loading skeleton to recent briefs list
                activeItem = document.createElement("div");
                activeItem.className = "recent-item loading-skeleton-item active";
                activeItem.id = `sidebar-run-${tempId}`;
                activeItem.innerHTML = `
                    <span class="recent-item-title skeleton-text-animation">${escHtml(query)}...</span>
                    <div class="skeleton-spinner"></div>
                `;

                if (recentBriefsList.firstChild && recentBriefsList.firstChild.className === "recent-item loading") {
                    recentBriefsList.innerHTML = "";
                }
                recentBriefsList.insertBefore(activeItem, recentBriefsList.firstChild);
            }

            let textTarget = null;
            try {
                const res = await authFetch("/api/chat/stream", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        query,
                        brief_filename: currentBriefFilename || null,
                        new_session: !currentBriefFilename
                    }),
                    signal: activeChatAbortController.signal
                });

                // Remove "Answering..." loading bubble
                const loadingBubble = document.getElementById("qa-loading-bubble");
                if (loadingBubble) loadingBubble.remove();

                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || "Server error");
                }

                // Create a live streaming bubble
                const streamDiv = document.createElement("div");
                streamDiv.className = "message assistant-message";
                streamDiv.innerHTML = `
                    <div class="avatar-star">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <ellipse cx="12" cy="12" rx="13.51" ry="6.14" transform="translate(-4.97 12) rotate(-45)"></ellipse>
                            <ellipse cx="12" cy="12" rx="6.14" ry="13.51" transform="translate(-4.97 12) rotate(-45)"></ellipse>
                            <circle cx="12" cy="12" r="0.95"></circle>
                        </svg>
                    </div>
                    <div class="message-content">
                        <div class="message-text streaming" id="stream-text-target"></div>
                    </div>
                `;
                idleWelcome.appendChild(streamDiv);
                textTarget = streamDiv.querySelector("#stream-text-target");

                // SSE stream reader
                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                let sseBuffer = "";
                let fullText = "";

                outer: while (true) {
                    let readResult;
                    try {
                        readResult = await reader.read();
                    } catch {
                        break; // aborted
                    }
                    const { done, value } = readResult;
                    if (done) break;

                    sseBuffer += decoder.decode(value, { stream: true });
                    const events = sseBuffer.split("\n\n");
                    sseBuffer = events.pop(); // keep incomplete chunk

                    for (const event of events) {
                        if (!event.startsWith("data: ")) continue;
                        let payload;
                        try { payload = JSON.parse(event.slice(6)); } catch { continue; }

                        if (payload.error) {
                            textTarget.innerHTML = `${escHtml(formatUserFriendlyError(payload.error))}`;
                            break outer;
                        }

                        if (payload.token) {
                            fullText += payload.token;
                            let displayMarkdown = fullText;
                            const titleMatch = fullText.match(/<title>([\s\S]*?)<\/title>/i);
                            if (titleMatch) {
                                const generatedTitle = titleMatch[1].trim();
                                if (generatedTitle && activeItem) {
                                    const titleEl = activeItem.querySelector(".recent-item-title");
                                    if (titleEl) {
                                        titleEl.textContent = generatedTitle;
                                        titleEl.classList.remove("skeleton-text-animation", "title-typing");
                                    }
                                }
                                displayMarkdown = fullText.replace(/<title>[\s\S]*?<\/title>/i, "").trim();
                            } else {
                                const partialTitleMatch = fullText.match(/<title>([\s\S]*)$/i);
                                if (partialTitleMatch && activeItem) {
                                    const titleEl = activeItem.querySelector(".recent-item-title");
                                    if (titleEl) {
                                        const partial = partialTitleMatch[1].trim();
                                        if (partial) {
                                            titleEl.textContent = partial;
                                            titleEl.classList.remove("skeleton-text-animation");
                                            titleEl.classList.add("title-typing");
                                        }
                                    }
                                }
                                displayMarkdown = fullText.replace(/<title>[\s\S]*$/i, "").trim();
                            }
                            // Live-render markdown as tokens arrive
                            textTarget.innerHTML = (typeof marked !== "undefined")
                                ? marked.parse(displayMarkdown)
                                : escHtml(displayMarkdown);

                            // Smart auto-scroll: scroll only if user is near the bottom
                            const threshold = 150;
                            const isNearBottom = chatMessages.scrollHeight - chatMessages.clientHeight - chatMessages.scrollTop < threshold;
                            if (isNearBottom) {
                                chatMessages.scrollTop = chatMessages.scrollHeight;
                            }
                        }

                        if (payload.done) {
                            textTarget.classList.remove("streaming");
                            if (activeItem) activeItem.remove();
                            // Strip title tags before passing to action setup
                            const cleanText = fullText.replace(/<title>[\s\S]*?<\/title>/i, "").trim();
                            setupAssistantMessageActions(streamDiv, cleanText);

                            if (payload.is_new && payload.filename) {
                                currentBriefFilename = payload.filename;
                                await loadBriefHistory();
                                await loadBriefContent(payload.filename);
                            } else if (payload.filename) {
                                currentBriefFilename = payload.filename;
                            }
                            break outer;
                        }
                    }
                }

            } catch (err) {
                if (textTarget) textTarget.classList.remove("streaming");
                const loadingBubble = document.getElementById("qa-loading-bubble");
                if (loadingBubble) loadingBubble.remove();

                if (err.name === "AbortError") {
                    appendChatMessage("assistant", "Generation stopped.");
                } else {
                    appendChatMessage("assistant", `${escHtml(formatUserFriendlyError(err.message))}`);
                }

                if (activeItem) {
                    activeItem.remove();
                }
            } finally {
                if (textTarget) textTarget.classList.remove("streaming");
                activeChatAbortController = null;
                stopResearchBtn.classList.add("hidden");
                sendQueryBtn.classList.remove("hidden");
                sendQueryBtn.disabled = false;
                sendQueryBtn.style.opacity = "1";
            }
            return;
        }

        const today = new Date().toISOString().split('T')[0];
        const randomHex = Math.floor(Math.random() * 16777215).toString(16).padStart(6, '0');
        const generatedRunId = `${today}-${randomHex}`;

        currentTopic = topic;
        topicInput.value = "";
        topicInput.style.height = "auto";
        resetState();

        // set active run state
        activeRunId = generatedRunId;
        currentRunId = generatedRunId;
        activeRunTopic = topic;
        activeRunStatus = "planning";

        // Prepend loading skeleton to recent briefs list
        const activeItem = document.createElement("div");
        activeItem.className = "recent-item loading-skeleton-item active";
        activeItem.id = `sidebar-run-${activeRunId}`;
        activeItem.innerHTML = `
            <span class="recent-item-title skeleton-text-animation">Researching: ${escHtml(topic)}...</span>
            <div class="skeleton-spinner"></div>
        `;
        activeItem.onclick = () => showActiveRunView();

        const existingSkeleton = recentBriefsList.querySelector(".loading-skeleton-item");
        if (existingSkeleton) existingSkeleton.remove();

        if (recentBriefsList.firstChild && recentBriefsList.firstChild.className === "recent-item loading") {
            recentBriefsList.innerHTML = "";
        }
        recentBriefsList.insertBefore(activeItem, recentBriefsList.firstChild);

        // Show user bubble and plan loader instantly
        userQueryBubble.textContent = topic;
        idleWelcome.classList.add("hidden");
        activeChatContent.classList.remove("hidden");

        const loader = document.getElementById("plan-generation-loader");
        if (loader) loader.classList.remove("hidden");
        const introText = activeChatContent.querySelector(".message-intro-text");
        if (introText) introText.classList.add("hidden");
        const planCard = activeChatContent.querySelector(".plan-card");
        if (planCard) planCard.classList.add("hidden");

        // Swap send to stop button to make plan generation interruptible!
        sendQueryBtn.classList.add("hidden");
        stopResearchBtn.classList.remove("hidden");
        stopResearchBtn.disabled = false;
        stopResearchBtn.style.opacity = "1";

        // Open viewer panel immediately
        openViewer(topic);

        activeChatAbortController = new AbortController();

        try {
            const res = await authFetch("/api/research", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    topic,
                    max_iterations: maxIterationsSetting,
                    max_subagents: maxSubagentsSetting,
                    run_id: generatedRunId
                }),
                signal: activeChatAbortController.signal
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || "Server error");
            }
            const { run_id, chat_id } = await res.json();
            // Update activeItem attributes
            const el = document.getElementById(`sidebar-run-${activeRunId}`);
            if (el) {
                el.setAttribute("data-chat-id", chat_id);
            }
            connectSSE(run_id);

        } catch (err) {
            resetState();

            if (err.name === "AbortError") {
                idleWelcome.innerHTML = `
                    <div class="welcome-text" style="text-align: center;">
                        <h2 style="font-size: 24px; font-weight: 500; margin-bottom: 12px; color: var(--text-muted);">Research Cancelled</h2>
                        <p style="color: var(--text-muted); font-size: 14px;">The research plan generation was cancelled before completion.</p>
                        <button class="btn-primary" id="reset-cancel-btn" style="margin-top:20px;padding:8px 16px;font-size:13px;background:#333;color:#fff;border:1px solid #444;border-radius:6px;cursor:pointer">New Research</button>
                    </div>`;
                const resetBtn = document.getElementById("reset-cancel-btn");
                if (resetBtn) {
                    resetBtn.addEventListener("click", () => {
                        resetState();
                    });
                }
            } else {
                showToast("Cannot Start Research", formatUserFriendlyError(err.message));
            }
        } finally {
            activeChatAbortController = null;
        }
    });

    // ── Stop / Cancel ─────────────────────────────────────────────────────────
    stopResearchBtn.addEventListener("click", async () => {
        if (activeChatAbortController) {
            activeChatAbortController.abort();
            activeChatAbortController = null;
        }
        if (currentRunId) {
            try {
                authFetch(`/api/research/cancel/${currentRunId}`, { method: "POST" });
            } catch (err) {
                // Silent catch
            }
        }
        // Immediately trigger local UI cancellation cleanup
        handleCancelled({ message: "Research stopped by user" });
    });

    // ── Start Research (plan approved) ────────────────────────────────────────
    startResearchBtn.addEventListener("click", async () => {
        if (!currentRunId) return;
        startResearchBtn.disabled = true;
        editPlanBtn.disabled = true;
        try {
            await authFetch(`/api/research/resume/${currentRunId}`, { method: "POST" });
        } catch (err) {
            alert(`Could not resume: ${err.message}`);
            startResearchBtn.disabled = false;
            editPlanBtn.disabled = false;
            return;
        }

        activeRunStatus = "running";
        const el = document.getElementById(`sidebar-run-${activeRunId}`);
        if (el) {
            const titleEl = el.querySelector(".recent-item-title");
            if (titleEl) titleEl.textContent = `Researching: ${activeRunTopic}...`;
        }

        // Open right panel
        openViewer(currentTopic);

        // Swap send→stop buttons
        sendQueryBtn.classList.add("hidden");
        stopResearchBtn.classList.remove("hidden");
    });

    // ── Edit Plan (toggles textarea for task editing - cosmetic) ──────────────
    editPlanBtn.addEventListener("click", () => {
        // Expand bullets to show all tasks
        renderPlanBullets(planTasks.length);
        bulletsMoreBtn.classList.add("hidden");
        editPlanBtn.textContent = "Done";
        editPlanBtn.onclick = () => { editPlanBtn.textContent = "Edit plan"; editPlanBtn.onclick = null; };
    });

    if (toggleThinkingBtn) {
        toggleThinkingBtn.addEventListener("click", () => {
            isThinkingHidden = !isThinkingHidden;
            const label = toggleThinkingBtn.querySelector("span:first-child");
            const arrow = toggleThinkingBtn.querySelector(".arrow");
            if (isThinkingHidden) {
                thinkingArea.classList.add("hidden");
                if (label) label.textContent = "Show thinking";
                if (arrow) arrow.style.transform = "rotate(0deg)";
            } else {
                thinkingArea.classList.remove("hidden");
                if (label) label.textContent = "Hide thinking";
                if (arrow) arrow.style.transform = "rotate(180deg)";
            }
        });
    }

    // ── Close viewer ──────────────────────────────────────────────────────────
    closeViewerBtn.addEventListener("click", () => {
        researchViewer.classList.add("collapsed");
    });

    // Dropdown DOM refs
    const exportBtn = document.getElementById("export-dropdown-btn");
    const exportMenu = document.getElementById("export-menu");
    const createBtn = document.getElementById("create-dropdown-btn");
    const createMenu = document.getElementById("create-menu");

    const copyBtn = document.getElementById("export-copy-btn");
    const exportMdBtn = document.getElementById("export-md-btn");
    const createSummaryBtn = document.getElementById("create-summary-btn");
    const createOutlineBtn = document.getElementById("create-outline-btn");

    // ── Outline dropdown ──────────────────────────────────────────────────────
    contentsBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        contentsMenu.classList.toggle("hidden");
        exportMenu.classList.add("hidden");
        createMenu.classList.add("hidden");
    });

    // ── Export dropdown ───────────────────────────────────────────────────────
    if (exportBtn && exportMenu) {
        exportBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            exportMenu.classList.toggle("hidden");
            contentsMenu.classList.add("hidden");
            createMenu.classList.add("hidden");
        });
    }

    // ── Create dropdown ───────────────────────────────────────────────────────
    if (createBtn && createMenu) {
        createBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            createMenu.classList.toggle("hidden");
            contentsMenu.classList.add("hidden");
            exportMenu.classList.add("hidden");
        });
    }

    // Close all menus when clicking outside
    document.addEventListener("click", () => {
        contentsMenu.classList.add("hidden");
        if (exportMenu) exportMenu.classList.add("hidden");
        if (createMenu) createMenu.classList.add("hidden");
    });

    // ── Copy to clipboard ─────────────────────────────────────────────────────
    if (copyBtn) {
        copyBtn.addEventListener("click", () => {
            navigator.clipboard.writeText(currentReportMarkdown || reportContent.textContent);
            showToast("Copied to Clipboard", "Report content copied successfully.");
        });
    }

    // ── Export as markdown file ───────────────────────────────────────────────
    if (exportMdBtn) {
        exportMdBtn.addEventListener("click", () => {
            const md = currentReportMarkdown || reportContent.textContent;
            const blob = new Blob([md], { type: "text/markdown" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `${(currentTopic || "sentinel-brief").toLowerCase().replace(/[^a-z0-9]+/g, "-")}-report.md`;
            a.click();
            URL.revokeObjectURL(url);
            showToast("Exported to Markdown", "Markdown report downloaded successfully.");
        });
    }

    // ── Create Document Summary ───────────────────────────────────────────────
    if (createSummaryBtn) {
        createSummaryBtn.addEventListener("click", () => {
            // Generate a summary locally from the markdown
            const lines = (currentReportMarkdown || reportContent.textContent).split("\n");
            const headers = lines.filter(l => l.startsWith("#") || l.startsWith("##") || l.startsWith("###")).map(l => l.replace(/#/g, "").trim());
            const bulletSummary = headers.slice(0, 6).map(h => `• **${h}**: Synthesized key findings and operational vectors.`).join("\n\n");

            // Create a temporary modal to present the summary
            const summaryOverlay = document.createElement("div");
            summaryOverlay.className = "modal-overlay active";
            summaryOverlay.innerHTML = `
                <div class="modal-content" style="max-width: 600px;">
                    <div class="modal-header">
                        <div class="modal-title">
                            <span>Document Summary: ${escHtml(currentTopic || "Report")}</span>
                        </div>
                        <button class="modal-close-btn" id="summary-close-x">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <line x1="18" y1="6" x2="6" y2="18"></line>
                                <line x1="6" y1="6" x2="18" y2="18"></line>
                            </svg>
                        </button>
                    </div>
                    <div class="modal-body" style="line-height: 1.6; font-size: 14px; color: var(--text-secondary); max-height: 400px; overflow-y: auto;">
                        <h4 style="color: var(--text-primary); margin-bottom: 12px;">Executive Overview</h4>
                        <p style="margin-bottom: 20px;">This intelligence brief details the core technical parameters, supply-chain configurations, and strategic positioning of the subject area. Key analytical pillars include:</p>
                        <div style="background-color: var(--bg-card); padding: 16px; border-radius: 8px; border: 1px solid var(--border-card);">
                            ${typeof marked !== "undefined" ? marked.parse(bulletSummary) : bulletSummary}
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn-primary" id="summary-close-btn" style="padding: 8px 16px; font-size: 13px; background:#333; color:#fff; border:1px solid #444; border-radius:6px; cursor:pointer">Close</button>
                    </div>
                </div>`;
            document.body.appendChild(summaryOverlay);

            const closeX = summaryOverlay.querySelector("#summary-close-x");
            const closeBtn = summaryOverlay.querySelector("#summary-close-btn");
            const closeSummary = () => summaryOverlay.remove();
            closeX.addEventListener("click", closeSummary);
            closeBtn.addEventListener("click", closeSummary);
        });
    }

    // ── Create Presentation Outline ───────────────────────────────────────────
    if (createOutlineBtn) {
        createOutlineBtn.addEventListener("click", () => {
            const lines = (currentReportMarkdown || reportContent.textContent).split("\n");
            const headers = lines.filter(l => l.startsWith("#") || l.startsWith("##") || l.startsWith("###")).map(l => l.replace(/#/g, "").trim());
            const slides = headers.slice(0, 5).map((h, idx) => `
                <div style="border-bottom: 1px solid var(--border-main); padding-bottom: 16px; margin-bottom: 16px;">
                    <strong style="color: var(--text-link); font-size: 12px; text-transform: uppercase;">Slide ${idx + 1}: ${h}</strong>
                    <div style="font-size: 14px; color: var(--text-primary); font-weight: 500; margin-top: 4px;">Key Talking Points</div>
                    <ul style="margin: 8px 0 0 20px; padding: 0; font-size: 13px; color: var(--text-secondary);">
                        <li>Introduce strategic significance and physical configurations of ${h}.</li>
                        <li>Address critical infrastructure requirements and utility dependencies.</li>
                        <li>Recommend structural vectors for localized policy enhancements.</li>
                    </ul>
                </div>
            `).join("");

            const outlineOverlay = document.createElement("div");
            outlineOverlay.className = "modal-overlay active";
            outlineOverlay.innerHTML = `
                <div class="modal-content" style="max-width: 600px;">
                    <div class="modal-header">
                        <div class="modal-title">
                            <span>Presentation Outline: ${escHtml(currentTopic || "Report")}</span>
                        </div>
                        <button class="modal-close-btn" id="outline-close-x">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <line x1="18" y1="6" x2="6" y2="18"></line>
                                <line x1="6" y1="6" x2="18" y2="18"></line>
                            </svg>
                        </button>
                    </div>
                    <div class="modal-body" style="line-height: 1.6; font-size: 14px; color: var(--text-secondary); max-height: 400px; overflow-y: auto;">
                        ${slides}
                    </div>
                    <div class="modal-footer">
                        <button class="btn-primary" id="outline-close-btn" style="padding: 8px 16px; font-size: 13px; background:#333; color:#fff; border:1px solid #444; border-radius:6px; cursor:pointer">Close</button>
                    </div>
                </div>`;
            document.body.appendChild(outlineOverlay);

            const closeX = outlineOverlay.querySelector("#outline-close-x");
            const closeBtn = outlineOverlay.querySelector("#outline-close-btn");
            const closeOutline = () => outlineOverlay.remove();
            closeX.addEventListener("click", closeOutline);
            closeBtn.addEventListener("click", closeOutline);
        });
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // SSE
    // ═══════════════════════════════════════════════════════════════════════════
    function connectSSE(runId) {
        if (eventSource) eventSource.close();
        eventSource = new EventSource(`/api/stream/${runId}?token=${encodeURIComponent(session.access_token)}`);

        eventSource.onmessage = (e) => {
            let event;
            try { event = JSON.parse(e.data); } catch { return; }

            switch (event.type) {
                case "plan_ready": handlePlanReady(event.data); break;
                case "log": handleLog(event.data); break;
                case "status": handleStatus(event.data); break;
                case "data":       /* intel counter — sources come via logs */ break;
                case "complete": handleComplete(event.data); break;
                case "cancelled": handleCancelled(event.data); break;
                case "error": handleError(event.data); break;
            }
        };

        eventSource.onerror = () => {
            // Browser retries automatically; don't close
        };
    }

    // ── plan_ready ────────────────────────────────────────────────────────────
    function handlePlanReady(data) {
        // Hide loader inside bubble, show plan contents
        const loader = document.getElementById("plan-generation-loader");
        if (loader) loader.classList.add("hidden");
        const introText = activeChatContent.querySelector(".message-intro-text");
        if (introText) introText.classList.remove("hidden");
        const planCard = activeChatContent.querySelector(".plan-card");
        if (planCard) planCard.classList.remove("hidden");

        idleWelcome.classList.add("hidden");

        activeRunStatus = "plan_approved_pending";
        const el = document.getElementById(`sidebar-run-${activeRunId}`);
        if (el) {
            const titleEl = el.querySelector(".recent-item-title");
            if (titleEl) titleEl.textContent = `Approve Plan: ${activeRunTopic}`;
        }

        // Populate user bubble
        userQueryBubble.textContent = data.topic || currentTopic;

        // Populate plan card
        planTitle.textContent = data.topic || currentTopic;
        planTasks = data.tasks || [];
        renderPlanBullets(2);

        if (planTasks.length > 2) {
            bulletsMoreBtn.textContent = `+ ${planTasks.length - 2} more angles`;
            bulletsMoreBtn.classList.remove("hidden");
        } else {
            bulletsMoreBtn.classList.add("hidden");
        }

        // Show chat section with plan card
        activeChatContent.classList.remove("hidden");

        // Reset plan step highlights
        setStepClass("step-websites", "plan-step active");
        setStepClass("step-analyze", "plan-step");
        setStepClass("step-report", "plan-step");
        setStepClass("step-ready", "plan-step");

        // Swap stop button to send button so user can edit and review the plan
        stopResearchBtn.classList.add("hidden");
        sendQueryBtn.classList.remove("hidden");
        sendQueryBtn.disabled = false;
        sendQueryBtn.style.opacity = "1";
    }

    bulletsMoreBtn.addEventListener("click", () => {
        renderPlanBullets(planTasks.length);
        bulletsMoreBtn.classList.add("hidden");
    });

    function renderPlanBullets(limit) {
        planBullets.innerHTML = "";
        planTasks.slice(0, limit).forEach((task, i) => {
            const d = document.createElement("div");
            d.className = "bullet-item";
            d.textContent = `(${i + 1}) ${task.task}`;
            planBullets.appendChild(d);
        });
    }

    // ── log ───────────────────────────────────────────────────────────────────
    function handleLog(data) {
        const msg = data.message || "";
        if (!msg) return;

        // Reveal logs pane
        thinkingSkeleton.classList.add("hidden");
        thinkingLogs.classList.remove("hidden");

        const node = (data.node || "engine").toUpperCase().replace(/_/g, " ");

        const item = document.createElement("div");
        item.className = "thinking-log-item";
        item.innerHTML = `
            <div class="thinking-node-header">
                <span class="thinking-node-icon">✦</span>
                <span>${escHtml(node)}</span>
            </div>
            <div class="thinking-node-desc">${escHtml(msg)}</div>`;
        thinkingLogs.appendChild(item);

        // Auto-scroll viewer body
        const vb = researchViewer.querySelector(".viewer-body");
        if (vb) vb.scrollTop = vb.scrollHeight;

        // Extract any URLs for live source cards
        extractUrls(msg);
    }

    // ── status ────────────────────────────────────────────────────────────────
    function handleStatus(data) {
        const node = data.node || "";
        if (node === "subagent") {
            setStepClass("step-websites", "plan-step active");
            setStepClass("step-analyze", "plan-step");
        } else if (["cross_examiner", "timeline_compiler", "sufficiency_evaluator"].includes(node)) {
            setStepClass("step-websites", "plan-step completed");
            setStepClass("step-analyze", "plan-step active");
        } else if (["synthesis", "citation_agent"].includes(node)) {
            setStepClass("step-websites", "plan-step completed");
            setStepClass("step-analyze", "plan-step completed");
            setStepClass("step-report", "plan-step active");
        }
    }

    // ── complete ──────────────────────────────────────────────────────────────
    function handleComplete(data) {
        closeSSE();

        const el = document.getElementById(`sidebar-run-${currentRunId}`);
        const chatId = el ? el.getAttribute("data-chat-id") : null;
        if (el) el.remove();
        activeRunId = null;
        activeRunStatus = "idle";

        setStepClass("step-websites", "plan-step completed");
        setStepClass("step-analyze", "plan-step completed");
        setStepClass("step-report", "plan-step completed");
        setStepClass("step-ready", "plan-step completed");
        const readyText = document.getElementById("step-ready-text");
        if (readyText) readyText.textContent = "Research complete ✓";

        stopResearchBtn.classList.add("hidden");
        sendQueryBtn.classList.remove("hidden");
        sendQueryBtn.disabled = false;
        sendQueryBtn.style.opacity = "1";

        if (data.final_report) {
            renderReport(data.final_report);
        } else {
            reportContent.innerHTML = `<div class="error-banner">No report generated. Check server logs.</div>`;
            reportContent.classList.remove("hidden");
        }

        loadBriefHistory().then(briefs => {
            if (briefs && briefs.length) {
                const newBrief = briefs.find(b => b.run_id === chatId || b.run_id === currentRunId) || briefs[0];
                if (newBrief) {
                    loadBriefContent(newBrief.filename);
                }
            }
        });
    }

    // ── cancelled ─────────────────────────────────────────────────────────────
    function handleCancelled(data) {
        closeSSE();

        const el = document.getElementById(`sidebar-run-${currentRunId}`);
        if (el) el.remove();

        // Also remove any general loading skeleton items
        const skeletons = recentBriefsList.querySelectorAll(".loading-skeleton-item");
        skeletons.forEach(s => s.remove());

        activeRunId = null;
        activeRunStatus = "idle";

        startResearchBtn.disabled = false;
        editPlanBtn.disabled = false;

        stopResearchBtn.classList.add("hidden");
        sendQueryBtn.classList.remove("hidden");
        sendQueryBtn.disabled = false;
        sendQueryBtn.style.opacity = "1";
        thinkingSkeleton.classList.add("hidden");

        const msg = data.message || "Research cancelled by user";
        // Check if banner already exists to avoid duplication
        if (!thinkingLogs.querySelector(".cancellation-banner")) {
            const banner = document.createElement("div");
            banner.className = "cancellation-banner";
            banner.innerHTML = `${escHtml(msg)}`;
            thinkingLogs.appendChild(banner);
            thinkingLogs.classList.remove("hidden");
        }

        // If the viewer is hidden, show cancel state on the left
        if (researchViewer.classList.contains("collapsed")) {
            idleWelcome.className = "welcome-screen";
            idleWelcome.innerHTML = `
                <div class="welcome-text" style="text-align:center">
                    <h2 style="font-size:24px;font-weight:500;margin-bottom:12px;color:var(--text-muted)">Research Cancelled</h2>
                    <p style="color:var(--text-muted);font-size:14px">The research plan generation was cancelled before completion.</p>
                    <button class="btn-primary" id="reset-cancel-btn" style="margin-top:20px;padding:8px 16px;font-size:13px;background:#333;color:#fff;border:1px solid #444;border-radius:6px;cursor:pointer">New Research</button>
                </div>`;
            const resetBtn = document.getElementById("reset-cancel-btn");
            if (resetBtn) {
                resetBtn.addEventListener("click", () => {
                    resetState();
                });
            }
        } else {
            // Show cancel status inside report content
            reportContent.innerHTML = `<div class="cancellation-banner">Research was cancelled. Partial findings may be visible above.</div>`;
            reportContent.classList.remove("hidden");
        }
    }


    // ── error ─────────────────────────────────────────────────────────────────
    function handleError(data) {
        closeSSE();
        thinkingSkeleton.classList.add("hidden");

        const el = document.getElementById(`sidebar-run-${currentRunId}`);
        if (el) el.remove();

        // Also remove any general loading skeleton items
        const skeletons = recentBriefsList.querySelectorAll(".loading-skeleton-item");
        skeletons.forEach(s => s.remove());

        activeRunId = null;
        activeRunStatus = "idle";

        startResearchBtn.disabled = false;
        editPlanBtn.disabled = false;

        const errMsg = formatUserFriendlyError(data.error || "Unknown error");
        const banner = document.createElement("div");
        banner.className = "error-banner";
        banner.innerHTML = `${escHtml(errMsg)}`;
        thinkingLogs.appendChild(banner);
        thinkingLogs.classList.remove("hidden");

        // If the viewer is hidden, update the idle/welcome panel to show the error
        if (researchViewer.classList.contains("collapsed")) {
            idleWelcome.innerHTML = `
                <div class="welcome-text" style="text-align:center">
                    <h2 style="font-size:24px;font-weight:500;margin-bottom:12px;color:#f87171">Generation Suspended</h2>
                    <p style="color:var(--text-muted);font-size:14px;max-width:500px;margin:0 auto;line-height:1.5">${escHtml(errMsg)}</p>
                    <button class="btn-primary" id="retry-plan-btn" style="margin-top:20px;padding:8px 16px;font-size:13px;background:#333;color:#fff;border:1px solid #444;border-radius:6px;cursor:pointer">Try Again</button>
                </div>`;
            const retryBtn = document.getElementById("retry-plan-btn");
            if (retryBtn) {
                retryBtn.addEventListener("click", () => {
                    resetState();
                });
            }
        } else {
            // If the viewer is open, show the error banner inside the report content area as well!
            reportContent.innerHTML = `<div class="error-banner">${escHtml(errMsg)}</div>`;
            reportContent.classList.remove("hidden");
        }

        stopResearchBtn.classList.add("hidden");
        sendQueryBtn.classList.remove("hidden");
        sendQueryBtn.disabled = false;
        sendQueryBtn.style.opacity = "1";
    }

    function formatUserFriendlyError(errMsg) {
        if (!errMsg) return "An unexpected error occurred. Please try again.";
        const msg = String(errMsg).toLowerCase();
        if (msg.includes("quota") || msg.includes("limit") || msg.includes("exhaust") || msg.includes("429") || msg.includes("credit") || msg.includes("billing")) {
            return "Sentinel is currently handling a high volume of requests. To maintain high-quality analysis, please wait a few moments before starting another run.";
        }
        return errMsg;
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // Helpers
    // ═══════════════════════════════════════════════════════════════════════════

    function openViewer(title) {
        viewerTitle.textContent = title;
        thinkingSkeleton.classList.remove("hidden");
        thinkingLogs.classList.add("hidden");
        sourcesPanel.classList.add("hidden");
        reportContent.classList.add("hidden");
        contentsWrapper.classList.add("hidden");
        isThinkingHidden = false;
        thinkingArea.classList.remove("hidden");
        if (toggleThinkingBtn) {
            const label = toggleThinkingBtn.querySelector("span:first-child");
            const arrow = toggleThinkingBtn.querySelector(".arrow");
            if (label) label.textContent = "Hide thinking";
            if (arrow) arrow.style.transform = "rotate(180deg)";
        }
        researchViewer.classList.remove("collapsed");
    }

    function closeSSE() {
        if (eventSource) { eventSource.close(); eventSource = null; }
    }

    function setStepClass(id, cls) {
        const el = document.getElementById(id);
        if (el) el.className = cls;
    }

    function escHtml(str) {
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function appendChatMessage(sender, text, isLoading = false) {
        if (idleWelcome.classList.contains("welcome-screen")) {
            idleWelcome.classList.remove("welcome-screen");
            idleWelcome.classList.add("chat-history-container");
            idleWelcome.innerHTML = "";
        }

        const div = document.createElement("div");

        if (sender === "user") {
            div.className = "message user-message";
            div.style.alignSelf = "flex-end";
            div.innerHTML = `<div class="message-bubble">${escHtml(text)}</div>`;
            idleWelcome.appendChild(div);
        } else {
            div.className = "message assistant-message";
            if (isLoading) {
                div.id = "qa-loading-bubble";
                div.innerHTML = `
                    <div class="avatar-star">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <ellipse cx="12" cy="12" rx="13.51" ry="6.14" transform="translate(-4.97 12) rotate(-45)"></ellipse>
                            <ellipse cx="12" cy="12" rx="6.14" ry="13.51" transform="translate(-4.97 12) rotate(-45)"></ellipse>
                            <circle cx="12" cy="12" r="0.95"></circle>
                        </svg>
                    </div>
                    <div class="message-content">
                        <div class="qa-loading-bubble-content">
                            <div class="typing-indicator">
                                <span></span>
                                <span></span>
                                <span></span>
                            </div>
                        </div>
                    </div>
                `;
            } else {
                let html = "";
                if (typeof marked !== "undefined") {
                    html = marked.parse(text);
                } else {
                    html = escHtml(text);
                }
                div.innerHTML = `
                    <div class="avatar-star">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <ellipse cx="12" cy="12" rx="13.51" ry="6.14" transform="translate(-4.97 12) rotate(-45)"></ellipse>
                            <ellipse cx="12" cy="12" rx="6.14" ry="13.51" transform="translate(-4.97 12) rotate(-45)"></ellipse>
                            <circle cx="12" cy="12" r="0.95"></circle>
                        </svg>
                    </div>
                    <div class="message-content">
                        <div class="message-text">${html}</div>
                    </div>
                `;
            }
            idleWelcome.appendChild(div);
        }
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return div;
    }

    // Extract URLs from log messages and render source cards
    function extractUrls(msg) {
        const urlRe = /https?:\/\/[^\s"'<>)\]]+/g;
        const matches = msg.match(urlRe);
        if (!matches) return;
        matches.forEach(raw => {
            const url = raw.replace(/[.,;:!?)]+$/, "");
            if (seenUrls.has(url)) return;
            seenUrls.add(url);
            addSourceCard(url);
        });
    }

    function addSourceCard(urlStr) {
        try {
            const u = new URL(urlStr);
            const domain = u.hostname.replace(/^www\./, "");
            let title = u.pathname.split("/").filter(Boolean).pop() || domain;
            title = decodeURIComponent(title).replace(/[-_]/g, " ").replace(/\.[a-z0-9]+$/i, "");
            if (title.length > 26) title = title.slice(0, 24) + "…";
            if (!title.trim()) title = "Source";

            const faviconUrl = `https://www.google.com/s2/favicons?domain=${u.hostname}&sz=32`;

            const card = document.createElement("div");
            card.className = "source-card";
            card.title = urlStr;
            card.onclick = () => window.open(urlStr, "_blank");
            card.innerHTML = `
                <img src="${faviconUrl}" alt="" class="source-favicon"
                     onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 16 16%22><rect width=%2216%22 height=%2216%22 rx=%222%22 fill=%22%23333%22/></svg>'">
                <div class="source-details">
                    <span class="source-title">${escHtml(title)}</span>
                    <span class="source-domain">${escHtml(domain)}</span>
                </div>`;

            sourcesGrid.appendChild(card);
            sourcesPanel.classList.remove("hidden");
        } catch {/* invalid URL */ }
    }

    function renderReport(markdown) {
        currentReportMarkdown = markdown;
        let displayMarkdown = markdown;
        const titleMatch = markdown.match(/<title>([\s\S]*?)<\/title>/i);
        if (titleMatch) {
            displayMarkdown = markdown.replace(/<title>[\s\S]*?<\/title>/i, "").trim();
        }
        try {
            reportContent.innerHTML = typeof marked !== "undefined"
                ? marked.parse(displayMarkdown)
                : `<pre>${escHtml(displayMarkdown)}</pre>`;
        } catch {
            reportContent.innerHTML = `<pre>${escHtml(displayMarkdown)}</pre>`;
        }
        reportContent.classList.remove("hidden");

        // Build outline
        const headers = reportContent.querySelectorAll("h1, h2, h3");
        contentsMenu.innerHTML = "";
        if (headers.length > 0) {
            contentsWrapper.classList.remove("hidden");
            headers.forEach((h, i) => {
                h.id = `hr-${i}`;
                const item = document.createElement("div");
                item.className = `contents-item level-${h.tagName.toLowerCase()}`;
                item.textContent = h.textContent;
                item.onclick = (ev) => {
                    ev.stopPropagation();
                    contentsMenu.classList.add("hidden");
                    h.scrollIntoView({ behavior: "smooth", block: "start" });
                };
                contentsMenu.appendChild(item);
            });
        }
    }

    function showActiveRunView() {
        if (!activeRunId) return;

        // highlight the active loading item in the sidebar
        const items = recentBriefsList.querySelectorAll(".recent-item");
        items.forEach(el => {
            if (el.id === `sidebar-run-${activeRunId}`) {
                el.classList.add("active");
            } else {
                el.classList.remove("active");
            }
        });

        // Set topic
        currentTopic = activeRunTopic;
        currentRunId = activeRunId;

        if (activeRunStatus === "planning") {
            // Restore generating plan UI inside message bubble
            idleWelcome.classList.add("hidden");
            activeChatContent.classList.remove("hidden");
            userQueryBubble.textContent = activeRunTopic;

            const loader = document.getElementById("plan-generation-loader");
            if (loader) loader.classList.remove("hidden");
            const introText = activeChatContent.querySelector(".message-intro-text");
            if (introText) introText.classList.add("hidden");
            const planCard = activeChatContent.querySelector(".plan-card");
            if (planCard) planCard.classList.add("hidden");

            // Open viewer
            openViewer(activeRunTopic);
            thinkingSkeleton.classList.remove("hidden");
            thinkingLogs.classList.add("hidden");
            reportContent.classList.add("hidden");
            contentsWrapper.classList.add("hidden");

            // Swap send to stop button to make plan generation interruptible
            sendQueryBtn.classList.add("hidden");
            stopResearchBtn.classList.remove("hidden");
            stopResearchBtn.disabled = false;
            stopResearchBtn.style.opacity = "1";
        } else if (activeRunStatus === "plan_approved_pending") {
            // Restore plan review UI
            idleWelcome.classList.add("hidden");
            activeChatContent.classList.remove("hidden");

            const loader = document.getElementById("plan-generation-loader");
            if (loader) loader.classList.add("hidden");
            const introText = activeChatContent.querySelector(".message-intro-text");
            if (introText) introText.classList.remove("hidden");
            const planCard = activeChatContent.querySelector(".plan-card");
            if (planCard) planCard.classList.remove("hidden");

            userQueryBubble.textContent = activeRunTopic;
            planTitle.textContent = activeRunTopic;
            renderPlanBullets(2);

            if (planTasks.length > 2) {
                bulletsMoreBtn.textContent = `+ ${planTasks.length - 2} more angles`;
                bulletsMoreBtn.classList.remove("hidden");
            } else {
                bulletsMoreBtn.classList.add("hidden");
            }

            openViewer(activeRunTopic);
            thinkingSkeleton.classList.remove("hidden");
            thinkingLogs.classList.add("hidden");
            reportContent.classList.add("hidden");
            contentsWrapper.classList.add("hidden");

            // Swap stop to send button for plan approval
            stopResearchBtn.classList.add("hidden");
            sendQueryBtn.classList.remove("hidden");
            sendQueryBtn.disabled = false;
            sendQueryBtn.style.opacity = "1";
        } else if (activeRunStatus === "running") {
            // Restore running research UI
            idleWelcome.classList.add("hidden");
            activeChatContent.classList.remove("hidden");

            userQueryBubble.textContent = activeRunTopic;
            planTitle.textContent = activeRunTopic;
            renderPlanBullets(planTasks.length);
            bulletsMoreBtn.classList.add("hidden");

            openViewer(activeRunTopic);
            if (thinkingLogs.children.length > 0) {
                thinkingSkeleton.classList.add("hidden");
                thinkingLogs.classList.remove("hidden");
            } else {
                thinkingSkeleton.classList.remove("hidden");
                thinkingLogs.classList.add("hidden");
            }
            reportContent.classList.add("hidden");
            contentsWrapper.classList.add("hidden");

            // Swap send to stop
            sendQueryBtn.classList.add("hidden");
            stopResearchBtn.classList.remove("hidden");
        }
    }

    function resetState(clearLocalStorage = true) {
        closeSearchView();
        closeSSE();
        currentRunId = null;
        seenUrls.clear();
        planTasks = [];
        currentReportMarkdown = "";
        currentBriefFilename = "";

        startResearchBtn.disabled = false;
        editPlanBtn.disabled = false;

        if (clearLocalStorage) {
            const activeChatKey = session ? `sentinel_active_chat_${session.user.id}` : "sentinel_active_chat";
            localStorage.removeItem(activeChatKey);
        }

        // Reset chat area
        idleWelcome.className = "welcome-screen";
        idleWelcome.innerHTML = `
            <div class="welcome-text" style="text-align:center">
                <h2 style="font-size:24px;font-weight:500;margin-bottom:12px">Research anything with Sentinel</h2>
                <p style="color:var(--text-muted);font-size:14px">Sentinel synthesizes no-bluff intelligence briefs with complete data and citations.</p>
            </div>`;
        activeChatContent.classList.add("hidden");
        userQueryBubble.textContent = "";

        const loader = document.getElementById("plan-generation-loader");
        if (loader) loader.classList.add("hidden");
        const introText = activeChatContent.querySelector(".message-intro-text");
        if (introText) introText.classList.remove("hidden");
        const planCard = activeChatContent.querySelector(".plan-card");
        if (planCard) planCard.classList.remove("hidden");

        // Remove any loading skeleton items in the sidebar
        const activeItems = recentBriefsList.querySelectorAll(".loading-skeleton-item");
        activeItems.forEach(el => el.remove());

        // Reset viewer
        researchViewer.classList.add("collapsed");
        thinkingLogs.innerHTML = "";
        sourcesGrid.innerHTML = "";
        reportContent.innerHTML = "";
        contentsMenu.innerHTML = "";
        thinkingSkeleton.classList.remove("hidden");
        thinkingLogs.classList.add("hidden");
        sourcesPanel.classList.add("hidden");
        reportContent.classList.add("hidden");
        contentsWrapper.classList.add("hidden");
        isThinkingHidden = false;

        // Reset buttons
        stopResearchBtn.classList.add("hidden");
        sendQueryBtn.classList.remove("hidden");
        sendQueryBtn.disabled = false;
        sendQueryBtn.style.opacity = "1";

        // Reset plan steps
        ["step-websites", "step-analyze", "step-report", "step-ready"].forEach(id => setStepClass(id, "plan-step"));
        const rt = document.getElementById("step-ready-text");
        if (rt) rt.textContent = "Ready in a few mins";
        planBullets.innerHTML = "";
        bulletsMoreBtn.classList.add("hidden");
    }

    // ── Brief history ─────────────────────────────────────────────────────────
    async function loadBriefHistory() {
        try {
            const res = await authFetch("/api/briefs");
            if (!res.ok) throw new Error("fetch failed");
            const briefs = await res.json();
            recentBriefs = briefs;
            recentBriefsList.innerHTML = "";

            if (activeRunId) {
                const activeItem = document.createElement("div");
                activeItem.className = "recent-item loading-skeleton-item active";
                activeItem.id = `sidebar-run-${activeRunId}`;
                let statusText = "Researching...";
                if (activeRunStatus === "planning") {
                    statusText = `Researching: ${activeRunTopic}...`;
                } else if (activeRunStatus === "plan_approved_pending") {
                    statusText = `Approve Plan: ${activeRunTopic}`;
                } else if (activeRunStatus === "running") {
                    statusText = `Researching: ${activeRunTopic}...`;
                }
                activeItem.innerHTML = `
                    <span class="recent-item-title skeleton-text-animation">${statusText}</span>
                    <div class="skeleton-spinner"></div>
                `;
                activeItem.onclick = () => showActiveRunView();
                recentBriefsList.appendChild(activeItem);
            }

            if (!briefs.length && !activeRunId) {
                recentBriefsList.innerHTML = `<div class="recent-item loading">No briefs yet</div>`;
                return briefs;
            }
            briefs.forEach(b => {
                const item = document.createElement("div");
                item.className = "recent-item";
                if (currentBriefFilename === b.filename) {
                    item.classList.add("active");
                }
                item.dataset.filename = b.filename;
                item.title = `${b.title} · ${b.date}`;

                item.innerHTML = `
                    <span class="recent-item-title">${escHtml(b.title)}</span>
                    <div class="recent-options-wrapper">
                        <button class="recent-options-btn" title="Options">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                                <circle cx="12" cy="12" r="1.5"></circle>
                                <circle cx="12" cy="5" r="1.5"></circle>
                                <circle cx="12" cy="19" r="1.5"></circle>
                            </svg>
                        </button>
                        <div class="recent-options-menu hidden">
                            <div class="recent-options-item rename-opt">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                                    <path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                                </svg>
                                <span>Rename</span>
                            </div>
                            <div class="recent-options-item delete-opt">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <polyline points="3 6 5 6 21 6"></polyline>
                                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                                </svg>
                                <span>Delete</span>
                            </div>
                        </div>
                    </div>
                `;

                item.querySelector(".recent-item-title").onclick = (e) => {
                    e.stopPropagation();
                    loadBriefContent(b.filename);
                };
                item.onclick = () => loadBriefContent(b.filename);

                const optBtn = item.querySelector(".recent-options-btn");
                const optMenu = item.querySelector(".recent-options-menu");

                optBtn.onclick = (e) => {
                    e.stopPropagation();
                    document.querySelectorAll(".recent-options-menu").forEach(m => {
                        if (m !== optMenu) m.classList.add("hidden");
                    });
                    document.querySelectorAll(".recent-options-btn").forEach(btn => {
                        if (btn !== optBtn) btn.classList.remove("active");
                    });
                    optMenu.classList.toggle("hidden");
                    optBtn.classList.toggle("active");
                };

                const renameOpt = item.querySelector(".rename-opt");
                renameOpt.onclick = (e) => {
                    e.stopPropagation();
                    optMenu.classList.add("hidden");
                    optBtn.classList.remove("active");
                    openRenameModal(b.filename, b.title);
                };

                const deleteOpt = item.querySelector(".delete-opt");
                deleteOpt.onclick = (e) => {
                    e.stopPropagation();
                    optMenu.classList.add("hidden");
                    optBtn.classList.remove("active");
                    openDeleteModal(b.filename, b.title);
                };

                recentBriefsList.appendChild(item);
            });
            return briefs;
        } catch {
            recentBriefsList.innerHTML = `<div class="recent-item loading">Failed to load</div>`;
            return [];
        }
    }

    function setupAssistantMessageActions(messageDiv, textContent) {
        const contentContainer = messageDiv.querySelector(".message-content");
        if (!contentContainer) return;

        if (contentContainer.querySelector(".chat-brief-actions-row")) return;

        const actionsRow = document.createElement("div");
        actionsRow.className = "chat-brief-actions-row";

        actionsRow.innerHTML = `
            <button class="chat-action-icon-btn thumbs-up" title="Thumbs Up">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
                </svg>
            </button>
            <button class="chat-action-icon-btn thumbs-down" title="Thumbs Down">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm10-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/>
                </svg>
            </button>
            <button class="chat-action-icon-btn copy-btn" title="Copy response">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                </svg>
            </button>
            <button class="chat-action-icon-btn more-options-btn" title="More options">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="1"></circle>
                    <circle cx="19" cy="12" r="1"></circle>
                    <circle cx="5" cy="12" r="1"></circle>
                </svg>
            </button>
            
            <div class="chat-actions-menu hidden">
                <div class="chat-actions-item export-btn">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21 15v4a2 2 0 0 1-2-2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>
                    </svg>
                    <span>Export MD</span>
                </div>
            </div>
        `;

        contentContainer.appendChild(actionsRow);

        const upBtn = actionsRow.querySelector(".thumbs-up");
        const downBtn = actionsRow.querySelector(".thumbs-down");
        const copyBtn = actionsRow.querySelector(".copy-btn");
        const moreBtn = actionsRow.querySelector(".more-options-btn");
        const menu = actionsRow.querySelector(".chat-actions-menu");
        const exportBtn = actionsRow.querySelector(".export-btn");

        upBtn.onclick = (e) => {
            e.stopPropagation();
            upBtn.classList.toggle("active");
            downBtn.classList.remove("active");
            showToast("Feedback Submitted", "Thank you for rating this response.");
        };

        downBtn.onclick = (e) => {
            e.stopPropagation();
            downBtn.classList.toggle("active");
            upBtn.classList.remove("active");
            showToast("Feedback Submitted", "Thank you for rating this response.");
        };

        copyBtn.onclick = (e) => {
            e.stopPropagation();
            navigator.clipboard.writeText(textContent).then(() => {
                showToast("Copied", "Response copied to clipboard.");
            });
        };

        moreBtn.onclick = (e) => {
            e.stopPropagation();
            document.querySelectorAll(".chat-actions-menu").forEach(m => {
                if (m !== menu) m.classList.add("hidden");
            });
            menu.classList.toggle("hidden");
        };

        exportBtn.onclick = (e) => {
            e.stopPropagation();
            menu.classList.add("hidden");
            triggerMarkdownDownload("response", textContent);
        };

        document.addEventListener("click", () => {
            menu.classList.add("hidden");
        });
    }

    async function loadBriefContent(filename) {
        closeSearchView();
        if (window.innerWidth <= 768 && sidebarElement) {
            sidebarElement.classList.add("collapsed");
        }
        // Immediately switch smoothly to skeleton loading screen
        idleWelcome.className = "chat-history-container";
        idleWelcome.innerHTML = `
            <div class="chat-skeleton-loader">
                <div class="skeleton-message user-skeleton">
                    <div class="skeleton-bubble"></div>
                </div>
                <div class="skeleton-message assistant-skeleton">
                    <div class="skeleton-avatar"></div>
                    <div class="skeleton-lines">
                        <div class="skeleton-line line-short"></div>
                        <div class="skeleton-line line-card"></div>
                        <div class="skeleton-line line-actions"></div>
                    </div>
                </div>
            </div>
        `;
        chatMessages.scrollTop = 0;

        try {
            const res = await authFetch(`/api/briefs/${filename}`);
            if (!res.ok) throw new Error("not found");
            const { content, chat_history } = await res.json();

            currentBriefFilename = filename;
            const activeChatKey = session ? `sentinel_active_chat_${session.user.id}` : "sentinel_active_chat";
            localStorage.setItem(activeChatKey, filename);

            // Get date metadata and title from history list if possible
            let dateStr = "Just now";
            let title = filename.replace(/\.md$/, "").replace(/[-_]/g, " ");
            const items = recentBriefsList.querySelectorAll(".recent-item");
            items.forEach(el => {
                if (el.dataset.filename === filename) {
                    el.classList.add("active");
                    const titleEl = el.querySelector(".recent-item-title");
                    if (titleEl) {
                        title = titleEl.textContent;
                    }
                    const parts = el.title.split("·");
                    if (parts.length > 1) {
                        dateStr = parts[parts.length - 1].trim();
                    }
                } else {
                    el.classList.remove("active");
                }
            });

            // De-highlight active run item
            const activeRunEl = recentBriefsList.querySelector(".loading-skeleton-item");
            if (activeRunEl) activeRunEl.classList.remove("active");

            currentTopic = title;
            currentReportMarkdown = content;

            // Render brief / conversation history
            idleWelcome.className = "chat-history-container";
            idleWelcome.innerHTML = "";
            activeChatContent.classList.add("hidden");

            let messages = chat_history || [];
            if (messages.length === 0) {
                // Fallback to default user query & assistant brief card if history is empty
                messages = [
                    { role: "user", content: title },
                    { role: "assistant", type: "brief", content: content, date: dateStr }
                ];
            }

            messages.forEach((msg) => {
                if (msg.role === "user") {
                    const div = document.createElement("div");
                    div.className = "message user-message";
                    div.style.alignSelf = "flex-end";
                    div.innerHTML = `<div class="message-bubble">${escHtml(msg.content)}</div>`;
                    idleWelcome.appendChild(div);
                } else {
                    const div = document.createElement("div");
                    div.className = "message assistant-message";

                    if (msg.type === "brief") {
                        div.innerHTML = `
                            <div class="avatar-star">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <ellipse cx="12" cy="12" rx="13.51" ry="6.14" transform="translate(-4.97 12) rotate(-45)"></ellipse>
                                    <ellipse cx="12" cy="12" rx="6.14" ry="13.51" transform="translate(-4.97 12) rotate(-45)"></ellipse>
                                    <circle cx="12" cy="12" r="0.95"></circle>
                                </svg>
                            </div>
                            <div class="message-content">
                                <span class="message-intro-text">I've completed your research. Feel free to ask me follow-up questions or request changes.</span>
                                
                                <div class="chat-brief-card" id="chat-brief-card-click">
                                    <div class="chat-brief-icon">
                                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                            <circle cx="12" cy="12" r="10"></circle>
                                            <line x1="2" y1="12" x2="22" y2="12"></line>
                                            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
                                        </svg>
                                    </div>
                                    <div class="chat-brief-info">
                                        <div class="chat-brief-title" id="chat-brief-title">${escHtml(title)}</div>
                                        <div class="chat-brief-meta">${escHtml(msg.date || dateStr)}</div>
                                    </div>
                                </div>
                                
                                <div class="chat-brief-actions-row">
                                    <button class="chat-action-icon-btn" title="Thumbs Up" id="thumbs-up-btn">
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
                                        </svg>
                                    </button>
                                    <button class="chat-action-icon-btn" title="Thumbs Down" id="thumbs-down-btn">
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm10-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/>
                                        </svg>
                                    </button>
                                    <button class="chat-action-icon-btn" title="Copy report markdown" id="copy-brief-btn">
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                                        </svg>
                                    </button>
                                    <button class="chat-action-icon-btn" title="More options" id="brief-more-options-btn">
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <circle cx="12" cy="12" r="1"></circle>
                                            <circle cx="19" cy="12" r="1"></circle>
                                            <circle cx="5" cy="12" r="1"></circle>
                                        </svg>
                                    </button>
                                    
                                    <div class="chat-actions-menu hidden" id="chat-actions-menu">
                                        <div class="chat-actions-item" id="chat-action-rename">
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                                                <path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                                            </svg>
                                            <span>Rename</span>
                                        </div>
                                        <div class="chat-actions-item" id="chat-action-export">
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                                <path d="M21 15v4a2 2 0 0 1-2-2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>
                                            </svg>
                                            <span>Export MD</span>
                                        </div>
                                        <div class="chat-actions-item delete-item" id="chat-action-delete">
                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                                <polyline points="3 6 5 6 21 6"></polyline>
                                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                                                <line x1="10" y1="11" x2="10" y2="17"></line>
                                                <line x1="14" y1="11" x2="14" y2="17"></line>
                                            </svg>
                                            <span>Delete</span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        `;
                    } else {
                        const cleanContent = msg.content.replace(/<title>[\s\S]*?<\/title>/i, "").trim();
                        let html = "";
                        if (typeof marked !== "undefined") {
                            html = marked.parse(cleanContent);
                        } else {
                            html = escHtml(cleanContent);
                        }
                        div.innerHTML = `
                            <div class="avatar-star">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <ellipse cx="12" cy="12" rx="13.51" ry="6.14" transform="translate(-4.97 12) rotate(-45)"></ellipse>
                                    <ellipse cx="12" cy="12" rx="6.14" ry="13.51" transform="translate(-4.97 12) rotate(-45)"></ellipse>
                                    <circle cx="12" cy="12" r="0.95"></circle>
                                </svg>
                            </div>
                            <div class="message-content">
                                <div class="message-text">${html}</div>
                            </div>
                        `;
                        setupAssistantMessageActions(div, cleanContent);
                    }
                    idleWelcome.appendChild(div);
                }
            });

            // Dynamic event listeners for the brief card
            const clickEl = document.getElementById("chat-brief-card-click");
            if (clickEl) {
                clickEl.addEventListener("click", () => {
                    if (researchViewer.classList.contains("collapsed")) {
                        openViewer(title);
                        thinkingSkeleton.classList.add("hidden");
                        thinkingArea.classList.add("hidden");
                        isThinkingHidden = true;
                        if (toggleThinkingBtn) {
                            const label = toggleThinkingBtn.querySelector("span:first-child");
                            const arrow = toggleThinkingBtn.querySelector(".arrow");
                            if (label) label.textContent = "Show thinking";
                            if (arrow) arrow.style.transform = "rotate(0deg)";
                        }
                        sourcesPanel.classList.add("hidden");
                        renderReport(content);
                    } else {
                        researchViewer.classList.add("collapsed");
                    }
                });
            }

            const thumbsUp = document.getElementById("thumbs-up-btn");
            const thumbsDown = document.getElementById("thumbs-down-btn");
            if (thumbsUp) {
                thumbsUp.addEventListener("click", () => {
                    thumbsUp.classList.toggle("active");
                    if (thumbsDown) thumbsDown.classList.remove("active");
                    showToast("Feedback Submitted", "Thank you for rating this intelligence brief!");
                });
            }
            if (thumbsDown) {
                thumbsDown.addEventListener("click", () => {
                    thumbsDown.classList.toggle("active");
                    if (thumbsUp) thumbsUp.classList.remove("active");
                    showToast("Feedback Submitted", "We will use your rating to improve future briefs.");
                });
            }

            const copyBtn = document.getElementById("copy-brief-btn");
            if (copyBtn) {
                copyBtn.addEventListener("click", () => {
                    navigator.clipboard.writeText(content).then(() => {
                        showToast("Copied to Clipboard", "Intelligence brief markdown copied successfully.");
                    }).catch(() => {
                        showToast("Copy Error", "Unable to copy content.");
                    });
                });
            }

            const moreOptionsBtn = document.getElementById("brief-more-options-btn");
            const actionsMenu = document.getElementById("chat-actions-menu");
            if (moreOptionsBtn && actionsMenu) {
                moreOptionsBtn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    actionsMenu.classList.toggle("hidden");
                });
            }

            document.addEventListener("click", () => {
                if (actionsMenu) actionsMenu.classList.add("hidden");
                document.querySelectorAll(".recent-options-menu").forEach(m => m.classList.add("hidden"));
                document.querySelectorAll(".recent-options-btn").forEach(btn => btn.classList.remove("active"));
            });

            const renameBtn = document.getElementById("chat-action-rename");
            if (renameBtn) {
                renameBtn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    if (actionsMenu) actionsMenu.classList.add("hidden");
                    openRenameModal(filename, title);
                });
            }

            const exportMd = document.getElementById("chat-action-export");
            if (exportMd) {
                exportMd.addEventListener("click", (e) => {
                    e.stopPropagation();
                    if (actionsMenu) actionsMenu.classList.add("hidden");
                    triggerMarkdownDownload(title, content);
                });
            }

            const deleteBtn = document.getElementById("chat-action-delete");
            if (deleteBtn) {
                deleteBtn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    if (actionsMenu) actionsMenu.classList.add("hidden");
                    openDeleteModal(filename, title);
                });
            }

            if (content && content.trim() !== "") {
                openViewer(title);

                // No active thinking for historical briefs
                thinkingSkeleton.classList.add("hidden");
                thinkingArea.classList.add("hidden");
                isThinkingHidden = true;
                if (toggleThinkingBtn) {
                    const label = toggleThinkingBtn.querySelector("span:first-child");
                    const arrow = toggleThinkingBtn.querySelector(".arrow");
                    if (label) label.textContent = "Show thinking";
                    if (arrow) arrow.style.transform = "rotate(0deg)";
                }

                sourcesPanel.classList.add("hidden");
                renderReport(content);
            } else {
                researchViewer.classList.add("collapsed");
            }

            // Auto-scroll chat to bottom
            chatMessages.scrollTop = chatMessages.scrollHeight;

        } catch (err) {
            alert(`Could not load brief: ${err.message}`);
        }
    }

    // ── Toast Notification Helper ─────────────────────────────────────────────
    function showToast(title, message) {
        const oldToast = document.querySelector(".toast-notification");
        if (oldToast) oldToast.remove();

        const toast = document.createElement("div");
        toast.className = "toast-notification";
        toast.innerHTML = `
            <div class="toast-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="16" x2="12" y2="12"></line>
                    <line x1="12" y1="8" x2="12.01" y2="8"></line>
                </svg>
            </div>
            <div class="toast-content">
                <div class="toast-title">${escHtml(title)}</div>
                <div class="toast-message">${escHtml(message)}</div>
            </div>`;
        document.body.appendChild(toast);

        setTimeout(() => toast.classList.add("active"), 50);

        setTimeout(() => {
            toast.classList.remove("active");
            setTimeout(() => toast.remove(), 400);
        }, 4000);
    }

    // ── Settings Dialog Modal ────────────────────────────────────────────────
    if (settingsBtn) {
        settingsBtn.addEventListener("click", () => {
            const oldOverlay = document.querySelector(".modal-overlay");
            if (oldOverlay) oldOverlay.remove();

            const overlay = document.createElement("div");
            overlay.className = "modal-overlay";
            overlay.innerHTML = `
                <div class="modal-content">
                    <div class="modal-header">
                        <div class="modal-title">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <circle cx="12" cy="12" r="3"></circle>
                                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
                            </svg>
                            <span>Engine Configuration</span>
                        </div>
                        <button class="modal-close-btn" id="modal-close-x">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <line x1="18" y1="6" x2="6" y2="18"></line>
                                <line x1="6" y1="6" x2="18" y2="18"></line>
                            </svg>
                        </button>
                    </div>
                    <div class="modal-body">
                        <div class="setting-row">
                            <span class="setting-label">Max Research Iterations</span>
                            <div class="setting-input-wrapper">
                                <input type="number" class="setting-input" id="cfg-iterations" min="1" max="10" value="${maxIterationsSetting}">
                                <span class="setting-description">Depth limit of the orchestrator loop. Higher values allow deeper investigation but consume more resources.</span>
                            </div>
                        </div>
                        <div class="setting-row">
                            <span class="setting-label">Max Parallel Subagents</span>
                            <div class="setting-input-wrapper">
                                <input type="number" class="setting-input" id="cfg-subagents" min="1" max="10" value="${maxSubagentsSetting}">
                                <span class="setting-description">Limit on concurrent search subagents. Tightly controls backend parallelization.</span>
                            </div>
                        </div>
                        <div class="setting-row">
                            <span class="setting-label">Theme Mode</span>
                            <div class="setting-input-wrapper">
                                <select class="setting-input" id="cfg-theme" style="width: 100%; max-width: 200px; padding: 6px; background: #18181b; color: #fff; border: 1px solid #2d2d30; border-radius: 4px;">
                                    <option value="dark" ${!isLightTheme ? 'selected' : ''}>Dark Mode</option>
                                    <option value="light" ${isLightTheme ? 'selected' : ''}>Light Mode</option>
                                </select>
                                <span class="setting-description">Switch between OLED dark mode and clean paper light mode.</span>
                            </div>
                        </div>
                        <div class="setting-row">
                            <span class="setting-label">Research Intelligence Engine</span>
                            <div class="setting-input-wrapper" style="margin-top: 4px;">
                                <span class="status-pill-active">✦ Active & Optimized</span>
                            </div>
                            <span class="setting-description">Sentinel automatically dynamically scales search routing based on queue priority.</span>
                        </div>
                        <div class="setting-row" style="border-top: 1px solid var(--border-card); padding-top: 16px; margin-top: 16px;">
                            <span class="setting-label">Subscription</span>
                            <div class="setting-input-wrapper" style="display: flex; align-items: center; gap: 12px;">
                                <span style="font-size: 13.5px; color: var(--text-secondary);">Sentinel Free Tier</span>
                                <button class="btn-upgrade" id="try-advanced-btn">Try Advanced</button>
                            </div>
                        </div>
                        <div class="setting-row">
                            <span class="setting-label">Account Options</span>
                            <div class="setting-input-wrapper">
                                <button class="btn-danger" id="settings-signout-btn" style="padding: 8px 16px; font-size: 13px; background:#e2566c; color:#fff; border:none; border-radius:6px; cursor:pointer; display:flex; align-items:center; gap:6px;">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
                                        <polyline points="16 17 21 12 16 7"></polyline>
                                        <line x1="21" y1="12" x2="9" y2="12"></line>
                                    </svg>
                                    <span>Log Out</span>
                                </button>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn-primary" id="modal-save-btn" style="padding: 8px 16px; font-size: 13px; background:#333; color:#fff; border:1px solid #444; border-radius:6px; cursor:pointer">Save Changes</button>
                    </div>
                </div>`;
            document.body.appendChild(overlay);

            setTimeout(() => overlay.classList.add("active"), 50);

            const closeX = overlay.querySelector("#modal-close-x");
            const saveBtn = overlay.querySelector("#modal-save-btn");
            const settingsSignout = overlay.querySelector("#settings-signout-btn");

            if (settingsSignout) {
                settingsSignout.addEventListener("click", async () => {
                    overlay.classList.remove("active");
                    setTimeout(() => overlay.remove(), 300);
                    if (supabase) {
                        await supabase.auth.signOut();
                    }
                });
            }

            const closeOverlay = (e) => {
                if (e.target === overlay || closeX.contains(e.target) || saveBtn.contains(e.target)) {
                    overlay.classList.remove("active");
                    setTimeout(() => overlay.remove(), 300);
                }
            };
            overlay.addEventListener("click", closeOverlay);
            closeX.addEventListener("click", closeOverlay);

            saveBtn.addEventListener("click", () => {
                const itVal = parseInt(overlay.querySelector("#cfg-iterations").value) || 1;
                const subVal = parseInt(overlay.querySelector("#cfg-subagents").value) || 3;
                const themeVal = overlay.querySelector("#cfg-theme").value;
                maxIterationsSetting = Math.max(1, Math.min(10, itVal));
                maxSubagentsSetting = Math.max(1, Math.min(10, subVal));

                if (themeVal === "light") {
                    document.body.classList.add("light-theme");
                    isLightTheme = true;
                    localStorage.setItem("theme", "light");
                } else {
                    document.body.classList.remove("light-theme");
                    isLightTheme = false;
                    localStorage.setItem("theme", "dark");
                }

                closeOverlay({ target: saveBtn });
                showToast("Configuration Saved", `Depth limit set to ${maxIterationsSetting}, parallel subagents set to ${maxSubagentsSetting}, theme set to ${themeVal}.`);
            });
        });
    }

    function openRenameModal(filename, currentTitle) {
        const oldOverlay = document.querySelector(".modal-overlay");
        if (oldOverlay) oldOverlay.remove();

        const overlay = document.createElement("div");
        overlay.className = "modal-overlay";
        overlay.innerHTML = `
            <div class="modal-content" style="max-width: 400px;">
                <div class="modal-header">
                    <div class="modal-title">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                            <path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                        </svg>
                        <span>Rename Brief</span>
                    </div>
                    <button class="modal-close-btn" id="rename-close-x">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"></line>
                            <line x1="6" y1="6" x2="18" y2="18"></line>
                        </svg>
                    </button>
                </div>
                <div class="modal-body" style="padding: 16px 20px;">
                    <div style="display: flex; flex-direction: column; gap: 8px; width: 100%;">
                        <label style="font-size: 13px; font-weight: 500; color: var(--text-secondary);">New Title</label>
                        <input type="text" id="rename-input" class="setting-input" value="${escHtml(currentTitle)}" style="width: 100%; padding: 8px; border: 1px solid var(--border-card); border-radius: 6px; background: var(--bg-card); color: var(--text-primary); font-family: var(--font-sans); outline: none;">
                    </div>
                </div>
                <div class="modal-footer" style="padding: 12px 20px;">
                    <button class="btn-primary" id="rename-save-btn" style="padding: 8px 16px; font-size: 13px; background: var(--text-link); color: #fff; border: none; border-radius: 6px; cursor: pointer; font-weight: 600;">Save Title</button>
                </div>
            </div>`;
        document.body.appendChild(overlay);

        setTimeout(() => overlay.classList.add("active"), 50);

        const closeX = overlay.querySelector("#rename-close-x");
        const saveBtn = overlay.querySelector("#rename-save-btn");
        const input = overlay.querySelector("#rename-input");

        const closeOverlay = () => {
            overlay.classList.remove("active");
            setTimeout(() => overlay.remove(), 300);
        };

        overlay.addEventListener("click", (e) => {
            if (e.target === overlay) closeOverlay();
        });
        closeX.addEventListener("click", closeOverlay);

        input.focus();
        input.select();
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                saveBtn.click();
            }
        });

        saveBtn.addEventListener("click", async () => {
            const newTitle = input.value.trim();
            if (!newTitle) return;
            saveBtn.disabled = true;
            saveBtn.textContent = "Saving...";

            try {
                const res = await authFetch(`/api/briefs/${filename}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ new_title: newTitle })
                });

                if (!res.ok) {
                    const errData = await res.json();
                    throw new Error(errData.detail || "Rename failed");
                }

                const result = await res.json();
                showToast("Brief Renamed", `Saved title as "${newTitle}".`);
                closeOverlay();

                const nextFilename = result.new_filename || filename;
                currentBriefFilename = nextFilename;
                loadBriefHistory().then(() => {
                    loadBriefContent(nextFilename);
                });

            } catch (err) {
                showToast("Rename Error", err.message);
                saveBtn.disabled = false;
                saveBtn.textContent = "Save Title";
            }
        });
    }

    function openDeleteModal(filename, currentTitle) {
        // Prevent deletion of that chat if it has any generation ongoing
        const isGenerating = (activeChatAbortController !== null || (activeRunStatus && activeRunStatus !== "idle") || currentRunId);
        if (isGenerating && currentBriefFilename === filename) {
            showToast("Cannot Delete Chat", "This session has an ongoing generation. Please stop the generation or wait for it to complete.");
            return;
        }

        const oldOverlay = document.querySelector(".modal-overlay");
        if (oldOverlay) oldOverlay.remove();

        const overlay = document.createElement("div");
        overlay.className = "modal-overlay";
        overlay.innerHTML = `
            <div class="modal-content" style="max-width: 400px;">
                <div class="modal-header">
                    <div class="modal-title" style="color: #E2566C;">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                        <span>Delete Chat</span>
                    </div>
                    <button class="modal-close-btn" id="delete-close-x">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"></line>
                            <line x1="6" y1="6" x2="18" y2="18"></line>
                        </svg>
                    </button>
                </div>
                <div class="modal-body" style="padding: 16px 20px;">
                    <p style="font-size: 13.5px; color: var(--text-secondary); line-height: 1.5; margin: 0;">
                        Are you sure you want to delete <strong>${escHtml(currentTitle)}</strong>? This action cannot be undone.
                    </p>
                </div>
                <div class="modal-footer" style="padding: 12px 20px; display: flex; justify-content: flex-end; gap: 8px;">
                    <button class="btn-secondary" id="delete-cancel-btn" style="padding: 8px 16px; font-size: 13px; background: transparent; color: var(--text-secondary); border: 1px solid var(--border-card); border-radius: 6px; cursor: pointer; font-weight: 500;">Cancel</button>
                    <button class="btn-danger" id="delete-confirm-btn" style="padding: 8px 16px; font-size: 13px; background: #E2566C; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-weight: 600;">Delete</button>
                </div>
            </div>`;
        document.body.appendChild(overlay);

        setTimeout(() => overlay.classList.add("active"), 50);

        const closeX = overlay.querySelector("#delete-close-x");
        const cancelBtn = overlay.querySelector("#delete-cancel-btn");
        const confirmBtn = overlay.querySelector("#delete-confirm-btn");

        const closeOverlay = () => {
            overlay.classList.remove("active");
            setTimeout(() => overlay.remove(), 300);
        };

        overlay.addEventListener("click", (e) => {
            if (e.target === overlay) closeOverlay();
        });
        closeX.addEventListener("click", closeOverlay);
        cancelBtn.addEventListener("click", closeOverlay);

        confirmBtn.addEventListener("click", async () => {
            confirmBtn.disabled = true;
            confirmBtn.textContent = "Deleting...";
            try {
                const delRes = await authFetch(`/api/briefs/${filename}`, { method: "DELETE" });
                if (!delRes.ok) throw new Error("Delete failed");
                showToast("Brief Deleted", `"${currentTitle}" was removed.`);
                closeOverlay();
                if (currentBriefFilename === filename) {
                    currentBriefFilename = "";
                    resetState();
                }
                loadBriefHistory();
            } catch (err) {
                showToast("Delete Error", err.message);
                confirmBtn.disabled = false;
                confirmBtn.textContent = "Delete";
            }
        });
    }

    function triggerMarkdownDownload(title, content) {
        const blob = new Blob([content], { type: "text/markdown;charset=utf-8;" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.setAttribute("download", `${title.replace(/\s+/g, "_").toLowerCase()}_report.md`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        showToast("Markdown Exported", "Report downloaded successfully.");
    }

});
