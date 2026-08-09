// Estado do espelhamento
let isRunning = false;
let currentMode = 'screen'; // UI tab: 'screen' | 'audio'
let activeMode = null; // from backend when running
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

// Defaults de marvin_hue.audio_mirror.AUDIO_MIRROR_PROFILES + intensity aliases
const AUDIO_PROFILES = {
    party: {
        fps: 36,
        brightness: 235,
        smoothing_factor: 0.70,
        transition_time: 0,
        energy_gain: 1.05,
    },
    chill: {
        fps: 18,
        brightness: 150,
        smoothing_factor: 0.28,
        transition_time: 2,
        energy_gain: 0.85,
    },
    pulse: {
        fps: 38,
        brightness: 250,
        smoothing_factor: 0.80,
        transition_time: 0,
        energy_gain: 1.15,
    },
    subtle: {
        fps: 24,
        brightness: 150,
        smoothing_factor: 0.28,
        transition_time: 2,
        energy_gain: 0.85,
    },
    moderate: {
        fps: 30,
        brightness: 200,
        smoothing_factor: 0.50,
        transition_time: 0,
        energy_gain: 1.0,
    },
    high: {
        fps: 36,
        brightness: 235,
        smoothing_factor: 0.70,
        transition_time: 0,
        energy_gain: 1.05,
    },
    extreme: {
        fps: 38,
        brightness: 250,
        smoothing_factor: 0.80,
        transition_time: 0,
        energy_gain: 1.15,
    },
};

function getSelectedProfile() {
    if (currentMode === 'audio') {
        return $('input[name="audio-profile"]:checked').val() || null;
    }
    return $('input[name="mirror-profile"]:checked').val() || null;
}

function setProfileUI(profileName) {
    if (currentMode === 'audio') {
        if (!profileName || !AUDIO_PROFILES[profileName]) {
            $('input[name="audio-profile"]').prop('checked', false);
            return;
        }
        $(`input[name="audio-profile"][value="${profileName}"]`).prop('checked', true);
        applyAudioProfileToSliders(profileName);
        return;
    }
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

function applyAudioProfileToSliders(profileName) {
    const p = AUDIO_PROFILES[profileName];
    if (!p) return;

    $('#fps-range').val(p.fps);
    $('#fps-value').text(p.fps);
    $('#brightness-range').val(p.brightness);
    $('#brightness-value').text(p.brightness);
    $('#smoothing-range').val(p.smoothing_factor);
    $('#smoothing-value').text(p.smoothing_factor);
    $('#transition-range').val(p.transition_time);
    $('#transition-value').text(Math.round(p.transition_time * 100));
    if (typeof p.energy_gain === 'number') {
        $('#energy-gain-range').val(p.energy_gain);
        $('#energy-gain-value').text(p.energy_gain);
    }
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
    if (typeof status.energy_gain === 'number') {
        $('#energy-gain-range').val(status.energy_gain);
        $('#energy-gain-value').text(status.energy_gain);
    }
    if (status.active_profile) {
        if (status.mode === 'audio' || AUDIO_PROFILES[status.active_profile]) {
            $(`input[name="audio-profile"][value="${status.active_profile}"]`).prop('checked', true);
        } else {
            $(`input[name="mirror-profile"][value="${status.active_profile}"]`).prop('checked', true);
        }
    }
}

function setModeUI(mode) {
    currentMode = mode === 'audio' ? 'audio' : 'screen';
    $('#tab-screen').toggleClass('active', currentMode === 'screen');
    $('#tab-audio').toggleClass('active', currentMode === 'audio');

    $('#screen-preview-wrap').toggleClass('d-none', currentMode !== 'screen');
    $('#audio-preview-wrap').toggleClass('d-none', currentMode !== 'audio');
    $('#screen-profiles').toggleClass('d-none', currentMode !== 'screen');
    $('#audio-profiles').toggleClass('d-none', currentMode !== 'audio');
    $('#saturation-wrap').toggleClass('d-none', currentMode !== 'screen');
    $('#energy-gain-wrap').toggleClass('d-none', currentMode !== 'audio');
    $('#help-screen').toggleClass('d-none', currentMode !== 'screen');
    $('#help-audio').toggleClass('d-none', currentMode !== 'audio');

    if (currentMode === 'audio') {
        $('#mode-help').text(
            'Espelhamento de música: reage ao áudio do sistema (monitor PulseAudio/PipeWire).'
        );
    } else {
        $('#mode-help').text(
            'Sincronize as cores das lâmpadas com o conteúdo da sua tela em tempo real.'
        );
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
        if (status.error) {
            console.warn('Mirror WS error:', status.error);
            alert(status.error);
            return;
        }
        updateUI(status);
    };

    ws.onclose = () => {
        console.log('WebSocket desconectado');
        updateConnectionStatus(false);

        if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
            reconnectAttempts++;
            setTimeout(connectWebSocket, 2000 * reconnectAttempts);
        }
    };

    ws.onerror = (error) => {
        console.error('Erro no WebSocket:', error);
    };
}

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

