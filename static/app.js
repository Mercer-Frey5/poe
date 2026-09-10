/**
 * POE v0.4 — script del client.
 *
 * Capacità:
 *   1. Contatore di caratteri live sulla textarea
 *   2. Copy-to-clipboard via event delegation (HTMX-safe)
 *   3. Enter per submit, Shift+Enter per andare a capo
 *   4. Wiki popover per tag cliccabili (data-wiki-title / data-wiki-body)
 *   5. Label edit toggle (inline rename osservazione)
 */

(function () {
    'use strict';

    // ─────────────────────────────────────────────────────────
    // 1. Contatore caratteri sulla textarea
    // ─────────────────────────────────────────────────────────

    function initCharCounter() {
        var textarea = document.querySelector('textarea[data-charcounter]');
        var counter = document.querySelector('[data-charcount]');
        if (!textarea || !counter) return;
        var update = function () { counter.textContent = textarea.value.length.toString(); };
        textarea.addEventListener('input', update);
        update();
    }

    // ─────────────────────────────────────────────────────────
    // 2. Copy-to-clipboard via event delegation
    // ─────────────────────────────────────────────────────────

    function copyToClipboard(text) {
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(text).then(
                function () { return true; },
                function () { return fallbackCopy(text); }
            );
        }
        return Promise.resolve(fallbackCopy(text));
    }

    function fallbackCopy(text) {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.position = 'absolute';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        var ok = false;
        try { ok = document.execCommand('copy'); } catch (_e) { ok = false; }
        document.body.removeChild(ta);
        return ok;
    }

    function initCopyButtons() {
        document.addEventListener('click', function (event) {
            var btn = event.target.closest('[data-copy-value]');
            if (!btn) return;
            var value = btn.getAttribute('data-copy-value');
            var label = btn.querySelector('.copy-label');
            copyToClipboard(value).then(function (ok) {
                btn.classList.add('copied');
                if (label) {
                    var orig = label.textContent;
                    label.textContent = ok ? 'ok' : 'err';
                    setTimeout(function () {
                        btn.classList.remove('copied');
                        label.textContent = orig;
                    }, 1200);
                }
            });
        });
    }

    // ─────────────────────────────────────────────────────────
    // 3. Enter-to-submit, Shift+Enter per newline
    // ─────────────────────────────────────────────────────────

    function initSubmitOnEnter() {
        var textarea = document.querySelector('textarea[data-submit-on-enter]');
        if (!textarea) return;
        textarea.addEventListener('keydown', function (event) {
            if (event.key !== 'Enter') return;
            if (event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) return;
            event.preventDefault();
            var form = textarea.closest('form');
            if (!form) return;
            if (typeof form.requestSubmit === 'function') {
                form.requestSubmit();
            } else {
                form.submit();
            }
        });
    }

    // ─────────────────────────────────────────────────────────
    // 4. Wiki popover per tag cliccabili
    // ─────────────────────────────────────────────────────────

    var _activePopover = null;
    var _activeTrigger = null;

    function createPopover(title, body) {
        var el = document.createElement('div');
        el.className = 'wiki-popover';
        el.setAttribute('role', 'dialog');
        el.setAttribute('aria-label', title);

        var header = document.createElement('div');
        header.className = 'wiki-popover-header';

        var titleEl = document.createElement('p');
        titleEl.className = 'wiki-popover-title';
        titleEl.textContent = title;

        var closeBtn = document.createElement('button');
        closeBtn.className = 'wiki-popover-close';
        closeBtn.textContent = '✕';
        closeBtn.setAttribute('aria-label', 'Chiudi');
        closeBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            closePopover();
        });

        header.appendChild(titleEl);
        header.appendChild(closeBtn);

        var bodyEl = document.createElement('p');
        bodyEl.className = 'wiki-popover-body';
        bodyEl.textContent = body;

        el.appendChild(header);
        el.appendChild(bodyEl);
        return el;
    }

    function positionPopover(popover, trigger) {
        document.body.appendChild(popover);
        var rect = trigger.getBoundingClientRect();
        var pw = popover.offsetWidth;
        var ph = popover.offsetHeight;

        var top = rect.top - ph - 8;
        if (top < 8) top = rect.bottom + 8;

        var left = rect.left + rect.width / 2 - pw / 2;
        if (left < 8) left = 8;
        if (left + pw > window.innerWidth - 8) left = window.innerWidth - pw - 8;

        // .wiki-popover è position:fixed → coordinate viewport. NON aggiungere
        // window.scrollY (causava l'apertura troppo in basso dopo lo scroll).
        popover.style.top = top + 'px';
        popover.style.left = left + 'px';
    }

    function closePopover() {
        if (_activePopover) { _activePopover.remove(); _activePopover = null; }
        _activeTrigger = null;
    }

    function initWikiPopovers() {
        document.addEventListener('click', function (event) {
            // Se si clicca nel popover stesso, non chiudere
            if (_activePopover && _activePopover.contains(event.target)) return;

            var trigger = event.target.closest('[data-wiki-title]');

            if (!trigger) {
                if (_activePopover) closePopover();
                return;
            }

            if (trigger === _activeTrigger) {
                closePopover();
                return;
            }

            closePopover();
            var title = trigger.getAttribute('data-wiki-title');
            var body  = trigger.getAttribute('data-wiki-body');
            if (!title) return;

            _activeTrigger = trigger;
            _activePopover = createPopover(title, body);
            positionPopover(_activePopover, trigger);
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && _activePopover) {
                closePopover();
                event.preventDefault();  // segnala agli altri handler che è gestito
                return;
            }
            if ((event.key === ' ' || event.key === 'Enter') && event.target.closest('[data-wiki-title]')) {
                event.preventDefault();
                event.target.closest('[data-wiki-title]').click();
            }
        });

        window.addEventListener('resize', function () {
            if (_activePopover && _activeTrigger) positionPopover(_activePopover, _activeTrigger);
        });
    }

    // ─────────────────────────────────────────────────────────
    // 5. Label edit — toggle inline form per rinomina osservazione
    // ─────────────────────────────────────────────────────────

    function showLabelForm(obsId) {
        var display = document.getElementById('obs-label-display-' + obsId);
        var form    = document.getElementById('obs-label-form-' + obsId);
        if (!display || !form) return;
        display.style.display = 'none';
        form.classList.remove('obs-label-form--hidden');
        var input = form.querySelector('input[name="label"]');
        if (input) { input.focus(); input.select(); }
    }

    function hideLabelForm(obsId) {
        var display = document.getElementById('obs-label-display-' + obsId);
        var form    = document.getElementById('obs-label-form-' + obsId);
        if (!display || !form) return;
        form.classList.add('obs-label-form--hidden');
        display.style.display = '';
    }

    function initLabelEdit() {
        // Apri form al click su ✎
        document.addEventListener('click', function (event) {
            var trigger = event.target.closest('.label-edit-trigger');
            if (!trigger) return;
            showLabelForm(trigger.dataset.obsId);
        });

        // Annulla al click su ✗
        document.addEventListener('click', function (event) {
            var btn = event.target.closest('.label-cancel-btn');
            if (!btn) return;
            hideLabelForm(btn.dataset.obsId);
        });

        // ESC annulla mentre l'input è attivo.
        // Importante: se un wiki popover è aperto, il suo ESC handler ha già
        // gestito l'evento; controlliamo defaultPrevented per evitare di
        // chiudere anche il label form.
        document.addEventListener('keydown', function (event) {
            if (event.key !== 'Escape') return;
            if (event.defaultPrevented) return;
            if (_activePopover) return;  // popover ESC ha priorità
            var active = document.activeElement;
            if (!active) return;
            var form = active.closest('.obs-label-form');
            if (!form) return;
            var obsId = form.id.replace('obs-label-form-', '');
            hideLabelForm(obsId);
        });
    }

    // ─────────────────────────────────────────────────────────
    // 6. Export dropdown — un bottone solo, apre un menu RAW/AI
    // ─────────────────────────────────────────────────────────

    function closeAllExportMenus() {
        document.querySelectorAll('.export-dropdown.open').forEach(function (d) {
            d.classList.remove('open');
            var t = d.querySelector('.export-menu-toggle');
            if (t) t.setAttribute('aria-expanded', 'false');
        });
    }

    function initExportMenu() {
        document.addEventListener('click', function (event) {
            var toggle = event.target.closest('.export-menu-toggle');
            if (toggle) {
                event.stopPropagation();
                var dropdown = toggle.closest('.export-dropdown');
                if (!dropdown) return;
                var wasOpen = dropdown.classList.contains('open');
                closeAllExportMenus();
                if (!wasOpen) {
                    dropdown.classList.add('open');
                    toggle.setAttribute('aria-expanded', 'true');
                }
                return;
            }
            if (!event.target.closest('.export-dropdown')) closeAllExportMenus();
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') closeAllExportMenus();
        });
    }

    // ─────────────────────────────────────────────────────────
    // Bootstrap
    // ─────────────────────────────────────────────────────────

    function initStatusBar() {
        var bar = document.getElementById('status-bar');
        if (!bar) return;
        var itemsContainer = bar.querySelector('.status-items');
        if (!itemsContainer) return;
        var others = bar.querySelector('.status-item.status-others');

        // Riordina i servizi LIVE coi problemi (offline/slow) per primi; "Altro"
        // (inventario, non live) resta sempre in coda.
        function reorderByProblemsFirst() {
            var items = Array.prototype.slice.call(
                itemsContainer.querySelectorAll('.status-item:not(.status-others)'));
            items.sort(function (a, b) {
                function priority(el) {
                    var dot = el.querySelector('.status-dot');
                    if (dot && dot.classList.contains('offline')) return 0;
                    if (dot && dot.classList.contains('slow')) return 1;
                    return 2;
                }
                return priority(a) - priority(b);
            });
            items.forEach(function (el) { itemsContainer.appendChild(el); });
            if (others) itemsContainer.appendChild(others);
        }

        function refresh() {
            fetch('/api/status').then(function (r) { return r.json(); }).then(function (d) {
                Object.keys(d).forEach(function (k) {
                    var item = bar.querySelector('[data-svc="' + k + '"]');
                    if (!item) return;
                    var dot = item.querySelector('.status-dot');
                    var name = item.querySelector('.status-name');
                    if (dot) { dot.classList.remove('online', 'slow', 'offline'); dot.classList.add(d[k].state || 'offline'); }
                    // 'llm' ha la label fissa "POE-AI" (è il selettore del motore): il
                    // nome del modello NON deve sovrascriverla — vive nel sotto-label
                    // .poe-ai-current, gestito dal picker. Gli altri servizi sì.
                    if (name && d[k].name && k !== 'llm') { name.textContent = d[k].name; }
                });
                reorderByProblemsFirst();
            }).catch(function () {
                bar.querySelectorAll('.status-item:not(.status-others) .status-dot').forEach(function (dot) {
                    dot.classList.remove('online', 'slow'); dot.classList.add('offline');
                });
                reorderByProblemsFirst();
            });
        }

        // "Altro": inventario del resto del catalogo (siti/tool non live-monitorati).
        // Caricato una volta; dropdown espandibile (position:fixed, fuori overflow).
        function initOthers() {
            if (!others) return;
            var pop = others.querySelector('.status-others-list');
            var count = others.querySelector('.status-others-count');
            function closePop() { pop.hidden = true; others.classList.remove('open'); others.setAttribute('aria-expanded', 'false'); }
            function togglePop() {
                var opening = pop.hidden;
                if (opening) { var r = others.getBoundingClientRect(); pop.style.left = Math.round(r.left) + 'px'; pop.style.top = Math.round(r.bottom + 6) + 'px'; }
                pop.hidden = !opening; others.classList.toggle('open', opening); others.setAttribute('aria-expanded', String(opening));
            }
            others.addEventListener('click', function (e) { e.stopPropagation(); togglePop(); });
            others.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); togglePop(); }
                else if (e.key === 'Escape') { closePop(); }
            });
            document.addEventListener('click', function (e) { if (!others.contains(e.target)) closePop(); });

            fetch('/api/tools').then(function (r) { return r.json(); }).then(function (d) {
                if (!d || !d.count) return;
                pop.innerHTML = '';
                Object.keys(d.groups).forEach(function (g) {
                    var h = document.createElement('div'); h.className = 'status-others-group'; h.textContent = g; pop.appendChild(h);
                    d.groups[g].forEach(function (nm) {
                        var row = document.createElement('div'); row.className = 'status-others-row';
                        row.innerHTML = '<div class="status-dot status-dot-neutral"></div><span></span>';
                        row.querySelector('span').textContent = nm; pop.appendChild(row);
                    });
                });
                if (count) count.textContent = String(d.count);
                others.hidden = false;
            }).catch(function () {});
        }

        initOthers();
        refresh();
        setInterval(refresh, 30000);
    }

    document.addEventListener('DOMContentLoaded', function () {
        initCharCounter();
        initCopyButtons();
        initSubmitOnEnter();
        initWikiPopovers();
        initLabelEdit();
        initExportMenu();
        initStatusBar();
    });

    document.body.addEventListener('htmx:afterSwap', function () {
        initCharCounter();
    });

})();

