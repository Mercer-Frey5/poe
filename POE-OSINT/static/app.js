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

        popover.style.top = (top + window.scrollY) + 'px';
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
    // Bootstrap
    // ─────────────────────────────────────────────────────────

    document.addEventListener('DOMContentLoaded', function () {
        initCharCounter();
        initCopyButtons();
        initSubmitOnEnter();
        initWikiPopovers();
        initLabelEdit();
    });

    document.body.addEventListener('htmx:afterSwap', function () {
        initCharCounter();
    });

})();

/* ── v0.5 — Entity card interactions ─────────────────── */

function toggleCard(card) {
    var wasExpanded = card.classList.contains('expanded');
    card.classList.toggle('expanded');

    // Auto-trigger geo/whois enrich al primo expand.
    // Usa htmx.ajax() — htmx.trigger() creerebbe un evento che bubble
    // fino alla card e la richiuderebbe immediatamente.
    if (!wasExpanded && window.htmx) {
        var btn = card.querySelector('[data-auto-enrich]');
        if (btn) {
            window.htmx.ajax('POST', btn.getAttribute('hx-post'), {
                source: btn,
                target: btn,
                swap: 'outerHTML'
            });
        }
    }
}

function toggleRaw(btn, event) {
    event.stopPropagation();
    var group = btn.closest('.source-group');
    if (group) group.classList.toggle('expanded');
}

function toggleAI(btn, event) {
    event.stopPropagation();
    var card = btn.closest('.entity-card');
    if (!card) return;

    card.classList.add('expanded');
    card.classList.toggle('multitasking');
    card.classList.toggle('ai-active');

    var aiWrapper     = card.querySelector('.ai-wrapper');
    var aiContent     = aiWrapper ? aiWrapper.querySelector('.ai-analysis-content') : null;
    var aiPlaceholder = aiWrapper ? aiWrapper.querySelector('.ai-placeholder') : null;

    if (card.classList.contains('ai-active')) {
        if (aiContent)     aiContent.classList.add('active');
        if (aiPlaceholder) aiPlaceholder.style.display = 'none';
    } else {
        if (aiContent)     aiContent.classList.remove('active');
        if (aiPlaceholder) aiPlaceholder.style.display = '';
    }
}
