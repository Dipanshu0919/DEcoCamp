// --- Helper Functions ---
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);
const toggleDisplay = (el, show) => el && (el.style.display = show ? 'inline' : 'none');

const toggleElements = (showEls, hideEls) => {
    showEls.forEach(el => toggleDisplay(el, true));
    hideEls.forEach(el => toggleDisplay(el, false));
};

// --- Alert System ---
function showAlert(message, type = 'info', duration = 5000, showButtons = false) {
    const alertBar = $('#alertBar');
    const alertText = $('#alertText');
    const alertButtons = $('#alertButtons');
    const alertCloseBtn = $('#alertCloseBtn');

    if(!alertBar) return;

    alertText.textContent = message;
    alertBar.classList.remove('success', 'info', 'warning', 'error');
    if (type !== 'info') alertBar.classList.add(type);

    if (type === 'success' && showButtons) {
        alertButtons.style.display = 'flex';
        alertCloseBtn.style.display = 'none';
        duration = 0;
    } else {
        alertButtons.style.display = 'none';
        alertCloseBtn.style.display = 'block';
    }

    alertBar.classList.add('show');
    if (duration > 0) setTimeout(closeAlert, duration);
}

const closeAlert = () => $('#alertBar')?.classList.remove('show');

// --- UI Interactions ---
function openeventchat(eventid) {
    const drawer = $('#sideChatDrawer');
    const iframe = $('#globalChatIframe');
    iframe.src = `/group-chat/from-event/${eventid}`;
    drawer.classList.add('open');
}

function closeEventChat() {
    $('#sideChatDrawer').classList.remove('open');
    setTimeout(() => $('#globalChatIframe').src = '', 400);
}

function toggleDescription(id, action) {
    const shortDesc = $(`#desc-short-${id}`);
    const fullDesc = $(`#desc-full-${id}`);
    const moreBtn = $(`#read-more-btn-${id}`);
    const lessBtn = $(`#read-less-btn-${id}`);
    if (action === 'more') { toggleElements([fullDesc, lessBtn], [shortDesc, moreBtn]); }
    else { toggleElements([shortDesc, moreBtn], [fullDesc, lessBtn]); }
}

function togglePasswordVisibility(id) {
    const field = $(`#${id}`);
    if (field) field.type = field.type === 'password' ? 'text' : 'password';
}

function filterCampaigns(searchInput) {
    const filter = searchInput.value.toLowerCase();
    const categoryWrapper = searchInput.closest('.campaign-category-wrapper');
    if (!categoryWrapper) return;
    categoryWrapper.querySelectorAll('.campaign-card').forEach(card => {
        card.classList.toggle('search-hidden', !card.innerText.toLowerCase().includes(filter));
    });
}

// --- Event Actions ---
function declineEvent(eventId) {
    // Uses translation from global config
    let reason = null;
    while (!reason || reason.trim() === "") {
        reason = prompt(SAHYOG_CONFIG.trans.declineReason);
        if (reason === null) { showAlert(SAHYOG_CONFIG.trans.declineCancelled, 'info'); return; }
    }
    window.location.href = `/decline_event/${eventId}/${encodeURIComponent(reason)}`;
}

window.asktodelete = id => {
    if (confirm(SAHYOG_CONFIG.trans.areYouSure)) { window.location.href = `deleteevent/${id}`; }
};