// Client-side peak hold for classic analyzer look (independent of backend hold)
const spectrumHold = { bass: 0, mid: 0, treble: 0 };
const spectrumSmooth = { bass: 0, mid: 0, treble: 0 };

function updateSpectrum(status) {
    const target = {
        bass: Math.max(0, Math.min(1, Number(status.bass) || 0)),
        mid: Math.max(0, Math.min(1, Number(status.mid) || 0)),
        treble: Math.max(0, Math.min(1, Number(status.treble) || 0)),
    };
    const beat = Math.max(0, Math.min(1, Number(status.beat) || 0));

    ['bass', 'mid', 'treble'].forEach((k) => {
        // Fast attack / medium release on the client for snappier bars
        const prev = spectrumSmooth[k];
        const t = target[k];
        const alpha = t > prev ? 0.55 : 0.22;
        spectrumSmooth[k] = prev + (t - prev) * alpha;
        if (spectrumSmooth[k] >= spectrumHold[k]) {
            spectrumHold[k] = spectrumSmooth[k];
        } else {
            spectrumHold[k] *= 0.93;
        }
        const body = Math.max(0.02, spectrumSmooth[k]);
        const hold = Math.max(body, spectrumHold[k]);
        $(`#bar-${k}`).css('height', `${(body * 100).toFixed(1)}%`);
        $(`#peak-${k}`).css('bottom', `calc(${(hold * 100).toFixed(1)}% + 18px)`);
        $(`#pct-${k}`).text(`${Math.round(body * 100)}%`);
    });

    const glow = Math.round(beat * 32);
    const opacity = (0.12 + beat * 0.6).toFixed(2);
    $('#spectrum-bars').css(
        'box-shadow',
        glow > 2
            ? `0 0 ${glow}px rgba(255, 200, 80, ${opacity}), inset 0 0 ${Math.round(glow / 2)}px rgba(255, 255, 255, ${beat * 0.12})`
            : 'none'
    );
    $('#spectrum-bars').toggleClass('beat-hit', beat > 0.35);
}

function updateTransportBadge(status) {
    const t = (status && status.transport) || 'rest';
    const badge = $('#transport-badge');
    badge.removeClass('rest entertainment');
    if (t === 'entertainment') {
        badge.addClass('entertainment').text('Entertainment');
    } else {
        badge.addClass('rest').text('REST');
    }
}

function updateUI(status) {
    isRunning = !!status.running;
    activeMode = status.mode || null;

    // Se backend está em um modo, alinha a aba (sem forçar se idle)
    if (isRunning && activeMode && activeMode !== currentMode) {
        setModeUI(activeMode);
    }

    const statusEl = $('#mirror-status');
    const statusText = $('#status-text');
    const startBtn = $('#start-btn');
    const stopBtn = $('#stop-btn');

    updateTransportBadge(status);

    if (isRunning) {
        statusEl.removeClass('inactive').addClass('active');
        statusEl.toggleClass('audio-mode', activeMode === 'audio');
        const label = activeMode === 'audio' ? 'Música Ativa' : 'Espelhamento Ativo';
        const icon = activeMode === 'audio' ? 'bi-music-note-beamed' : 'bi-broadcast';
        const transport = status.transport || 'rest';
        statusText.html(
            `<i class="bi ${icon}"></i> ${label}<br><small>${status.fps} FPS · ${transport}</small>`
        );
        startBtn.prop('disabled', true);
        stopBtn.prop('disabled', false);

        updateColorPreview(status.colors);
        if (activeMode === 'audio') {
            updateSpectrum(status);
        } else {
            updateMonitorPreview(status.colors);
        }
    } else {
        statusEl.removeClass('active audio-mode').addClass('inactive');
        statusText.html('<i class="bi bi-display"></i> Espelhamento Inativo');
        startBtn.prop('disabled', false);
        stopBtn.prop('disabled', true);

        $('#color-preview').html('<div class="text-muted">Inicie o espelhamento para ver as cores</div>');
        clearMonitorPreview();
        updateSpectrum({ bass: 0, mid: 0, treble: 0, beat: 0 });
    }
}

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