/* ── v0.5 — Entity card interactions ─────────────────── */

// Lookup live di una risorsa (auto al primo expand, o via bottone "Riprova").
// Usa fetch() diretto, NON htmx: i lookup devono partire e risolversi anche se
// htmx non ha caricato (era servito da CDN unpkg — se lenta/bloccata, window.htmx
// restava undefined e il lookup non partiva mai, bloccato su "Verifica in corso").
// Esito garantito: successo -> render, errore/timeout -> messaggio + Riprova. Mai
// bloccato per sempre.
function postFragment(el, url, timeoutMs) {
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, timeoutMs);
    return fetch(url, { method: 'POST', signal: controller.signal })
        .then(function (r) {
            if (!r.ok) { throw new Error('HTTP ' + r.status); }
            return r.text();
        })
        .then(function (html) { clearTimeout(timer); el.innerHTML = html; })
        .catch(function (err) {
            clearTimeout(timer);
            var body = el.querySelector('.source-body') || el;
            var why = (err && err.name === 'AbortError') ? 'timeout' : 'errore';
            body.innerHTML = '<span class="lookup-error">Nessuna risposta (' + why + ').</span> '
                + '<button type="button" class="btn-raw btn-retry-lookup">Riprova</button>';
        });
}

function fireAutoLookup(el) {
    el.dataset.lookupLoaded = '1';
    return postFragment(el, el.getAttribute('data-lookup-url'), 15000);
}

