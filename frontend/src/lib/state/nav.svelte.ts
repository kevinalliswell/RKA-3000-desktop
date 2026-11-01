/** In-app navigation: one page at a time, with an optional experiment id (e.g. analysis of #12). */
export type Page =
  | 'overview' | 'preflight' | 'current' | 'recipes' | 'history' | 'alarms' | 'devices' | 'audit' | 'analysis' | 'reports'
  | 'settings';

export interface NavGroup {
  title: string;
  items: { id: Page; label: string; crumb: string }[];
}

export const NAV: NavGroup[] = [
  { title: '工作台', items: [
    { id: 'overview', label: '实时总览', crumb: '工作台 / OVERVIEW' },
    { id: 'preflight', label: '实验准备', crumb: '实验工作流 / PREPARE' },
    { id: 'current', label: '当前实验', crumb: '实验运行 / CURRENT' },
  ] },
  { title: '实验管理', items: [
    { id: 'recipes', label: '实验配方', crumb: '实验管理 / RECIPES' },
    { id: 'history', label: '历史实验', crumb: '实验管理 / HISTORY' },
    { id: 'alarms', label: '报警事件', crumb: '实验管理 / ALARMS' },
  ] },
  { title: '系统与结果', items: [
    { id: 'analysis', label: '分析与归档', crumb: '结果与归档 / ANALYSIS' },
    { id: 'reports', label: '报告中心', crumb: '系统与结果 / REPORTS' },
    { id: 'devices', label: '设备诊断', crumb: '系统与结果 / DEVICES' },
    { id: 'audit', label: '操作审计', crumb: '系统与结果 / AUDIT' },
    { id: 'settings', label: '系统设置', crumb: '系统与结果 / SETTINGS' },
  ] },
];

class Navigator {
  page: Page = $state('overview');
  experimentId: number | null = $state(null);

  go(page: Page, experimentId: number | null = null): void {
    this.page = page;
    this.experimentId = experimentId;
    if (typeof window !== 'undefined') window.scrollTo?.({ top: 0 });
  }

  crumb(): string {
    for (const group of NAV) for (const item of group.items) if (item.id === this.page) return item.crumb;
    return '';
  }
}

export const nav = new Navigator();
