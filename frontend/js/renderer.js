/**
 * UIRenderer — 纯 DOM 渲染层
 *
 * 职责：
 *  - marked.js 封装（含降级）
 *  - 消息气泡 / 思考块 / 工具卡片 / 思考指示器 的创建与更新
 *  - 任务状态横幅 / 错误横幅
 *  - 不持有业务状态，只操作 DOM
 */
class UIRenderer {
  constructor(app) {
    this.app = app;
  }

  // ==================================================================
  // Markdown
  // ==================================================================

  /** 配置 marked（由 App 初始化时调用一次） */
  initMarked() {
    const check = () => {
      if (typeof marked !== 'undefined') {
        try {
          marked.setOptions({
            breaks: true,
            gfm: true,
            headerIds: false,
            mangle: false,
            highlight: (code, lang) => {
              if (lang && typeof hljs !== 'undefined' && hljs.getLanguage(lang)) {
                try { return hljs.highlight(code, { language: lang }).value; }
                catch (_) {}
              }
              return code;
            }
          });
          console.log('marked.js 初始化成功');
        } catch (e) { console.warn('marked 配置失败:', e); }
      } else {
        setTimeout(check, 100);
      }
    };
    check();
  }

  renderMarkdown(content) {
    if (!content) return '';
    if (typeof marked !== 'undefined') {
      try { return marked.parse(content); }
      catch (_) {}
    }
    // 降级：手写简易正则
    return this._fallbackMarkdown(content);
  }

  _fallbackMarkdown(text) {
    let h = this.esc(text);
    h = h.replace(/```(\w*)\n([\s\S]*?)```/g, (_, __, code) => `<pre><code>${this.esc(code.trim())}</code></pre>`);
    h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
    h = h.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    h = h.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    h = h.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    h = h.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    h = h.replace(/^[\-\*] (.+)$/gm, '<li>$1</li>');
    h = h.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>');
    return h.split('\n\n').map(p => p.trim()).filter(Boolean).map(p => {
      if (/^<(h|pre|ul|ol|hr|blockquote)/.test(p)) return p;
      return `<p>${p.replace(/\n/g, '<br>')}</p>`;
    }).join('\n');
  }

  // ==================================================================
  // 消息
  // ==================================================================

  createMessage(role, content) {
    const row = this.createMessageRow(role);
    row.querySelector('.msg-bubble').innerHTML = this.renderMarkdown(content);
    this.scrollDown();
    return row;
  }

  createMessageRow(role) {
    const row = document.createElement('div');
    row.className = `msg-row ${role}`;
    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    row.appendChild(bubble);
    this.el('messagesWrapper').appendChild(row);
    return row;
  }

  appendAssistantText(row, text) {
    const bubble = row.querySelector('.msg-bubble');
    const old = bubble.querySelector('.streaming-text');
    if (old) old.remove();
    const p = document.createElement('p');
    p.className = 'streaming-text';
    p.textContent = text;
    bubble.appendChild(p);
    this.scrollDown();
    return p;
  }

  // ==================================================================
  // 思考块（DeepSeek 风格可折叠）
  // ==================================================================

  createThinkingBox(startTime) {
    if (!startTime) startTime = Date.now();
    const container = document.createElement('div');
    container.className = 'thinking-container';

    const header = document.createElement('div');
    header.className = 'thinking-header';
    header.innerHTML = `
      <span class="thinking-icon"></span>
      <span class="thinking-header-text">思考中…</span>
      <span class="thinking-header-dots"><span></span><span></span><span></span></span>
      <span class="thinking-chevron">▼</span>`;

    const body = document.createElement('div');
    body.className = 'thinking-body';

    container.appendChild(header);
    container.appendChild(body);
    this.el('messagesWrapper').appendChild(container);
    this.scrollDown();

    const box = { container, header, body, headerText: header.querySelector('.thinking-header-text'), startTime, bodyText: '', _collapsed: false, _elapsedText: '' };

    header.addEventListener('click', () => {
      if (box._collapsed) this.expandThinkingBox(box);
      else this.collapseThinkingBox(box);
    });

    return box;
  }

  collapseThinkingBox(box) {
    if (!box || box._collapsed) return;
    box._collapsed = true;
    box.container.classList.add('collapsed');
    box.container.classList.remove('streaming');
    if (!box._elapsedText) {
      box._elapsedText = `思考过程 (${((Date.now() - box.startTime) / 1000).toFixed(1)}s)`;
    }
    box.headerText.textContent = box._elapsedText;
    box.header.querySelector('.thinking-chevron').innerHTML = '▶';
    const dots = box.header.querySelector('.thinking-header-dots');
    if (dots) dots.style.display = 'none';
    this.scrollDown();
  }

