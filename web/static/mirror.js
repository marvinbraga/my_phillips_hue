// Estado do espelhamento
let isRunning = false;
let ws = null;
let positionsData = {};
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;

// Defaults espelhados de marvin_hue.screen_mirror.MIRROR_PROFILES
const MIRROR_PROFILES = {
    cinema: {
        fps: 12,
        brightness: 160,
        saturation_boost: 1.1,
        smoothing_factor: 0.35,
        transition_time: 2,
    },
    fps: {
        fps: 30,
        brightness: 200,
        saturation_boost: 1.4,
        smoothing_factor: 0.7,
        transition_time: 0,
    },
    ambient: {
        fps: 8,
        brightness: 120,
        saturation_boost: 1.0,
        smoothing_factor: 0.25,
        transition_time: 3,
    },
};

function getSelectedProfile() {
    const checked = $('input[name="mirror-profile"]:checked').val();
    return checked || null;
}

function setProfileUI(profileName) {
    if (!profileName || !MIRROR_PROFILES[profileName]) {
        $('input[name="mirror-profile"]').prop('checked', false);
        return;
    }
    $(`input[name="mirror-profile"][value="${profileName}"]`).prop('checked', true);
    applyProfileToSliders(profileName);
}

function applyProfileToSliders(profileName) {
    const p = MIRROR_PROFILES[profileName];
    if (!p) return;

    $('#fps-range').val(p.fps);
    $('#fps-value').text(p.fps);
    $('#brightness-range').val(p.brightness);
    $('#brightness-value').text(p.brightness);
    $('#saturation-range').val(p.saturation_boost);
    $('#saturation-value').text(p.saturation_boost);
    $('#smoothing-range').val(p.smoothing_factor);
    $('#smoothing-value').text(p.smoothing_factor);
    $('#transition-range').val(p.transition_time);
    $('#transition-value').text(Math.round(p.transition_time * 100));
}

function syncSlidersFromStatus(status) {
    if (!status) return;
    if (typeof status.fps === 'number') {
        $('#fps-range').val(status.fps);
        $('#fps-value').text(status.fps);
    }
    if (typeof status.brightness === 'number') {
        $('#brightness-range').val(status.brightness);
        $('#brightness-value').text(status.brightness);
    }
    if (typeof status.saturation_boost === 'number') {
        $('#saturation-range').val(status.saturation_boost);
        $('#saturation-value').text(status.saturation_boost);
    }
    if (typeof status.smoothing_factor === 'number') {
        $('#smoothing-range').val(status.smoothing_factor);
        $('#smoothing-value').text(status.smoothing_factor);
    }
    if (typeof status.transition_time === 'number') {
        $('#transition-range').val(status.transition_time);
        $('#transition-value').text(Math.round(status.transition_time * 100));
    }
    if (status.active_profile) {
        $(`input[name="mirror-profile"][value="${status.active_profile}"]`).prop('checked', true);
    }
}

