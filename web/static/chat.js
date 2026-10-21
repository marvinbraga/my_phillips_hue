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
            addMessage(data.content, 'bot');
            break;
        case 'error':
            hideTypingIndicator();
            addMessage(data.content, 'error');
            break;
        case 'cleared':
            clearMessages();
            addMessage('Histórico limpo. Como posso ajudar?', 'bot');
            break;
    }
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
        messageDiv.innerHTML = marked.parse(content);
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

// Enviar mensagem
function sendMessage() {
    const message = messageInput.value.trim();
    if (!message) return;

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
        const color = light.color;
        const rgbColor = `rgb(${color.r}, ${color.g}, ${color.b})`;
        const isOn = light.on && light.reachable;
        const stateClass = isOn ? 'on' : 'off';

        return `
            <div class="light-mini" title="${light.name}">
                <div class="light-mini-bulb ${stateClass}"
                     style="background-color: ${rgbColor}; --light-color: ${rgbColor}">
                </div>
                <span class="light-mini-name">${light.name}</span>
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
connectWebSocket();
checkChatStatus();
loadLightsStatus();
