// Estado global
let lightsData = [];
let positionsData = [];

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

// Carregar dados de posicionamento
function loadPositions() {
    $.getJSON('/positions', function(data) {
        lightsData = data.lights;
        positionsData = data.positions;
        renderLightsList();
        updateMonitorVisualization();
        renderSpecialPositions();
    }).fail(function() {
        alert('Erro ao carregar configurações de posicionamento');
    });
}

// Renderizar lista de lâmpadas
function renderLightsList() {
    const container = $('#lights-list');
    container.empty();

    lightsData.forEach((light, index) => {
        const positionInfo = positionsData.find(p => p.id === light.position);
        const positionLabel = positionInfo ? positionInfo.label : 'Não definido';

        const card = $(`
            <div class="card light-card mb-2" data-light-index="${index}">
                <div class="card-body py-2 px-3">
                    <div class="d-flex justify-content-between align-items-center">
                        <div class="d-flex align-items-center">
                            <div class="form-check form-switch me-3">
                                <input class="form-check-input light-enabled" type="checkbox"
                                       id="light-${index}" ${light.enabled ? 'checked' : ''}>
                            </div>
                            <div>
                                <strong>${light.name}</strong>
                                <br>
                                <span class="badge position-badge ${light.position === 'none' ? 'bg-secondary' : 'bg-primary'}">
                                    ${positionLabel}
                                </span>
                            </div>
                        </div>
                        <div>
                            <select class="form-select form-select-sm position-select" data-light-index="${index}">
                                ${positionsData.map(pos => `
                                    <option value="${pos.id}" ${light.position === pos.id ? 'selected' : ''}>
                                        ${pos.label}
                                    </option>
                                `).join('')}
                            </select>
                        </div>
                    </div>
                </div>
            </div>
        `);
        container.append(card);
    });

    // Event handlers
    $('.light-enabled').on('change', function() {
        const index = $(this).closest('.light-card').data('light-index');
        lightsData[index].enabled = $(this).is(':checked');
        updateMonitorVisualization();
    });

    $('.position-select').on('change', function() {
        const index = $(this).data('light-index');
        const newPosition = $(this).val();
        lightsData[index].position = newPosition;
        renderLightsList();
        updateMonitorVisualization();
    });
}

// Atualizar visualização do monitor
function updateMonitorVisualization() {
    // Resetar todos os slots
    $('.position-slot').removeClass('has-light').find('.light-count').remove();

    // Contar lâmpadas por posição
    const positionCounts = {};
    lightsData.forEach(light => {
        if (light.enabled && light.position !== 'none' && light.position !== 'center' && light.position !== 'ambient') {
            positionCounts[light.position] = (positionCounts[light.position] || 0) + 1;
        }
    });

    // Atualizar slots visuais
    Object.keys(positionCounts).forEach(position => {
        const slot = $(`.position-slot[data-position="${position}"]`);
        if (slot.length) {
            slot.addClass('has-light');
            if (positionCounts[position] > 1) {
                slot.append(`<span class="light-count">${positionCounts[position]}</span>`);
            }
        }
    });
}

// Renderizar posições especiais
function renderSpecialPositions() {
    const container = $('#special-positions');
    container.empty();

    const specialPositions = positionsData.filter(p => ['none', 'center', 'ambient'].includes(p.id));

    specialPositions.forEach(pos => {
        const lightsInPosition = lightsData.filter(l => l.position === pos.id && l.enabled);
        const col = $(`
            <div class="col-md-4 mb-3">
                <div class="card h-100 ${lightsInPosition.length > 0 ? 'border-primary' : ''}">
                    <div class="card-body">
                        <h6 class="card-title">
                            <i class="bi bi-${pos.id === 'none' ? 'x-circle' : pos.id === 'center' ? 'bullseye' : 'globe'}"></i>
                            ${pos.label}
                        </h6>
                        <p class="card-text small text-muted">${pos.description}</p>
                        <div class="small">
                            ${lightsInPosition.length > 0
                                ? lightsInPosition.map(l => `<span class="badge bg-secondary me-1">${l.name}</span>`).join('')
                                : '<span class="text-muted">Nenhuma lâmpada</span>'
                            }
                        </div>
                    </div>
                </div>
            </div>
        `);
        container.append(col);
    });
}

// Salvar configuração
function savePositions() {
    $.ajax({
        type: 'POST',
        url: '/positions',
        contentType: 'application/json',
        data: JSON.stringify({ lights: lightsData }),
        success: function() {
            const toast = new bootstrap.Toast($('#save-toast'));
            toast.show();
        },
        error: function(jqXHR, textStatus, errorThrown) {
            alert('Erro ao salvar configuração: ' + errorThrown);
        }
    });
}

// Restaurar configuração padrão
function resetPositions() {
    if (confirm('Tem certeza que deseja restaurar as configurações padrão?')) {
        $.ajax({
            type: 'POST',
            url: '/positions/reset',
            success: function() {
                loadPositions();
                const toast = $('#save-toast');
                toast.find('.toast-body').html('<i class="bi bi-check-circle"></i> Configurações restauradas!');
                new bootstrap.Toast(toast).show();
            },
            error: function(jqXHR, textStatus, errorThrown) {
                alert('Erro ao restaurar configurações: ' + errorThrown);
            }
        });
    }
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

// Click em slot de posição
function setupPositionSlotClicks() {
    $('.position-slot').on('click', function() {
        const position = $(this).data('position');
        const lightsInPosition = lightsData.filter(l => l.position === position && l.enabled);

        if (lightsInPosition.length > 0) {
            const names = lightsInPosition.map(l => l.name).join(', ');
            alert(`Lâmpadas na posição "${position}":\n${names}`);
        } else {
            alert(`Nenhuma lâmpada na posição "${position}"`);
        }
    });
}

// Inicialização
$(document).ready(function() {
    initTheme();
    checkBridgeStatus();
    loadPositions();
    setupPositionSlotClicks();

    $('#save-btn').click(savePositions);
    $('#reset-btn').click(resetPositions);
    $('#refresh-btn').click(loadPositions);
    $('#theme-btn').click(toggleTheme);
});
