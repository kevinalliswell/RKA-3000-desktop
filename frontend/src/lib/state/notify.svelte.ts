export type Tone = 'ok' | 'warn' | 'danger' | 'info';

export interface Toast {
  id: number;
  tone: Tone;
  title: string;
  text?: string;
}

let nextId = 1;

/** Transient user feedback. Technical detail belongs in the diagnostics area, not here. */
export class Notifier {
  toasts: Toast[] = $state([]);

  push(tone: Tone, title: string, text?: string, ttlMs = 6000): void {
    const toast = { id: nextId++, tone, title, text };
    this.toasts = [...this.toasts, toast];
    if (ttlMs > 0) setTimeout(() => this.dismiss(toast.id), ttlMs);
  }

  dismiss(id: number): void {
    this.toasts = this.toasts.filter((toast) => toast.id !== id);
  }
}

export const notifier = new Notifier();
