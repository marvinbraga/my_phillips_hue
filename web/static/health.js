/**
 * Health dashboard — polls GET /api/health every 5s and updates cards.
 */
(function () {
    'use strict';

    const POLL_MS = 5000;
    let timer = null;
    let inFlight = false;

    function el(id) {
        return document.getElementById(id);
    }

    function setText(id, value) {
        const node = el(id);
        if (node) {
            node.textContent = value == null || value === '' ? '—' : String(value);
        }
    }

    function setPill(id, ok, okLabel, badLabel) {
        const node = el(id);
        if (!node) {
            return;
        }
        node.textContent = ok ? okLabel : badLabel;
        node.className = 'badge status-pill ' + (ok ? 'text-bg-success' : 'text-bg-danger');
    }

    function formatTs(iso) {
        if (!iso) {
            return '—';
        }
        try {
            const d = new Date(iso);
            if (Number.isNaN(d.getTime())) {
                return iso;
            }
            return d.toLocaleString('pt-BR');
        } catch (_e) {
            return iso;
        }
    }

    function render(data) {
        const grid = el('health-grid');
        if (grid) {
            grid.classList.remove('skeleton');
        }
        const err = el('health-error');
        if (err) {
            err.classList.add('d-none');
            err.textContent = '';
        }

        const bridge = data.bridge || {};
        setPill('bridge-pill', !!bridge.connected, 'Conectada', 'Offline');
        setText('bridge-ip', bridge.bridge_ip);
        setText('bridge-light-count', bridge.light_count);

        const lights = data.lights || {};
        const unreachable = lights.unreachable || 0;
        setPill('lights-pill', unreachable === 0, 'OK', unreachable + ' offline');
        setText('lights-total', lights.total);
        setText('lights-unreachable', unreachable);
        setText('lights-disabled', lights.disabled_in_app);

        const mirror = data.mirror || {};
        setPill('mirror-pill', !!mirror.running, 'Ativo', 'Parado');
        setText('mirror-fps', mirror.fps);
        setText('mirror-profile', mirror.profile == null ? 'nenhum' : mirror.profile);

        const chat = data.chat || {};
        setPill('chat-pill', !!chat.available, 'Disponível', 'Indisponível');
        setText('chat-reason', chat.available ? '—' : (chat.reason || 'sem diagnóstico'));

        const registry = data.registry || {};
        setPill('registry-pill', true, 'OK', 'OK');
        setText('registry-count', registry.count);
        setText('registry-db', registry.db_path);
        setText('registry-sync', formatTs(registry.last_sync_at));

        const schedules = data.schedules || {};
        setPill(
            'schedules-pill',
            !!schedules.runner_alive,
            'Runner ativo',
            'Runner parado'
        );
        setText('schedules-enabled', schedules.enabled_count);
        setText(
            'schedules-runner',
            schedules.runner_alive ? 'vivo' : 'não iniciado (fase E)'
        );

        setText('health-updated', 'Atualizado: ' + formatTs(data.timestamp));
    }

    function showError(message) {
        const err = el('health-error');
        if (err) {
            err.textContent = message;
            err.classList.remove('d-none');
        }
        setText('health-updated', 'Falha ao atualizar');
    }

    function fetchHealth() {
        if (inFlight) {
            return;
        }
        inFlight = true;
        fetch('/api/health', { headers: { Accept: 'application/json' } })
            .then(function (res) {
                if (!res.ok) {
                    throw new Error('HTTP ' + res.status);
                }
                return res.json();
            })
            .then(render)
            .catch(function (e) {
                showError('Não foi possível carregar /api/health: ' + e.message);
            })
            .finally(function () {
                inFlight = false;
            });
    }

    function start() {
        fetchHealth();
        timer = window.setInterval(fetchHealth, POLL_MS);
        const btn = el('health-refresh');
        if (btn) {
            btn.addEventListener('click', function () {
                fetchHealth();
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }

    window.addEventListener('beforeunload', function () {
        if (timer) {
            window.clearInterval(timer);
        }
    });
})();
