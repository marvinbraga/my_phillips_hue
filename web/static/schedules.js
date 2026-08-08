const DAY_LABELS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];
let schedulesCache = [];
let configsCache = [];
let groupsCache = [];
let scheduleModal = null;

function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function showToast(message, variant) {
    const el = $('#app-toast');
    el.removeClass('text-bg-success text-bg-danger text-bg-warning')
        .addClass(`text-bg-${variant || 'success'}`);
    $('#app-toast-body').text(message);
    bootstrap.Toast.getOrCreateInstance(el[0], { delay: 4000 }).show();
}

function apiErrorMessage(jqXHR, fallback) {
    try {
        const body = jqXHR.responseJSON;
        if (body && typeof body.detail === 'string') return body.detail;
    } catch (e) { /* ignore */ }
    return fallback || 'Erro';
}

function formatDays(csv) {
    if (!csv) return 'Todos';
    return csv.split(',').filter(Boolean).map(function (d) {
        return DAY_LABELS[parseInt(d, 10)] || d;
    }).join(', ');
}

function loadMeta() {
    return $.when(
        $.getJSON('/configurations').then(function (d) { configsCache = d || []; }),
        $.getJSON('/api/groups').then(function (d) { groupsCache = d || []; })
    );
}

function fillMetaSelects() {
    const cfg = $('#payload-config');
    cfg.empty();
    configsCache.forEach(function (c) {
        cfg.append($('<option>', { value: c.name, text: c.name }));
    });
    const grp = $('#payload-group');
    grp.empty().append($('<option>', { value: '', text: '— nenhum —' }));
    groupsCache.forEach(function (g) {
        grp.append($('<option>', { value: g.id, text: g.name }));
    });
}

function loadSchedules() {
    $('#schedules-loading').show();
    $('#schedules-empty').hide();
    $('#schedules-table').hide();
    $.getJSON('/api/schedules', function (data) {
        schedulesCache = Array.isArray(data) ? data : [];
        renderSchedules();
    }).fail(function (jqXHR) {
        schedulesCache = [];
        renderSchedules();
        showToast(apiErrorMessage(jqXHR, 'Erro ao carregar'), 'danger');
    }).always(function () {
        $('#schedules-loading').hide();
    });
}

function renderSchedules() {
    const tbody = $('#schedules-tbody');
    tbody.empty();
    if (!schedulesCache.length) {
        $('#schedules-table').hide();
        $('#schedules-empty').show();
        return;
    }
    $('#schedules-empty').hide();
    $('#schedules-table').show();
    schedulesCache.forEach(function (s) {
        const enabled = s.enabled
            ? '<span class="badge bg-success">Sim</span>'
            : '<span class="badge bg-secondary">Não</span>';
        const payloadHint = s.action_payload
            ? (s.action_payload.config_name || s.action_payload.group_id || '')
            : '';
        const row = $(`
            <tr>
                <td><strong>${escapeHtml(s.name)}</strong></td>
                <td><code>${escapeHtml(s.time_hhmm)}</code></td>
                <td><small>${escapeHtml(formatDays(s.days_of_week))}</small></td>
                <td><small>${escapeHtml(s.action_type)}${payloadHint ? ' · ' + escapeHtml(payloadHint) : ''}</small></td>
                <td>${enabled}</td>
                <td class="text-end text-nowrap">
                    <button type="button" class="btn btn-sm btn-outline-success me-1 btn-run" data-id="${escapeHtml(s.id)}" title="Executar agora">
                        <i class="bi bi-play-fill"></i>
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-primary me-1 btn-edit" data-id="${escapeHtml(s.id)}">
                        <i class="bi bi-pencil"></i>
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-danger btn-delete" data-id="${escapeHtml(s.id)}" data-name="${escapeHtml(s.name)}">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            </tr>
        `);
        tbody.append(row);
    });
    tbody.find('.btn-run').on('click', function () { runNow($(this).data('id')); });
    tbody.find('.btn-edit').on('click', function () { openEdit($(this).data('id')); });
    tbody.find('.btn-delete').on('click', function () { deleteSchedule($(this).data('id'), $(this).data('name')); });
}

function selectedWeekdays() {
    const days = [];
    $('.wd:checked').each(function () { days.push($(this).val()); });
    return days.join(',');
}

function setWeekdays(csv) {
    $('.wd').prop('checked', false);
    if (!csv) return;
    String(csv).split(',').forEach(function (d) {
        $(`.wd[value="${d.trim()}"]`).prop('checked', true);
    });
}

