"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { LoaderCircle, Mic, MonitorUp, RefreshCw } from "lucide-react";
import { LiveConsole } from "@/components/live-console";
import { LevelMeter, useLevelProbe } from "@/components/live-meter";
import { ApiRequestError } from "@/lib/api";
import {
  AudioCapture,
  LiveSocket,
  createLiveSession,
  listMicrophones,
  openStream,
  streamLabel,
  type LiveDraft,
  type LiveSource,
} from "@/lib/live-capture";

type Phase = "setup" | "starting" | "live" | "stopping";
type Connection = "connecting" | "open" | "reconnecting";
type Preview = { stream: MediaStream; source: LiveSource; label: string };

const MAX_VOCAB = 800;
const CONFIRM_STOP_MS = 4000;
const FIELD_BASE =
  "mt-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-800 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20";
const FIELD = `${FIELD_BASE} w-full`;

function defaultTitle() {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `Ghi trực tiếp ${pad(now.getHours())}:${pad(now.getMinutes())} ngày ${pad(now.getDate())}/${pad(now.getMonth() + 1)}`;
}

function sourceError(error: unknown, source: LiveSource): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof DOMException && error.name === "NotAllowedError") {
    return source === "mic" ? "Trình duyệt đang chặn micro. Cho phép micro ở biểu tượng ổ khóa trên thanh địa chỉ." : "Đã hủy chọn tab.";
  }
  if (error instanceof DOMException && error.name === "NotFoundError") return "Không tìm thấy micro nào trên máy.";
  return source === "mic" ? "Không mở được micro." : "Không thu được âm thanh của tab.";
}

