/** Business rule data served by Python (/api/rules); pages read it instead of hard-coding rules. */
import * as api from '../api/endpoints';
import type { Rules } from '../api/types';

class RulesStore {
  value: Rules | null = $state(null);
  private loading: Promise<Rules | null> | null = null;

  load(): Promise<Rules | null> {
    if (this.value) return Promise.resolve(this.value);
    this.loading ??= api.rules().then((rules) => (this.value = rules)).catch(() => {
      this.loading = null;
      return null;
    });
    return this.loading;
  }

  /** Gases an experiment of this type may use besides its inert gas (empty until loaded). */
  processGases(type: 'reduction' | 'oxidation'): string[] {
    return this.value?.process_gases[type] ?? [];
  }
}

export const rules = new RulesStore();
