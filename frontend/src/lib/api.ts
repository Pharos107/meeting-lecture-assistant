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
// Tăng mỗi khi phiên bị xóa. Lượt làm mới bắt đầu từ phiên cũ thì bỏ kết quả của nó.
let sessionGeneration = 0;

function endSession() {
  sessionGeneration += 1;
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = null;
  clearAuthSession();
}

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
  const generation = sessionGeneration;
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
  if (generation !== sessionGeneration) return false;
  if (!res.ok) {
    if (res.status === 401 && getRefreshToken() === token) endSession();
    return false;
  }
  const json = (await res.json()) as AuthResponse;
  // Đăng xuất xảy ra trong lúc chờ thì không ghi lại phiên vừa xóa.
  if (generation !== sessionGeneration) return false;
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
  endSession();
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

async function revokeSession() {
  const token = getRefreshToken();
  endSession();
  if (!token) return;
  await fetch("/api/auth/logout", {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify({ refresh_token: token }),
  }).catch(() => undefined);
}

/** Thu hồi refresh token hiện tại. Chạy trong cùng khóa với lượt làm mới để không thu hồi nhầm token cũ. */
export async function logout() {
  await refreshing?.catch(() => false);
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  if (locks) await locks.request(REFRESH_LOCK, revokeSession);
  else await revokeSession();
  if (typeof window !== "undefined") window.location.assign("/login");
}

// ----- Kiểu dữ liệu của API job -----

export type JobStatus =
  | "queued"
  | "capturing"
  | "preprocessing"
  | "transcribing"
  | "diarizing"
  | "ready"
  | "failed"
  | "cancelled";

export type JobWarning = { code: string; message: string };

export type JobSummary = {
  id: string;
  title: string;
  source: "upload" | "live";
  status: JobStatus;
  duration_ms: number | null;
  warnings: JobWarning[];
  created_at: string;
};

export type JobDetail = JobSummary & {
  error_code: string | null;
  error_message: string | null;
  vocabulary: string | null;
  num_speakers: number | null;
  diarization_device: "cuda" | "cpu" | null;
  started_at: string | null;
  finished_at: string | null;
};

export type ApiWord = { text: string; start_ms: number; end_ms: number; speaker_label?: string | null };

export type ApiSegment = {
  id: string;
  position?: number;
  start_ms: number;
  end_ms: number;
  text_raw: string;
  text_cleaned?: string | null;
  text_edited?: string | null;
  speaker_label?: string | null;
  speaker_name?: string | null;
  words: ApiWord[];
};

export type ApiSpeaker = { label: string; display_name: string; source: "manual" | "voice_profile" | null };

export type Transcript = { pass: number | null; segments: ApiSegment[]; speakers: ApiSpeaker[] };

export type JobEvent =
  | { type: "stage"; seq: number; stage: string; detail: string }
  | {
      type: "chunk";
      seq: number;
      chunk_index: number;
      chunk_count: number;
      processing_time_ms: number;
      expected_next_chunk_ms: number;
      segments: ApiSegment[];
    }
  | { type: "speakers"; seq: number }
  | { type: "warning"; seq: number; code: string; message: string }
  | { type: "done"; seq: number }
  | { type: "error"; seq: number; code: string; message: string };

export const ACTIVE_STATUSES: JobStatus[] = ["queued", "capturing", "preprocessing", "transcribing", "diarizing"];

export const STATUS_LABELS: Record<JobStatus, string> = {
  queued: "Đang chờ",
  capturing: "Đang thu",
  preprocessing: "Chuẩn hóa âm thanh",
  transcribing: "Đang nhận dạng",
  diarizing: "Gán người nói",
  ready: "Sẵn sàng",
  failed: "Lỗi",
  cancelled: "Đã hủy",
};

// ----- Tải file lên. Dùng XHR để có tiến độ gửi, fetch chưa báo được phần này -----

function sendUpload(form: FormData, onProgress: (ratio: number) => void, signal?: AbortSignal) {
  return new Promise<{ status: number; body: string }>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/jobs");
    const token = getAccessToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => resolve({ status: xhr.status, body: xhr.responseText });
    xhr.onerror = () => reject(new ApiRequestError(0, "network_error", "Mất kết nối khi tải file lên."));
    xhr.onabort = () => reject(new ApiRequestError(0, "aborted", "Đã hủy tải lên."));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(form);
  });
}

function uploadError(status: number, body: string): ApiRequestError {
  try {
    const error = JSON.parse(body)?.error;
    if (error) return new ApiRequestError(status, error.code, error.message, error.fields);
  } catch {
    // Thân lỗi không phải JSON, ví dụ trang lỗi của proxy.
  }
  return new ApiRequestError(status, "server_unavailable", "Không kết nối được máy chủ.");
}

export async function uploadJob(
  form: FormData,
  onProgress: (ratio: number) => void,
  signal?: AbortSignal,
): Promise<{ job_id: string; status: JobStatus }> {
  await ensureSession();
  let res = await sendUpload(form, onProgress, signal);
  if (res.status === 401) {
    if (!(await refreshSession())) {
      redirectToLogin();
      throw uploadError(res.status, res.body);
    }
    res = await sendUpload(form, onProgress, signal);
  }
  if (res.status < 200 || res.status >= 300) throw uploadError(res.status, res.body);
  return JSON.parse(res.body);
}

// ----- SSE qua fetch, vì EventSource không gắn được header Authorization -----

type StreamOptions = {
  afterSeq: number;
  signal: AbortSignal;
  onEvent: (event: JobEvent) => void;
};

/** Đọc SSE của job đến khi server đóng stream. Trả seq cuối đã nhận để nối lại. */
export async function streamJobEvents(jobId: string, { afterSeq, signal, onEvent }: StreamOptions): Promise<number> {
  let lastSeq = afterSeq;
  const res = await apiFetch(`/api/jobs/${encodeURIComponent(jobId)}/events?after_seq=${afterSeq}`, {
    headers: { Accept: "text/event-stream" },
    signal,
  });
  if (!res.ok || !res.body) throw await readError(res);

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
      const parsed = parseFrame(frame);
      if (!parsed) continue;
      if (parsed.seq <= lastSeq) continue;
      lastSeq = parsed.seq;
      onEvent(parsed);
    }
  }
  return lastSeq;
}

function parseFrame(frame: string): JobEvent | null {
  let type = "message";
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon < 0 ? line : line.slice(0, colon);
    const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") type = value;
    else if (field === "data") data.push(value);
  }
  if (data.length === 0) return null;
  try {
    const payload = JSON.parse(data.join("\n"));
    if (typeof payload?.seq !== "number") return null;
    return { ...payload, type } as JobEvent;
  } catch {
    return null;
  }
}