function toggleCard(card) {
    var wasExpanded = card.classList.contains('expanded');
    card.classList.toggle('expanded');
    if (wasExpanded) return;

    // Primo expand: lookup live delle risorse OSINT (crt.sh, urlscan.io, NVD,
    // Team Cymru, AbuseIPDB/VirusTotal/Shodan) — partono da sole via fetch().
    // Fuori dal guard htmx qui sotto: devono funzionare anche se htmx non ha
    // caricato. Un'entità può avere più risorse insieme (es. dominio: crt.sh +
    // urlscan.io), quindi querySelectorAll + un flag per elemento.
    var lookups = card.querySelectorAll('[data-auto-lookup]');
    var lookupPromises = [];
    lookups.forEach(function (el) {
        if (el.dataset.lookupLoaded) return;
        lookupPromises.push(fireAutoLookup(el));
    });

    // Analisi AI dell'IOC (lazy, isolata per-IOC via /entity-ai): via htmx se
    // disponibile. L'enrichment geo/WHOIS è già in riga (fatto in /analyze).
    // Parte SOLO dopo che i lookup live sono risolti: il prompt lato server
    // include i loro dati raw (vedi _LIVE_LOOKUP_CACHE in main.py), quindi
    // deve trovarli già in cache quando /entity-ai viene chiamato.
    Promise.all(lookupPromises).then(function () {
        fireEntityAi(card);
    });
}

