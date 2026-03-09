const chatSocket = io('/chat');

// DOM elements
const messagesContainer = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const btnSend = document.getElementById('btn-send');
const btnStop = document.getElementById('btn-stop');
const btnClear = document.getElementById('btn-clear');
const sessionStatus = document.getElementById('session-status');
const thinkingIndicator = document.getElementById('thinking-indicator');
const welcomeMsg = document.getElementById('welcome-msg');

// State
let isGenerating = false;
let autoScroll = true;
let currentAssistantBubble = null;
let currentResponseText = '';
let renderTimeout = null;
// Local copy of chat messages for "Copy Chat" feature
let chatMessages = [];

// Configure marked
marked.setOptions({
  breaks: true,
  gfm: true,
});

// ── Auto-scroll detection ──
messagesContainer.addEventListener('scroll', () => {
  const { scrollTop, scrollHeight, clientHeight } = messagesContainer;
  autoScroll = scrollHeight - scrollTop - clientHeight < 60;
});

function scrollToBottom() {
  if (autoScroll) {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }
}

// ── Session management ──
// Auto-start session on connect
chatSocket.on('connect', () => {
  sessionStatus.textContent = 'Connecting...';
  sessionStatus.className = 'text-xs text-yellow-400';
  chatSocket.emit('start_session');
});

chatSocket.on('disconnect', () => {
  sessionStatus.textContent = 'Disconnected';
  sessionStatus.className = 'text-xs text-red-400';
  setGenerating(false);
});

chatSocket.on('session_status', (data) => {
  if (data.status === 'started') {
    sessionStatus.textContent = 'Connected';
    sessionStatus.className = 'text-xs text-green-400';
    btnSend.disabled = false;
    chatInput.focus();
  } else if (data.status === 'stopped') {
    sessionStatus.textContent = 'Disconnected';
    sessionStatus.className = 'text-xs text-gray-400';
    btnSend.disabled = true;
    setGenerating(false);
  }
});

// Replay persisted history on reconnect
chatSocket.on('history_replay', (data) => {
  clearChatDOM();
  chatMessages = [];
  const msgs = data.messages || [];
  if (msgs.length === 0) return;
  // Hide welcome message
  if (welcomeMsg) welcomeMsg.remove();
  msgs.forEach((msg) => {
    chatMessages.push(msg);
    if (msg.role === 'user') {
      appendUserBubble(msg.content);
    } else {
      const bubble = createAssistantBubble();
      bubble.innerHTML = marked.parse(msg.content);
      addCopyButtons(bubble);
    }
  });
  scrollToBottom();
});

// ── Message handling ──
chatSocket.on('generation_started', () => {
  setGenerating(true);
  thinkingIndicator.classList.remove('hidden');
});

chatSocket.on('output', (data) => {
  // Hide thinking on first chunk
  thinkingIndicator.classList.add('hidden');

  if (data.stream === 'error') {
    appendErrorBubble(data.data);
    return;
  }

  // Create or append to assistant bubble
  if (!currentAssistantBubble) {
    currentAssistantBubble = createAssistantBubble();
    currentResponseText = '';
  }
  currentResponseText += data.data;

  // Debounce markdown rendering
  if (renderTimeout) clearTimeout(renderTimeout);
  renderTimeout = setTimeout(() => {
    renderAssistantBubble();
  }, 80);
});

chatSocket.on('generation_complete', () => {
  // Final render
  if (currentAssistantBubble) {
    renderAssistantBubble();
    addCopyButtons(currentAssistantBubble);
  }
  // Track assistant response locally
  if (currentResponseText.trim()) {
    chatMessages.push({ role: 'assistant', content: currentResponseText.trim() });
  }
  finishGeneration();
});

chatSocket.on('generation_stopped', () => {
  if (currentAssistantBubble) {
    renderAssistantBubble();
    // Add stopped indicator
    const indicator = document.createElement('div');
    indicator.className = 'text-xs text-gray-400 italic mt-1';
    indicator.textContent = '(generation stopped)';
    currentAssistantBubble.appendChild(indicator);
    addCopyButtons(currentAssistantBubble);
  }
  if (currentResponseText.trim()) {
    chatMessages.push({ role: 'assistant', content: currentResponseText.trim() });
  }
  finishGeneration();
});

