// Estado
let lightsCache = [];
let editingOriginal = null;
let lightModal = null;

function escapeHtml(value) {
    if (value === null || value === undefined) {
        return '';
    }
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function showToast(message, variant) {
    const toastEl = $('#app-toast');
    const body = $('#app-toast-body');
    const icon = variant === 'danger'
        ? 'bi-exclamation-triangle'
        : variant === 'warning'
            ? 'bi-exclamation-circle'
            : 'bi-check-circle';
    toastEl
        .removeClass('text-bg-success text-bg-danger text-bg-warning text-bg-primary')
        .addClass(`text-bg-${variant || 'success'}`);
    body.html(`<i class="bi ${icon}"></i> ${escapeHtml(message)}`);
    const toast = bootstrap.Toast.getOrCreateInstance(toastEl[0], { delay: 4500 });
    toast.show();
}

function apiErrorMessage(jqXHR, fallback) {
    const status = jqXHR && jqXHR.status;
    let detail = null;
    try {
        const body = jqXHR.responseJSON;
        if (body) {
            if (typeof body.detail === 'string') {
                detail = body.detail;
            } else if (Array.isArray(body.detail)) {
                detail = body.detail.map(function (d) {
                    return d.msg || JSON.stringify(d);
                }).join('; ');
            }
        }
    } catch (e) {
        // ignore parse errors
    }

    if (status === 409) {
        return detail || 'Conflito: nome ou identificador já existe.';
    }
    if (status === 404) {
        return detail || 'Lâmpada não encontrada.';
    }
    if (status === 503) {
        return detail || 'Serviço indisponível (bridge ou registro). Tente novamente.';
    }
    if (status === 400) {
        return detail || 'Dados inválidos. Verifique os campos.';
    }
    if (status === 422) {
        return detail || 'Validação falhou. Verifique os campos.';
    }
    return detail || fallback || 'Erro na operação.';
}

function checkBridgeStatus() {
    $.getJSON('/api/bridge/status', function (data) {
        const statusEl = $('#bridge-status');
        if (data.connected) {
            statusEl.html(
                `<i class="bi bi-circle-fill text-success"></i> Bridge conectada (${escapeHtml(data.bridge_ip)}) - ${data.light_count} lâmpadas`
            );
        } else {
            statusEl.html('<i class="bi bi-circle-fill text-danger"></i> Bridge desconectada');
        }
    }).fail(function () {
        $('#bridge-status').html(
            '<i class="bi bi-circle-fill text-danger"></i> Erro ao verificar conexão'
        );
    });
}

function loadLights() {
    const includeDeleted = $('#include-deleted').is(':checked');
    $('#lights-loading').show();
    $('#lights-empty').hide();
    $('#lights-table').hide();

    $.getJSON(`/api/lights?include_deleted=${includeDeleted ? 'true' : 'false'}`, function (data) {
        lightsCache = Array.isArray(data) ? data : [];
        renderLightsTable();
    }).fail(function (jqXHR) {
        lightsCache = [];
        renderLightsTable();
        showToast(apiErrorMessage(jqXHR, 'Erro ao carregar lâmpadas'), 'danger');
    }).always(function () {
        $('#lights-loading').hide();
    });
}

function renderLightsTable() {
    const tbody = $('#lights-tbody');
    tbody.empty();

    if (!lightsCache.length) {
        $('#lights-table').hide();
        $('#lights-empty').show();
        return;
    }

    $('#lights-empty').hide();
    $('#lights-table').show();

    lightsCache.forEach(function (light) {
        const deleted = !!light.deleted_at;
        const enabledBadge = light.enabled_for_app
            ? '<span class="badge bg-success">Sim</span>'
            : '<span class="badge bg-secondary">Não</span>';
        const statusBadge = deleted
            ? '<span class="badge bg-danger">Excluída</span>'
            : '<span class="badge bg-success">Ativa</span>';
        const eyeLimit = light.eye_safety_limit_pct === null || light.eye_safety_limit_pct === undefined
            ? '—'
            : String(light.eye_safety_limit_pct);

        let actions;
        if (deleted) {
            actions = '<span class="text-muted small">—</span>';
        } else {
            actions = `
                <button type="button" class="btn btn-sm btn-outline-primary me-1 btn-edit"
                        data-id="${escapeHtml(light.id)}" title="Editar">
                    <i class="bi bi-pencil"></i>
                </button>
                <button type="button" class="btn btn-sm btn-outline-danger btn-delete"
                        data-id="${escapeHtml(light.id)}" data-name="${escapeHtml(light.name)}" title="Excluir">
                    <i class="bi bi-trash"></i>
                </button>
            `;
        }

        const row = $(`
            <tr class="${deleted ? 'row-deleted' : ''}" data-id="${escapeHtml(light.id)}">
                <td><strong>${escapeHtml(light.name)}</strong></td>
                <td>${escapeHtml(light.nickname) || '<span class="text-muted">—</span>'}</td>
                <td>${escapeHtml(light.room) || '<span class="text-muted">—</span>'}</td>
                <td><code class="small">${escapeHtml(light.bridge_light_id) || '—'}</code></td>
                <td>${escapeHtml(eyeLimit)}</td>
                <td>${enabledBadge}</td>
                <td>${statusBadge}</td>
                <td class="text-end actions-cell">${actions}</td>
            </tr>
        `);
        tbody.append(row);
    });

    tbody.find('.btn-edit').on('click', function () {
        const id = $(this).data('id');
        openEditModal(id);
    });
    tbody.find('.btn-delete').on('click', function () {
        const id = $(this).data('id');
        const name = $(this).data('name');
        deleteLight(id, name);
    });
}

function emptyToNull(value) {
    if (value === undefined || value === null) {
        return null;
    }
    const trimmed = String(value).trim();
    return trimmed === '' ? null : trimmed;
}

function parseEyeLimit(raw) {
    if (raw === undefined || raw === null || String(raw).trim() === '') {
        return null;
    }
    const n = parseInt(raw, 10);
    if (Number.isNaN(n)) {
        return null;
    }
    return n;
}

function resetForm() {
    $('#light-id').val('');
    $('#light-name').val('');
    $('#light-nickname').val('');
    $('#light-room').val('');
    $('#light-bridge-id').val('');
    $('#light-eye-limit').val('');
    $('#light-notes').val('');
    $('#light-enabled').prop('checked', true);
    editingOriginal = null;
}

function openCreateModal() {
    resetForm();
    $('#light-modal-title').text('Nova lâmpada');
    lightModal.show();
}

function openEditModal(id) {
    const light = lightsCache.find(function (x) {
        return x.id === id;
    });
    if (!light) {
        showToast('Lâmpada não encontrada na lista. Atualize e tente de novo.', 'warning');
        return;
    }
    if (light.deleted_at) {
        showToast('Lâmpadas excluídas não podem ser editadas.', 'warning');
        return;
    }

    editingOriginal = light;
    $('#light-id').val(light.id);
    $('#light-name').val(light.name || '');
    $('#light-nickname').val(light.nickname || '');
    $('#light-room').val(light.room || '');
    $('#light-bridge-id').val(light.bridge_light_id || '');
    $('#light-eye-limit').val(
        light.eye_safety_limit_pct === null || light.eye_safety_limit_pct === undefined
            ? ''
            : light.eye_safety_limit_pct
    );
    $('#light-notes').val(light.notes || '');
    $('#light-enabled').prop('checked', !!light.enabled_for_app);
    $('#light-modal-title').text('Editar lâmpada');
    lightModal.show();
}

function buildCreatePayload() {
    const name = $('#light-name').val().trim();
    if (!name) {
        alert('Informe o nome da lâmpada.');
        return null;
    }
    const eye = parseEyeLimit($('#light-eye-limit').val());
    if (eye !== null && (eye < 0 || eye > 100)) {
        alert('Limite ocular deve estar entre 0 e 100.');
        return null;
    }
    return {
        name: name,
        nickname: emptyToNull($('#light-nickname').val()),
        room: emptyToNull($('#light-room').val()),
        notes: emptyToNull($('#light-notes').val()),
        bridge_light_id: emptyToNull($('#light-bridge-id').val()),
        eye_safety_limit_pct: eye,
        enabled_for_app: $('#light-enabled').is(':checked'),
    };
}

function buildUpdatePayload(original) {
    const name = $('#light-name').val().trim();
    if (!name) {
        alert('Informe o nome da lâmpada.');
        return null;
    }
    const eye = parseEyeLimit($('#light-eye-limit').val());
    if (eye !== null && (eye < 0 || eye > 100)) {
        alert('Limite ocular deve estar entre 0 e 100.');
        return null;
    }

    const next = {
        name: name,
        nickname: emptyToNull($('#light-nickname').val()),
        room: emptyToNull($('#light-room').val()),
        notes: emptyToNull($('#light-notes').val()),
        bridge_light_id: emptyToNull($('#light-bridge-id').val()),
        eye_safety_limit_pct: eye,
        enabled_for_app: $('#light-enabled').is(':checked'),
    };

    // Only send changed fields (null clears optional strings)
    const patch = {};
    Object.keys(next).forEach(function (key) {
        const a = original[key] === undefined ? null : original[key];
        const b = next[key];
        if (a !== b) {
            patch[key] = b;
        }
    });
    return patch;
}

function saveLight() {
    const id = $('#light-id').val();
    const isEdit = !!id;
    let payload;
    let url;
    let method;

    if (isEdit) {
        payload = buildUpdatePayload(editingOriginal || {});
        if (payload === null) {
            return;
        }
        if (Object.keys(payload).length === 0) {
            lightModal.hide();
            showToast('Nenhuma alteração para salvar.', 'warning');
            return;
        }
        url = `/api/lights/${encodeURIComponent(id)}`;
        method = 'PATCH';
    } else {
        payload = buildCreatePayload();
        if (payload === null) {
            return;
        }
        url = '/api/lights';
        method = 'POST';
    }

    const $btn = $('#light-save-btn').prop('disabled', true);
    $.ajax({
        type: method,
        url: url,
        contentType: 'application/json',
        data: JSON.stringify(payload),
        success: function () {
            lightModal.hide();
            showToast(isEdit ? 'Lâmpada atualizada.' : 'Lâmpada criada.', 'success');
            loadLights();
        },
        error: function (jqXHR) {
            alert(apiErrorMessage(jqXHR, isEdit ? 'Erro ao atualizar lâmpada.' : 'Erro ao criar lâmpada.'));
        },
        complete: function () {
            $btn.prop('disabled', false);
        },
    });
}

function deleteLight(id, name) {
    const label = name || id;
    if (!confirm(`Excluir a lâmpada "${label}"?\n\nA exclusão é lógica (soft-delete).`)) {
        return;
    }
    $.ajax({
        type: 'DELETE',
        url: `/api/lights/${encodeURIComponent(id)}`,
        success: function () {
            showToast('Lâmpada excluída.', 'success');
            loadLights();
        },
        error: function (jqXHR) {
            alert(apiErrorMessage(jqXHR, 'Erro ao excluir lâmpada.'));
        },
    });
}

function syncFromBridge() {
    const $btn = $('#sync-btn').prop('disabled', true);
    $.ajax({
        type: 'POST',
        url: '/api/lights/sync?reactivate_deleted=false',
        success: function (data) {
            const msg =
                `Sync: ${data.created} criadas, ${data.updated} atualizadas, ` +
                `${data.unchanged} inalteradas, ${data.skipped_deleted} excluídas ignoradas ` +
                `(bridge: ${data.total_bridge}).`;
            showToast(msg, 'success');
            loadLights();
            checkBridgeStatus();
        },
        error: function (jqXHR) {
            alert(apiErrorMessage(jqXHR, 'Erro ao sincronizar com a bridge.'));
        },
        complete: function () {
            $btn.prop('disabled', false);
        },
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
    lightModal = new bootstrap.Modal(document.getElementById('lightModal'));
    initTheme();
    checkBridgeStatus();
    loadLights();

    $('#theme-btn').on('click', toggleTheme);
    $('#refresh-btn').on('click', loadLights);
    $('#include-deleted').on('change', loadLights);
    $('#sync-btn, #empty-sync-btn').on('click', syncFromBridge);
    $('#new-btn, #empty-new-btn').on('click', openCreateModal);
    $('#light-save-btn').on('click', saveLight);

    $('#light-form').on('submit', function (e) {
        e.preventDefault();
        saveLight();
    });
});
