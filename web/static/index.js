let lightsRefreshInterval = null;
let isLoadingLights = false;
// Status requests are numbered; responses to requests started before the last
// action (apply / off / undo) describe the old state and are discarded.
let lightsRequestSeq = 0;
let lastActionSeq = 0;
let pendingLightsRefresh = false;
// Selection whose preview stays on screen until a post-action status arrives
/** @type {ConfigItem|null} */
let awaitingStatusFor = null;

/**
 * @typedef {{r: number, g: number, b: number, brightness: number, enabled: boolean}} PreviewColor
 * @typedef {{light_name: string, color: object, preview: PreviewColor}} ConfigSetting
 * @typedef {{name: string, description: string, settings?: ConfigSetting[]}} ConfigItem
 */

/** @type {ConfigItem[]} */
let configurationsCache = [];
/** @type {ConfigItem[]} */
let filteredConfigurations = [];
let pickerActiveIndex = -1;

// Preview state: polling only updates lastLightsStatus; rendering overlays the preview
let lastLightsStatus = null;
let lightsStatusFailed = false;
/** @type {ConfigItem|null} */
let selectedConfig = null;
/** @type {ConfigItem|null} */
let hoverConfig = null;
let hoverFromKeyboard = false;
let selectionPreviewDismissed = false;
let hoverPreviewTimer = null;
/** @type {ConfigItem|null} item under the mouse (pending or shown) */
let hoverCandidate = null;
let lastTouchAt = 0;
// After a mouse star toggle the list re-renders under a still pointer; the browser
// then fires mouseover on whatever row slid under it. Hover previews stay off until
// the pointer really moves. Holds the click's {x, y} while active.
let suppressHoverUntilMove = null;

// Favorites: names marked on the server; toggles are optimistic and re-synced on error
/** @type {Set<string>} */
let favoriteNames = new Set();
let favoritesOnly = false;
// Per scene name: at most one PUT/DELETE in flight; `desired` is the latest wanted state
/** @type {Object<string, {inFlight: boolean, desired: boolean}>} */
const favoriteSync = {};
let favoriteFeedbackTimer = null;

// Last applied scene (recorded by the server on any apply); null = none or cleared
// by Desligar/Desfazer. Only its badge is shown: it is selected without preview.
/** @type {{name: string, appliedAt: Date}|null} */
let lastApplied = null;
// Bumped by every apply/off/undo on this page: a GET /configurations/last-applied
// started before the bump answers with older data and is ignored
let lastAppliedLocalSeq = 0;

// Scene deletion: name awaiting confirmation in the modal; one DELETE at a time
let deleteConfigModal = null;
/** @type {string|null} */
let deleteConfigTarget = null;
let deleteConfigInFlight = false;
let configFeedbackTimer = null;

const HOVER_PREVIEW_DELAY_MS = 80;
const HOVER_RESUME_MOVE_PX = 2;
const TOUCH_MOUSE_GUARD_MS = 800;
const FAVORITES_ONLY_STORAGE_KEY = 'controle.favoritesOnly';
const FAVORITE_FEEDBACK_MS = 4000;
const CONFIG_FEEDBACK_MS = 5000;
const LAST_APPLIED_REFRESH_MS = 30000;

function loadLightsStatus() {
    // Evita requisições simultâneas
    if (isLoadingLights) {
        return;
    }
    isLoadingLights = true;
    const requestSeq = ++lightsRequestSeq;

    $.getJSON('/api/lights/status', function(data) {
        if (requestSeq <= lastActionSeq) {
            return;
        }
        lastLightsStatus = (data && Array.isArray(data.lights)) ? data.lights : [];
        lightsStatusFailed = false;
        finishAwaitingStatus();
        refreshLightsView();
    }).fail(function() {
        if (requestSeq <= lastActionSeq) {
            return;
        }
        lightsStatusFailed = true;
        finishAwaitingStatus();
        // With a preview it stays on top of the last known state; otherwise shows the error
        refreshLightsView();
    }).always(function() {
        isLoadingLights = false;
        if (pendingLightsRefresh) {
            pendingLightsRefresh = false;
            loadLightsStatus();
        }
    });
}

// After a successful action: discard in-flight (pre-action) status and fetch a fresh one.
// keepPreview keeps the selected scene's preview until that fresh status lands.
function refreshAfterAction(keepPreview) {
    lastActionSeq = lightsRequestSeq;
    clearTimeout(hoverPreviewTimer);
    hoverConfig = null;
    hoverFromKeyboard = false;
    if (keepPreview && selectedConfig) {
        awaitingStatusFor = selectedConfig;
        selectionPreviewDismissed = false;
        refreshLightsView();
    } else {
        awaitingStatusFor = null;
        showRealState();
    }
    if (isLoadingLights) {
        pendingLightsRefresh = true;
    } else {
        loadLightsStatus();
    }
}

function finishAwaitingStatus() {
    if (!awaitingStatusFor) {
        return;
    }
    // Only drop the preview if the user hasn't picked another scene meanwhile
    if (selectedConfig === awaitingStatusFor) {
        selectionPreviewDismissed = true;
    }
    awaitingStatusFor = null;
}

function getEffectivePreview() {
    if (hoverConfig) {
        return hoverConfig;
    }
    if (selectedConfig && !selectionPreviewDismissed) {
        return selectedConfig;
    }
    return null;
}

function refreshLightsView() {
    const preview = getEffectivePreview();
    updatePreviewHeader(preview);
    if (!preview && (lightsStatusFailed || lastLightsStatus === null)) {
        // No preview and no real state to show: error or loading placeholder
        const message = lightsStatusFailed
            ? '<i class="bi bi-exclamation-triangle me-2"></i> Erro ao carregar lâmpadas'
            : '<i class="bi bi-hourglass-split me-2"></i> Carregando lâmpadas...';
        $('#lights-container').html(
            '<div class="lights-loading' + (lightsStatusFailed ? ' text-danger' : '') + '">' + message + '</div>'
        );
        return;
    }
    renderLights(lastLightsStatus || [], preview);
}