// --- AI Generation Logic ---
async function generateDescription() {
    // Check global config for user status
    if (SAHYOG_CONFIG.currentUser === "None") {
        showAlert(SAHYOG_CONFIG.trans.loginForAI, 'warning');
        return;
    }
    const form = $('#addEventForm');
    const formData = new FormData(form);
    const requiredFields = ['eventname', 'location', 'category', 'eventstartdate', 'eventenddate', 'eventstarttime', 'eventendtime'];
    const missing = requiredFields.filter(key => !formData.get(key));

    if (missing.length > 0) {
        showAlert(SAHYOG_CONFIG.trans.fillFieldsAI, 'warning');
        return;
    }

    const btn = $('#aiBtn');
    const originalText = btn.innerHTML;
    const resultsContainer = $('#aiResults');
    btn.disabled = true;
    btn.innerHTML = `✨ ${SAHYOG_CONFIG.trans.generating}`;
    resultsContainer.classList.remove('show');
    resultsContainer.innerHTML = '';

    try {
        const response = await fetch('/generate_ai_description', { method: 'POST', body: formData });
        if (!response.ok) throw new Error('Generation failed');
        const data = await response.json();

        // Labels map
        const labels = {
            'desc1': SAHYOG_CONFIG.trans.formal,
            'desc2': SAHYOG_CONFIG.trans.informal,
            'desc3': SAHYOG_CONFIG.trans.promotional,
            'desc4': SAHYOG_CONFIG.trans.entertaining
        };

        Object.keys(data).forEach(key => {
            const card = document.createElement('div');
            card.className = `ai-option-card ai-card-${key}`;
            card.innerHTML = `<h5>${labels[key] || key}</h5><p>${data[key]}</p>`;
            card.onclick = () => {
                $('#descriptionField').value = data[key];
                showAlert(SAHYOG_CONFIG.trans.descUpdated, 'success');
                $('#descriptionField').scrollIntoView({behavior: 'smooth', block: 'center'});
            };
            resultsContainer.appendChild(card);
        });
        $('#aiInstruction').style.display = 'block';
        resultsContainer.classList.add('show');
    } catch (error) {
        console.error('AI Error:', error);
        showAlert(SAHYOG_CONFIG.trans.aiFailed, 'warning');
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// --- Dynamic Content Loading ---
const contentLoaders = {
    campaigns: { loaded: false, callback: initializeCampaignListeners },
    addForm: { loaded: false, callback: initializeAddFormListeners },
    pending: { loaded: false, callback: initializePendingListeners }
};

function rerunScripts(container) {
    container.querySelectorAll('script').forEach(oldScript => {
        const newScript = document.createElement('script');
        oldScript.getAttributeNames().forEach(attr =>
            newScript.setAttribute(attr, oldScript.getAttribute(attr))
        );
        newScript.textContent = oldScript.textContent;
        oldScript.parentNode.replaceChild(newScript, oldScript);
    });
}

async function loadContent(type, url, loadingId, contentId, retryFn) {
    if (contentLoaders[type].loaded && !window.location.hash.includes('campaigns')) return;
    if (type === 'campaigns') contentLoaders[type].loaded = false;

    const loadingState = $(loadingId);
    const content = $(contentId);

    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`Failed to load ${type}`);
        content.innerHTML = await response.text();
        rerunScripts(content);
        content.style.display = 'block';
        loadingState.style.display = 'none';
        contentLoaders[type].loaded = true;
        contentLoaders[type].callback?.();
    } catch (error) {
        console.error(`Error loading ${type}:`, error);
        loadingState.innerHTML = `
            <p style="color: var(--danger-color);">${SAHYOG_CONFIG.trans.loadFailed}</p>
            <button class="cta" onclick="${retryFn}">${SAHYOG_CONFIG.trans.retry}</button>
        `;
    }
}

const loadCampaigns = () => loadContent('campaigns', '/show_campaigns', '#campaignsLoadingState', '#campaignsContent', 'loadCampaigns()');
const loadAddForm = () => loadContent('addForm', '/show_add_form', '#addFormLoadingState', '#addFormContent', 'loadAddForm()');
const loadPendingEvents = () => loadContent('pending', '/show_pending_events', '#pendingLoadingState', '#pendingContent', 'loadPendingEvents()');

// --- Initialization Logic ---
function initializeCampaignListeners() {
    const campaignsSection = $('#campaigns');
    const backToAllBtn = $('#backToAllBtn');
    const allCategoryWrappers = $$('.campaign-category-wrapper');
    campaignsSection?.addEventListener('click', e => {
        if (!e.target.matches('.view-all-btn')) return;
        const categoryIdToShow = e.target.dataset.categoryId;
        allCategoryWrappers.forEach(wrapper => {
            const show = wrapper.dataset.categoryId === categoryIdToShow;
            wrapper.style.display = show ? 'block' : 'none';
            if (show) wrapper.querySelectorAll('.campaign-card.hidden').forEach(c => c.classList.remove('hidden'));
        });
        backToAllBtn.style.display = 'block';
        campaignsSection.scrollIntoView({ behavior: 'smooth' });
    });
    backToAllBtn?.addEventListener('click', () => {
        allCategoryWrappers.forEach(w => {
            w.style.display = 'block';
            w.querySelectorAll('.campaign-card').forEach((c, i) => i >= 4 && c.classList.add('hidden'));
        });
        backToAllBtn.style.display = 'none';
    });
}

