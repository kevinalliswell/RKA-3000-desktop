/** Per-machine UI preferences (theme, current operator name). Browser storage may be unavailable. */
export type Theme = 'system' | 'light' | 'dark' | 'blue';
export const THEMES: { id: Theme; label: string }[] = [
  { id: 'system', label: '跟随系统' }, { id: 'light', label: '浅色' }, { id: 'dark', label: '深色' }, { id: 'blue', label: '科技蓝' },
];

function read(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

function write(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* storage blocked: keep in memory only */ }
}

class Prefs {
  theme: Theme = $state('system');
  operator = $state('');

  load(): void {
    const theme = read('rka3000-theme');
    if (theme && THEMES.some((t) => t.id === theme)) this.theme = theme as Theme;
    this.operator = read('rka3000-operator') ?? '';
    this.applyTheme();
  }

  setTheme(theme: Theme): void {
    this.theme = theme;
    write('rka3000-theme', theme);
    this.applyTheme();
  }

  /** Topbar shortcut: light → dark → blue → light (pins the theme). */
  cycleTheme(): void {
    const order: Theme[] = ['light', 'dark', 'blue'];
    const current = this.effectiveTheme();
    this.setTheme(order[(order.indexOf(current) + 1) % order.length]!);
  }

  effectiveTheme(): Exclude<Theme, 'system'> {
    if (this.theme !== 'system') return this.theme;
    try { return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'; } catch { return 'light'; }
  }

  setOperator(name: string): void {
    this.operator = name.trim().slice(0, 40);
    write('rka3000-operator', this.operator);
  }

  private applyTheme(): void {
    if (typeof document === 'undefined') return;
    if (this.theme === 'system') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = this.theme;
  }
}

export const prefs = new Prefs();