function togglePayloadFields() {
    const action = $('#schedule-action').val();
    const needConfig = action === 'apply_config' || action === 'apply_group';
    const needGroup = action === 'apply_group' || action === 'power_on' || action === 'power_off';
    $('#payload-config-wrap').toggle(needConfig);
    $('#payload-group-wrap').toggle(needGroup || action === 'apply_group');
}

function openCreate() {
    $('#schedule-id').val('');
    $('#schedule-name').val('');
    $('#schedule-time').val('08:00');
    setWeekdays('');
    $('#schedule-action').val('apply_config');
    $('#schedule-enabled').prop('checked', true);
    fillMetaSelects();
    togglePayloadFields();
    $('#schedule-modal-title').text('Novo agendamento');
    scheduleModal.show();
}

function openEdit(id) {
    const s = schedulesCache.find(function (x) { return x.id === id; });
    if (!s) return;
    fillMetaSelects();
    $('#schedule-id').val(s.id);
    $('#schedule-name').val(s.name);
    $('#schedule-time').val(s.time_hhmm);
    setWeekdays(s.days_of_week);
    $('#schedule-action').val(s.action_type);
    $('#schedule-enabled').prop('checked', !!s.enabled);
    const p = s.action_payload || {};
    if (p.config_name) $('#payload-config').val(p.config_name);
    if (p.group_id) $('#payload-group').val(p.group_id);
    togglePayloadFields();
    $('#schedule-modal-title').text('Editar agendamento');
    scheduleModal.show();
}

function buildPayload() {
    const action = $('#schedule-action').val();
    const payload = {};
    if (action === 'apply_config' || action === 'apply_group') {
        payload.config_name = $('#payload-config').val() || '';
    }
    if (action === 'apply_group' || action === 'power_on' || action === 'power_off') {
        const gid = $('#payload-group').val();
        if (gid) payload.group_id = gid;
    }
    return payload;
}

function saveSchedule() {
    const id = $('#schedule-id').val();
    const name = $('#schedule-name').val().trim();
    const time = $('#schedule-time').val();
    if (!name || !time) {
        alert('Nome e horário são obrigatórios.');
        return;
    }
    // input type=time may return HH:MM:SS
    const timeHhmm = time.slice(0, 5);
    const body = {
        name: name,
        time_hhmm: timeHhmm,
        action_type: $('#schedule-action').val(),
        enabled: $('#schedule-enabled').is(':checked'),
        days_of_week: selectedWeekdays(),
        action_payload: buildPayload(),
    };
    const isEdit = !!id;
    $.ajax({
        type: isEdit ? 'PATCH' : 'POST',
        url: isEdit ? `/api/schedules/${encodeURIComponent(id)}` : '/api/schedules',
        contentType: 'application/json',
        data: JSON.stringify(body),
        success: function () {
            scheduleModal.hide();
            showToast(isEdit ? 'Agendamento atualizado.' : 'Agendamento criado.', 'success');
            loadSchedules();
        },
        error: function (jqXHR) {
            alert(apiErrorMessage(jqXHR, 'Erro ao salvar'));
        },
    });
}

function deleteSchedule(id, name) {
    if (!confirm(`Excluir agendamento "${name}"?`)) return;
    $.ajax({
        type: 'DELETE',
        url: `/api/schedules/${encodeURIComponent(id)}`,
        success: function () {
            showToast('Excluído.', 'success');
            loadSchedules();
        },
        error: function (jqXHR) {
            showToast(apiErrorMessage(jqXHR, 'Erro ao excluir'), 'danger');
        },
    });
}

function runNow(id) {
    $.ajax({
        type: 'POST',
        url: `/api/schedules/${encodeURIComponent(id)}/run`,
        success: function () {
            showToast('Executado.', 'success');
            loadSchedules();
        },
        error: function (jqXHR) {
            showToast(apiErrorMessage(jqXHR, 'Erro ao executar'), 'danger');
        },
    });
}

$(document).ready(function () {
    const saved = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-bs-theme', saved);
    scheduleModal = new bootstrap.Modal(document.getElementById('scheduleModal'));
    $('#theme-btn').on('click', function () {
        const cur = document.documentElement.getAttribute('data-bs-theme');
        const next = cur === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-bs-theme', next);
        localStorage.setItem('theme', next);
    });
    $('#new-btn').on('click', openCreate);
    $('#refresh-btn').on('click', loadSchedules);
    $('#schedule-save-btn').on('click', saveSchedule);
    $('#schedule-action').on('change', togglePayloadFields);
    loadMeta().always(function () {
        fillMetaSelects();
        loadSchedules();
    });
});