function updatePreviewHeader(preview) {
    const $badge = $('#preview-badge');
    const $realBtn = $('#real-state-btn');
    if (preview) {
        $badge.text('Prévia: ' + preview.name).attr('title', preview.description || preview.name).removeClass('d-none');
        $realBtn.removeClass('d-none');
    } else {
        $badge.text('').addClass('d-none');
        $realBtn.addClass('d-none');
    }
}

// Single light ordering for the lights card and the picker color dots, so they can't drift
function compareLightNames(a, b) {
    return String(a).localeCompare(String(b), 'pt-BR');
}

function brightnessPercent(value) {
    return Math.round((Number(value || 0) / 254) * 100);
}

function buildLightView(name, status, setting, hasPreview, statusKnown) {
    const view = {
        name: name,
        color: (status && status.color) || { r: 128, g: 128, b: 128 },
        bulbClass: 'off',
        circleClass: '',
        tag: '',
        title: ''
    };
    const isReachable = status ? status.reachable : true;
    const isOn = status ? status.on : false;
    const realTitle = status
        ? `${name}\nBrilho: ${brightnessPercent(status.brightness)}%\n${isOn ? 'Ligada' : 'Desligada'}${!isReachable ? ' (Inacessível)' : ''}`
        : `${name}\nEstado atual desconhecido`;

    if (status && !isReachable) {
        view.bulbClass = 'unreachable';
        view.title = realTitle;
        return view;
    }

    view.bulbClass = isOn ? 'on' : 'off';
    view.title = realTitle;

    if (!hasPreview) {
        return view;
    }

    if (!setting || !setting.preview) {
        view.circleClass = 'untouched';
        view.tag = 'não alterada';
        view.title = realTitle + '\nNão alterada pela cena';
        return view;
    }

    if (!status && statusKnown) {
        // Status loaded fine but the bridge doesn't report this light: apply would fail for it
        view.bulbClass = 'off';
        view.circleClass = 'not-found';
        view.tag = 'não encontrada';
        view.title = `${name}\nNão encontrada na bridge: a cena não poderá alterá-la`;
        return view;
    }

    const preview = setting.preview;
    if (preview.enabled === false) {
        view.circleClass = 'disabled-app';
        view.tag = 'desabilitada no app';
        view.title = realTitle + '\nDesabilitada no app: a cena não altera esta lâmpada';
        return view;
    }

    view.color = { r: preview.r, g: preview.g, b: preview.b };
    view.bulbClass = 'on';
    view.circleClass = 'preview';
    view.title = `${name}\nPrévia — brilho: ${brightnessPercent(preview.brightness)}%`;
    return view;
}

function renderLights(lights, preview) {
    const container = $('#lights-container');
    container.empty();

    const statusList = Array.isArray(lights) ? lights : [];
    const statusByName = {};
    statusList.forEach(function (light) {
        statusByName[light.name] = light;
    });

    const settingsByName = {};
    const names = statusList.map(function (light) { return light.name; });
    if (preview && Array.isArray(preview.settings)) {
        preview.settings.forEach(function (setting) {
            settingsByName[setting.light_name] = setting;
            // Lights in the scene but missing from the status are still shown
            if (!Object.prototype.hasOwnProperty.call(statusByName, setting.light_name)) {
                names.push(setting.light_name);
            }
        });
    }

    if (names.length === 0) {
        container.html(
            '<div class="lights-loading">' +
            '<i class="bi bi-lightbulb-off me-2"></i> Nenhuma lâmpada encontrada' +
            '</div>'
        );
        return;
    }

    // Ordenar lâmpadas por nome (ordem crescente)
    names.sort(compareLightNames);

    const statusKnown = !lightsStatusFailed && lastLightsStatus !== null;
    names.forEach(function(lightName) {
        const view = buildLightView(
            lightName, statusByName[lightName], settingsByName[lightName], Boolean(preview), statusKnown
        );
        const rgbColor = `rgb(${view.color.r}, ${view.color.g}, ${view.color.b})`;

        const lightElement = $('<div>', {
            class: ('light-circle ' + view.circleClass).trim(),
            title: view.title
        });

        const bulb = $('<div>', {
            class: `light-bulb ${view.bulbClass}`,
            css: {
                backgroundColor: rgbColor,
                '--light-color': rgbColor
            }
        });

        const name = $('<span>', {
            class: 'light-name',
            text: lightName
        });

        lightElement.append(bulb).append(name);
        if (view.tag) {
            lightElement.append($('<span>', { class: 'light-tag', text: view.tag }));
        }
        container.append(lightElement);
    });
}

function startLightsAutoRefresh() {
    // Atualiza a cada 3 segundos
    if (lightsRefreshInterval) {
        clearInterval(lightsRefreshInterval);
    }
    lightsRefreshInterval = setInterval(loadLightsStatus, 3000);
}

function normalizeFilterText(text) {
    return String(text || '')
        .toLowerCase()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .trim();
}

function truncateDescription(description, maxLen) {
    const text = String(description || '').trim();
    if (text.length <= maxLen) {
        return text;
    }
    return text.slice(0, maxLen) + '…';
}

function getFilteredConfigurations(query) {
    const needle = normalizeFilterText(query);
    if (!needle) {
        return configurationsCache.slice();
    }
    return configurationsCache.filter(function (item) {
        const haystack = normalizeFilterText(item.name + ' ' + (item.description || ''));
        return haystack.indexOf(needle) !== -1;
    });
}

function isFavorite(item) {
    return Boolean(item) && favoriteNames.has(item.name);
}

function countFavorites() {
    return configurationsCache.filter(isFavorite).length;
}

// Visual order: favorites first, then the rest (each keeps the cache's pt-BR order).
// With the favorites filter on, only favorites.
function orderByFavorites(items) {
    const favorites = items.filter(isFavorite);
    if (favoritesOnly) {
        return { favorites: favorites, others: [] };
    }
    const others = items.filter(function (item) {
        return !isFavorite(item);
    });
    return { favorites: favorites, others: others };
}

