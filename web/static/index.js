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

const HOVER_PREVIEW_DELAY_MS = 80;
const TOUCH_MOUSE_GUARD_MS = 800;

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

function renderConfigList() {
    const $list = $('#configurations-list');
    const query = $('#configurations-filter').val();
    filteredConfigurations = getFilteredConfigurations(query);
    pickerActiveIndex = -1;

    $('#configurations-count').text(filteredConfigurations.length + ' de ' + configurationsCache.length);

    if (!configurationsCache.length) {
        setPickerMessage('Nenhuma configuração disponível');
        updateSelectedChip();
        return;
    }

    if (!filteredConfigurations.length) {
        setPickerMessage('Nenhum resultado para “' + String(query).trim() + '”');
        updateSelectedChip();
        return;
    }

    $list.empty();
    filteredConfigurations.forEach(function (item) {
        const $option = $('<div>', {
            id: configOptionId(item),
            class: 'config-picker-item',
            role: 'option',
            'aria-selected': 'false',
            title: item.description || item.name
        });
        $option.data('config', item);
        const $text = $('<span>', { class: 'item-text' });
        $text.append($('<span>', { class: 'item-name', text: item.name }));
        $text.append($('<span>', {
            class: 'item-desc',
            text: truncateDescription(item.description, 90)
        }));
        $option.append($text).append(buildColorDots(item));
        $list.append($option);
    });

    updatePickerStates();
}

function updatePickerStates() {
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
        if (el && typeof el.scrollIntoView === 'function') {
            el.scrollIntoView({ block: 'nearest' });
        }
    } else {
        $list.removeAttr('aria-activedescendant');
        $filter.removeAttr('aria-activedescendant');
    }

    updateSelectedChip();
}

function updateSelectedChip() {
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

function loadConfigurations() {
    const $filter = $('#configurations-filter');
    $filter.prop('disabled', true).attr('placeholder', 'Carregando configurações...');
    $('#configurations-count').text('');
    setPickerMessage('Carregando configurações...');

    $.getJSON('/configurations?include_settings=true', function (data) {
        configurationsCache = Array.isArray(data) ? data.slice() : [];
        // Re-sort client-side: pt-BR collation orders accented names correctly,
        // unlike the server's codepoint sort.
        configurationsCache.sort(function (a, b) {
            return String(a.name).localeCompare(String(b.name), 'pt-BR');
        });
        $filter.prop('disabled', false).attr('placeholder', 'Filtrar por nome ou descrição...');
        renderConfigList();
    }).fail(function () {
        configurationsCache = [];
        filteredConfigurations = [];
        $filter.prop('disabled', false).attr('placeholder', 'Erro ao carregar configurações');
        $('#configurations-count').text('');
        setPickerMessage('Erro ao carregar configurações', 'text-danger');
        selectConfiguration(null);
    });
}

function initConfigurationsPicker() {
    const $filter = $('#configurations-filter');
    const $list = $('#configurations-list');

    $filter.on('input', function () {
        // The list is rebuilt, so any hover/keyboard preview is stale
        clearHoverPreview();
        renderConfigList();
    });

    $filter.on('keydown', function (event) {
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

    $list.on('click', '.config-picker-item', function () {
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

    $list.on('mouseover', '.config-picker-item', function () {
        if (Date.now() - lastTouchAt < TOUCH_MOUSE_GUARD_MS) {
            return;
        }
        const item = $(this).data('config');
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
    });

    $list.on('mouseleave', function () {
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
        url: `/apply`,
        contentType: 'application/json',
        data: JSON.stringify({
            config_name: 'all_off',
            transition_time_secs: 1
        }),
        success: function (data) {
            btn.html('<i class="bi bi-check-circle"></i> Desligadas!');
            setTimeout(() => {
                btn.html(originalHtml).prop('disabled', false);
            }, 2000);
            refreshAfterAction(false);
        },
        error: function (jqXHR, textStatus, errorThrown) {
            btn.html(originalHtml).prop('disabled', false);
            alert('Erro ao desligar lâmpadas: ' + errorThrown);
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
    loadConfigurations();
    loadLightsStatus();
    startLightsAutoRefresh();
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