  expandThinkingBox(box) {
    if (!box) return;
    box._collapsed = false;
    box.container.classList.remove('collapsed');
    box.header.querySelector('.thinking-chevron').innerHTML = '▼';
    this.scrollDown();
  }

  updateThinkingHeader(box, text, isStreaming) {
    if (!box) return;
    if (isStreaming) {
      box.container.classList.add('streaming');
      const dots = box.header.querySelector('.thinking-header-dots');
      if (dots) dots.style.display = '';
    }
    if (text && !box._collapsed) box.headerText.textContent = text;
  }

  // ==================================================================
  // 思考指示器
  // ==================================================================

  createThinkingIndicator() {
    const el = document.createElement('div');
    el.className = 'thinking-indicator';
    el.innerHTML = `
      <span class="thinking-dots"><span class="thinking-dot"></span><span class="thinking-dot"></span><span class="thinking-dot"></span></span>
      <span class="thinking-indicator-text">正在思考…</span>`;
    this.el('messagesWrapper').appendChild(el);
    this.scrollDown();
    return el;
  }

  updateThinkingText(el, text) {
    if (!el || !el.parentNode) return;
    const span = el.querySelector('.thinking-indicator-text');
    if (span) span.textContent = text;
    this.scrollDown();
  }

  removeThinkingIndicator(el) {
    if (!el || !el.parentNode) return;
    el.style.opacity = '0';
    setTimeout(() => { if (el.parentNode) el.remove(); }, 200);
  }

  // ==================================================================
  // 工具卡片
  // ==================================================================

  createToolCard(name, args, step, status) {
    const icons = { calculator: '🔢', search: '🔍', todo: '📋' };
    const labels = { pending: '执行中', success: '完成', error: '失败' };
    const card = document.createElement('div');
    card.className = status === 'pending' ? 'tool-card open' : 'tool-card';
    card.dataset.toolName = name;
    if (status === 'pending') card.dataset.pending = 'true';

    card.innerHTML = `
      <div class="tool-card-header">
        <span class="tool-card-icon">${icons[name] || '🔧'}</span>
        <span class="tool-card-name">${this.esc(name)}</span>
        ${step ? `<span style="font-size:10px;color:var(--text-muted);">步骤 ${step}</span>` : ''}
        <span class="tool-card-badge ${status || 'success'}">${labels[status] || status || '完成'}</span>
        <span class="tool-card-chevron"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg></span>
      </div>
      <div class="tool-card-body">
        ${args ? `<div class="tool-card-section-label">参数</div><div class="tool-card-code">${this.esc(JSON.stringify(args, null, 2))}</div>` : ''}
        <div class="tool-card-section-label">结果</div>
        <div class="tool-card-code tool-card-result">等待中…</div>
      </div>`;
    card.querySelector('.tool-card-header').addEventListener('click', () => card.classList.toggle('open'));
    this.el('messagesWrapper').appendChild(card);
    this.scrollDown();
    return card;
  }

  createToolCardStatic(name, args) {
    const icons = { calculator: '🔢', search: '🔍', todo: '📋' };
    const card = document.createElement('div');
    card.className = 'tool-card';
    card.dataset.toolName = name;
    card.dataset.pending = 'true';  // Let updateLastPendingToolCard find it
    card.innerHTML = `
      <div class="tool-card-header">
        <span class="tool-card-icon">${icons[name] || '🔧'}</span>
        <span class="tool-card-name">${this.esc(name)}</span>
        <span class="tool-card-badge pending">等待</span>
        <span class="tool-card-chevron"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg></span>
      </div>
      <div class="tool-card-body">
        ${args ? `<div class="tool-card-section-label">参数</div><div class="tool-card-code">${this.esc(JSON.stringify(args, null, 2))}</div>` : ''}
        <div class="tool-card-section-label">结果</div>
        <div class="tool-card-code tool-card-result">等待中…</div>
      </div>`;
    card.querySelector('.tool-card-header').addEventListener('click', () => card.classList.toggle('open'));
    this.el('messagesWrapper').appendChild(card);
    return card;
  }

  updateToolCardResult(card, result, success) {
    const re = card.querySelector('.tool-card-result');
    if (re) re.textContent = result;
    const badge = card.querySelector('.tool-card-badge');
    if (badge) { badge.textContent = success ? '完成' : '失败'; badge.className = 'tool-card-badge ' + (success ? 'success' : 'error'); }
    delete card.dataset.pending;
    this.scrollDown();
  }