function configOptionId(item) {
    // Stable id: position in the sorted cache, not in the filtered list
    return 'config-opt-' + configurationsCache.indexOf(item);
}

function setPickerMessage(text, extraClass) {
    const $list = $('#configurations-list');
    $list.empty().removeAttr('aria-activedescendant');
    $list.append($('<div>', {
        class: ('config-picker-empty ' + (extraClass || '')).trim(),
        text: text
    }));
}

function buildColorDots(item) {
    const $dots = $('<span>', { class: 'item-dots', 'aria-hidden': 'true' });
    const settings = (item.settings || []).filter(function (setting) {
        return setting && setting.preview;
    });
    settings.sort(function (a, b) {
        return compareLightNames(a.light_name, b.light_name);
    });
    settings.forEach(function (setting) {
        const p = setting.preview;
        const detail = p.enabled === false ? 'desabilitada no app' : brightnessPercent(p.brightness) + '%';
        $dots.append($('<span>', {
            class: 'item-dot' + (p.enabled === false ? ' is-disabled' : ''),
            title: setting.light_name + ' — ' + detail,
            css: { backgroundColor: `rgb(${p.r}, ${p.g}, ${p.b})` }
        }));
    });
    return $dots;
}

function buildFavoriteButton(item) {
    const favorite = isFavorite(item);
    const $btn = $('<button>', {
        type: 'button',
        class: 'config-fav-btn' + (favorite ? ' is-favorite' : ''),
        tabindex: '-1',
        'aria-label': 'Favoritar ' + item.name,
        'aria-pressed': favorite ? 'true' : 'false',
        title: favorite ? 'Remover dos favoritos' : 'Adicionar aos favoritos'
    });
    $btn.append($('<i>', {
        class: favorite ? 'bi bi-star-fill' : 'bi bi-star',
        'aria-hidden': 'true'
    }));
    return $btn;
}

// "agora", "há 5 min", "há 2 h", "há 1 dia", "há 3 dias" (future clock skew → "agora")
function formatRelativeTimePtBr(date, now) {
    const diffMs = (now || new Date()).getTime() - date.getTime();
    if (!isFinite(diffMs) || diffMs < 60000) {
        return 'agora';
    }
    const minutes = Math.floor(diffMs / 60000);
    if (minutes < 60) {
        return 'há ' + minutes + ' min';
    }
    const hours = Math.floor(minutes / 60);
    if (hours < 24) {
        return 'há ' + hours + ' h';
    }
    const days = Math.floor(hours / 24);
    return 'há ' + days + (days === 1 ? ' dia' : ' dias');
}

function isLastApplied(item) {
    return Boolean(item) && Boolean(lastApplied) && lastApplied.name === item.name;
}

function buildLastAppliedBadge() {
    return $('<span>', {
        class: 'item-last-applied',
        text: 'Última aplicada · ' + formatRelativeTimePtBr(lastApplied.appliedAt),
        title: 'Aplicada em ' + lastApplied.appliedAt.toLocaleString('pt-BR')
    });
}

// Updates the badge in place (no list re-render: keeps scroll, hover and active item)
function updateLastAppliedBadges() {
    const $items = $('#configurations-list .config-picker-item');
    $items.find('.item-last-applied').remove();
    if (!lastApplied) {
        return;
    }
    $items.each(function () {
        if (isLastApplied($(this).data('config'))) {
            $(this).find('.item-name').append(buildLastAppliedBadge());
        }
    });
}

function setLastAppliedLocally(name) {
    lastAppliedLocalSeq++;
    lastApplied = name ? { name: name, appliedAt: new Date() } : null;
    updateLastAppliedBadges();
}

function buildConfigOption(item) {
    const $option = $('<div>', {
        id: configOptionId(item),
        class: 'config-picker-item',
        role: 'option',
        'aria-selected': 'false',
        title: item.description || item.name
    });
    $option.data('config', item);
    const $text = $('<span>', { class: 'item-text' });
    const $name = $('<span>', { class: 'item-name', text: item.name });
    if (isLastApplied(item)) {
        $name.append(buildLastAppliedBadge());
    }
    $text.append($name);
    $text.append($('<span>', {
        class: 'item-desc',
        text: truncateDescription(item.description, 90)
    }));
    $option.append($text).append(buildColorDots(item)).append(buildFavoriteButton(item));
    return $option;
}

function buildSectionHeader(text) {
    return $('<div>', {
        class: 'config-picker-section',
        role: 'presentation',
        text: text
    });
}

/**
 * Rebuilds the list. options.keepActive keeps the active item (and the scroll
 * position, unless options.scrollToActive) across the re-render, e.g. after a
 * favorite toggle; otherwise the active item is reset as on a new filter.
 */
function renderConfigList(options) {
    const opts = options || {};
    const $list = $('#configurations-list');
    const query = $('#configurations-filter').val();
    const previousActive = opts.keepActive ? (filteredConfigurations[pickerActiveIndex] || null) : null;
    const previousScrollTop = $list.scrollTop();

    const sections = orderByFavorites(getFilteredConfigurations(query));
    filteredConfigurations = sections.favorites.concat(sections.others);
    pickerActiveIndex = previousActive ? filteredConfigurations.indexOf(previousActive) : -1;

    // A preview of an item that is no longer listed would be orphaned
    if (hoverConfig && filteredConfigurations.indexOf(hoverConfig) === -1) {
        setHoverPreview(null);
    }

    const favoriteTotal = countFavorites();
    $('#configurations-count').text(favoritesOnly
        ? filteredConfigurations.length + ' de ' + favoriteTotal + ' favoritas'
        : filteredConfigurations.length + ' de ' + configurationsCache.length);

    if (!configurationsCache.length) {
        setPickerMessage('Nenhuma configuração disponível');
        updateSelectedChip();
        return;
    }

    if (favoritesOnly && favoriteTotal === 0) {
        setPickerMessage('Nenhuma favorita ainda — clique na ☆ de uma cena');
        updateSelectedChip();
        return;
    }

    if (!filteredConfigurations.length) {
        setPickerMessage('Nenhum resultado para “' + String(query).trim() + '”');
        updateSelectedChip();
        return;
    }

    $list.empty();
    // Headers only when the list really has two groups to tell apart
    const showSections = !favoritesOnly && sections.favorites.length > 0;
    if (showSections) {
        $list.append(buildSectionHeader('Favoritas'));
    }
    sections.favorites.forEach(function (item) {
        $list.append(buildConfigOption(item));
    });
    if (showSections && sections.others.length) {
        $list.append(buildSectionHeader('Todas as cenas'));
    }
    sections.others.forEach(function (item) {
        $list.append(buildConfigOption(item));
    });

    if (opts.keepActive) {
        $list.scrollTop(previousScrollTop);
    }
    updatePickerStates(opts.keepActive && !opts.scrollToActive);
}

