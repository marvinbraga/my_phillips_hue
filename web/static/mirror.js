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
        // Default Party when user didn't pick a profile — bare defaults
        // (fps=10, no beat boost) look "broken" next to system audio.
        return $('input[name="audio-profile"]:checked').val() || 'party';
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
    // Sync select from server only when not mid-edit (status WS must not
    // overwrite a just-chosen option before hot-swap lands).
    if (Object.prototype.hasOwnProperty.call(status, 'config_name')) {
        const sel = $('#audio-config-select');
        const el = sel.length ? sel.get(0) : null;
        if (el && document.activeElement !== el && !sel.data('applying')) {
            const serverVal = status.config_name || '';
            if (sel.val() !== serverVal) {
                sel.val(serverVal);
            }
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
        // Bare defaults (fps≈10, no beat profile) look "broken" — prefer Party.
        if (!$('input[name="audio-profile"]:checked').length) {
            $('input[name="audio-profile"][value="party"]').prop('checked', true);
            applyAudioProfileToSliders('party');
        }
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

// Client-side spectrum: multi-bar canvas (server-fed bins) + summary meters
const spectrumHold = { bass: 0, mid: 0, treble: 0 };
const spectrumSmooth = { bass: 0, mid: 0, treble: 0 };
let spectrumBinsSmooth = [];
let spectrumBinsHold = [];
let spectrumRaf = 0;

function spectrumBarColor(t, isLight) {
    // Prism: blue → cyan → green → yellow → red (audioMotion-like)
    const stops = isLight
        ? [
            [40, 90, 200],
            [0, 180, 200],
            [30, 180, 80],
            [230, 180, 20],
            [220, 60, 40],
          ]
        : [
            [50, 120, 255],
            [0, 220, 220],
            [40, 230, 90],
            [255, 210, 40],
            [255, 70, 50],
          ];
    const x = Math.max(0, Math.min(0.999, t));
    const seg = (stops.length - 1) * x;
    const i = Math.floor(seg);
    const f = seg - i;
    const a = stops[i];
    const b = stops[Math.min(stops.length - 1, i + 1)];
    const r = Math.round(a[0] + (b[0] - a[0]) * f);
    const g = Math.round(a[1] + (b[1] - a[1]) * f);
    const bl = Math.round(a[2] + (b[2] - a[2]) * f);
    return `rgb(${r},${g},${bl})`;
}

function ensureSpectrumCanvasSize() {
    const canvas = document.getElementById('spectrum-canvas');
    if (!canvas) return null;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(64, Math.floor(rect.width * dpr));
    const h = Math.max(64, Math.floor(rect.height * dpr));
    if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
    }
    return canvas;
}

function drawSpectrumCanvas(bins, beat) {
    const canvas = ensureSpectrumCanvasSize();
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    const isLight =
        document.body.classList.contains('light-theme') ||
        document.documentElement.getAttribute('data-bs-theme') === 'light';

    ctx.clearRect(0, 0, w, h);
    // subtle grid / base
    ctx.fillStyle = isLight ? 'rgba(0,0,0,0.03)' : 'rgba(255,255,255,0.03)';
    ctx.fillRect(0, 0, w, h);

    const n = bins.length || 48;
    const gap = Math.max(1, Math.floor(w / n * 0.12));
    const barW = Math.max(1, (w - gap * (n + 1)) / n);
    const floor = Math.max(1, Math.floor(h * 0.02));

    for (let i = 0; i < n; i++) {
        const v = Math.max(0, Math.min(1, bins[i] || 0));
        const hold = Math.max(v, spectrumBinsHold[i] || 0);
        const bh = Math.max(floor, Math.floor(v * (h - 4)));
        const x = gap + i * (barW + gap);
        const y = h - bh;
        const t = n <= 1 ? 0 : i / (n - 1);
        ctx.fillStyle = spectrumBarColor(t, isLight);
        // rounded-ish bar via rect
        ctx.globalAlpha = 0.92;
        ctx.fillRect(x, y, barW, bh);
        // peak cap
        const capY = h - Math.max(floor, Math.floor(hold * (h - 4))) - 2;
        ctx.globalAlpha = 0.95;
        ctx.fillStyle = isLight ? 'rgba(20,20,30,0.75)' : 'rgba(255,255,255,0.92)';
        ctx.fillRect(x, Math.max(0, capY), barW, Math.max(2, Math.floor(2 * (window.devicePixelRatio || 1))));
    }
    ctx.globalAlpha = 1;

    // beat flash overlay
    if (beat > 0.2) {
        ctx.fillStyle = `rgba(255, 210, 80, ${0.04 + beat * 0.10})`;
        ctx.fillRect(0, 0, w, h);
    }
}

function updateSpectrum(status) {
    const target = {
        bass: Math.max(0, Math.min(1, Number(status.bass) || 0)),
        mid: Math.max(0, Math.min(1, Number(status.mid) || 0)),
        treble: Math.max(0, Math.min(1, Number(status.treble) || 0)),
    };
    const beat = Math.max(0, Math.min(1, Number(status.beat) || 0));

    // Multi-bar bins from server (fallback: synthesize from bass/mid/treble)
    let rawBins = Array.isArray(status.spectrum) ? status.spectrum.map((v) => Number(v) || 0) : [];
    if (!rawBins.length) {
        const n = 48;
        rawBins = new Array(n);
        for (let i = 0; i < n; i++) {
            const t = i / (n - 1);
            if (t < 0.28) rawBins[i] = target.bass * (0.6 + 0.4 * (1 - t / 0.28));
            else if (t < 0.65) rawBins[i] = target.mid * (0.55 + 0.45 * Math.sin((t - 0.28) / 0.37 * Math.PI));
            else rawBins[i] = target.treble * (0.5 + 0.5 * ((t - 0.65) / 0.35));
        }
    }

    if (spectrumBinsSmooth.length !== rawBins.length) {
        spectrumBinsSmooth = rawBins.slice();
        spectrumBinsHold = rawBins.slice();
    } else {
        for (let i = 0; i < rawBins.length; i++) {
            const t = Math.max(0, Math.min(1, rawBins[i]));
            const prev = spectrumBinsSmooth[i];
            // Fast attack / medium release
            const alpha = t > prev ? 0.58 : 0.20;
            spectrumBinsSmooth[i] = prev + (t - prev) * alpha;
            if (spectrumBinsSmooth[i] >= spectrumBinsHold[i]) {
                spectrumBinsHold[i] = spectrumBinsSmooth[i];
            } else {
                spectrumBinsHold[i] *= 0.92;
            }
        }
    }

    if (!spectrumRaf) {
        spectrumRaf = requestAnimationFrame(() => {
            spectrumRaf = 0;
            drawSpectrumCanvas(spectrumBinsSmooth, beat);
        });
    } else {
        drawSpectrumCanvas(spectrumBinsSmooth, beat);
    }

    // Summary meters (bass/mid/treble)
    ['bass', 'mid', 'treble'].forEach((k) => {
        const prev = spectrumSmooth[k];
        const t = target[k];
        const alpha = t > prev ? 0.55 : 0.22;
        spectrumSmooth[k] = prev + (t - prev) * alpha;
        if (spectrumSmooth[k] >= spectrumHold[k]) {
            spectrumHold[k] = spectrumSmooth[k];
        } else {
            spectrumHold[k] *= 0.93;
        }
        const body = Math.max(0, spectrumSmooth[k]);
        $(`#bar-${k}`).css('width', `${(body * 100).toFixed(1)}%`);
        $(`#pct-${k}`).text(`${Math.round(body * 100)}%`);
    });

    const glow = Math.round(beat * 32);
    const opacity = (0.12 + beat * 0.6).toFixed(2);
    const panel = $('#spectrum-panel');
    panel.css(
        'box-shadow',
        glow > 2
            ? `0 0 ${glow}px rgba(255, 200, 80, ${opacity}), inset 0 0 ${Math.round(glow / 2)}px rgba(255, 255, 255, ${beat * 0.12})`
            : 'none'
    );
    panel.toggleClass('beat-hit', beat > 0.35);
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
        updateSpectrum({ bass: 0, mid: 0, treble: 0, beat: 0, spectrum: [] });
    }
}

