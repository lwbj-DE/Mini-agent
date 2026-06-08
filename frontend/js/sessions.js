/**
 * SessionManager — 会话 CRUD + 侧栏渲染
 */
class SessionManager {
  constructor(app) {
    this.app = app;
  }

  // ==================================================================
  // API
  // ==================================================================

  async _req(method, path, body) {
    const opts = { method, headers: {} };
    if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    const res = await fetch(path, opts);
    if (!res.ok) throw new Error(`API ${method} ${path} (${res.status})`);
    return res;
  }
  async _json(method, path, body) { return (await this._req(method, path, body)).json(); }

  // ==================================================================
  // CRUD
  // ==================================================================

  async loadList() {
    try { this.app.state.sessions = await this._json('GET', '/api/sessions'); }
    catch (_) { this.app.state.sessions = []; }
    this.renderList();
  }

  renderList() {
    const list = this.app.dom.sessionList;
    list.innerHTML = '';
    if (!this.app.state.sessions.length) {
      list.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-muted);font-size:12px;">暂无对话记录</div>';
      return;
    }
    for (const s of this.app.state.sessions) {
      let badge = '';
      if (s.task_total > 0) {
        badge = `<span class="session-task-badge" title="任务进度">📋 ${s.task_done}/${s.task_total}</span>`;
      }
      const el = document.createElement('div');
      el.className = 'session-item' + (s.id === this.app.state.currentSessionId ? ' active' : '');
      el.dataset.id = s.id;
      el.innerHTML = `<span class="session-item-name" title="${this.app.renderer.esc(s.name)}">${this.app.renderer.esc(s.name)}</span>${badge}<button class="session-item-delete" data-action="delete" title="删除">✕</button>`;
      el.addEventListener('click', (e) => {
        if (e.target.dataset.action === 'delete') { e.stopPropagation(); this.delete(s.id); }
        else this.switchTo(s.id);
      });
      list.appendChild(el);
    }
  }

  async switchTo(id) {
    this.app.state.currentSessionId = id;
    if (this.app.state.abortController) { this.app.state.abortController.abort(); this.app.state.abortController = null; }
    this.app.state.isStreaming = false;

    this.renderList();
    this.app.dom.welcomeScreen.style.display = 'none';
    this.app.renderer.clearMessages();
    this.app.dom.messagesWrapper.appendChild(this.app.dom.welcomeScreen);

    try {
      const s = await this._json('GET', `/api/sessions/${id}`);
      this.app.dom.chatTitle.textContent = s.name || 'Mini Agent';

      // 任务横幅
      const tasks = this._tasksFromState(s);
      if (tasks.length > 0) {
        const done = tasks.filter(t => t.status === 'done').length;
        this.app.renderer.createTaskBanner(tasks.length, done);
      }

      if (s.messages?.length) {
        this.app.dom.welcomeScreen.style.display = 'none';
        this._renderHistory(s.messages);
      }
    } catch (_) {}
    this.app.renderer.scrollDown();
    this.app.dom.chatInput.focus();
  }

  async create() {
    if (this.app.state.isStreaming) return;
    try {
      const s = await this._json('POST', '/api/sessions');
      this.app.state.currentSessionId = s.id;
      await this.loadList();
      this.app.dom.welcomeScreen.style.display = '';
      this.app.renderer.clearMessages();
      this.app.dom.messagesWrapper.appendChild(this.app.dom.welcomeScreen);
      this.app.dom.chatTitle.textContent = 'Mini Agent';
      this.app.renderer.scrollDown();
      this.app.dom.chatInput.focus();
    } catch (_) {}
  }

  async delete(id) {
    if (this.app.state.isStreaming) return;
    try {
      await this._json('DELETE', `/api/sessions/${id}`);
      if (this.app.state.currentSessionId === id) {
        this.app.state.currentSessionId = null;
        this.app.renderer.clearMessages();
        this.app.dom.welcomeScreen.style.display = '';
        this.app.dom.chatTitle.textContent = 'Mini Agent';
      }
      await this.loadList();
    } catch (_) {}
  }

  // ==================================================================
  // helpers
  // ==================================================================

  _tasksFromState(s) {
    try { return s.tool_state?.todo?.tasks || []; }
    catch (_) { return []; }
  }

  _renderHistory(messages) {
    for (const msg of messages) {
      if (msg.role === 'user') {
        this.app.renderer.createMessage('user', msg.content);
      } else if (msg.role === 'assistant') {
        if (msg.tool_calls?.length) {
          for (const tc of msg.tool_calls) {
            this.app.renderer.createToolCardStatic(tc.function.name, this.app.renderer.parseArgs(tc.function.arguments));
          }
        }
        if (msg.content) this.app.renderer.createMessage('assistant', msg.content);
      } else if (msg.role === 'tool') {
        this.app.renderer.updateLastPendingToolCard(msg.content);
      }
    }
  }
}