function updatePickerStates(skipScroll) {
    const $list = $('#configurations-list');
    const $filter = $('#configurations-filter');
    const $items = $list.find('.config-picker-item');

    $items.each(function () {
        const isSelected = $(this).data('config') === selectedConfig;
        $(this).toggleClass('selected', isSelected).attr('aria-selected', isSelected ? 'true' : 'false');
    });

    $items.removeClass('active');
    if (pickerActiveIndex >= 0 && pickerActiveIndex < $items.length) {
        const $active = $items.eq(pickerActiveIndex);
        $active.addClass('active');
        $list.attr('aria-activedescendant', $active.attr('id'));
        $filter.attr('aria-activedescendant', $active.attr('id'));
        const el = $active.get(0);
        if (!skipScroll && el && typeof el.scrollIntoView === 'function') {
            el.scrollIntoView({ block: 'nearest' });
        }
    } else {
        $list.removeAttr('aria-activedescendant');
        $filter.removeAttr('aria-activedescendant');
    }

    updateSelectedChip();
}

function updateDeleteButton() {
    const $btn = $('#delete-config-btn');
    const enabled = Boolean(selectedConfig) && !deleteConfigInFlight;
    $btn.prop('disabled', !enabled)
        .toggleClass('btn-outline-danger', enabled)
        .toggleClass('btn-outline-secondary', !enabled)
        .attr('title', selectedConfig
            ? 'Excluir “' + selectedConfig.name + '”'
            : 'Selecione uma configuração para excluir');
}

function updateSelectedChip() {
    updateDeleteButton();
    const $chip = $('#configurations-selected-chip');
    const hidden = !selectedConfig || filteredConfigurations.indexOf(selectedConfig) !== -1;
    if (hidden) {
        $chip.addClass('d-none');
        return;
    }
    $chip.find('.chip-name').text(selectedConfig.name);
    $chip.removeClass('d-none');
}

function selectConfiguration(item) {
    clearTimeout(hoverPreviewTimer);
    // The clicked item is under the mouse: don't re-preview it as hover
    hoverCandidate = item || null;
    selectedConfig = item || null;
    hoverConfig = null;
    hoverFromKeyboard = false;
    selectionPreviewDismissed = false;
    updatePickerStates();
    refreshLightsView();
}

// Scrolls only the list (never the page) so the row sits in its middle
function scrollItemIntoList(item) {
    const list = document.getElementById('configurations-list');
    const row = document.getElementById(configOptionId(item));
    if (!list || !row) {
        return;
    }
    const listRect = list.getBoundingClientRect();
    const rowRect = row.getBoundingClientRect();
    list.scrollTop += rowRect.top - listRect.top - (list.clientHeight - row.offsetHeight) / 2;
}

// Selection without preview: the lights card keeps showing the real state
function selectWithoutPreview(item) {
    clearTimeout(hoverPreviewTimer);
    selectedConfig = item;
    selectionPreviewDismissed = true;
    updatePickerStates(true);
    refreshLightsView();
    scrollItemIntoList(item);
}

function setHoverPreview(item, fromKeyboard) {
    clearTimeout(hoverPreviewTimer);
    if (fromKeyboard || !item) {
        hoverCandidate = null;
    }
    hoverConfig = item || null;
    hoverFromKeyboard = Boolean(item) && Boolean(fromKeyboard);
    refreshLightsView();
}

function clearHoverPreview() {
    if (!hoverConfig) {
        clearTimeout(hoverPreviewTimer);
        hoverCandidate = null;
        return;
    }
    setHoverPreview(null);
}

// Back to the real state: drops hover and the selection preview (keeps filter and selected value)
function showRealState() {
    clearTimeout(hoverPreviewTimer);
    // hoverCandidate is kept: a mouseover re-fired on the item still under the
    // pointer must not bring the preview back (only moving to another item does)
    hoverConfig = null;
    hoverFromKeyboard = false;
    selectionPreviewDismissed = true;
    refreshLightsView();
}

function moveActiveItem(step) {
    if (!filteredConfigurations.length) {
        return;
    }
    if (pickerActiveIndex < 0) {
        pickerActiveIndex = step > 0 ? 0 : filteredConfigurations.length - 1;
    } else {
        pickerActiveIndex = (pickerActiveIndex + step + filteredConfigurations.length) % filteredConfigurations.length;
    }
    updatePickerStates();
    setHoverPreview(filteredConfigurations[pickerActiveIndex], true);
}

function showFavoriteFeedback(text) {
    const $feedback = $('#favorites-feedback');
    clearTimeout(favoriteFeedbackTimer);
    $feedback.text(text).removeClass('d-none');
    favoriteFeedbackTimer = setTimeout(function () {
        $feedback.text('').addClass('d-none');
    }, FAVORITE_FEEDBACK_MS);
}

function setFavoriteLocal(name, favorite) {
    if (favorite) {
        favoriteNames.add(name);
    } else {
        favoriteNames.delete(name);
    }
}

