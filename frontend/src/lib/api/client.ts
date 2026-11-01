import type { ApiErrorBody } from './types';

export class ApiError extends Error {
  code: string;
  detail: unknown;
  constructor(body: ApiErrorBody) {
    super(body.message);
    this.name = 'ApiError';
    this.code = body.code;
    this.detail = body.detail;
  }
  /** The backend process is gone or never started; retrying will not help. */
  get fatal(): boolean {
    return this.code === 'backend_exited' || this.code === 'backend_unavailable';
  }
  get transient(): boolean {
    return this.code === 'unreachable' || this.code === 'bad_response' || this.code === 'network';
  }
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

let tauriInvoke: ((cmd: string, args?: Record<string, unknown>) => Promise<unknown>) | null | undefined;

async function resolveInvoke() {
  if (tauriInvoke !== undefined) return tauriInvoke;
  try {
    const core = await import('@tauri-apps/api/core');
    tauriInvoke = core.isTauri() ? core.invoke : null;
  } catch {
    tauriInvoke = null;
  }
  return tauriInvoke;
}

function parseError(raw: unknown): ApiError {
  if (raw instanceof ApiError) return raw;
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw) as Partial<ApiErrorBody>;
      if (parsed && typeof parsed.message === 'string') {
        return new ApiError({ code: parsed.code ?? 'error', message: parsed.message, detail: parsed.detail });
      }
    } catch {
      /* not JSON */
    }
    return new ApiError({ code: 'error', message: raw });
  }
  if (raw instanceof Error) return new ApiError({ code: 'network', message: raw.message });
  return new ApiError({ code: 'error', message: String(raw) });
}

/** Single transport for every page: Tauri IPC in the desktop, same-origin proxy in the browser. */
export async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const invoke = await resolveInvoke();
  if (invoke) {
    try {
      return (await invoke('api_request', { method, path, body: body ?? null })) as T;
    } catch (error) {
      throw parseError(error);
    }
  }
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(20000),
    });
  } catch (error) {
    throw new ApiError({ code: 'unreachable', message: `本地业务服务不可用: ${(error as Error).message}` });
  }
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as T & { error?: ApiErrorBody }) : ({} as T & { error?: ApiErrorBody });
  if (!response.ok) {
    throw new ApiError(payload.error ?? { code: 'http_error', message: `请求失败（${response.status}）` });
  }
  return payload;
}

export interface BackendStatus {
  available: boolean;
  exited: boolean;
  exit_code: number | null;
  error: string | null;
}

/** Desktop-only process status; in the browser the backend is assumed external. */
export async function backendStatus(): Promise<BackendStatus | null> {
  const invoke = await resolveInvoke();
  if (!invoke) return null;
  try {
    return (await invoke('backend_status')) as BackendStatus;
  } catch {
    return null;
  }
}

export async function revealExport(path: string): Promise<boolean> {
  const invoke = await resolveInvoke();
  if (!invoke) return false;
  await invoke('reveal_export', { path });
  return true;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