// Conectar WebSocket
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/mirror`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('WebSocket conectado');
        reconnectAttempts = 0;
        updateConnectionStatus(true);
    };

    ws.onmessage = (event) => {
        const status = JSON.parse(event.data);
        updateUI(status);
    };

    ws.onclose = () => {
        console.log('WebSocket desconectado');
        updateConnectionStatus(false);

        // Tentar reconectar
        if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
            reconnectAttempts++;
            setTimeout(connectWebSocket, 2000 * reconnectAttempts);
        }
    };

    ws.onerror = (error) => {
        console.error('Erro no WebSocket:', error);
    };
}

// Atualizar status de conexão
function updateConnectionStatus(connected) {
    const indicator = $('#connection-status');
    if (connected) {
        indicator.removeClass('text-danger').addClass('text-success');
        indicator.html('<i class="bi bi-wifi"></i> Conectado');
    } else {
        indicator.removeClass('text-success').addClass('text-danger');
        indicator.html('<i class="bi bi-wifi-off"></i> Desconectado');
    }
}

// Carregar configuração de posições para mapear lâmpadas
function loadPositions() {
    fetch('/positions')
        .then(response => response.json())
        .then(data => {
            positionsData = {};
            data.lights.forEach(light => {
                if (light.enabled && light.position !== 'none') {
                    if (!positionsData[light.position]) {
                        positionsData[light.position] = [];
                    }
                    positionsData[light.position].push(light.name);
                }
            });
        });
}

// Atualizar UI baseado no status
function updateUI(status) {
    isRunning = status.running;

    const statusEl = $('#mirror-status');
    const statusText = $('#status-text');
    const startBtn = $('#start-btn');
    const stopBtn = $('#stop-btn');

    if (isRunning) {
        statusEl.removeClass('inactive').addClass('active');
        statusText.html(`<i class="bi bi-broadcast"></i> Espelhamento Ativo<br><small>${status.fps} FPS</small>`);
        startBtn.prop('disabled', true);
        stopBtn.prop('disabled', false);

        // Atualizar preview de cores
        updateColorPreview(status.colors);
        updateMonitorPreview(status.colors);
    } else {
        statusEl.removeClass('active').addClass('inactive');
        statusText.html('<i class="bi bi-display"></i> Espelhamento Inativo');
        startBtn.prop('disabled', false);
        stopBtn.prop('disabled', true);

        $('#color-preview').html('<div class="text-muted">Inicie o espelhamento para ver as cores</div>');
        clearMonitorPreview();
    }
}

// Atualizar preview de cores
function updateColorPreview(colors) {
    const container = $('#color-preview');
    container.empty();

    if (!colors || Object.keys(colors).length === 0) {
        container.html('<div class="text-muted">Aguardando cores...</div>');
        return;
    }

    Object.entries(colors).forEach(([lightName, rgb]) => {
        const [r, g, b] = rgb;
        const colorHex = rgbToHex(r, g, b);

        container.append(`
            <div class="color-item">
                <div class="color-swatch" style="background-color: ${colorHex}"></div>
                <div class="color-name" title="${lightName}">${lightName}</div>
            </div>
        `);
    });
}

// Atualizar preview do monitor
function updateMonitorPreview(colors) {
    if (!colors) return;

    // Agrupar cores por posição
    const positionColors = {};

    Object.entries(colors).forEach(([lightName, rgb]) => {
        // Encontrar a posição desta lâmpada
        for (const [position, lights] of Object.entries(positionsData)) {
            if (lights.includes(lightName)) {
                positionColors[position] = rgb;
                break;
            }
        }
    });

    // Atualizar regiões do monitor
    $('.region').each(function() {
        const position = $(this).data('position');
        if (positionColors[position]) {
            const [r, g, b] = positionColors[position];
            $(this).css('background-color', rgbToHex(r, g, b));
        }
    });
}

// Limpar preview do monitor
function clearMonitorPreview() {
    $('.region').css('background-color', 'transparent');
}

// Converter RGB para Hex
function rgbToHex(r, g, b) {
    return '#' + [r, g, b].map(x => {
        const hex = x.toString(16);
        return hex.length === 1 ? '0' + hex : hex;
    }).join('');
}

// Iniciar espelhamento via WebSocket
function startMirror() {
    const fps = parseInt($('#fps-range').val(), 10);
    const brightness = parseInt($('#brightness-range').val(), 10);
    const profile = getSelectedProfile();
    const payload = { action: 'start', fps, brightness };
    if (profile) {
        payload.profile = profile;
    }

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(payload));
    } else {
        // Fallback para HTTP
        const body = { fps, brightness };
        if (profile) {
            body.profile = profile;
        }
        fetch('/mirror/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        })
        .then(response => response.json())
        .then(data => {
            if (data.detail) {
                alert(data.detail);
            } else if (data.error) {
                alert(data.error);
            }
        })
        .catch(err => alert('Erro ao iniciar: ' + err));
    }
}

// Parar espelhamento via WebSocket
function stopMirror() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'stop' }));
    } else {
        // Fallback para HTTP
        fetch('/mirror/stop', { method: 'POST' })
        .then(response => response.json())
        .catch(err => alert('Erro ao parar: ' + err));
    }
}

function flashApplyButton() {
    const btn = $('#apply-settings-btn');
    const originalHtml = btn.html();
    btn.html('<i class="bi bi-check-circle"></i> Aplicado!').addClass('btn-success').removeClass('btn-outline-primary');
    setTimeout(() => {
        btn.html(originalHtml).removeClass('btn-success').addClass('btn-outline-primary');
    }, 2000);
}

// Aplicar configurações via WebSocket
function applySettings(options) {
    const includeProfile = !options || options.includeProfile !== false;
    const settings = {
        action: 'settings',
        fps: parseInt($('#fps-range').val(), 10),
        brightness: parseInt($('#brightness-range').val(), 10),
        saturation_boost: parseFloat($('#saturation-range').val()),
        smoothing_factor: parseFloat($('#smoothing-range').val()),
        transition_time: parseFloat($('#transition-range').val())
    };
    const profile = getSelectedProfile();
    if (includeProfile && profile) {
        settings.profile = profile;
    }

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(settings));
        flashApplyButton();
    } else {
        // Fallback para HTTP
        const body = {
            fps: settings.fps,
            brightness: settings.brightness,
            saturation_boost: settings.saturation_boost,
            smoothing_factor: settings.smoothing_factor,
            transition_time: settings.transition_time
        };
        if (settings.profile) {
            body.profile = settings.profile;
        }
        fetch('/mirror/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        })
        .then(() => flashApplyButton())
        .catch(err => alert('Erro ao aplicar: ' + err));
    }
}

function onProfileSelected() {
    const profile = getSelectedProfile();
    if (!profile) return;
    applyProfileToSliders(profile);
    // Envia profile ao backend (e sliders alinhados); se mirror ativo, aplica em tempo real
    applySettings({ includeProfile: true });
}

// Buscar status inicial
function fetchInitialStatus() {
    fetch('/mirror/status')
        .then(response => response.json())
        .then(status => {
            updateUI(status);
            syncSlidersFromStatus(status);
        })
        .catch(err => console.error('Erro ao buscar status:', err));
}

// Verificar status da bridge
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

// Tema
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

// Event listeners para sliders
function setupSliders() {
    $('#fps-range').on('input', function() {
        $('#fps-value').text($(this).val());
    });

    $('#brightness-range').on('input', function() {
        $('#brightness-value').text($(this).val());
    });

    $('#saturation-range').on('input', function() {
        $('#saturation-value').text($(this).val());
    });

    $('#smoothing-range').on('input', function() {
        $('#smoothing-value').text($(this).val());
    });

    $('#transition-range').on('input', function() {
        // Converte décimos de segundo para milissegundos para exibição
        $('#transition-value').text(Math.round(parseFloat($(this).val()) * 100));
    });
}

// Inicialização
$(document).ready(function() {
    initTheme();
    checkBridgeStatus();
    loadPositions();
    setupSliders();
    fetchInitialStatus();

    // Conectar WebSocket
    connectWebSocket();

    // Event handlers
    $('#start-btn').click(startMirror);
    $('#stop-btn').click(stopMirror);
    $('#apply-settings-btn').click(function() { applySettings(); });
    $('#theme-btn').click(toggleTheme);
    $('input[name="mirror-profile"]').on('change', onProfileSelected);
});

// Cleanup ao sair da página
$(window).on('beforeunload', function() {
    if (ws) {
        ws.close();
    }
});