function initializeAddFormListeners() {
    const form = $('#addEventForm');
    if (!form) return;
    form.addEventListener('submit', e => {
        e.preventDefault();
        e.target.dataset.url = '/addeventreq';
        handleFormSubmit(e.target, text => {
            if (text.includes('Please Login')) showSection('home');
            if (text.includes('Registered')) setTimeout(() => location.reload(), 4000);
        });
    });
    form.addEventListener('change', e => {
        const fd = new FormData();
        fd.append('field', e.target.name);
        fd.append('value', e.target.value);
        fetch('/save_draft', { method: 'POST', body: fd });
    });
}

function initializePendingListeners() {
    $$('.approve-btn').forEach(btn => {
        btn.addEventListener('click', e => {
            e.preventDefault();
            const row = btn.closest('tr');
            if (!row) return;
            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = SAHYOG_CONFIG.trans.processing;
            const formData = new FormData();
            row.querySelectorAll('input, select, textarea').forEach(input => {
                formData.append(input.name, input.value);
            });
            fetch('/addevent', { method: 'POST', body: formData })
            .then(response => {
                if (response.redirected) { window.location.href = response.url; return null; }
                return response.text();
            })
            .then(text => {
                if (text === null) return;
                const isSuccess = text.toLowerCase().includes('success') ||
                                 text.toLowerCase().includes('approved') ||
                                 text.toLowerCase().includes('added');
                showAlert(text, isSuccess ? 'success' : 'info');
                if (isSuccess) {
                    row.style.opacity = '0';
                    setTimeout(() => { contentLoaders.pending.loaded = false; loadPendingEvents(); }, 1000);
                } else {
                    btn.disabled = false;
                    btn.textContent = originalText;
                }
            })
            .catch(error => {
                console.error('Error:', error);
                showAlert(SAHYOG_CONFIG.trans.errorOccurred, 'error');
                btn.disabled = false;
                btn.textContent = originalText;
            });
        });
    });
}

const handleFormSubmit = async (form, callback) => {
    const btn = form.querySelector('button[type="submit"]');
    const originalBtnText = btn.textContent;
    btn.disabled = true;
    btn.textContent = SAHYOG_CONFIG.trans.processing;
    try {
        const response = await fetch(form.dataset.url, { method: 'POST', body: new FormData(form) });
        const text = await response.text();
        const type = text.includes('Success') || text.includes('Registered') ? 'success' :
                     text.includes('Error') || text.includes('Invalid') ? 'error' : 'info';
        showAlert(text, type);
        callback?.(text);
    } catch (error) {
        showAlert(SAHYOG_CONFIG.trans.errorOccurred, 'error');
        console.error(error);
    } finally {
        btn.disabled = false;
        btn.textContent = originalBtnText;
    }
};

const showSection = id => {
    const target = id || 'home';
    $$('.navlink').forEach(l => l.classList.toggle('active', l.dataset.section === target));
    $$('main > section').forEach(s => s.classList.toggle('active', s.id === target));
    window.scrollTo(0, 0);
    $('nav')?.classList.remove('active');
    if (target === 'campaigns') loadCampaigns();
    if (target === 'add') loadAddForm();
    if (target === 'pending') loadPendingEvents();
};

const addFormSubmitListener = (selector, url, callback) => {
    $(selector)?.addEventListener('submit', e => {
        e.preventDefault();
        e.target.dataset.url = url;
        handleFormSubmit(e.target, callback);
    });
};

// --- Calendar Logic ---
let calendar;

window.toggleView = function(view) {
    const listBtn = $('#listViewBtn');
    const calBtn = $('#calendarViewBtn');
    const listContent = $('#campaignsContent');
    const calContent = $('#calendarView');
    if (!contentLoaders.campaigns.loaded) loadCampaigns();
    if (view === 'list') {
        listBtn.classList.add('active'); calBtn.classList.remove('active');
        listContent.style.display = 'block'; calContent.style.display = 'none';
    } else {
        listBtn.classList.remove('active'); calBtn.classList.add('active');
        listContent.style.display = 'none'; calContent.style.display = 'block';
        if (!calendar) { initCalendar(); } else { setTimeout(() => calendar.render(), 100); }
    }
};

