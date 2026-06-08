/**
 * ChatEngine — SSE 流式对话核心
 */
class ChatEngine {
  constructor(app) {
    this.app = app;
  }

  stop() {
    if (this.app.state.abortController) {
      this.app.state.abortController.abort();
    }
    this._setSending(false);
  }

  async send(message) {
    if (this.app.state.isStreaming) return;
    if (!message) return;

    if (!this.app.state.currentSessionId) {
      await this.app.sessions.create();
      if (!this.app.state.currentSessionId) return;
    }

    const R = this.app.renderer;
    const state = this.app.state;

    state.isStreaming = true;
    this._setSending(true);
    this.app.dom.welcomeScreen.style.display = 'none';
    this.app.dom.chatInput.value = '';
    this.app.dom.chatInput.style.height = 'auto';
    this.app.dom.chatInput.focus();

    const sendTime = Date.now();

    R.createMessage('user', message);

    const thinkingEl = R.createThinkingIndicator();
    const assistantRow = R.createMessageRow('assistant');

    let thinkingBox = null;
    let thinkingStarted = false;
    let streamingTextEl = null;
    let fullResponseText = '';  // 独立于 DOM 的完整响应文本
    let currentToolCard = null;

    state.abortController = new AbortController();

    try {
      const res = await fetch(`/api/sessions/${state.currentSessionId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, mode: state.mode }),
        signal: state.abortController.signal,
      });
      if (!res.ok) throw new Error(`服务器错误 (${res.status})`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop();

        for (const part of parts) {
          if (!part.trim()) continue;
          const ev = R.parseSSE(part);
          if (!ev) continue;

          switch (ev.type) {

            case 'step_start':
              break;

            case 'reasoning':
              if (!thinkingStarted) {
                thinkingStarted = true;
                R.removeThinkingIndicator(thinkingEl);
                thinkingBox = R.createThinkingBox(sendTime);
              }
              if (thinkingBox) {
                thinkingBox.bodyText += ev.content;
                thinkingBox.body.textContent = thinkingBox.bodyText;
                R.scrollDown();
              }
              R.updateThinkingHeader(thinkingBox, '思考中…', true);
              break;

            case 'message':
              // Progressive content token
              if (!ev.final && ev.content) {
                if (thinkingBox && !thinkingBox._collapsed) R.collapseThinkingBox(thinkingBox);
                if (thinkingEl) R.removeThinkingIndicator(thinkingEl);
                if (!streamingTextEl) {
                  streamingTextEl = R.appendAssistantText(assistantRow, '');
                  streamingTextEl.classList.add('streaming-cursor');
                }
                fullResponseText += ev.content;
                streamingTextEl.textContent = fullResponseText;
                R.scrollDown();
              }
              // Final marker: render accumulated text as markdown
              if (ev.final) {
                this._applyMarkdown(R, assistantRow, fullResponseText);
                if (thinkingBox && !thinkingBox._collapsed) R.collapseThinkingBox(thinkingBox);
              }
              break;

            case 'tool_call':
              R.updateThinkingHeader(thinkingBox, `调用工具: ${ev.name}…`, false);
              currentToolCard = R.createToolCard(ev.name, ev.args, ev.step, 'pending');
              break;

            case 'tool_result':
              if (currentToolCard) {
                R.updateToolCardResult(currentToolCard, ev.result, ev.success);
                currentToolCard.classList.remove('open');
              }
              currentToolCard = null;
              break;

            case 'plan_created':
              if (ev.steps) {
                this._currentPlan = { steps: ev.steps, card: R.createPlanCard(ev.steps) };
              }
              break;

            case 'plan_step_update':
              if (this._currentPlan) {
                R.updatePlanStep(this._currentPlan.card, ev.index, ev.status);
              }
              break;

            case 'error':
              R.createErrorBanner(ev.message);
              break;
          }
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') {
        console.error('流错误:', e);
        R.createErrorBanner('连接错误：' + e.message);
      }
    } finally {
      state.isStreaming = false;
      state.abortController = null;
      this._setSending(false);

      // 兜底：无论流是否正常结束，渲染最终 markdown
      this._applyMarkdown(R, assistantRow, fullResponseText);

      if (thinkingEl) R.removeThinkingIndicator(thinkingEl);
      if (thinkingBox && !thinkingBox._collapsed) R.collapseThinkingBox(thinkingBox);

      this.app.dom.messagesWrapper.querySelectorAll('.tool-card-badge.pending')
        .forEach(b => { b.textContent = '完成'; b.className = 'tool-card-badge success'; });

      await this.app.sessions.loadList();
      this.app.dom.chatInput.focus();
    }
  }

  // 将完整响应文本渲染为 markdown HTML 注入 bubble
  _applyMarkdown(R, row, text) {
    if (!row || !text) return;
    const bubble = row.querySelector('.msg-bubble');
    if (!bubble) return;
    bubble.innerHTML = R.renderMarkdown(text);
    // CSS cursor 残留清理
    bubble.querySelectorAll('.streaming-cursor').forEach(el => el.classList.remove('streaming-cursor'));
  }

  // 按钮状态切换（纯 CSS：不加 innerHTML，不改 DOM 结构）
  _setSending(sending) {
    const btn = this.app.dom.btnSend;
    if (!btn) return;
    if (sending) {
      btn.classList.add('stop');
    } else {
      btn.classList.remove('stop');
    }
  }
}
