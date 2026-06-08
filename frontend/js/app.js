/**
 * MiniAgentApp — 应用入口
 *
 * 编排 ThemeManager / SessionManager / ChatEngine / UIRenderer
 * 绑定全局事件，启动应用。
 */
class MiniAgentApp {
  constructor() {
    // --- 全局状态 ---
    this.state = {
      currentSessionId: null,
      sessions: [],
      isStreaming: false,
      abortController: null,
      theme: 'light',
      mode: 'react',  // 'react' | 'plan_execute'
    };

    // --- DOM 缓存 ---
    const $ = (s) => document.querySelector(s);
    this.dom = {
      sidebar: $('#sidebar'),
      sessionList: $('#sessionList'),
      btnNewChat: $('#btnNewChat'),
      btnSidebarToggle: $('#btnSidebarToggle'),
      btnThemeToggle: $('#btnThemeToggle'),
      chatTitle: $('#chatTitle'),
      messagesContainer: $('#messagesContainer'),
      messagesWrapper: $('#messagesWrapper'),
      welcomeScreen: $('#welcomeScreen'),
      modeSelectorBtn: $('#modeSelectorBtn'),
      modeDropdown: $('#modeDropdown'),
      currentModeText: $('#currentModeText'),
      chatInput: $('#chatInput'),
      btnSend: $('#btnSend'),
    };

    // --- 子模块（按依赖顺序）---
    this.renderer = new UIRenderer(this);
    this.theme = new ThemeManager(this);
    this.sessions = new SessionManager(this);
    this.chat = new ChatEngine(this);
  }

  // ==================================================================
  // 初始化
  // ==================================================================

  init() {
    this.renderer.initMarked();
    this.theme.init();
    this._bindEvents();
    this.sessions.loadList();
    this.dom.chatInput.focus();
  }

  // ==================================================================
  // 事件绑定
  // ==================================================================

  _bindEvents() {
    const d = this.dom;

    d.btnNewChat.addEventListener('click', () => this.sessions.create());
    d.btnThemeToggle.addEventListener('click', () => this.theme.toggle());
    d.btnSidebarToggle.addEventListener('click', () => d.sidebar.classList.toggle('open'));

    // 模式选择器
    d.modeSelectorBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      d.modeSelectorBtn.classList.toggle('open');
      d.modeDropdown.classList.toggle('show');
    });
    d.modeDropdown.querySelectorAll('.mode-dropdown-item').forEach(item => {
      item.addEventListener('click', (e) => {
        const mode = item.dataset.mode;
        this.state.mode = mode;
        d.modeDropdown.querySelectorAll('.mode-dropdown-item').forEach(i => i.classList.remove('active'));
        item.classList.add('active');
        const labels = { react: '⚡ 快速', plan_execute: '📋 规划' };
        d.currentModeText.textContent = labels[mode] || '⚡ 快速';
        d.modeDropdown.classList.remove('show');
        d.modeSelectorBtn.classList.remove('open');
        d.chatInput.focus();
      });
    });
    document.addEventListener('click', () => {
      d.modeDropdown.classList.remove('show');
      d.modeSelectorBtn.classList.remove('open');
    });

    d.btnSend.addEventListener('click', () => {
      if (this.state.isStreaming) {
        this.chat.stop();
      } else {
        this.chat.send(d.chatInput.value.trim());
      }
    });

    d.chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.chat.send(d.chatInput.value.trim());
      }
    });

    d.chatInput.addEventListener('input', () => {
      d.chatInput.style.height = 'auto';
      d.chatInput.style.height = Math.min(d.chatInput.scrollHeight, 200) + 'px';
    });

    // 建议卡片
    d.messagesWrapper.addEventListener('click', (e) => {
      const chip = e.target.closest('.suggestion-chip');
      if (chip?.dataset.prompt && !this.state.isStreaming) {
        d.chatInput.value = chip.dataset.prompt;
        d.chatInput.style.height = 'auto';
        d.chatInput.style.height = Math.min(d.chatInput.scrollHeight, 200) + 'px';
        this.chat.send(chip.dataset.prompt);
      }
    });

    // 移动端点击外部关闭侧栏
    document.addEventListener('click', (e) => {
      if (window.innerWidth <= 768 &&
          !d.sidebar.contains(e.target) &&
          e.target !== d.btnSidebarToggle &&
          !d.btnSidebarToggle.contains(e.target)) {
        d.sidebar.classList.remove('open');
      }
    });
  }
}

// --- 启动 ---
const app = new MiniAgentApp();
app.init();
