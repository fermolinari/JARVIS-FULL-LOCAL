// Controlador principal: orb + voz sempre-ligada + bridge HTTP/SSE com Python.

const log = document.getElementById('log');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const stateText = document.getElementById('state-text');
const micBtn = document.getElementById('mic-btn');
const micIndicator = document.getElementById('mic-indicator');
const sendBtn = document.getElementById('send-btn');
const textInput = document.getElementById('text-input');
const activationOverlay = document.getElementById('activation-overlay');

let currentJarvisMsg = null;
let currentJarvisFullText = '';
let busy = false;
let activated = false;

function setState(state, text) {
    if (window.orb) window.orb.setState(state);
    stateText.textContent = state;
    if (text) statusText.textContent = text;
}

function setOnline(ok, msg) {
    statusDot.classList.toggle('online', ok);
    statusDot.classList.toggle('error', !ok);
    statusText.textContent = msg;
}

function setMicIndicator(on) {
    if (!micIndicator) return;
    micIndicator.classList.toggle('on', on);
    micIndicator.classList.toggle('off', !on);
    micIndicator.textContent = on ? 'MIC ON' : 'MIC OFF';
    micBtn.classList.toggle('active', on);
}

function appendUser(text) {
    const div = document.createElement('div');
    div.className = 'msg user';
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
}

function appendJarvisStart() {
    const div = document.createElement('div');
    div.className = 'msg jarvis';
    div.textContent = '';
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    currentJarvisMsg = div;
    currentJarvisFullText = '';
    return div;
}

function appendJarvisToken(text) {
    if (!currentJarvisMsg) appendJarvisStart();
    currentJarvisMsg.textContent += text;
    currentJarvisFullText += text;
    log.scrollTop = log.scrollHeight;
}

function appendJarvisEnd(fullText) {
    const text = fullText || currentJarvisFullText;
    currentJarvisMsg = null;
    currentJarvisFullText = '';
    if (text && window.voice) {
        setState('speaking', 'falando');
        window.voice.speak(text);
    } else {
        setState('idle', 'pronto');
    }
}

function appendTool(name, args) {
    const div = document.createElement('div');
    div.className = 'msg tool';
    div.textContent = `⚙ ${name}(${formatArgs(args)})`;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
}

function appendToolResult(toolDiv, result) {
    if (!toolDiv) return;
    toolDiv.textContent += `\n↳ ${truncate(result, 220)}`;
    log.scrollTop = log.scrollHeight;
}

function appendError(text) {
    const div = document.createElement('div');
    div.className = 'msg error';
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
}

function formatArgs(args) {
    if (!args) return '';
    return Object.entries(args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ');
}

function truncate(s, n) {
    if (!s) return '';
    return s.length > n ? s.substring(0, n) + '…' : s;
}

let lastToolDiv = null;

function handleEvent(ev) {
    switch (ev.type) {
        case 'tool_call':
            lastToolDiv = appendTool(ev.name, ev.args);
            setState('thinking', `executando ${ev.name}`);
            break;
        case 'tool_result':
            appendToolResult(lastToolDiv, ev.result);
            break;
        case 'assistant_start':
            setState('thinking', 'gerando resposta');
            appendJarvisStart();
            break;
        case 'token':
            appendJarvisToken(ev.text);
            break;
        case 'assistant_end':
            appendJarvisEnd(ev.full_text);
            busy = false;
            break;
        case 'error':
            appendError(ev.message);
            setState('error', 'erro');
            busy = false;
            break;
        case 'wake':
            // 2 palmas detectadas — garante mic sempre-ligado e cumprimenta
            if (window.voice) {
                window.voice.enableAlwaysOn();
                if (ev.message) {
                    setState('speaking', 'detectado');
                    window.voice.speak(ev.message);
                }
            }
            break;
    }
}

// --- HTTP API ---

async function send(text) {
    if (!text || busy) return;
    busy = true;
    appendUser(text);
    textInput.value = '';
    setState('thinking', 'enviando');
    try {
        const res = await fetch('/api/send_message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text }),
        });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            appendError(data.error || `HTTP ${res.status}`);
            busy = false;
            setState('idle', 'pronto');
        }
    } catch (e) {
        appendError(`falha de rede: ${e}`);
        busy = false;
        setState('error', 'desconectado');
    }
}

