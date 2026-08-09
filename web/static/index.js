let lightsRefreshInterval = null;
let isLoadingLights = false;

/** @type {{name: string, description: string}[]} */
let configurationsCache = [];
let comboboxActiveIndex = -1;
let comboboxIsOpen = false;

function loadLightsStatus() {
    // Evita requisições simultâneas
    if (isLoadingLights) {
        return;
    }
    isLoadingLights = true;

    $.getJSON('/api/lights/status', function(data) {
        renderLights(data.lights);
    }).fail(function() {
        $('#lights-container').html(
            '<div class="lights-loading text-danger">' +
            '<i class="bi bi-exclamation-triangle me-2"></i> Erro ao carregar lâmpadas' +
            '</div>'
        );
    }).always(function() {
        isLoadingLights = false;
    });
}

function renderLights(lights) {
    const container = $('#lights-container');
    container.empty();

    if (!lights || lights.length === 0) {
        container.html(
            '<div class="lights-loading">' +
            '<i class="bi bi-lightbulb-off me-2"></i> Nenhuma lâmpada encontrada' +
            '</div>'
        );
        return;
    }

    // Ordenar lâmpadas por nome (ordem crescente)
    lights.sort((a, b) => a.name.localeCompare(b.name, 'pt-BR'));

    lights.forEach(function(light) {
        const color = light.color;
        const rgbColor = `rgb(${color.r}, ${color.g}, ${color.b})`;
        const isOn = light.on;
        const isReachable = light.reachable;

        let statusClass = 'off';
        if (!isReachable) {
            statusClass = 'unreachable';
        } else if (isOn) {
            statusClass = 'on';
        }

        const lightElement = $('<div>', {
            class: 'light-circle',
            title: `${light.name}\nBrilho: ${Math.round((light.brightness / 254) * 100)}%\n${isOn ? 'Ligada' : 'Desligada'}${!isReachable ? ' (Inacessível)' : ''}`
        });

        const bulb = $('<div>', {
            class: `light-bulb ${statusClass}`,
            css: {
                backgroundColor: rgbColor,
                '--light-color': rgbColor
            }
        });

        const name = $('<span>', {
            class: 'light-name',
            text: light.name
        });

        lightElement.append(bulb).append(name);
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

function setComboboxValue(name, options) {
    options = options || {};
    const $hidden = $('#configurations');
    const $filter = $('#configurations-filter');
    const $wrap = $('#configurations-combobox');

    $hidden.val(name || '');
    if (name) {
        $filter.val(name);
        $wrap.addClass('has-value');
    } else if (!options.keepFilterText) {
        $filter.val('');
        $wrap.removeClass('has-value');
    } else {
        $wrap.toggleClass('has-value', Boolean($filter.val()));
    }

    if (options.close !== false) {
        closeComboboxMenu();
    }
}

function openComboboxMenu() {
    const $menu = $('#configurations-menu');
    const $filter = $('#configurations-filter');
    $menu.addClass('open');
    $filter.attr('aria-expanded', 'true');
    comboboxIsOpen = true;
}

function closeComboboxMenu() {
    const $menu = $('#configurations-menu');
    const $filter = $('#configurations-filter');
    $menu.removeClass('open').empty();
    $filter.attr('aria-expanded', 'false');
    comboboxIsOpen = false;
    comboboxActiveIndex = -1;
}

function updateComboboxActiveItem($items) {
    $items.removeClass('active').attr('aria-selected', 'false');
    if (comboboxActiveIndex < 0 || comboboxActiveIndex >= $items.length) {
        return;
    }
    const $active = $items.eq(comboboxActiveIndex);
    $active.addClass('active').attr('aria-selected', 'true');
    const el = $active.get(0);
    if (el && typeof el.scrollIntoView === 'function') {
        el.scrollIntoView({ block: 'nearest' });
    }
}

function renderConfigurationsMenu(query) {
    const $menu = $('#configurations-menu');
    $menu.empty();

    if (!configurationsCache.length) {
        $menu.append(
            $('<div>', {
                class: 'config-combobox-empty',
                text: 'Nenhuma configuração disponível'
            })
        );
        openComboboxMenu();
        return;
    }

    const filtered = getFilteredConfigurations(query);
    if (!filtered.length) {
        $menu.append(
            $('<div>', {
                class: 'config-combobox-empty',
                text: 'Nenhum resultado para “' + query + '”'
            })
        );
        comboboxActiveIndex = -1;
        openComboboxMenu();
        return;
    }

    filtered.forEach(function (item, index) {
        const $btn = $('<button>', {
            type: 'button',
            class: 'config-combobox-item',
            role: 'option',
            'data-name': item.name,
            'data-index': index,
            'aria-selected': 'false'
        });
        $btn.append($('<span>', { class: 'item-name', text: item.name }));
        $btn.append($('<span>', {
            class: 'item-desc',
            text: truncateDescription(item.description, 90)
        }));
        $menu.append($btn);
    });

    comboboxActiveIndex = 0;
    updateComboboxActiveItem($menu.find('.config-combobox-item'));
    openComboboxMenu();
}

function loadConfigurations() {
    const $filter = $('#configurations-filter');
    $filter.prop('disabled', true).attr('placeholder', 'Carregando configurações...');

    $.getJSON(`/configurations`, function (data) {
        configurationsCache = Array.isArray(data) ? data.slice() : [];
        configurationsCache.sort(function (a, b) {
            return String(a.name).localeCompare(String(b.name), 'pt-BR');
        });
        $filter.prop('disabled', false).attr('placeholder', 'Digite para filtrar configurações...');
        if ($filter.is(':focus')) {
            renderConfigurationsMenu($filter.val());
        }
    }).fail(function () {
        configurationsCache = [];
        $filter
            .prop('disabled', false)
            .attr('placeholder', 'Erro ao carregar configurações')
            .val('');
        setComboboxValue('');
    });
}

function initConfigurationsCombobox() {
    const $filter = $('#configurations-filter');
    const $menu = $('#configurations-menu');
    const $clear = $('#configurations-clear');
    const $wrap = $('#configurations-combobox');

    $filter.on('input', function () {
        const text = $filter.val();
        // Typing invalidates a previous selection until the user picks again
        $('#configurations').val('');
        $wrap.toggleClass('has-value', Boolean(String(text).trim()));
        renderConfigurationsMenu(text);
    });

    $filter.on('focus', function () {
        renderConfigurationsMenu($filter.val());
    });

    $filter.on('keydown', function (event) {
        const $items = $menu.find('.config-combobox-item');

        if (event.key === 'ArrowDown') {
            event.preventDefault();
            if (!comboboxIsOpen) {
                renderConfigurationsMenu($filter.val());
                return;
            }
            if (!$items.length) {
                return;
            }
            comboboxActiveIndex = (comboboxActiveIndex + 1) % $items.length;
            updateComboboxActiveItem($items);
            return;
        }

        if (event.key === 'ArrowUp') {
            event.preventDefault();
            if (!comboboxIsOpen || !$items.length) {
                return;
            }
            comboboxActiveIndex = comboboxActiveIndex <= 0
                ? $items.length - 1
                : comboboxActiveIndex - 1;
            updateComboboxActiveItem($items);
            return;
        }

        if (event.key === 'Enter') {
            if (comboboxIsOpen && $items.length && comboboxActiveIndex >= 0) {
                event.preventDefault();
                const name = $items.eq(comboboxActiveIndex).data('name');
                setComboboxValue(name);
            }
            return;
        }

        if (event.key === 'Escape') {
            if (comboboxIsOpen) {
                event.preventDefault();
                closeComboboxMenu();
            }
            return;
        }

        if (event.key === 'Tab') {
            closeComboboxMenu();
        }
    });

    $menu.on('mousedown', '.config-combobox-item', function (event) {
        // Prevent input blur before click handler runs
        event.preventDefault();
        setComboboxValue($(this).data('name'));
    });

    $menu.on('mouseenter', '.config-combobox-item', function () {
        const $items = $menu.find('.config-combobox-item');
        comboboxActiveIndex = $items.index(this);
        updateComboboxActiveItem($items);
    });

    $clear.on('click', function () {
        setComboboxValue('');
        $filter.trigger('focus');
    });

    $(document).on('mousedown', function (event) {
        if (!$wrap.is(event.target) && $wrap.has(event.target).length === 0) {
            // If user typed something that exactly matches a name, keep it selected
            const typed = String($filter.val() || '').trim();
            const selected = $('#configurations').val();
            if (!selected && typed) {
                const exact = configurationsCache.find(function (item) {
                    return item.name === typed;
                });
                if (exact) {
                    setComboboxValue(exact.name);
                    return;
                }
            }
            closeComboboxMenu();
        }
    });
}

function applyConfiguration(event) {
    event.preventDefault();

    let configName = $('#configurations').val();
    if (!configName) {
        // Allow applying when the typed text is an exact config name
        const typed = String($('#configurations-filter').val() || '').trim();
        const exact = configurationsCache.find(function (item) {
            return item.name === typed;
        });
        if (exact) {
            configName = exact.name;
            setComboboxValue(configName);
        }
    }
    if (!configName) {
        alert('Por favor, selecione uma configuração.');
        $('#configurations-filter').trigger('focus');
        return;
    }

    const transitionTimeSecs = $('#transition_time_secs').val() || 0;
    const durationMinutes = $('#duration_minutes').val() || null;

    const btn = $('#apply-btn');
    const originalHtml = btn.html();
    btn.html('<i class="bi bi-hourglass-split"></i> Aplicando...').prop('disabled', true);

    $.ajax({
        type: 'POST',
        url: `/apply`,
        contentType: 'application/json',
        data: JSON.stringify({
            config_name: configName,
            transition_time_secs: parseFloat(transitionTimeSecs),
            duration_minutes: durationMinutes ? parseFloat(durationMinutes) : null
        }),
        success: function (data) {
            btn.html('<i class="bi bi-check-circle"></i> Aplicado!').removeClass('btn-primary').addClass('btn-success');
            setTimeout(() => {
                btn.html(originalHtml).removeClass('btn-success').addClass('btn-primary').prop('disabled', false);
            }, 2000);
        },
        error: function (jqXHR, textStatus, errorThrown) {
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
            transition_time_secs: 1,
            duration_minutes: null
        }),
        success: function (data) {
            btn.html('<i class="bi bi-check-circle"></i> Desligadas!');
            setTimeout(() => {
                btn.html(originalHtml).prop('disabled', false);
            }, 2000);
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
            loadLightsStatus();
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
    initConfigurationsCombobox();
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