// Resize-aware spectrum canvas
$(window).on('resize', () => {
    if (spectrumBinsSmooth.length) {
        drawSpectrumCanvas(spectrumBinsSmooth, 0);
    } else {
        ensureSpectrumCanvasSize();
    }
});

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

function getSelectedAudioConfigName() {
    const val = ($('#audio-config-select').val() || '').trim();
    return val || null;
}

/**
 * Hot-swap the LightConfig palette while music is running (or arm it idle).
 * Uses REST /mirror/settings so config_name is never dropped on the WS path.
 */
function applyAudioConfigSelection() {
    const select = $('#audio-config-select');
    const config_name = getSelectedAudioConfigName() || '';
    select.data('applying', true);
    return fetch('/mirror/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            mode: 'audio',
            config_name: config_name,
        }),
    })
        .then(async (response) => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                const detail = data.detail || response.statusText;
                alert(typeof detail === 'string' ? detail : JSON.stringify(detail));
                return;
            }
            if (data.status) {
                updateUI(data.status);
            }
        })
        .catch((err) => alert('Erro ao trocar configuração: ' + err))
        .finally(() => {
            select.data('applying', false);
        });
}

function loadAudioConfigurations() {
    const select = $('#audio-config-select');
    if (!select.length) {
        return;
    }
    fetch('/configurations')
        .then(r => r.json())
        .then(data => {
            const previous = select.val() || '';
            select.find('option:not(:first)').remove();
            const list = Array.isArray(data) ? data : [];
            list.forEach(item => {
                const name = item && item.name ? String(item.name) : '';
                if (!name) {
                    return;
                }
                const opt = $('<option></option>').attr('value', name).text(name);
                select.append(opt);
            });
            if (previous) {
                select.val(previous);
            }
        })
        .catch(err => console.warn('audio configurations:', err));
}