async function greet() {
    try {
        await fetch('/api/greet', { method: 'POST' });
    } catch (e) {
        console.warn('greet falhou:', e);
    }
}

async function checkHealth() {
    try {
        const res = await fetch('/api/health');
        const data = await res.json();
        setOnline(data.ok, data.message);
        setState(data.ok ? 'idle' : 'error', data.ok ? 'pronto' : 'falha');
    } catch (e) {
        setOnline(false, `bridge offline: ${e}`);
    }
}

// --- SSE: eventos do Python ---

function connectEvents() {
    const es = new EventSource('/api/events');
    es.onopen = () => {
        // health check assim que conectar
        checkHealth();
    };
    es.onmessage = (e) => {
        try {
            const data = JSON.parse(e.data);
            handleEvent(data);
        } catch (err) {
            console.warn('SSE parse:', err, e.data);
        }
    };
    es.onerror = () => {
        setOnline(false, 'reconectando...');
        // EventSource auto-reconnect; nada a fazer
    };
}

// --- Ativação inicial (primeiro clique destrava mic + áudio) ---

function activate() {
    if (activated) return;
    activated = true;
    activationOverlay.classList.add('gone');

    // Toca um utterance vazio pra destravar speechSynthesis no Chrome
    if (window.speechSynthesis) {
        try {
            const warm = new SpeechSynthesisUtterance(' ');
            warm.volume = 0;
            speechSynthesis.speak(warm);
        } catch (_) {}
    }

    // Liga o mic em modo sempre-ligado
    if (window.voice) {
        window.voice.enableAlwaysOn();
    }

    // Cumprimenta de cara (igual a 2 palmas)
    setTimeout(() => greet(), 500);
}

activationOverlay.addEventListener('click', activate);

// --- Inputs ---

sendBtn.addEventListener('click', () => send(textInput.value.trim()));
textInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        send(textInput.value.trim());
    }
});

// Mic button: alterna o modo SEMPRE-LIGADO (não é single-shot mais)
function toggleMic() {
    if (!window.voice) return;
    if (window.voice.alwaysOn) {
        window.voice.disableAlwaysOn();
    } else {
        window.voice.enableAlwaysOn();
    }
}

micBtn.addEventListener('click', toggleMic);

// Atalho de teclado: Ctrl+M alterna mic, Esc interrompe a fala
window.addEventListener('keydown', (e) => {
    if (e.ctrlKey && (e.key === 'm' || e.key === 'M')) {
        e.preventDefault();
        toggleMic();
        return;
    }
    if (e.key === 'Escape') {
        if (window.voice && window.voice.speaking) {
            e.preventDefault();
            window.voice.cancel();
            setState('idle', 'interrompido');
        }
    }
});

// Clique no orb (canvas) interrompe a fala atual
const orbCanvas = document.getElementById('orb-canvas');
if (orbCanvas) {
    orbCanvas.style.pointerEvents = 'auto';
    orbCanvas.addEventListener('click', () => {
        if (!activated) return;
        if (window.voice && window.voice.speaking) {
            window.voice.cancel();
            setState('idle', 'interrompido');
        }
    });
}

// --- Voice callbacks ---

if (window.voice) {
    window.voice.onAlwaysOnChange = (on) => {
        setMicIndicator(on);
        if (on && !busy) setState('listening', 'ouvindo');
        else if (!on && !busy) setState('idle', 'pronto');
    };
    window.voice.onListenStart = () => {
        if (!busy) setState('listening', 'ouvindo');
    };
    window.voice.onListenEnd = () => {
        // Não muda estado: o auto-restart vai reconectar; só visual se realmente parou
        if (!window.voice.alwaysOn && !busy) setState('idle', 'pronto');
    };
    window.voice.onTranscript = (text) => {
        // Ignora transcrições enquanto o JARVIS fala (pra não criar eco)
        if (window.voice.suspended) return;
        send(text);
    };
    window.voice.onSpeakStart = () => setState('speaking', 'falando');
    window.voice.onSpeakEnd   = () => {
        if (!busy) setState(window.voice && window.voice.alwaysOn ? 'listening' : 'idle',
                            window.voice && window.voice.alwaysOn ? 'ouvindo' : 'pronto');
    };
    window.voice.onAudioFrame = (level) => {
        if (window.orb) window.orb.setAudioLevel(level);
    };
}

// Estado inicial visual
setMicIndicator(false);
connectEvents();