export default function LivePage() {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("setup");
  const [source, setSource] = useState<LiveSource>("mic");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [opening, setOpening] = useState(false);
  const [microphones, setMicrophones] = useState<{ id: string; label: string }[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const [title, setTitle] = useState(defaultTitle);
  const [vocabulary, setVocabulary] = useState("");
  const [speakers, setSpeakers] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sourceProblem, setSourceProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [drafts, setDrafts] = useState<Map<string, LiveDraft>>(new Map());
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [confirmStop, setConfirmStop] = useState(false);
  const socketRef = useRef<LiveSocket | null>(null);
  const captureRef = useRef<AudioCapture | null>(null);
  const previewRef = useRef<Preview | null>(null);
  const jobRef = useRef<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const probe = useLevelProbe(preview?.stream ?? null);

  const speakersValue = speakers.trim() ? Number(speakers) : undefined;
  const speakersInvalid = speakersValue !== undefined && (!Number.isInteger(speakersValue) || speakersValue < 1 || speakersValue > 20);

  const dropPreview = useCallback(() => {
    previewRef.current?.stream.getTracks().forEach((track) => track.stop());
    previewRef.current = null;
    setPreview(null);
  }, []);

  const teardown = useCallback(() => {
    captureRef.current?.stop();
    captureRef.current = null;
    socketRef.current?.close();
    socketRef.current = null;
  }, []);

  useEffect(
    () => () => {
      teardown();
      previewRef.current?.stream.getTracks().forEach((track) => track.stop());
    },
    [teardown],
  );

  useEffect(() => {
    if (phase !== "live" && phase !== "stopping") return;
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("beforeunload", warn);
    };
  }, [phase]);

  useEffect(() => {
    if (!confirmStop) return;
    const timer = window.setTimeout(() => setConfirmStop(false), CONFIRM_STOP_MS);
    return () => window.clearTimeout(timer);
  }, [confirmStop]);

  async function openSource(next: LiveSource, device?: string) {
    setSourceProblem(null);
    setOpening(true);
    dropPreview();
    try {
      const stream = await openStream(next, device);
      const opened = { stream, source: next, label: streamLabel(stream, next) };
      stream.getAudioTracks()[0]?.addEventListener("ended", () => {
        if (previewRef.current?.stream !== stream || captureRef.current) return;
        previewRef.current = null;
        setPreview(null);
        setSourceProblem(next === "tab" ? "Tab đã ngừng chia sẻ. Chọn lại tab cần thu." : "Micro đã ngắt. Bật lại micro.");
      });
      previewRef.current = opened;
      setPreview(opened);
      if (next === "mic") {
        setMicrophones(await listMicrophones());
        setDeviceId(stream.getAudioTracks()[0]?.getSettings().deviceId ?? "");
      }
    } catch (failure) {
      setSourceProblem(sourceError(failure, next));
    } finally {
      setOpening(false);
    }
  }

  function chooseSource(next: LiveSource) {
    if (next === source) return;
    dropPreview();
    setSourceProblem(null);
    setSource(next);
  }

  const stop = useCallback(async () => {
    const socket = socketRef.current;
    if (!socket) return;
    setConfirmStop(false);
    setPhase("stopping");
    captureRef.current?.stop();
    captureRef.current = null;
    await socket.stop();
  }, []);

  async function start() {
    const current = previewRef.current;
    if (!current) return;
    setError(null);
    setNotice(null);
    setPhase("starting");
    try {
      const session = await createLiveSession({
        title: title.trim(),
        vocabulary: vocabulary.trim() || undefined,
        num_speakers: speakersValue,
      });
      jobRef.current = session.job_id;
      setJobId(session.job_id);
      const socket = new LiveSocket(session, {
        onConnection: setConnection,
        onMessage: (message) => {
          if (message.type === "draft") {
            setDrafts((previous) => {
              const next = new Map(previous);
              if (message.stable && !message.text) next.delete(message.segment_id);
              else next.set(message.segment_id, message);
              return next;
            });
          } else if (message.type === "warning") {
            setNotice(message.message);
          } else if (message.type === "stopped") {
            teardown();
            router.push(`/jobs/${message.job_id}`);
          }
        },
        onFatal: (failure) => {
          teardown();
          if (jobRef.current && (failure.code === "connection_lost" || failure.code === "invalid_state")) {
            router.push(`/jobs/${jobRef.current}`);
            return;
          }
          dropPreview();
          setError(failure.message);
          setPhase("setup");
        },
      });
      socketRef.current = socket;
      socket.connect();
      const capture = new AudioCapture(
        (frame) => socket.send(frame),
        () => void stop(),
      );
      captureRef.current = capture;
      await capture.start(current.stream);
      setDrafts(new Map());
      setStartedAt(Date.now());
      setNow(Date.now());
      setPhase("live");
    } catch (failure) {
      if (socketRef.current) await socketRef.current.stop();
      teardown();
      dropPreview();
      setError(failure instanceof ApiRequestError ? failure.message : "Không bắt đầu được phiên ghi.");
      setPhase("setup");
    }
  }

  const ordered = [...drafts.values()].sort((a, b) => a.start_ms - b.start_ms);

  if ((phase === "live" || phase === "stopping") && jobId) {
    const sourceLabel =
      preview?.source === "tab"
        ? `Âm thanh tab: ${preview.label}`
        : `Micro: ${microphones.find((device) => device.id === deviceId)?.label ?? preview?.label ?? ""}`;
    return (
      <LiveConsole
        jobId={jobId}
        title={title}
        sourceLabel={sourceLabel}
        probe={probe}
        startedAt={startedAt}
        now={now}
        drafts={ordered}
        connected={connection === "open"}
        stopping={phase === "stopping"}
        degraded={notice}
        confirmStop={confirmStop}
        onStop={() => (confirmStop ? void stop() : setConfirmStop(true))}
      />
    );
  }

  const canStart = Boolean(preview) && Boolean(title.trim()) && !speakersInvalid && phase === "setup";

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 lg:py-10">
      <h1 className="text-2xl font-bold tracking-tight text-[#0f2744]">Ghi trực tiếp</h1>
      <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600">
        Chữ nháp hiện ngay trong lúc nói. Khi dừng, hệ thống nhận dạng lại cả bản thu, gán người nói, rồi thay bản nháp bằng bản chuẩn.
      </p>

      <form
        className="mt-6 grid overflow-hidden rounded-2xl border border-sky-100 bg-white lg:grid-cols-[minmax(0,1fr)_22rem]"
        onSubmit={(event) => {
          event.preventDefault();
          if (canStart) void start();
        }}
      >
        <section className="p-5 sm:p-6">
          <h2 className="text-sm font-semibold text-[#0f2744]">Nguồn âm thanh</h2>
          <div role="radiogroup" aria-label="Nguồn âm thanh" className="mt-3 inline-flex rounded-xl bg-slate-100 p-1">
            {(
              [
                ["mic", "Micro", Mic],
                ["tab", "Âm thanh tab", MonitorUp],
              ] as const
            ).map(([value, label, Icon]) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={source === value}
                onClick={() => chooseSource(value)}
                className={`inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium ${
                  source === value ? "bg-white text-[#0f2744] shadow-sm" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                <Icon className="size-4" />
                {label}
              </button>
            ))}
          </div>

          <div className="mt-5 rounded-xl border border-slate-200 p-4">
            {preview ? (
              <>
                {source === "mic" ? (
                  <label className="block text-xs font-medium text-slate-600" htmlFor="device">
                    Micro đang dùng
                    <select
                      id="device"
                      value={deviceId}
                      onChange={(event) => {
                        setDeviceId(event.target.value);
                        void openSource("mic", event.target.value);
                      }}
                      className={FIELD}
                    >
                      {microphones.map((device) => (
                        <option key={device.id} value={device.id}>
                          {device.label}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <div className="flex items-center gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-medium text-slate-600">Tab đang chia sẻ</p>
                      <p className="mt-0.5 truncate text-sm text-slate-800">{preview.label}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void openSource("tab")}
                      className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                    >
                      <RefreshCw className="size-3.5" />
                      Đổi tab
                    </button>
                  </div>
                )}
                <div className="mt-4">
                  <LevelMeter probe={probe} />
                </div>
              </>
            ) : (
              <div>
                <p className="text-sm leading-6 text-slate-600">
                  {source === "mic"
                    ? "Bật micro để kiểm tra tiếng trước khi ghi."
                    : "Chọn tab đang phát, ví dụ một video hoặc cuộc họp trực tuyến, rồi bật Chia sẻ âm thanh trong hộp thoại."}
                </p>
                <button
                  type="button"
                  disabled={opening}
                  onClick={() => void openSource(source)}
                  className="mt-3 inline-flex items-center gap-2 rounded-full bg-[#0f2744] px-4 py-2 text-sm font-medium text-white hover:bg-[#1b3a60] disabled:opacity-60"
                >
                  {opening ? <LoaderCircle className="size-4 animate-spin" /> : source === "mic" ? <Mic className="size-4" /> : <MonitorUp className="size-4" />}
                  {source === "mic" ? "Bật micro" : "Chọn tab"}
                </button>
                {sourceProblem ? <p className="mt-3 text-sm text-rose-700">{sourceProblem}</p> : null}
              </div>
            )}
          </div>

          <p className="mt-3 text-xs leading-5 text-slate-500">
            {source === "mic"
              ? "Muốn thu video đang phát trên máy này thì chọn Âm thanh tab. Micro lọc tiếng vọng nên có thể bỏ mất tiếng phát từ chính trình duyệt."
              : "Chỉ Chrome và Edge chia sẻ được âm thanh tab. Hình của tab không gửi lên máy chủ."}
          </p>
        </section>

        <section className="border-t border-sky-100 bg-slate-50/60 p-5 sm:p-6 lg:border-l lg:border-t-0">
          <h2 className="text-sm font-semibold text-[#0f2744]">Thông tin bản ghi</h2>
          <label className="mt-3 block text-xs font-medium text-slate-600" htmlFor="title">
            Tiêu đề
            <input id="title" value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} className={FIELD} />
          </label>
          <label className="mt-4 block text-xs font-medium text-slate-600" htmlFor="vocabulary">
            Thuật ngữ, tên riêng
            <textarea
              id="vocabulary"
              value={vocabulary}
              maxLength={MAX_VOCAB}
              rows={3}
              placeholder="Ví dụ: Sprint, KPI, anh Hưng phòng kế toán"
              onChange={(event) => setVocabulary(event.target.value)}
              className={`${FIELD} resize-none`}
            />
            <span className="mt-1 block text-right text-[11px] font-normal tabular-nums text-slate-400">
              {vocabulary.length}/{MAX_VOCAB}
            </span>
          </label>
          <label className="mt-1 block text-xs font-medium text-slate-600" htmlFor="num_speakers">
            Số người nói, nếu biết trước
            <input
              id="num_speakers"
              inputMode="numeric"
              value={speakers}
              placeholder="Tự nhận"
              onChange={(event) => setSpeakers(event.target.value)}
              className={`${FIELD_BASE} block w-28`}
            />
          </label>
          {speakersInvalid ? <p className="mt-1 text-xs text-rose-600">Số người nói phải từ 1 đến 20.</p> : null}

          {error ? <p className="mt-4 rounded-xl bg-rose-50 px-3.5 py-2.5 text-sm text-rose-700">{error}</p> : null}

          <button
            type="submit"
            disabled={!canStart}
            className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-full bg-rose-600 px-5 py-3 text-sm font-semibold text-white hover:bg-rose-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {phase === "starting" ? <LoaderCircle className="size-4 animate-spin" /> : <span className="size-2.5 rounded-full bg-white" />}
            {phase === "starting" ? "Đang kết nối" : "Bắt đầu ghi"}
          </button>
          {!preview ? <p className="mt-2 text-center text-xs text-slate-500">Mở nguồn âm thanh trước khi ghi.</p> : null}
        </section>
      </form>
    </div>
  );
}