// Optimistic toggle: update the list now; the server is synced per name in order.
// pointer ({x, y}) is the click position for mouse toggles, null for keyboard.
function toggleFavorite(item, fromKeyboard, pointer) {
    if (!item) {
        return;
    }
    const name = item.name;
    const favorite = !favoriteNames.has(name);
    setFavoriteLocal(name, favorite);

    if (!fromKeyboard) {
        // The user clicked the star, not asked for a preview
        suppressHoverUntilMove = pointer || { x: NaN, y: NaN };
        clearHoverPreview();
    }
    renderConfigList({ keepActive: true, scrollToActive: Boolean(fromKeyboard) });

    const state = favoriteSync[name] || (favoriteSync[name] = { inFlight: false, desired: favorite });
    state.desired = favorite;
    sendFavoriteSync(name);
}

function sendFavoriteSync(name) {
    const state = favoriteSync[name];
    if (!state || state.inFlight) {
        return;
    }
    const sent = state.desired;
    state.inFlight = true;
    $.ajax({
        type: sent ? 'PUT' : 'DELETE',
        url: '/configurations/favorites/' + encodeURIComponent(name)
    }).done(function () {
        state.inFlight = false;
        if (state.desired !== sent) {
            sendFavoriteSync(name);
            return;
        }
        delete favoriteSync[name];
    }).fail(function () {
        state.inFlight = false;
        if (state.desired !== sent) {
            // A newer toggle supersedes this one; its own outcome decides
            sendFavoriteSync(name);
            return;
        }
        delete favoriteSync[name];
        resyncFavoritesAfterFailure(name, sent);
    });
}

// The server's list is the truth after a failure (the failed request may still
// have been applied); names with a sync still pending keep their local state.
function resyncFavoritesAfterFailure(name, wanted) {
    const message = wanted
        ? 'Não foi possível favoritar “' + name + '”.'
        : 'Não foi possível remover “' + name + '” dos favoritos.';
    $.getJSON('/configurations/favorites').done(function (data) {
        const serverNames = (data && Array.isArray(data.favorites)) ? data.favorites.map(String) : [];
        const next = new Set(serverNames);
        Object.keys(favoriteSync).forEach(function (pendingName) {
            if (favoriteSync[pendingName].desired) {
                next.add(pendingName);
            } else {
                next.delete(pendingName);
            }
        });
        favoriteNames = next;
    }).fail(function () {
        // Server unreachable: best guess is that the failed change didn't happen
        if (!favoriteSync[name]) {
            setFavoriteLocal(name, !wanted);
        }
    }).always(function () {
        renderConfigList({ keepActive: true });
        showFavoriteFeedback(message);
    });
}

function readFavoritesOnly() {
    try {
        return window.localStorage.getItem(FAVORITES_ONLY_STORAGE_KEY) === '1';
    } catch (e) {
        return false;
    }
}

function writeFavoritesOnly(value) {
    try {
        window.localStorage.setItem(FAVORITES_ONLY_STORAGE_KEY, value ? '1' : '0');
    } catch (e) { /* storage unavailable: the toggle just isn't remembered */ }
}

function updateFavoritesFilterButton() {
    const $btn = $('#favorites-filter-btn');
    $btn.toggleClass('active', favoritesOnly).attr('aria-pressed', favoritesOnly ? 'true' : 'false');
    $btn.find('i').toggleClass('bi-star-fill', favoritesOnly).toggleClass('bi-star', !favoritesOnly);
}

function setFavoritesOnly(value) {
    favoritesOnly = Boolean(value);
    writeFavoritesOnly(favoritesOnly);
    updateFavoritesFilterButton();
    clearHoverPreview();
    renderConfigList();
}

// Favorites never block the picker: any failure (e.g. older backend) means "no favorites"
function fetchFavoriteNames() {
    return $.getJSON('/configurations/favorites').then(function (data) {
        return (data && Array.isArray(data.favorites)) ? data.favorites : [];
    }, function () {
        return [];
    });
}

// Never blocks the picker. Resolves null (no scene) or undefined (request failed)
function fetchLastApplied() {
    return $.getJSON('/configurations/last-applied').then(function (data) {
        if (!data || typeof data.name !== 'string' || !data.name) {
            return null;
        }
        const appliedAt = data.applied_at ? new Date(data.applied_at) : null;
        return {
            name: data.name,
            appliedAt: appliedAt && !isNaN(appliedAt.getTime()) ? appliedAt : new Date()
        };
    }, function () {
        return undefined;
    });
}

// Resolves the server info, or undefined when the request failed or an
// apply/off/undo on this page made the answer stale
function requestLastApplied() {
    const startSeq = lastAppliedLocalSeq;
    return fetchLastApplied().then(function (info) {
        return lastAppliedLocalSeq === startSeq ? info : undefined;
    });
}

// Initial load, once the list is rendered: badge + pre-selection (without preview)
function applyInitialLastApplied(info) {
    if (info === undefined) {
        return;
    }
    lastApplied = info;
    updateLastAppliedBadges();
    if (!info || selectedConfig) {
        // Never override a scene the user picked while this request was in flight
        return;
    }
    const item = configurationsCache.find(function (config) {
        return config.name === info.name;
    });
    if (item) {
        selectWithoutPreview(item);
    }
}

// Back on a visible tab: another device/tab may have applied a scene meanwhile.
// Only the badge follows; the user's selection is left alone.
function refreshLastAppliedBadge() {
    requestLastApplied().done(function (info) {
        if (info === undefined) {
            return;
        }
        lastApplied = info;
        updateLastAppliedBadges();
    });
}