function updateMonitorPreview(colors) {
    if (!colors) return;

    const positionColors = {};

    Object.entries(colors).forEach(([lightName, rgb]) => {
        for (const [position, lights] of Object.entries(positionsData)) {
            if (lights.includes(lightName)) {
                positionColors[position] = rgb;
                break;
            }
        }
    });

    $('.region').each(function() {
        const position = $(this).data('position');
        if (positionColors[position]) {
            const [r, g, b] = positionColors[position];
            $(this).css('background-color', rgbToHex(r, g, b));
        }
    });
}

function clearMonitorPreview() {
    $('.region').css('background-color', 'transparent');
}

function rgbToHex(r, g, b) {
    return '#' + [r, g, b].map(x => {
        const hex = x.toString(16);
        return hex.length === 1 ? '0' + hex : hex;
    }).join('');
}

function startMirror() {
    const fps = parseInt($('#fps-range').val(), 10);
    const brightness = parseInt($('#brightness-range').val(), 10);
    const profile = getSelectedProfile();
    const mode = currentMode;
    const transport_preference = $('#transport-pref').val() || 'auto';
    const area_id = $('#ent-area-select').val() || null;
    const payload = { action: 'start', mode, fps, brightness, transport_preference };
    if (profile) {
        payload.profile = profile;
    }
    if (area_id) {
        payload.area_id = area_id;
    }

    if (ws && ws.readyState === WebSocket.OPEN) {
        // WS path may not support entertainment fields fully — prefer REST start
        fetch('/mirror/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mode,
                fps,
                brightness,
                profile: profile || undefined,
                transport_preference,
                area_id: area_id || undefined,
            }),
        })
        .then(response => response.json())
        .then(data => {
            if (data.detail) {
                alert(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
            } else if (data.status) {
                updateUI(data.status);
            }
        })
        .catch(err => alert('Erro ao iniciar: ' + err));
    } else {
        const body = { mode, fps, brightness, transport_preference };
        if (profile) {
            body.profile = profile;
        }
        if (area_id) {
            body.area_id = area_id;
        }
        fetch('/mirror/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        })
        .then(response => response.json())
        .then(data => {
            if (data.detail) {
                alert(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
            } else if (data.error) {
                alert(data.error);
            } else if (data.status) {
                updateUI(data.status);
            }
        })
        .catch(err => alert('Erro ao iniciar: ' + err));
    }
}

function loadEntertainmentStatus() {
    fetch('/mirror/entertainment/status')
        .then(r => r.json())
        .then(data => {
            const enabledBadge = $('#ent-enabled-badge');
            if (data.enabled) {
                enabledBadge.removeClass('bg-secondary').addClass('bg-success').text('enabled');
            } else {
                enabledBadge.removeClass('bg-success').addClass('bg-secondary').text('flag off');
            }
            const readyText = $('#ent-ready-text');
            if (data.ready) {
                readyText.text('credenciais OK');
            } else {
                readyText.text('não pareado');
            }
            const select = $('#ent-area-select');
            select.empty();
            const areas = data.areas || [];
            if (!areas.length) {
                select.append('<option value="">— sem áreas —</option>');
                select.prop('disabled', true);
            } else {
                select.prop('disabled', false);
                areas.forEach(a => {
                    const label = `${a.name || a.id} (${a.channel_count || 0} ch)`;
                    select.append(`<option value="${a.id}">${label}</option>`);
                });
                if (data.default_area_id) {
                    select.val(data.default_area_id);
                }
            }
            if (data.transport) {
                updateTransportBadge({ transport: data.transport });
            }
        })
        .catch(err => console.warn('entertainment status:', err));
}

function pairEntertainment() {
    if (!confirm('Pressione o botão de link da bridge Hue e confirme para iniciar o pairing.')) {
        return;
    }
    const btn = $('#ent-pair-btn');
    btn.prop('disabled', true).text('Pairing…');
    fetch('/mirror/entertainment/pair', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
    })
        .then(async r => {
            const data = await r.json();
            if (!r.ok) {
                throw new Error(data.detail || JSON.stringify(data));
            }
            alert(data.message || 'Pairing OK');
            loadEntertainmentStatus();
        })
        .catch(err => alert('Pairing falhou: ' + err))
        .finally(() => {
            btn.prop('disabled', false).html('<i class="bi bi-link-45deg"></i> Pair (botão da bridge)');
        });
}

