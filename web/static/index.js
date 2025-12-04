let lightsRefreshInterval = null;
let isLoadingLights = false;

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

function loadConfigurations() {
    $.getJSON(`/configurations`, function (data) {
        const configurationsSelect = $('#configurations');
        configurationsSelect.empty();
        configurationsSelect.append($('<option>', {
            value: '',
            text: 'Selecione uma configuração...'
        }));
        $.each(data, function (index, item) {
            configurationsSelect.append($('<option>', {
                value: item.name,
                text: `${item.name} - ${item.description.trim().slice(0, 80)}...`
            }));
        });
    }).fail(function() {
        $('#configurations').html('<option value="">Erro ao carregar configurações</option>');
    });
}

function applyConfiguration(event) {
    event.preventDefault();

    const configName = $('#configurations').val();
    if (!configName) {
        alert('Por favor, selecione uma configuração.');
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
    loadConfigurations();
    loadLightsStatus();
    startLightsAutoRefresh();
    $('#apply-btn').click(applyConfiguration);
    $('#off-btn').click(turnOffAllLights);
    $('#theme-btn').click(toggleTheme);
    $('#refresh-lights-btn').click(function() {
        const btn = $(this);
        btn.find('i').addClass('spin');
        loadLightsStatus();
        setTimeout(() => btn.find('i').removeClass('spin'), 500);
    });
});