// options.reload: refresh after a change on this page (e.g. a deletion). Keeps the
// list, filter, scroll and selection on screen, never pre-selects the last applied
// scene, and on failure leaves the current list in place.
function loadConfigurations(options) {
    const reload = Boolean(options && options.reload);
    const $filter = $('#configurations-filter');
    if (!reload) {
        $filter.prop('disabled', true).attr('placeholder', 'Carregando configurações...');
        $('#configurations-count').text('');
        setPickerMessage('Carregando configurações...');
    }

    // In parallel, but outside $.when: the list never waits for it
    const lastAppliedRequest = requestLastApplied();

    $.when(
        $.getJSON('/configurations?include_settings=true'),
        fetchFavoriteNames()
    ).done(function (configResult, favorites) {
        const data = configResult[0];
        configurationsCache = Array.isArray(data) ? data.slice() : [];
        favoriteNames = new Set(Array.isArray(favorites) ? favorites.map(String) : []);
        // Re-sort client-side: pt-BR collation orders accented names correctly,
        // unlike the server's codepoint sort.
        configurationsCache.sort(function (a, b) {
            return String(a.name).localeCompare(String(b.name), 'pt-BR');
        });
        $filter.prop('disabled', false).attr('placeholder', 'Filtrar por nome ou descrição...');
        if (reload) {
            remapStateToCache();
            renderConfigList({ keepActive: true });
            lastAppliedRequest.done(function (info) {
                if (info !== undefined) {
                    lastApplied = info;
                    updateLastAppliedBadges();
                }
            });
            return;
        }
        renderConfigList();
        lastAppliedRequest.done(applyInitialLastApplied);
    }).fail(function () {
        if (reload) {
            showConfigFeedback('Não foi possível recarregar a lista de configurações.', true);
            return;
        }
        configurationsCache = [];
        filteredConfigurations = [];
        $filter.prop('disabled', false).attr('placeholder', 'Erro ao carregar configurações');
        $('#configurations-count').text('');
        setPickerMessage('Erro ao carregar configurações', 'text-danger');
        selectConfiguration(null);
    });
}

// After a reload the cache holds new objects: point the selection (and the
// pending post-apply preview) at the fresh item with the same name.
function remapStateToCache() {
    function fresh(item) {
        if (!item) {
            return null;
        }
        return configurationsCache.find(function (config) {
            return config.name === item.name;
        }) || null;
    }
    const wasAwaitingSelected = Boolean(awaitingStatusFor) && awaitingStatusFor === selectedConfig;
    if (hoverConfig) {
        clearTimeout(hoverPreviewTimer);
        hoverConfig = null;
        hoverFromKeyboard = false;
    }
    hoverCandidate = null;
    if (selectedConfig) {
        const item = fresh(selectedConfig);
        if (item) {
            selectedConfig = item;
        } else {
            selectedConfig = null;
            selectionPreviewDismissed = false;
        }
    }
    awaitingStatusFor = wasAwaitingSelected ? selectedConfig : fresh(awaitingStatusFor);
    refreshLightsView();
}

function showConfigFeedback(text, isError) {
    const $feedback = $('#configurations-feedback');
    clearTimeout(configFeedbackTimer);
    $feedback.text(text)
        .toggleClass('text-danger', Boolean(isError))
        .toggleClass('text-success', !isError)
        .removeClass('d-none');
    configFeedbackTimer = setTimeout(function () {
        $feedback.text('').addClass('d-none');
    }, CONFIG_FEEDBACK_MS);
}

// Drops a deleted scene from everything this page holds (list, favorites, badge,
// selection and preview) without waiting for the reload.
function removeConfigurationLocally(name) {
    configurationsCache = configurationsCache.filter(function (item) {
        return item.name !== name;
    });
    favoriteNames.delete(name);
    if (lastApplied && lastApplied.name === name) {
        // The server reports an orphaned last-applied scene as null too
        lastApplied = null;
    }
    if (awaitingStatusFor && awaitingStatusFor.name === name) {
        awaitingStatusFor = null;
    }
    if (hoverConfig && hoverConfig.name === name) {
        setHoverPreview(null);
    }
    if (selectedConfig && selectedConfig.name === name) {
        selectConfiguration(null);
    }
    renderConfigList({ keepActive: true });
}

function setDeleteConfirmBusy(busy) {
    const $btn = $('#delete-config-confirm-btn');
    $btn.prop('disabled', busy).html(busy
        ? '<i class="bi bi-hourglass-split" aria-hidden="true"></i> Excluindo...'
        : '<i class="bi bi-trash" aria-hidden="true"></i> Excluir');
}

function openDeleteConfigModal() {
    if (!selectedConfig || deleteConfigInFlight || !deleteConfigModal) {
        return;
    }
    deleteConfigTarget = selectedConfig.name;
    $('#delete-config-name').text('“' + deleteConfigTarget + '”');
    $('#delete-config-error').text('').addClass('d-none');
    setDeleteConfirmBusy(false);
    deleteConfigModal.show();
}

function errorDetail(jqXHR, fallback) {
    const body = jqXHR && jqXHR.responseJSON;
    if (body && body.detail) {
        return typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    }
    return fallback || 'erro desconhecido';
}

function confirmDeleteConfig() {
    const name = deleteConfigTarget;
    if (!name || deleteConfigInFlight) {
        return;
    }
    deleteConfigInFlight = true;
    setDeleteConfirmBusy(true);
    updateDeleteButton();
    $('#delete-config-error').text('').addClass('d-none');

    $.ajax({
        type: 'DELETE',
        url: '/configurations/' + encodeURIComponent(name)
    }).done(function () {
        deleteConfigModal.hide();
        removeConfigurationLocally(name);
        showConfigFeedback('Configuração “' + name + '” excluída.', false);
        loadConfigurations({ reload: true });
    }).fail(function (jqXHR, textStatus, errorThrown) {
        if (jqXHR.status === 404) {
            // Already gone (another tab or the chat): the list just catches up
            deleteConfigModal.hide();
            removeConfigurationLocally(name);
            showConfigFeedback('A configuração “' + name + '” já tinha sido excluída.', true);
            loadConfigurations({ reload: true });
            return;
        }
        $('#delete-config-error')
            .text('Não foi possível excluir: ' + errorDetail(jqXHR, errorThrown))
            .removeClass('d-none');
    }).always(function () {
        deleteConfigInFlight = false;
        setDeleteConfirmBusy(false);
        updateDeleteButton();
    });
}