function initCalendar() {
    const calendarEl = document.getElementById('calendar');
    calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        headerToolbar: { left: 'prev,next today', center: 'title', right: 'dayGridMonth,listWeek' },
        events: function(info, successCallback, failureCallback) {
            fetch('/api').then(r => r.json()).then(data => {
                const events = data['active events'].map(e => ({
                    title: e.eventname,
                    start: e.eventstartdate + (e.eventstarttime ? 'T' + e.eventstarttime : ''),
                    url: '#',
                    extendedProps: { description: e.description, location: e.location }
                }));
                successCallback(events);
            }).catch(failureCallback);
        },
        eventClick: function(info) {
            info.jsEvent.preventDefault();
            showAlert(`${info.event.title}\n📍 ${info.event.extendedProps.location}\n📅 ${info.event.start.toLocaleDateString()}`, 'info');
        }
    });
    calendar.render();
}

// --- Global Globals / Exports ---
window.changetemplate = () => fetch("/changetemplate").then(() => location.reload());
window.viewyourevents = username => fetch(`/viewyourevents/${username}`, { method: 'POST' })
    .then(() => { window.location.href = '#campaigns'; location.reload(); });
window.sendsortreq = sortby => fetch(`/setsortby/${sortby}`, { method: 'POST' })
    .then(() => { window.location.href = '#campaigns'; location.reload(); });