function fireEntityAi(card) {
    if (!window.htmx) return;
    var ai = card.querySelector('[data-auto-ai]');
    if (ai && !ai.dataset.aiLoaded) {
        ai.dataset.aiLoaded = '1';
        ai.innerHTML = '<span class="ai-loading">Analisi in corso…</span>';
        window.htmx.ajax('POST', ai.getAttribute('data-ai-url'), {
            target: ai,
            swap: 'innerHTML',
            values: {
                entity_type: ai.getAttribute('data-entity-type'),
                entity_value: ai.getAttribute('data-entity-value')
            }
        });
    }
}

// Delegazione click (CSP-safe: la CSP blocca gli onclick inline). Vale anche
// sul contenuto inserito via HTMX, perché il listener è su document.
document.addEventListener('click', function (event) {
    // "Riprova": rilancia un lookup live rimasto in timeout/errore. Va
    // controllato PRIMA di .btn-raw (il bottone ha entrambe le classi, per
    // ereditarne lo stile).
    var retryBtn = event.target.closest('.btn-retry-lookup');
    if (retryBtn) {
        event.stopPropagation();
        var lookupEl = retryBtn.closest('[data-lookup-url]');
        if (lookupEl && window.htmx) {
            lookupEl.innerHTML = '<div class="source-body"><span class="live-lookup-loading">Verifica in corso…</span></div>';
            delete lookupEl.dataset.lookupLoaded;
            fireAutoLookup(lookupEl);
        }
        return;
    }
    // "Verifica": innesca un lookup ON-DEMAND che non è mai partito da solo
    // (WhatsMyName e simili — troppo lenti per l'auto-fire all'expand).
    // Stessa logica di fireAutoLookup, ma partita da un click esplicito
    // invece che da toggleCard(). Va controllato PRIMA di .btn-raw generico
    // (il bottone ha entrambe le classi, per ereditarne lo stile).
    var manualBtn = event.target.closest('.btn-manual-lookup');
    if (manualBtn) {
        event.stopPropagation();
        var manualEl = manualBtn.closest('[data-lookup-url]');
        if (manualEl && !manualEl.dataset.lookupLoaded) {
            manualEl.querySelector('.source-body').innerHTML =
                '<span class="live-lookup-loading">Verifica in corso…</span>';
            fireAutoLookup(manualEl);
        }
        return;
    }
    // "raw": mostra/nasconde il testo grezzo della fonte (resta espansa).
    var rawBtn = event.target.closest('.btn-raw');
    if (rawBtn) {
        event.stopPropagation();
        var g = rawBtn.closest('.source-group');
        if (g) { g.classList.add('expanded'); g.classList.toggle('show-raw'); }
        return;
    }
    // Header di una fonte: espandi/chiudi la vista formattata.
    var sh = event.target.closest('.source-header');
    if (sh) {
        event.stopPropagation();
        var grp = sh.closest('.source-group');
        if (grp) grp.classList.toggle('expanded');
        return;
    }
    // Elementi interattivi: non espandere la card.
    if (event.target.closest('a, button, input, label, textarea, select, form, [data-wiki-title], [data-copy-value]')) return;
    // Espandi/richiudi SOLO cliccando la riga compatta (.entity-row) — non
    // qualunque punto dentro .entity-card, altrimenti un click sul testo del
    // pannello già espanso (titolo categoria, kv-grid, spazio vuoto) lo
    // richiude a sorpresa, interrompendo la lettura di un lookup live appena
    // arrivato (sembra "non funzionare" quando in realtà si è solo richiuso).
    var row = event.target.closest('.entity-row');
    if (row) toggleCard(row.closest('.entity-card'));
});