  updateLastPendingToolCard(result) {
    const card = this.el('messagesWrapper').querySelector('.tool-card[data-pending="true"]');
    if (card) this.updateToolCardResult(card, result, !result.startsWith('Error'));
  }

  // ==================================================================
  // 横幅
  // ==================================================================

  createTaskBanner(total, done) {
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    const barFill = total > 0 ? Math.max(2, pct) : 0;
    const banner = document.createElement('div');
    banner.className = 'task-status-banner';
    banner.innerHTML = `
      <div class="task-status-header"><span>📋 上次留下的任务计划</span><span class="task-status-count">${done}/${total} 已完成</span></div>
      <div class="task-status-bar"><div class="task-status-fill" style="width:${barFill}%"></div></div>
      <div class="task-status-hint">继续对话即可推进任务 — 告诉 Agent "完成了第 X 步" 或 "查看当前进度"</div>`;
    this.el('messagesWrapper').appendChild(banner);
  }

  createErrorBanner(msg) {
    const el = document.createElement('div');
    el.className = 'error-banner';
    el.textContent = '错误：' + msg;
    this.el('messagesWrapper').appendChild(el);
    this.scrollDown();
  }

  createStepIndicator(step, max) {
    const el = document.createElement('div');
    el.className = 'step-indicator';
    el.innerHTML = `<span class="step-dot"></span> 步骤 ${step}/${max}`;
    this.el('messagesWrapper').appendChild(el);
    this.scrollDown();
  }

  // ==================================================================
  // 计划卡片（Plan-Execute 模式）
  // ==================================================================

  createPlanCard(steps) {
    const card = document.createElement('div');
    card.className = 'plan-card';
    const icons = { pending: '○', in_progress: '◐', done: '●', failed: '✕' };
    const labels = { pending: '等待', in_progress: '执行中', done: '完成', failed: '失败' };
    card.innerHTML = `
      <div class="plan-card-header">📋 执行计划 · ${steps.length} 步</div>
      <div class="plan-card-body">
        ${steps.map((s, i) => `
          <div class="plan-step" data-plan-index="${i}">
            <span class="plan-step-icon">${icons.pending}</span>
            <span class="plan-step-title">${this.esc(s.title || s.description || `步骤${i+1}`)}</span>
            <span class="plan-step-status pending">${labels.pending}</span>
          </div>
        `).join('')}
      </div>`;
    this.el('messagesWrapper').appendChild(card);
    this.scrollDown();
    return card;
  }

  updatePlanStep(card, index, status) {
    const row = card.querySelector(`.plan-step[data-plan-index="${index}"]`);
    if (!row) return;
    const icons = { pending: '○', in_progress: '◐', done: '●', failed: '✕' };
    const labels = { pending: '等待', in_progress: '执行中', done: '完成', failed: '失败' };
    const icon = row.querySelector('.plan-step-icon');
    const badge = row.querySelector('.plan-step-status');
    if (icon) icon.textContent = icons[status] || '○';
    if (badge) {
      badge.textContent = labels[status] || status;
      badge.className = 'plan-step-status ' + status;
    }
    this.scrollDown();
  }

  // ==================================================================
  // 工具
  // ==================================================================

  clearMessages() {
    this.el('messagesWrapper').querySelectorAll(
      '.msg-row,.tool-card,.thinking-container,.plan-card,.task-status-banner,.step-indicator,.error-banner,.thinking-indicator'
    ).forEach(el => el.remove());
  }

  el(id) { return this.app.dom[id]; }

  esc(s) {
    const m = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
    return String(s).replace(/[&<>"']/g, c => m[c]);
  }

  parseArgs(a) {
    if (typeof a === 'object') return a;
    if (typeof a === 'string') { try { return JSON.parse(a); } catch (_) { return { raw: a }; } }
    return {};
  }

  parseSSE(text) {
    const lines = text.split('\n');
    let type = 'message', data = '';
    for (const line of lines) {
      if (line.startsWith('event: ')) type = line.slice(7).trim();
      else if (line.startsWith('data: ')) data = line.slice(6);
    }
    if (!data) return null;
    try { const p = JSON.parse(data); p.type = type; return p; }
    catch (_) { return null; }
  }

  scrollDown() {
    requestAnimationFrame(() => {
      const mc = this.el('messagesContainer');
      if (mc) mc.scrollTop = mc.scrollHeight;
    });
  }
}
