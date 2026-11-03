import { ApiRequestError, apiJson } from "@/lib/api";

export type LiveSource = "mic" | "tab";

export type LiveSessionStart = {
  session_id: string;
  job_id: string;
  ticket: string;
  expires_in: number;
  ws_path: string;
};

type LiveTicket = { ticket: string; expires_in: number; ws_path: string };

export type LiveDraft = {
  type: "draft";
  segment_id: string;
  start_ms: number;
  end_ms: number;
  text: string;
  stable: boolean;
  seq: number;
};

export type LiveMessage =
  | { type: "hello_ok"; session_id: string }
  | LiveDraft
  | { type: "warning"; code: string; message: string }
  | { type: "stopped"; job_id: string }
  | { type: "error"; code: string; message: string };

export function createLiveSession(body: { title: string; vocabulary?: string; num_speakers?: number }) {
  return apiJson<LiveSessionStart>("/api/live/sessions", { method: "POST", body: JSON.stringify(body) });
}

function refreshTicket(sessionId: string) {
  return apiJson<LiveTicket>(`/api/live/sessions/${sessionId}/ticket`, { method: "POST" });
}

function stopSession(sessionId: string) {
  return apiJson<unknown>(`/api/live/sessions/${sessionId}/stop`, { method: "POST" });
}

/** Mở micro hoặc âm thanh tab. Track video của tab giữ lại, không vẽ ra, để trình duyệt không tắt audio. */
export async function openStream(source: LiveSource, deviceId?: string): Promise<MediaStream> {
  if (source === "mic") {
    return navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
      },
      video: false,
    });
  }
  const display = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
  if (display.getAudioTracks().length === 0) {
    display.getTracks().forEach((track) => track.stop());
    throw new ApiRequestError(0, "no_tab_audio", "Chưa bật chia sẻ âm thanh trong hộp thoại chia sẻ.");
  }
  return display;
}

/** Micro trên máy. Tên chỉ có sau khi trang được cấp quyền thu âm. */
export async function listMicrophones(): Promise<{ id: string; label: string }[]> {
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices
    .filter((device) => device.kind === "audioinput" && device.deviceId)
    .map((device, index) => ({ id: device.deviceId, label: device.label || `Micro ${index + 1}` }));
}

/** Tên nguồn đang thu: tên micro, hoặc tiêu đề tab đã chọn. */
export function streamLabel(stream: MediaStream, source: LiveSource) {
  if (source === "tab") return stream.getVideoTracks()[0]?.label || "Tab đã chọn";
  return stream.getAudioTracks()[0]?.label || "Micro";
}

/** Đọc mức âm của một stream, đổi sang 0–1 theo thang -60 dBFS đến 0 dBFS. */
export class LevelProbe {
  private readonly context = new AudioContext();
  private readonly analyser: AnalyserNode;
  private readonly buffer: Float32Array<ArrayBuffer>;

  constructor(stream: MediaStream) {
    this.analyser = this.context.createAnalyser();
    this.analyser.fftSize = 1024;
    this.buffer = new Float32Array(this.analyser.fftSize);
    this.context.createMediaStreamSource(new MediaStream(stream.getAudioTracks())).connect(this.analyser);
  }

  read() {
    this.analyser.getFloatTimeDomainData(this.buffer);
    let sum = 0;
    for (const sample of this.buffer) sum += sample * sample;
    const rms = Math.sqrt(sum / this.buffer.length);
    const db = 20 * Math.log10(Math.max(rms, 1e-6));
    return Math.min(1, Math.max(0, (db + 60) / 60));
  }

  close() {
    void this.context.close().catch(() => undefined);
  }
}

/** Thu âm, hạ mẫu về PCM 16 kHz, và gửi từng khung 100 ms qua callback. */
export class AudioCapture {
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;

  constructor(private readonly onFrame: (frame: ArrayBuffer) => void, private readonly onEnded: () => void) {}

  async start(stream: MediaStream) {
    this.stream = stream;
    this.stream.getAudioTracks()[0]?.addEventListener("ended", () => this.onEnded());
    this.context = new AudioContext();
    await this.context.audioWorklet.addModule("/pcm-worklet.js");
    const input = this.context.createMediaStreamSource(new MediaStream(this.stream.getAudioTracks()));
    this.node = new AudioWorkletNode(this.context, "pcm-frame-processor");
    this.node.port.onmessage = (event: MessageEvent<ArrayBuffer>) => this.onFrame(event.data);
    input.connect(this.node);
  }