chatSocket.on('history_cleared', () => {
  chatMessages = [];
  clearChatDOM();
});

// ── UI actions ──
function sendMessage() {
  const msg = chatInput.value.trim();
  if (!msg || isGenerating) return;

  // Hide welcome message
  if (welcomeMsg) welcomeMsg.remove();

  // Track locally
  chatMessages.push({ role: 'user', content: msg });

  // Add user bubble
  appendUserBubble(msg);

  // Send to server
  chatSocket.emit('send_message', { message: msg });

  // Clear input
  chatInput.value = '';
  chatInput.style.height = 'auto';
  btnSend.disabled = true;
}

function cancelGeneration() {
  chatSocket.emit('cancel_generation');
}

function clearHistory() {
  chatSocket.emit('clear_history');
}

// Textarea: Enter to send, Shift+Enter for newline
chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// Auto-resize textarea
chatInput.addEventListener('input', () => {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 150) + 'px';
  btnSend.disabled = !chatInput.value.trim() || isGenerating;
});

// ── Bubble creation ──
function appendUserBubble(text) {
  const wrapper = document.createElement('div');
  wrapper.className = 'flex justify-end';

  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble-user';
  bubble.textContent = text;

  wrapper.appendChild(bubble);
  messagesContainer.appendChild(wrapper);
  scrollToBottom();
}

function createAssistantBubble() {
  const wrapper = document.createElement('div');
  wrapper.className = 'flex justify-start';

  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble-assistant prose prose-sm dark:prose-invert max-w-none';

  wrapper.appendChild(bubble);
  messagesContainer.appendChild(wrapper);
  scrollToBottom();
  return bubble;
}

function renderAssistantBubble() {
  if (!currentAssistantBubble || !currentResponseText) return;
  currentAssistantBubble.innerHTML = marked.parse(currentResponseText);
  scrollToBottom();
}

function appendErrorBubble(text) {
  const wrapper = document.createElement('div');
  wrapper.className = 'flex justify-start';

  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble-assistant bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 text-sm';
  bubble.textContent = text;

  wrapper.appendChild(bubble);
  messagesContainer.appendChild(wrapper);
  scrollToBottom();
}

// ── Code block copy buttons ──
function addCopyButtons(container) {
  container.querySelectorAll('pre').forEach((pre) => {
    if (pre.querySelector('.copy-btn')) return;

    const wrapper = document.createElement('div');
    wrapper.className = 'code-block-wrapper';
    pre.parentNode.insertBefore(wrapper, pre);
    wrapper.appendChild(pre);

    const btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.textContent = 'Copy';
    btn.addEventListener('click', () => {
      const code = pre.querySelector('code')
        ? pre.querySelector('code').textContent
        : pre.textContent;
      navigator.clipboard.writeText(code).then(() => {
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = 'Copy'; }, 2000);
      });
    });
    wrapper.appendChild(btn);
  });
}

// ── Helpers ──
function setGenerating(value) {
  isGenerating = value;
  btnStop.classList.toggle('hidden', !value);
  btnSend.classList.toggle('hidden', value);
  chatInput.disabled = value;
  if (!value) {
    thinkingIndicator.classList.add('hidden');
    btnSend.disabled = !chatInput.value.trim();
    chatInput.focus();
  }
}

function finishGeneration() {
  currentAssistantBubble = null;
  currentResponseText = '';
  renderTimeout = null;
  setGenerating(false);
}

function clearChatDOM() {
  messagesContainer.innerHTML = '';
  currentAssistantBubble = null;
  currentResponseText = '';
}

// ── Copy full chat history to clipboard ──
function copyChatHistory() {
  if (chatMessages.length === 0) return;

  const text = chatMessages.map((msg) => {
    const label = msg.role === 'user' ? 'You' : 'Claude';
    return `**${label}:**\n${msg.content}`;
  }).join('\n\n---\n\n');

  const btn = document.getElementById('btn-copy-chat');
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = 'Copy Chat'; }, 2000);
  }).catch(() => {
    // Fallback for non-HTTPS contexts
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = 'Copy Chat'; }, 2000);
  });
}