function initDeleteConfig() {
    const modalEl = document.getElementById('deleteConfigModal');
    if (!modalEl || typeof bootstrap === 'undefined') {
        return;
    }
    deleteConfigModal = new bootstrap.Modal(modalEl);
    $('#delete-config-btn').on('click', openDeleteConfigModal);
    $('#delete-config-confirm-btn').on('click', confirmDeleteConfig);
    modalEl.addEventListener('hidden.bs.modal', function () {
        if (!deleteConfigInFlight) {
            deleteConfigTarget = null;
        }
    });
    updateDeleteButton();
}

// Mouse hover over an element of the list: schedule a preview of its row
function handleHoverTarget(target) {
    const $row = $(target).closest('.config-picker-item');
    if (!$row.length) {
        return;
    }
    const item = $row.data('config');
    if ($(target).closest('.config-fav-btn').length) {
        // The star neither starts nor replaces a preview; it only cancels a
        // pending one for another item (pointer reached this star from it)
        if (hoverCandidate && hoverCandidate !== item && hoverCandidate !== hoverConfig) {
            clearTimeout(hoverPreviewTimer);
            hoverCandidate = null;
        }
        return;
    }
    if (!item || item === hoverCandidate) {
        // mouseover also fires when crossing child elements of the same item
        return;
    }
    hoverCandidate = item;
    clearTimeout(hoverPreviewTimer);
    hoverPreviewTimer = setTimeout(function () {
        if (hoverCandidate === item) {
            setHoverPreview(item, false);
        }
    }, HOVER_PREVIEW_DELAY_MS);
}

function initConfigurationsPicker() {
    const $filter = $('#configurations-filter');
    const $list = $('#configurations-list');

    $filter.on('input', function () {
        // The list is rebuilt, so any hover/keyboard preview is stale
        clearHoverPreview();
        renderConfigList();
    });

    favoritesOnly = readFavoritesOnly();
    updateFavoritesFilterButton();
    $('#favorites-filter-btn').on('click', function () {
        setFavoritesOnly(!favoritesOnly);
    });

    $filter.on('keydown', function (event) {
        if ((event.ctrlKey || event.metaKey) && !event.altKey && String(event.key).toLowerCase() === 'd') {
            // Ctrl+D / Cmd+D favorites the active item instead of bookmarking the page
            event.preventDefault();
            if (pickerActiveIndex >= 0 && pickerActiveIndex < filteredConfigurations.length) {
                toggleFavorite(filteredConfigurations[pickerActiveIndex], true);
            }
            return;
        }

        if (event.key === 'ArrowDown') {
            event.preventDefault();
            moveActiveItem(1);
            return;
        }

        if (event.key === 'ArrowUp') {
            event.preventDefault();
            moveActiveItem(-1);
            return;
        }

        if (event.key === 'Enter') {
            // Never submit the form from the filter; Enter only selects
            event.preventDefault();
            if (pickerActiveIndex >= 0 && pickerActiveIndex < filteredConfigurations.length) {
                selectConfiguration(filteredConfigurations[pickerActiveIndex]);
            }
            return;
        }

        if (event.key === 'Escape') {
            // Stop the native type=search Esc from clearing the filter text
            event.preventDefault();
            showRealState();
        }
    });

    $filter.on('blur', function () {
        if (hoverFromKeyboard) {
            clearHoverPreview();
        }
    });

    // Star: never selects or previews. Delegated handlers run deepest first, so
    // stopPropagation here keeps the item's click handler from firing.
    $list.on('mousedown', '.config-fav-btn', function (event) {
        // Keep focus where it was (usually the filter) so Ctrl+D / ↑↓ keep working
        event.preventDefault();
    });
    $list.on('click', '.config-fav-btn', function (event) {
        event.preventDefault();
        event.stopPropagation();
        toggleFavorite($(this).closest('.config-picker-item').data('config'), false,
            { x: event.clientX, y: event.clientY });
    });

    $list.on('click', '.config-picker-item', function (event) {
        if ($(event.target).closest('.config-fav-btn').length) {
            return;
        }
        const item = $(this).data('config');
        pickerActiveIndex = filteredConfigurations.indexOf(item);
        selectConfiguration(item);
    });

    // Hover preview: mouse only (touch relies on click). Emulated mouse events
    // that follow a touch are ignored via lastTouchAt.
    const listEl = $list.get(0);
    if (listEl) {
        listEl.addEventListener('touchstart', function () {
            lastTouchAt = Date.now();
        }, { passive: true });
    }

    $list.on('mouseover', '.config-picker-item', function (event) {
        if (Date.now() - lastTouchAt < TOUCH_MOUSE_GUARD_MS || suppressHoverUntilMove) {
            return;
        }
        handleHoverTarget(event.target);
    });

    $list.on('mousemove', function (event) {
        if (!suppressHoverUntilMove) {
            return;
        }
        const origin = suppressHoverUntilMove;
        const moved = !(Math.abs(event.clientX - origin.x) <= HOVER_RESUME_MOVE_PX
            && Math.abs(event.clientY - origin.y) <= HOVER_RESUME_MOVE_PX);
        if (!moved) {
            return;
        }
        suppressHoverUntilMove = null;
        // No new mouseover comes while staying on the same row: resume from here
        if (Date.now() - lastTouchAt >= TOUCH_MOUSE_GUARD_MS) {
            handleHoverTarget(event.target);
        }
    });

    $list.on('mouseleave', function () {
        suppressHoverUntilMove = null;
        hoverCandidate = null;
        clearTimeout(hoverPreviewTimer);
        if (hoverConfig && !hoverFromKeyboard) {
            setHoverPreview(null);
        }
    });

    $('#real-state-btn').on('click', showRealState);
}

