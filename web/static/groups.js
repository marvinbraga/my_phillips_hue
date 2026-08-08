let groupsCache = [];
let lightsCache = [];
let configsCache = [];
let groupModal = null;
let applyModal = null;

function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function showToast(message, variant) {
    const toastEl = $('#app-toast');
    toastEl
        .removeClass('text-bg-success text-bg-danger text-bg-warning')
        .addClass(`text-bg-${variant || 'success'}`);
    $('#app-toast-body').text(message);
    bootstrap.Toast.getOrCreateInstance(toastEl[0], { delay: 4000 }).show();
}

function apiErrorMessage(jqXHR, fallback) {
    try {
        const body = jqXHR.responseJSON;
        if (body && typeof body.detail === 'string') return body.detail;
    } catch (e) { /* ignore */ }
    return fallback || 'Erro na operação.';
}

function loadLightsForForm() {
    return $.getJSON('/api/lights').then(function (data) {
        lightsCache = Array.isArray(data) ? data : [];
        return lightsCache;
    });
}

function loadConfigs() {
    return $.getJSON('/configurations').then(function (data) {
        configsCache = Array.isArray(data) ? data : [];
        return configsCache;
    });
}

function loadGroups() {
    $('#groups-loading').show();
    $('#groups-empty').hide();
    $('#groups-table').hide();
    $.getJSON('/api/groups', function (data) {
        groupsCache = Array.isArray(data) ? data : [];
        renderGroups();
    }).fail(function (jqXHR) {
        groupsCache = [];
        renderGroups();
        showToast(apiErrorMessage(jqXHR, 'Erro ao carregar grupos'), 'danger');
    }).always(function () {
        $('#groups-loading').hide();
    });
}

function lightNameById(id) {
    const light = lightsCache.find(function (l) { return l.id === id; });
    return light ? light.name : id;
}

function renderGroups() {
    const tbody = $('#groups-tbody');
    tbody.empty();
    if (!groupsCache.length) {
        $('#groups-table').hide();
        $('#groups-empty').show();
        return;
    }
    $('#groups-empty').hide();
    $('#groups-table').show();

    groupsCache.forEach(function (g) {
        const memberLabels = (g.light_ids || []).map(lightNameById).join(', ') || '—';
        const roomBadge = g.room
            ? `<span class="badge bg-secondary">${escapeHtml(g.room)}</span>`
            : '<span class="text-muted">—</span>';
        const row = $(`
            <tr data-id="${escapeHtml(g.id)}">
                <td><strong>${escapeHtml(g.name)}</strong></td>
                <td>${roomBadge}</td>
                <td><small>${escapeHtml(memberLabels)}</small></td>
                <td class="text-end text-nowrap">
                    <button type="button" class="btn btn-sm btn-outline-success me-1 btn-on" data-id="${escapeHtml(g.id)}" title="Ligar">
                        <i class="bi bi-lightbulb"></i>
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-secondary me-1 btn-off" data-id="${escapeHtml(g.id)}" title="Desligar">
                        <i class="bi bi-lightbulb-off"></i>
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-primary me-1 btn-apply" data-id="${escapeHtml(g.id)}" title="Aplicar config">
                        <i class="bi bi-palette"></i>
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-primary me-1 btn-edit" data-id="${escapeHtml(g.id)}" title="Editar">
                        <i class="bi bi-pencil"></i>
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-danger btn-delete" data-id="${escapeHtml(g.id)}" data-name="${escapeHtml(g.name)}" title="Excluir">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            </tr>
        `);
        tbody.append(row);
    });

    tbody.find('.btn-on').on('click', function () { setPower($(this).data('id'), true); });
    tbody.find('.btn-off').on('click', function () { setPower($(this).data('id'), false); });
    tbody.find('.btn-apply').on('click', function () { openApplyModal($(this).data('id')); });
    tbody.find('.btn-edit').on('click', function () { openEditModal($(this).data('id')); });
    tbody.find('.btn-delete').on('click', function () { deleteGroup($(this).data('id'), $(this).data('name')); });
}

function renderMemberChecks(selectedIds) {
    const box = $('#group-members');
    box.empty();
    const selected = new Set(selectedIds || []);
    if (!lightsCache.length) {
        box.html('<div class="text-muted small">Nenhuma lâmpada no catálogo. Cadastre em /lights.</div>');
        return;
    }
    lightsCache.forEach(function (light) {
        const id = `member-${light.id}`;
        const checked = selected.has(light.id) ? 'checked' : '';
        box.append(`
            <div class="form-check">
                <input class="form-check-input member-cb" type="checkbox" value="${escapeHtml(light.id)}" id="${escapeHtml(id)}" ${checked}>
                <label class="form-check-label" for="${escapeHtml(id)}">${escapeHtml(light.name)}</label>
            </div>
        `);
    });
}