function startMirror() {
    const fps = parseInt($('#fps-range').val(), 10);
    const brightness = parseInt($('#brightness-range').val(), 10);
    const profile = getSelectedProfile();
    const mode = currentMode;
    const transport_preference = $('#transport-pref').val() || 'auto';
    const area_id = $('#ent-area-select').val() || null;
    const config_name = mode === 'audio' ? getSelectedAudioConfigName() : null;
    const payload = { action: 'start', mode, fps, brightness, transport_preference };
    if (profile) {
        payload.profile = profile;
    }
    if (area_id) {
        payload.area_id = area_id;
    }
    if (config_name) {
        payload.config_name = config_name;
    }

    if (ws && ws.readyState === WebSocket.OPEN) {
        // WS path may not support entertainment fields fully — prefer REST start
        const body = {
            mode,
            fps,
            brightness,
            profile: profile || undefined,
            transport_preference,
            area_id: area_id || undefined,
        };
        if (config_name) {
            body.config_name = config_name;
        }
        fetch('/mirror/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
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
        if (config_name) {
            body.config_name = config_name;
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
        // Always send config_name for audio so empty clears / selection hot-swaps
        settings.config_name = getSelectedAudioConfigName() || '';
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
        if (mode === 'audio') {
            body.config_name = settings.config_name;
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
    loadAudioConfigurations();

    connectWebSocket();

    $('#start-btn').click(startMirror);
    $('#stop-btn').click(stopMirror);
    $('#apply-settings-btn').click(function() { applySettings(); });
    $('#theme-btn').click(toggleTheme);
    $('#ent-pair-btn').click(pairEntertainment);
    $('input[name="mirror-profile"]').on('change', onProfileSelected);
    $('input[name="audio-profile"]').on('change', onProfileSelected);
    $('#audio-config-select').on('change', function() {
        // Always apply palette via HTTP so it works even when WS settings
        // path is lagging; clear smooth blend on the server immediately.
        if (currentMode === 'audio') {
            applyAudioConfigSelection();
        }
    });

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