function applyConfiguration(event) {
    event.preventDefault();

    const configName = selectedConfig && selectedConfig.name;
    if (!configName) {
        alert('Por favor, selecione uma configuração.');
        $('#configurations-filter').trigger('focus');
        return;
    }

    const transitionTimeSecs = $('#transition_time_secs').val() || 0;

    const btn = $('#apply-btn');
    const originalHtml = btn.html();
    btn.html('<i class="bi bi-hourglass-split"></i> Aplicando...').prop('disabled', true);

    $.ajax({
        type: 'POST',
        url: `/apply`,
        contentType: 'application/json',
        data: JSON.stringify({
            config_name: configName,
            transition_time_secs: parseFloat(transitionTimeSecs)
        }),
        success: function (data) {
            btn.html('<i class="bi bi-check-circle"></i> Aplicado!').removeClass('btn-primary').addClass('btn-success');
            setTimeout(() => {
                btn.html(originalHtml).removeClass('btn-success').addClass('btn-primary').prop('disabled', false);
            }, 2000);
            // 200/207 with at least one light applied: the server recorded it too
            if (data && Array.isArray(data.applied) && data.applied.length) {
                setLastAppliedLocally(configName);
            }
            refreshAfterAction(true);
        },
        error: function (jqXHR, textStatus, errorThrown) {
            // Keep the preview so the user can retry
            btn.html(originalHtml).prop('disabled', false);
            alert('Erro ao aplicar configuração: ' + errorThrown);
        }
    });
}

function turnOffAllLights() {
    const btn = $('#off-btn');
    const originalHtml = btn.html();
    btn.html('<i class="bi bi-hourglass-split"></i> Desligando...').prop('disabled', true);

    $.ajax({
        type: 'POST',
        url: '/lights/off',
        contentType: 'application/json',
        data: JSON.stringify({ transition_time_secs: 1 }),
        success: function (data, textStatus, jqXHR) {
            // jQuery treats 207 (partial) as success
            let label = 'Desligadas!';
            if (jqXHR.status === 207) {
                const failedCount = data && Array.isArray(data.failed) ? data.failed.length : 0;
                label = failedCount > 0 ? `Desligadas (${failedCount} falharam)` : 'Desligadas (parcial)';
            }
            btn.html('<i class="bi bi-check-circle"></i> ' + label);
            setTimeout(() => {
                btn.html(originalHtml).prop('disabled', false);
            }, 2000);
            // The server forgets the last scene once at least one light went off
            if (data && Array.isArray(data.applied) && data.applied.length) {
                setLastAppliedLocally(null);
            }
            refreshAfterAction(false);
        },
        error: function (jqXHR, textStatus, errorThrown) {
            btn.html(originalHtml).prop('disabled', false);
            let detail = errorThrown || 'erro desconhecido';
            const body = jqXHR.responseJSON;
            if (body && body.detail) {
                detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
            } else if (body && body.message) {
                detail = body.message;
            }
            alert('Erro ao desligar lâmpadas: ' + detail);
        }
    });
}

function checkBridgeStatus() {
    $.getJSON('/api/bridge/status', function(data) {
        const statusEl = $('#bridge-status');
        if (data.connected) {
            statusEl.html(`<i class="bi bi-circle-fill text-success"></i> Bridge conectada (${data.bridge_ip}) - ${data.light_count} lâmpadas`);
        } else {
            statusEl.html(`<i class="bi bi-circle-fill text-danger"></i> Bridge desconectada`);
        }
    }).fail(function() {
        $('#bridge-status').html('<i class="bi bi-circle-fill text-danger"></i> Erro ao verificar conexão');
    });
}

function undoLastScene() {
    const btn = $('#undo-btn');
    const originalHtml = btn.html();
    btn.html('<i class="bi bi-hourglass-split"></i> Desfazendo...').prop('disabled', true);
    $.ajax({
        type: 'POST',
        url: '/api/history/undo',
        success: function (data) {
            btn.html('<i class="bi bi-check-circle"></i> Desfeito!');
            setTimeout(function () {
                btn.html(originalHtml).prop('disabled', false);
            }, 2000);
            // The restored snapshot is not a named scene
            setLastAppliedLocally(null);
            refreshAfterAction(false);
            const count = data && data.restored_count != null ? data.restored_count : '?';
            // soft feedback without blocking UI
            console.info('Undo restored lights:', count);
        },
        error: function (jqXHR) {
            btn.html(originalHtml).prop('disabled', false);
            let detail = 'Erro ao desfazer';
            try {
                if (jqXHR.responseJSON && jqXHR.responseJSON.detail) {
                    detail = jqXHR.responseJSON.detail;
                }
            } catch (e) { /* ignore */ }
            alert(detail);
        }
    });
}

function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    setTheme(savedTheme);
}

function setTheme(theme) {
    document.documentElement.setAttribute('data-bs-theme', theme);
    localStorage.setItem('theme', theme);

    const icon = $('#theme-icon');
    if (theme === 'dark') {
        icon.removeClass('bi-moon-fill').addClass('bi-sun-fill');
    } else {
        icon.removeClass('bi-sun-fill').addClass('bi-moon-fill');
    }
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-bs-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    setTheme(newTheme);
}

$(document).ready(function () {
    initTheme();
    checkBridgeStatus();
    initConfigurationsPicker();
    initDeleteConfig();
    loadConfigurations();
    loadLightsStatus();
    startLightsAutoRefresh();
    // Keeps "há X" current without re-rendering the list
    setInterval(updateLastAppliedBadges, LAST_APPLIED_REFRESH_MS);
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible' && configurationsCache.length) {
            refreshLastAppliedBadge();
        }
    });
    $('#apply-btn').click(applyConfiguration);
    $('#off-btn').click(turnOffAllLights);
    $('#undo-btn').click(undoLastScene);
    $('#theme-btn').click(toggleTheme);
    $('#refresh-lights-btn').click(function() {
        const btn = $(this);
        btn.find('i').addClass('spin');
        loadLightsStatus();
        setTimeout(() => btn.find('i').removeClass('spin'), 500);
    });
});