function selectedMemberIds() {
    const ids = [];
    $('.member-cb:checked').each(function () { ids.push($(this).val()); });
    return ids;
}

function openCreateModal() {
    $('#group-id').val('');
    $('#group-name').val('');
    $('#group-room').val('');
    $('#group-notes').val('');
    $('#group-modal-title').text('Novo grupo');
    renderMemberChecks([]);
    groupModal.show();
}

function openEditModal(id) {
    const g = groupsCache.find(function (x) { return x.id === id; });
    if (!g) {
        showToast('Grupo não encontrado', 'warning');
        return;
    }
    $('#group-id').val(g.id);
    $('#group-name').val(g.name || '');
    $('#group-room').val(g.room || '');
    $('#group-notes').val(g.notes || '');
    $('#group-modal-title').text('Editar grupo');
    renderMemberChecks(g.light_ids || []);
    groupModal.show();
}

function saveGroup() {
    const id = $('#group-id').val();
    const name = $('#group-name').val().trim();
    if (!name) {
        alert('Informe o nome do grupo.');
        return;
    }
    const payload = {
        name: name,
        room: ($('#group-room').val() || '').trim() || null,
        notes: ($('#group-notes').val() || '').trim() || null,
        light_ids: selectedMemberIds(),
    };
    const isEdit = !!id;
    const $btn = $('#group-save-btn').prop('disabled', true);
    $.ajax({
        type: isEdit ? 'PATCH' : 'POST',
        url: isEdit ? `/api/groups/${encodeURIComponent(id)}` : '/api/groups',
        contentType: 'application/json',
        data: JSON.stringify(payload),
        success: function () {
            groupModal.hide();
            showToast(isEdit ? 'Grupo atualizado.' : 'Grupo criado.', 'success');
            loadGroups();
        },
        error: function (jqXHR) {
            alert(apiErrorMessage(jqXHR, 'Erro ao salvar grupo.'));
        },
        complete: function () { $btn.prop('disabled', false); },
    });
}

function deleteGroup(id, name) {
    if (!confirm(`Excluir o grupo "${name}"?`)) return;
    $.ajax({
        type: 'DELETE',
        url: `/api/groups/${encodeURIComponent(id)}`,
        success: function () {
            showToast('Grupo excluído.', 'success');
            loadGroups();
        },
        error: function (jqXHR) {
            showToast(apiErrorMessage(jqXHR, 'Erro ao excluir'), 'danger');
        },
    });
}

function setPower(id, on) {
    $.ajax({
        type: 'POST',
        url: `/api/groups/${encodeURIComponent(id)}/power`,
        contentType: 'application/json',
        data: JSON.stringify({ on: on }),
        success: function () {
            showToast(on ? 'Grupo ligado.' : 'Grupo desligado.', 'success');
        },
        error: function (jqXHR) {
            showToast(apiErrorMessage(jqXHR, 'Erro ao alterar energia'), 'danger');
        },
    });
}

function openApplyModal(id) {
    $('#apply-group-id').val(id);
    const sel = $('#apply-config');
    sel.empty();
    configsCache.forEach(function (c) {
        sel.append($('<option>', { value: c.name, text: `${c.name} — ${(c.description || '').slice(0, 60)}` }));
    });
    applyModal.show();
}

function confirmApply() {
    const id = $('#apply-group-id').val();
    const configName = $('#apply-config').val();
    if (!configName) {
        alert('Selecione uma configuração.');
        return;
    }
    $.ajax({
        type: 'POST',
        url: `/api/groups/${encodeURIComponent(id)}/apply`,
        contentType: 'application/json',
        data: JSON.stringify({ config_name: configName, transition_time_secs: 0 }),
        success: function () {
            applyModal.hide();
            showToast('Configuração aplicada ao grupo.', 'success');
        },
        error: function (jqXHR) {
            showToast(apiErrorMessage(jqXHR, 'Erro ao aplicar'), 'danger');
        },
    });
}

function initTheme() {
    const saved = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-bs-theme', saved);
    const icon = $('#theme-icon');
    if (saved === 'dark') icon.removeClass('bi-moon-fill').addClass('bi-sun-fill');
}

$(document).ready(function () {
    initTheme();
    groupModal = new bootstrap.Modal(document.getElementById('groupModal'));
    applyModal = new bootstrap.Modal(document.getElementById('applyModal'));
    $('#theme-btn').on('click', function () {
        const cur = document.documentElement.getAttribute('data-bs-theme');
        const next = cur === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-bs-theme', next);
        localStorage.setItem('theme', next);
        initTheme();
    });
    $('#new-btn').on('click', openCreateModal);
    $('#refresh-btn').on('click', loadGroups);
    $('#group-save-btn').on('click', saveGroup);
    $('#apply-confirm-btn').on('click', confirmApply);
    $.when(loadLightsForForm(), loadConfigs()).always(function () {
        loadGroups();
    });
});