// ── Split view resize (linea centrale tra info tool e Analisi AI) ──────────────
// Rapporto volatile per pagina: scritto come --ioc-split sul contenitore
// .entity-groups condiviso, quindi TUTTE le card della pagina lo seguono. Nessuna
// persistenza: al reload il CSS ripristina il default 50%. CSP-safe: listener
// delegati su document, nessun handler inline. Pointer Events = mouse+touch.
(function () {
    var CLAMP_MIN = 25, CLAMP_MAX = 75, STEP = 2;
    var drag = null;   // { splitter, panel }

    function clamp(pct) { return Math.max(CLAMP_MIN, Math.min(CLAMP_MAX, pct)); }

    function apply(splitter, pct) {
        var groups = splitter.closest('.entity-groups');
        if (groups) groups.style.setProperty('--ioc-split', clamp(pct) + '%');
    }

    function pctFromX(panel, clientX) {
        var r = panel.getBoundingClientRect();
        if (r.width <= 0) return 50;
        return (clientX - r.left) / r.width * 100;
    }

    document.addEventListener('pointerdown', function (e) {
        var splitter = e.target.closest && e.target.closest('.panel-splitter');
        if (!splitter) return;
        var panel = splitter.closest('.panel-main-content');
        if (!panel) return;
        drag = { splitter: splitter, panel: panel };
        splitter.classList.add('dragging');
        try { splitter.setPointerCapture(e.pointerId); } catch (_) {}
        e.preventDefault();
    });

    document.addEventListener('pointermove', function (e) {
        if (!drag) return;
        apply(drag.splitter, pctFromX(drag.panel, e.clientX));
    });

    function endDrag() {
        if (!drag) return;
        drag.splitter.classList.remove('dragging');
        drag = null;
    }
    document.addEventListener('pointerup', endDrag);
    document.addEventListener('pointercancel', endDrag);

    // Doppio-click sullo splitter: reset a 50/50 (rimuove la var inline → default CSS).
    document.addEventListener('dblclick', function (e) {
        var splitter = e.target.closest && e.target.closest('.panel-splitter');
        if (!splitter) return;
        var groups = splitter.closest('.entity-groups');
        if (groups) groups.style.removeProperty('--ioc-split');
    });

    // Frecce ←/→ con focus sullo splitter: ±2% (accessibilità da tastiera).
    document.addEventListener('keydown', function (e) {
        var splitter = e.target.closest && e.target.closest('.panel-splitter');
        if (!splitter) return;
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
        var groups = splitter.closest('.entity-groups');
        var cur = groups ? (parseFloat(groups.style.getPropertyValue('--ioc-split')) || 50) : 50;
        apply(splitter, cur + (e.key === 'ArrowRight' ? STEP : -STEP));
        e.preventDefault();
    });
})();