// --- DOM Ready ---
document.addEventListener('DOMContentLoaded', () => {
    const storedAlert = localStorage.getItem('showLanguageChangeAlert');
    if (storedAlert) {
        try {
            const alertData = JSON.parse(storedAlert);
            showAlert(alertData.message, 'success', 0, true);
            localStorage.removeItem('showLanguageChangeAlert');
        } catch (e) { console.error('Error parsing stored alert:', e); }
    }

    document.body.addEventListener('click', e => {
        if (e.target.matches('.navlink')) {
            e.preventDefault();
            showSection(e.target.dataset.section);
            location.hash = e.target.dataset.section;
        }
    });

    if (location.hash) { showSection(location.hash.slice(1)); }
    else { showSection('home'); }
    window.addEventListener('hashchange', () => showSection(location.hash.slice(1)));

    addFormSubmitListener('#loginpage', '/login', text => text.includes('Success') && location.reload());
    addFormSubmitListener('#signuppage', '/signup', text => text.includes('Success') && location.reload());
    addFormSubmitListener('#forgetpasswordpage', '/forgetpassword', text => text.includes('Success') && location.reload());

    $('.toggle-buttons')?.addEventListener('click', e => {
        if (e.target.tagName !== 'BUTTON') return;
        if (e.target.id === 'listViewBtn' || e.target.id === 'calendarViewBtn') return;
        const isLogin = e.target.id === 'login-tab-btn';
        $('#login-tab-btn').classList.toggle('active', isLogin);
        $('#signup-tab-btn').classList.toggle('active', !isLogin);
        $('#loginpage').classList.toggle('active', isLogin);
        $('#signuppage').classList.toggle('active', !isLogin);
        $('#forgetpasswordpage').classList.remove('active');
        $('.toggle-buttons').style.display = 'flex';
    });

    // Forget Password Toggle
    $('#forget-pass-link')?.addEventListener('click', () => {
        const loginUserVal = $('input[name="loginusername"]').value;
        if(loginUserVal) $('#forgetemail').value = loginUserVal;
        const loginPassVal = $('#loginpassword').value;
        if(loginPassVal) $('#newpassword').value = loginPassVal;

        $('#loginpage').classList.remove('active');
        $('#forgetpasswordpage').classList.add('active');
        $('.toggle-buttons').style.display = 'none';
    });

    $('#backToLoginBtn')?.addEventListener('click', () => {
        $('#forgetpasswordpage').classList.remove('active');
        $('#loginpage').classList.add('active');
        $('.toggle-buttons').style.display = 'flex';
    });

    // Forget Password OTP
    $('#sendForgetOtpBtn')?.addEventListener('click', async e => {
         const btn = e.target;
         const emailEl = $('#forgetemail');
         if (!emailEl.checkValidity()) { return showAlert(SAHYOG_CONFIG.trans.enterValidEmail, 'warning'); }
         btn.disabled = true;
         btn.textContent = SAHYOG_CONFIG.trans.sending;
         try {
            const fd = new FormData();
            fd.append('email', emailEl.value);
            const response = await fetch("/sendforgetotp", { method: "POST", body: fd });
            const text = await response.text();
            if (!response.ok) throw new Error(text || 'Failed to send OTP');
            showAlert(text, 'success');
            $('#forget-step-2').style.display = 'block';
            btn.style.display = 'none';
            emailEl.readOnly = true;
         } catch (err) {
            showAlert(err.message, 'error');
         } finally {
            if (btn.style.display !== 'none') {
                setTimeout(() => { btn.disabled = false; btn.textContent = SAHYOG_CONFIG.trans.sendOtp; }, 5000);
            }
         }
    });

    // Forget Password Submit
    const forgetForm = $('#forgetpasswordpage');
    if (forgetForm) {
        forgetForm.addEventListener('submit', async e => {
            e.preventDefault();
            const otpVal = forgetForm.querySelector('input[name="forgetotp"]').value;
            const newPass = $('#newpassword').value;
            const confirmPass = $('#confirmnewpassword').value;

            if (!otpVal || !newPass || !confirmPass) {
                 return showAlert(SAHYOG_CONFIG.trans.fillAllFields, 'warning');
            }
            if (newPass !== confirmPass) {
                return showAlert(SAHYOG_CONFIG.trans.passwordMismatch, 'error');
            }

            const btn = forgetForm.querySelector('.submit-btn');
            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = SAHYOG_CONFIG.trans.processing;

            try {
                const fd = new FormData(forgetForm);
                const response = await fetch("/forgetpassword", { method: "POST", body: fd });
                const text = await response.text();

                if(text.includes('Success')) {
                     showAlert(text, 'success');
                     setTimeout(() => location.reload(), 2000);
                } else {
                     showAlert(text, 'error');
                }
            } catch (err) {
                 showAlert(SAHYOG_CONFIG.trans.errorOccurred, 'error');
            } finally {
                 btn.disabled = false;
                 btn.textContent = originalText;
            }
        });
    }

    // Signup OTP
    $('#sendOtpBtn')?.addEventListener('click', async e => {
        const btn = e.target;
        const emailEl = $('#email');
        if (!emailEl.checkValidity()) { return showAlert(SAHYOG_CONFIG.trans.enterValidEmail, 'warning'); }
        btn.disabled = true;
        btn.textContent = SAHYOG_CONFIG.trans.sending;
        try {
            const fd = new FormData();
            fd.append('email', emailEl.value);
            const response = await fetch("/sendsignupotp", { method: "POST", body: fd });
            const text = await response.text();
            if (!response.ok) throw new Error(text || 'Failed to send OTP');
            showAlert(text, 'info');
        } catch (err) {
            showAlert(err.message, 'error');
        } finally {
            setTimeout(() => { btn.disabled = false; btn.textContent = SAHYOG_CONFIG.trans.sendOtp; }, 5000);
        }
    });

    // Language Dropdown
    const languageBtn = $('#languageBtn');
    const languageDropdown = $('#languageDropdown');

    if (languageBtn) {
        languageBtn.addEventListener('click', e => {
            e.stopPropagation();
            languageDropdown.style.display = languageDropdown.style.display === 'none' ? 'block' : 'none';
        });

        $$('.lang-option').forEach(option => {
            option.addEventListener('click', async e => {
                const langCode = e.target.dataset.lang;
                const langName = e.target.textContent;
                localStorage.setItem('selectedLanguage', langCode);
                try {
                    showAlert(`${SAHYOG_CONFIG.trans.changingLangTo} ${langName}...`, 'info', 0);
                    const response = await fetch(`/setlanguage/${langCode}`, { method: 'POST' });
                    if (!response.ok) throw new Error("Failed to set language");
                    localStorage.setItem('showLanguageChangeAlert', JSON.stringify({
                        message: `${SAHYOG_CONFIG.trans.langChangedTo} ${langName}. ${SAHYOG_CONFIG.trans.reloadMsg}`,
                        duration: 0
                    }));
                    window.location.reload();
                } catch (err) {
                    showAlert(SAHYOG_CONFIG.trans.langChangeError, 'error');
                    console.error(err);
                }
                languageDropdown.style.display = 'none';
            });
        });

        document.addEventListener('click', e => {
            if (!e.target.closest('.language-selector')) { languageDropdown.style.display = 'none'; }
        });
    }
});