function stopMirror() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'stop' }));
    } else {
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

function applySettings(options) {
    const includeProfile = !options || options.includeProfile !== false;
    const mode = currentMode;
    const settings = {
        action: 'settings',
        mode,
        fps: parseInt($('#fps-range').val(), 10),
        brightness: parseInt($('#brightness-range').val(), 10),
        smoothing_factor: parseFloat($('#smoothing-range').val()),
        transition_time: parseFloat($('#transition-range').val())
    };
    if (mode === 'screen') {
        settings.saturation_boost = parseFloat($('#saturation-range').val());
    } else {
        settings.energy_gain = parseFloat($('#energy-gain-range').val());
    }
    const profile = getSelectedProfile();
    if (includeProfile && profile) {
        settings.profile = profile;
    }

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(settings));
        flashApplyButton();
    } else {
        const body = {
            mode: settings.mode,
            fps: settings.fps,
            brightness: settings.brightness,
            smoothing_factor: settings.smoothing_factor,
            transition_time: settings.transition_time
        };
        if (settings.saturation_boost != null) {
            body.saturation_boost = settings.saturation_boost;
        }
        if (settings.energy_gain != null) {
            body.energy_gain = settings.energy_gain;
        }
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
    if (currentMode === 'audio') {
        applyAudioProfileToSliders(profile);
    } else {
        applyProfileToSliders(profile);
    }
    applySettings({ includeProfile: true });
}

function fetchInitialStatus() {
    fetch('/mirror/status')
        .then(response => response.json())
        .then(status => {
            if (status.mode === 'audio' || status.mode === 'screen') {
                setModeUI(status.mode);
            }
            updateUI(status);
            syncSlidersFromStatus(status);
        })
        .catch(err => console.error('Erro ao buscar status:', err));
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
        $('#transition-value').text(Math.round(parseFloat($(this).val()) * 100));
    });

    $('#energy-gain-range').on('input', function() {
        $('#energy-gain-value').text($(this).val());
    });
}

$(document).ready(function() {
    initTheme();
    checkBridgeStatus();
    loadPositions();
    setupSliders();
    setModeUI('screen');
    fetchInitialStatus();
    loadEntertainmentStatus();

    connectWebSocket();

    $('#start-btn').click(startMirror);
    $('#stop-btn').click(stopMirror);
    $('#apply-settings-btn').click(function() { applySettings(); });
    $('#theme-btn').click(toggleTheme);
    $('#ent-pair-btn').click(pairEntertainment);
    $('input[name="mirror-profile"]').on('change', onProfileSelected);
    $('input[name="audio-profile"]').on('change', onProfileSelected);

    $('#tab-screen').on('click', function() {
        if (!isRunning || activeMode === 'screen' || !activeMode) {
            setModeUI('screen');
        } else {
            // Running other mode: still allow UI switch for settings, but warn
            setModeUI('screen');
        }
    });
    $('#tab-audio').on('click', function() {
        setModeUI('audio');
    });
});

$(window).on('beforeunload', function() {
    if (ws) {
        ws.close();
    }
});
