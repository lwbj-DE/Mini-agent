/**
 * ThemeManager — 浅色/深色主题切换 + localStorage 持久化
 */
class ThemeManager {
  constructor(app) {
    this.app = app;
  }

  init() {
    const saved = localStorage.getItem('mini-agent-theme');
    this.apply(saved || 'light');
  }

  apply(theme) {
    this.app.state.theme = theme;
    if (theme === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    localStorage.setItem('mini-agent-theme', theme);
    this._updateButton();
  }

  toggle() {
    this.apply(this.app.state.theme === 'light' ? 'dark' : 'light');
  }

  _updateButton() {
    const btn = this.app.dom.btnThemeToggle;
    if (!btn) return;
    const label = btn.querySelector('.theme-label');
    if (label) label.textContent = this.app.state.theme === 'light' ? '深色模式' : '浅色模式';
  }
}