// ── Selettore LLM runtime "POE-AI" (Locale Llama <-> Claude) ───────────────────
// Volatile: nessun localStorage. CSP-safe: listener delegati, nessun onclick inline.
(function () {
    var toggle = document.getElementById('poe-ai-toggle');
    if (!toggle) return;
    var picker = toggle.querySelector('.poe-ai-picker');
    var current = toggle.querySelector('.poe-ai-current');
    var CLAUDE_MODELS = [['sonnet', 'Sonnet'], ['opus', 'Opus'], ['haiku', 'Haiku']];
    var state = { backend: 'local', model: 'sonnet' };

    function currentLabel() {
        if (state.backend === 'claude') {
            var nm = state.model ? state.model.charAt(0).toUpperCase() + state.model.slice(1) : '';
            return ('· Claude ' + nm).trim();
        }
        // Questo picker offre solo mlx/claude, ma deve MOSTRARE correttamente
        // uno stato impostato altrove (pannello Settings): un backend
        // compatibile OpenAI puntato a un endpoint pubblico e' "cloud", non
        // "Llama" locale. Dirlo qui evita di far credere locale un motore
        // che sta mandando i dati fuori.
        if (state.backend === 'cloud') return '· AI esterna';
        return '· Llama';
    }

    function render() {
        var models = CLAUDE_MODELS.map(function (m) {
            return '<label class="poe-ai-model"><input type="radio" name="poe-ai-model" value="' + m[0] + '"' +
                   (state.backend === 'claude' && state.model === m[0] ? ' checked' : '') + '> ' + m[1] + '</label>';
        }).join('');
        picker.innerHTML =
            '<div class="poe-ai-title">Motore LLM</div>' +
            '<label class="poe-ai-row"><input type="radio" name="poe-ai-backend" value="mlx"' +
              (state.backend !== 'claude' ? ' checked' : '') + '> Locale (Llama)</label>' +
            '<label class="poe-ai-row"><input type="radio" name="poe-ai-backend" value="claude"' +
              (state.backend === 'claude' ? ' checked' : '') + '> Claude</label>' +
            '<div class="poe-ai-models"' + (state.backend === 'claude' ? '' : ' hidden') + '>' + models +
              '<p class="poe-ai-warn">&#9888; i dati OSINT escono verso il cloud Anthropic (opt-in)</p></div>' +
            '<div class="poe-ai-actions"><button type="button" class="poe-ai-apply">Applica</button>' +
              '<span class="poe-ai-msg"></span></div>';
    }

    function open() {
        render();
        // position:fixed → ancoro il picker al toggle via bounding rect, così esce
        // dall'overflow della .status-bar (come fa il popover "Altro").
        var r = toggle.getBoundingClientRect();
        picker.style.left = Math.round(r.left) + 'px';
        picker.style.top = Math.round(r.bottom + 6) + 'px';
        picker.hidden = false;
        toggle.setAttribute('aria-expanded', 'true');
    }
    function close() { picker.hidden = true; toggle.setAttribute('aria-expanded', 'false'); }

    // Stato iniziale dal server.
    fetch('/api/status').then(function (r) { return r.json(); }).then(function (d) {
        if (d && d.llm) {
            state.backend = d.llm.kind === 'claude' ? 'claude' : (d.llm.kind === 'cloud' ? 'cloud' : 'local');
            current.textContent = currentLabel();
        }
    }).catch(function () {});

    // Apri/chiudi cliccando l'item (ma non quando si clicca DENTRO il picker).
    toggle.addEventListener('click', function (e) {
        if (e.target.closest('.poe-ai-picker')) return;
        if (picker.hidden) open(); else close();
    });
    toggle.addEventListener('keydown', function (e) {
        if ((e.key === 'Enter' || e.key === ' ') && e.target === toggle) {
            e.preventDefault();
            if (picker.hidden) open(); else close();
        }
    });

    // Mostra/nascondi i modelli Claude al cambio backend.
    picker.addEventListener('change', function (e) {
        if (e.target.name === 'poe-ai-backend') {
            var models = picker.querySelector('.poe-ai-models');
            if (models) models.hidden = e.target.value !== 'claude';
        }
    });

    // Applica → POST /admin/llm/backend.
    picker.addEventListener('click', function (e) {
        if (!e.target.classList.contains('poe-ai-apply')) return;
        var bSel = picker.querySelector('input[name="poe-ai-backend"]:checked');
        var backend = bSel ? bSel.value : 'mlx';
        var model = '';
        if (backend === 'claude') {
            var mSel = picker.querySelector('input[name="poe-ai-model"]:checked');
            model = mSel ? mSel.value : 'sonnet';
        }
        var msg = picker.querySelector('.poe-ai-msg');
        msg.textContent = '…';
        fetch('/admin/llm/backend', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: 'backend=' + encodeURIComponent(backend) + '&model=' + encodeURIComponent(model),
        }).then(function (r) {
            return r.json().then(function (j) { return { ok: r.ok, j: j }; });
        }).then(function (res) {
            if (!res.ok || !res.j.ok) { msg.textContent = (res.j && res.j.error) || 'errore'; return; }
            state.backend = res.j.kind === 'claude' ? 'claude' : (res.j.kind === 'cloud' ? 'cloud' : 'local');
            state.model = res.j.model || '';
            current.textContent = currentLabel();
            close();
        }).catch(function () { msg.textContent = 'errore di rete'; });
    });

    // Chiudi cliccando fuori.
    document.addEventListener('click', function (e) {
        if (!toggle.contains(e.target) && !picker.hidden) close();
    });
})();