  stop() {
    this.node?.port.close();
    this.node?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    void this.context?.close().catch(() => undefined);
    this.node = null;
    this.stream = null;
    this.context = null;
  }
}

const RECONNECT_MS = 1_500;
// Quá 30 giây không có socket thì worker tự dừng phiên, nên thôi nối lại sau mốc này.
const RECONNECT_WINDOW_MS = 25_000;
const MAX_QUEUED_FRAMES = 250;

type LiveSocketHandlers = {
  onMessage: (message: LiveMessage) => void;
  onConnection: (state: "connecting" | "open" | "reconnecting") => void;
  onFatal: (error: { code: string; message: string }) => void;
};

/** WebSocket của phiên nghe: hello, gửi khung PCM, nối lại bằng ticket mới khi rớt dưới 30 giây. */
export class LiveSocket {
  private socket: WebSocket | null = null;
  private queue: ArrayBuffer[] = [];
  private ticket: string;
  private stopping = false;
  private closed = false;
  private lostAt: number | null = null;

  constructor(private readonly start: LiveSessionStart, private readonly handlers: LiveSocketHandlers) {
    this.ticket = start.ticket;
  }

  connect() {
    if (this.closed) return;
    this.handlers.onConnection(this.lostAt == null ? "connecting" : "reconnecting");
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${scheme}://${window.location.host}${this.start.ws_path}?ticket=${encodeURIComponent(this.ticket)}`);
    socket.binaryType = "arraybuffer";
    this.socket = socket;
    socket.onopen = () => socket.send(JSON.stringify({ type: "hello", sample_rate: 16000 }));
    socket.onmessage = (event) => {
      if (typeof event.data !== "string") return;
      const message = JSON.parse(event.data) as LiveMessage;
      if (message.type === "hello_ok") {
        this.lostAt = null;
        this.handlers.onConnection("open");
        this.flush();
      } else if (message.type === "error") {
        this.closed = true;
        this.handlers.onFatal(message);
      } else if (message.type === "stopped") {
        this.closed = true;
      }
      this.handlers.onMessage(message);
    };
    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.socket = null;
      if (this.closed) return;
      this.lostAt ??= Date.now();
      if (Date.now() - this.lostAt > RECONNECT_WINDOW_MS) {
        this.closed = true;
        this.handlers.onFatal({ code: "connection_lost", message: "Mất kết nối quá lâu. Phiên đã chuyển sang xử lý bản chuẩn." });
        return;
      }
      this.handlers.onConnection("reconnecting");
      window.setTimeout(() => void this.reconnect(), RECONNECT_MS);
    };
  }

  private async reconnect() {
    if (this.closed) return;
    try {
      this.ticket = (await refreshTicket(this.start.session_id)).ticket;
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 409) {
        this.closed = true;
        this.handlers.onFatal({ code: "invalid_state", message: "Phiên nghe đã dừng." });
        return;
      }
    }
    this.connect();
  }

  private flush() {
    const socket = this.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN || this.lostAt != null) return;
    for (const frame of this.queue) socket.send(frame);
    this.queue = [];
  }

  send(frame: ArrayBuffer) {
    if (this.closed || this.stopping) return;
    const socket = this.socket;
    if (socket && socket.readyState === WebSocket.OPEN && this.lostAt == null && this.queue.length === 0) {
      socket.send(frame);
      return;
    }
    // Giữ vài giây audio trong lúc nối lại. Rớt lâu hơn thì phần cũ nhất bị bỏ.
    this.queue.push(frame);
    if (this.queue.length > MAX_QUEUED_FRAMES) this.queue.shift();
  }

  /** Gửi stop qua socket nếu còn mở, không thì gọi REST. Server trả `stopped` rồi đóng socket. */
  async stop() {
    this.stopping = true;
    const socket = this.socket;
    if (socket && socket.readyState === WebSocket.OPEN) {
      this.flush();
      socket.send(JSON.stringify({ type: "stop" }));
      return;
    }
    this.closed = true;
    await stopSession(this.start.session_id).catch(() => undefined);
    this.handlers.onMessage({ type: "stopped", job_id: this.start.job_id });
  }

  close() {
    this.closed = true;
    this.socket?.close();
    this.socket = null;
  }
}
