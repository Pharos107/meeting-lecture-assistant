import {
  clearAuthSession,
  getAccessToken,
  getRefreshToken,
  saveAuthSession,
  type AuthResponse,
} from "@/lib/auth";

export class ApiRequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly fields?: Record<string, string>,
  ) {
    super(message);
  }
}

const REFRESH_LOCK = "stt-auth-refresh";
const REFRESH_EARLY_MS = 60_000;

let refreshing: Promise<boolean> | null = null;
let refreshTimer: ReturnType<typeof setTimeout> | null = null;

function rememberedInLocalStorage() {
  return typeof window !== "undefined" && localStorage.getItem("refresh_token") !== null;
}

function scheduleRefresh(expiresInSeconds: number) {
  if (typeof window === "undefined") return;
  if (refreshTimer) clearTimeout(refreshTimer);
  const wait = Math.max(5_000, expiresInSeconds * 1000 - REFRESH_EARLY_MS);
  refreshTimer = setTimeout(() => void refreshSession(), wait);
}

async function rotateRefreshToken(): Promise<boolean> {
  // Đọc token trong khóa: tab khác có thể vừa xoay token, token cũ dùng lại sẽ bị thu hồi.
  const token = getRefreshToken();
  if (!token) return false;
  let res: Response;
  try {
    res = await fetch("/api/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ refresh_token: token }),
    });
  } catch {
    return false;
  }
  if (!res.ok) {
    if (res.status === 401 && getRefreshToken() === token) clearAuthSession();
    return false;
  }
  const json = (await res.json()) as AuthResponse;
  saveAuthSession({
    accessToken: json.access_token,
    refreshToken: json.refresh_token,
    user: json.user,
    rememberMe: rememberedInLocalStorage(),
  });
  scheduleRefresh(json.expires_in);
  return true;
}

/** Xin access token mới bằng refresh token. Nhiều lời gọi cùng lúc dùng chung một request. */
export function refreshSession(): Promise<boolean> {
  if (refreshing) return refreshing;
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  const run = locks
    ? locks.request(REFRESH_LOCK, rotateRefreshToken).then((done) => done)
    : rotateRefreshToken();
  const shared = run.finally(() => {
    refreshing = null;
  });
  refreshing = shared;
  return shared;
}

/** Bảo đảm có access token trong bộ nhớ, ví dụ sau khi tải lại trang. */
export async function ensureSession(): Promise<boolean> {
  if (getAccessToken()) return true;
  return refreshSession();
}

/** Gọi sau khi đăng nhập hoặc đăng ký để hẹn giờ làm mới token. */
export function startSessionTimer(expiresInSeconds: number) {
  scheduleRefresh(expiresInSeconds);
}

export function redirectToLogin() {
  clearAuthSession();
  if (typeof window !== "undefined") window.location.assign("/login");
}

function withAuth(init: RequestInit = {}): RequestInit {
  const headers = new Headers(init.headers);
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return { ...init, headers };
}

/** fetch kèm Bearer. Gặp 401 thì làm mới token và thử lại đúng một lần. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  await ensureSession();
  let res = await fetch(path, withAuth(init));
  if (res.status !== 401) return res;
  if (!(await refreshSession())) {
    redirectToLogin();
    return res;
  }
  res = await fetch(path, withAuth(init));
  if (res.status === 401) redirectToLogin();
  return res;
}

export async function readError(res: Response): Promise<ApiRequestError> {
  const json = await res.json().catch(() => null);
  const error = json?.error;
  return new ApiRequestError(
    res.status,
    error?.code ?? "server_unavailable",
    error?.message ?? "Không kết nối được máy chủ.",
    error?.fields,
  );
}

export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json; charset=utf-8");
  }
  let res: Response;
  try {
    res = await apiFetch(path, { ...init, headers });
  } catch {
    throw new ApiRequestError(0, "network_error", "Không kết nối được máy chủ.");
  }
  if (!res.ok) throw await readError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function logout() {
  const token = getRefreshToken();
  if (token) {
    await fetch("/api/auth/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ refresh_token: token }),
    }).catch(() => undefined);
  }
  redirectToLogin();
}
