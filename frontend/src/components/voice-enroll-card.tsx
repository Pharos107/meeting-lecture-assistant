"use client";

import { useEffect, useRef, useState } from "react";
import { FileAudio, LoaderCircle, Mic, RotateCcw, Square } from "lucide-react";
import { LevelMeter, useLevelProbe } from "@/components/live-meter";
import { ApiRequestError, createVoiceProfile } from "@/lib/api";
import { formatMs } from "@/lib/format";
import { LevelProbe, openMicrophone } from "@/lib/live-capture";

// Máy chủ nhận mẫu 20 đến 40 giây. Chừa một khoảng vì file thu ra có thể lệch đồng hồ vài trăm mili giây.
const MIN_RECORD_MS = 21_000;
const TARGET_RECORD_MS = 30_000;
const MAX_RECORD_MS = 38_000;
const MAX_FILE_BYTES = 32 * 1024 * 1024;
const ACCEPT = ".mp3,.wav,.m4a,.aac,.ogg,.opus,.flac,.webm,audio/*";

// Đo ồn nền sau khi bộ lọc của trình duyệt đã chạy, tức đúng mức sẽ nằm trong mẫu.
// Bỏ phần đầu vì khử ồn và tự cân âm lượng cần một lúc để bắt nhịp.
const NOISE_WARMUP_MS = 400;
const NOISE_MEASURE_MS = 2_000;
// Cùng mốc "không có tiếng" của đồng hồ mức âm, khoảng -45 dBFS. Điểm xuất phát, cần chỉnh theo số đo.
const NOISY_FLOOR_DB = -45;

const READING =
  "Xin chào, tôi đang thu mẫu giọng để hệ thống nhận ra tôi trong các buổi họp sau. Hôm nay tôi đi làm sớm hơn mọi ngày và ghé quán quen uống một ly cà phê sữa đá. Trong tuần này, nhóm chúng tôi cần hoàn thành báo cáo, rà soát lại kế hoạch, và chuẩn bị nội dung cho buổi trình bày vào thứ sáu. Nếu có câu hỏi, mọi người cứ nhắn cho tôi bất cứ lúc nào.";

type Mode = "mic" | "file";
/** checking: đang đo ồn nền. noisy: đo xong, ồn quá, chờ người dùng chọn. */
type MicPhase = "idle" | "checking" | "noisy" | "recording";
type Recording = { blob: Blob; url: string; filename: string; durationMs: number };
type Errors = { display_name?: string; file?: string; form?: string };

function recorderType(): { mimeType: string; extension: string } | null {
  if (typeof MediaRecorder === "undefined") return null;
  const options = [
    { mimeType: "audio/webm;codecs=opus", extension: "webm" },
    { mimeType: "audio/ogg;codecs=opus", extension: "ogg" },
    { mimeType: "audio/mp4", extension: "m4a" },
  ];
  return options.find((option) => MediaRecorder.isTypeSupported(option.mimeType)) ?? { mimeType: "", extension: "webm" };
}

/** Trung vị mức âm trong lúc người dùng im lặng. Trung vị để một tiếng ho không làm sai kết quả. */
async function measureNoiseFloor(stream: MediaStream, signal: AbortSignal): Promise<number | null> {
  const probe = new LevelProbe(stream);
  try {
    await new Promise((resolve) => setTimeout(resolve, NOISE_WARMUP_MS));
    const levels: number[] = [];
    const until = Date.now() + NOISE_MEASURE_MS;
    while (Date.now() < until) {
      if (signal.aborted) return null;
      levels.push(probe.readDb());
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    levels.sort((a, b) => a - b);
    return levels[Math.floor(levels.length / 2)] ?? null;
  } finally {
    probe.close();
  }
}

function micError(error: unknown) {
  if (error instanceof DOMException && error.name === "NotAllowedError") return "Trình duyệt chưa được cấp quyền dùng micro.";
  if (error instanceof DOMException && error.name === "NotFoundError") return "Không tìm thấy micro trên máy.";
  return "Không mở được micro.";
}

export function VoiceEnrollCard({ disabled, onCreated }: { disabled: boolean; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [mode, setMode] = useState<Mode>("mic");
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [recording, setRecording] = useState<Recording | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [errors, setErrors] = useState<Errors>({});
  const [submitting, setSubmitting] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [phase, setPhase] = useState<MicPhase>("idle");
  const [floorDb, setFloorDb] = useState<number | null>(null);
  const checkAbort = useRef<AbortController | null>(null);
  const probe = useLevelProbe(stream);
  const isRecording = phase === "recording";
  const micOpen = stream !== null;

  // Đóng micro, dừng bước đo, và thu hồi URL nghe thử khi rời trang.
  const streamRef = useRef(stream);
  streamRef.current = stream;
  const urlRef = useRef<string | null>(null);
  urlRef.current = recording?.url ?? null;
  useEffect(
    () => () => {
      checkAbort.current?.abort();
      recorderRef.current?.stop();
      streamRef.current?.getTracks().forEach((track) => track.stop());
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    },
    [],
  );

  useEffect(() => {
    if (!isRecording) return;
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      const elapsed = Date.now() - startedAt;
      setElapsedMs(elapsed);
      if (elapsed >= MAX_RECORD_MS) recorderRef.current?.stop();
    }, 200);
    return () => window.clearInterval(timer);
  }, [isRecording]);

  function clearRecording() {
    if (recording) URL.revokeObjectURL(recording.url);
    setRecording(null);
    setElapsedMs(0);
  }

  /** Mở micro qua cùng bộ lọc với phiên nghe trực tiếp, đo ồn nền, rồi mới thu. */
  async function startRecording() {
    if (!recorderType()) {
      setErrors({ file: "Trình duyệt này không thu âm được. Hãy chọn file ghi sẵn." });
      return;
    }
    clearRecording();
    setErrors({});
    setFloorDb(null);
    let opened: MediaStream;
    try {
      opened = await openMicrophone();
    } catch (error) {
      setErrors({ file: micError(error) });
      return;
    }
    setStream(opened);
    await checkNoise(opened);
  }

  async function checkNoise(opened: MediaStream) {
    setPhase("checking");
    const controller = new AbortController();
    checkAbort.current = controller;
    const floor = await measureNoiseFloor(opened, controller.signal);
    if (controller.signal.aborted || floor === null) return;
    checkAbort.current = null;
    setFloorDb(floor);
    if (floor > NOISY_FLOOR_DB) {
      setPhase("noisy");
      return;
    }
    beginRecorder(opened);
  }

  function closeMic() {
    checkAbort.current?.abort();
    checkAbort.current = null;
    stream?.getTracks().forEach((track) => track.stop());
    setStream(null);
    setPhase("idle");
  }

  function beginRecorder(opened: MediaStream) {
    const type = recorderType() ?? { mimeType: "", extension: "webm" };
    const recorder = new MediaRecorder(opened, type.mimeType ? { mimeType: type.mimeType } : undefined);
    const parts: Blob[] = [];
    const startedAt = Date.now();
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) parts.push(event.data);
    };
    recorder.onstop = () => {
      opened.getTracks().forEach((track) => track.stop());
      recorderRef.current = null;
      setStream(null);
      setPhase("idle");
      const durationMs = Date.now() - startedAt;
      const blob = new Blob(parts, { type: recorder.mimeType || type.mimeType || "audio/webm" });
      setElapsedMs(durationMs);
      setRecording({ blob, url: URL.createObjectURL(blob), filename: `mau-giong.${type.extension}`, durationMs });
      if (durationMs < MIN_RECORD_MS) {
        setErrors({ file: "Bản thu ngắn hơn 20 giây. Hãy thu lại và đọc hết đoạn văn." });
      }
    };
    recorderRef.current = recorder;
    recorder.start(1000);
    setPhase("recording");
  }

  function stopRecording() {
    recorderRef.current?.stop();
  }

  function pickFile(next: File | null) {
    setErrors({});
    if (next && next.size > MAX_FILE_BYTES) {
      setFile(null);
      setErrors({ file: "File lớn hơn 32 MB. Mẫu giọng chỉ cần 20 đến 40 giây." });
      return;
    }
    setFile(next);
  }

  const sample = mode === "mic" ? recording : file ? { blob: file, filename: file.name } : null;
  const shortRecording = mode === "mic" && recording !== null && recording.durationMs < MIN_RECORD_MS;
  const canSubmit = !disabled && !submitting && !micOpen && sample !== null && !shortRecording && name.trim() !== "";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    const nextErrors: Errors = {};
    if (!trimmed || trimmed.length > 80) nextErrors.display_name = "Tên hiển thị phải từ 1 đến 80 ký tự.";
    if (!sample) nextErrors.file = mode === "mic" ? "Hãy thu mẫu giọng trước." : "Vui lòng chọn file.";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0 || !sample) return;
    setSubmitting(true);
    try {
      await createVoiceProfile(trimmed, sample.blob, sample.filename);
      setName("");
      clearRecording();
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      onCreated();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        const fields = error.fields ?? {};
        setErrors({
          display_name: fields.display_name,
          file: fields.file,
          form: fields.display_name || fields.file ? undefined : error.message,
        });
      } else {
        setErrors({ form: "Không lưu được hồ sơ giọng." });
      }
    } finally {
      setSubmitting(false);
    }
  }

  const progress = Math.min(1, elapsedMs / MAX_RECORD_MS);

  return (
    <form onSubmit={submit} className="rounded-3xl bg-white p-5 ring-1 ring-sky-100">
      <h2 className="text-base font-semibold text-[#0f2744]">Thêm hồ sơ</h2>
      <p className="mt-1 text-sm text-slate-500">Một người, nói khoảng 30 giây ở nơi yên tĩnh.</p>

      <label className="mt-4 block text-sm font-medium text-slate-700" htmlFor="voice-name">
        Tên hiển thị
      </label>
      <input
        id="voice-name"
        value={name}
        maxLength={80}
        onChange={(event) => setName(event.target.value)}
        placeholder="Ví dụ: Lê Hải Đăng"
        aria-invalid={errors.display_name ? true : undefined}
        className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 px-3 text-sm outline-none focus:border-blue-400 focus:ring-3 focus:ring-blue-100 aria-invalid:border-rose-400"
      />
      {errors.display_name ? <p className="mt-1 text-xs text-rose-600">{errors.display_name}</p> : null}

      <div className="mt-4 grid grid-cols-2 gap-1 rounded-full bg-slate-100 p-1 text-sm" role="tablist" aria-label="Cách lấy mẫu">
        {(
          [
            ["mic", "Thu bằng micro", Mic],
            ["file", "Chọn file", FileAudio],
          ] as const
        ).map(([value, label, Icon]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={mode === value}
            disabled={micOpen}
            onClick={() => {
              setMode(value);
              setErrors({});
            }}
            className={`inline-flex items-center justify-center gap-1.5 rounded-full px-3 py-1.5 font-medium transition-colors disabled:opacity-60 ${
              mode === value ? "bg-white text-blue-700 shadow-sm" : "text-slate-600 hover:text-slate-900"
            }`}
          >
            <Icon className="size-4" />
            {label}
          </button>
        ))}
      </div>

      {mode === "mic" ? (
        <div className="mt-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Đọc to đoạn sau</p>
          <p className="mt-1.5 rounded-2xl bg-sky-50/70 px-4 py-3 text-sm leading-6 text-slate-700">{READING}</p>

          <div className="mt-4 flex items-center gap-3">
            {isRecording ? (
              <button
                type="button"
                onClick={stopRecording}
                className="inline-flex h-10 items-center gap-2 rounded-full bg-rose-600 px-4 text-sm font-semibold text-white hover:bg-rose-700"
              >
                <Square className="size-3.5 fill-current" />
                Dừng
              </button>
            ) : phase === "checking" ? (
              <>
                <span className="inline-flex h-10 items-center gap-2 rounded-full bg-sky-50 px-4 text-sm font-medium text-blue-700">
                  <LoaderCircle className="size-4 animate-spin" />
                  Giữ yên lặng…
                </span>
                <button type="button" onClick={closeMic} className="h-10 rounded-full px-3 text-sm text-slate-600 hover:bg-slate-100">
                  Hủy
                </button>
              </>
            ) : phase === "noisy" ? null : (
              <button
                type="button"
                onClick={() => void startRecording()}
                disabled={disabled || submitting}
                className="inline-flex h-10 items-center gap-2 rounded-full bg-gradient-to-r from-blue-500 to-blue-600 px-4 text-sm font-semibold text-white shadow-lg shadow-blue-500/25 disabled:opacity-60"
              >
                {recording ? <RotateCcw className="size-4" /> : <Mic className="size-4" />}
                {recording ? "Thu lại" : "Bắt đầu thu"}
              </button>
            )}
            <span className="ml-auto text-2xl font-light tabular-nums text-[#0f2744]" aria-label="Thời gian đã thu">
              {formatMs(elapsedMs)}
            </span>
          </div>

          {phase === "checking" ? (
            <p className="mt-2 text-xs text-slate-500" aria-live="polite">
              Đang đo tiếng ồn nền. Đừng nói trong khoảng 2 giây, trang sẽ tự bắt đầu thu.
            </p>
          ) : null}
          {phase === "noisy" && floorDb !== null ? (
            <div className="mt-3 rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-900" role="alert">
              <p>
                Tiếng ồn nền khoảng <span className="font-semibold tabular-nums">{Math.round(floorDb)} dBFS</span>, to hơn mức nên
                thu ({NOISY_FLOOR_DB} dBFS). Mẫu thu ở chỗ ồn làm hệ thống khó nhận ra giọng trong buổi họp. Hãy tắt quạt, đóng cửa,
                hoặc ngồi gần micro hơn rồi đo lại.
              </p>
              <div className="mt-2.5 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => stream && void checkNoise(stream)}
                  className="h-8 rounded-full bg-amber-600 px-3 text-xs font-semibold text-white hover:bg-amber-700"
                >
                  Đo lại
                </button>
                <button
                  type="button"
                  onClick={() => stream && beginRecorder(stream)}
                  className="h-8 rounded-full border border-amber-300 bg-white px-3 text-xs font-medium text-amber-900 hover:border-amber-400"
                >
                  Vẫn thu
                </button>
                <button type="button" onClick={closeMic} className="h-8 rounded-full px-3 text-xs text-amber-900 hover:bg-amber-100">
                  Hủy
                </button>
              </div>
            </div>
          ) : null}

          <div className="relative mt-3 h-2 rounded-full bg-slate-100" aria-hidden="true">
            <div
              className={`h-full rounded-full transition-[width] duration-200 ${
                elapsedMs >= MIN_RECORD_MS ? "bg-emerald-500" : "bg-blue-500"
              }`}
              style={{ width: `${progress * 100}%` }}
            />
            <span className="absolute top-[-3px] h-3.5 w-px bg-slate-400" style={{ left: `${(MIN_RECORD_MS / MAX_RECORD_MS) * 100}%` }} />
            <span className="absolute top-[-3px] h-3.5 w-px bg-emerald-600" style={{ left: `${(TARGET_RECORD_MS / MAX_RECORD_MS) * 100}%` }} />
          </div>
          <div className="mt-1 flex justify-between text-[11px] text-slate-400">
            <span>0:00</span>
            <span>tối thiểu 0:21 · nên 0:30 · tự dừng {formatMs(MAX_RECORD_MS)}</span>
          </div>

          {micOpen ? (
            <div className="mt-3">
              <LevelMeter probe={probe} />
            </div>
          ) : null}
          {recording && !micOpen ? <audio src={recording.url} controls className="mt-3 h-9 w-full" /> : null}
          {floorDb !== null && phase !== "noisy" && phase !== "checking" ? (
            <p className={`mt-2 text-xs ${floorDb > NOISY_FLOOR_DB ? "text-amber-800" : "text-slate-500"}`}>
              Ồn nền lúc thu: <span className="tabular-nums">{Math.round(floorDb)} dBFS</span>
              {floorDb > NOISY_FLOOR_DB ? ", hơi ồn" : ", đủ yên tĩnh"}. Trình duyệt đã bật khử ồn và khử vọng, giống khi ghi trực tiếp.
            </p>
          ) : null}
        </div>
      ) : (
        <div className="mt-4">
          <input
            ref={fileInput}
            type="file"
            accept={ACCEPT}
            onChange={(event) => pickFile(event.target.files?.[0] ?? null)}
            className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-full file:border-0 file:bg-sky-50 file:px-4 file:py-2 file:text-sm file:font-medium file:text-blue-700 hover:file:bg-sky-100"
          />
          <p className="mt-2 text-xs text-slate-500">File ghi một người nói, dài 20 đến 40 giây, còn ít nhất 15 giây có tiếng.</p>
        </div>
      )}

      {errors.file ? <p className="mt-2 text-xs text-rose-600">{errors.file}</p> : null}
      {errors.form ? <p className="mt-3 rounded-2xl bg-rose-50 px-3 py-2 text-sm text-rose-700">{errors.form}</p> : null}
      {disabled ? (
        <p className="mt-3 rounded-2xl bg-amber-50 px-3 py-2 text-sm text-amber-800">Đã đủ 20 hồ sơ. Xóa bớt một hồ sơ để thêm mới.</p>
      ) : null}

      <button
        type="submit"
        disabled={!canSubmit}
        className="mt-5 inline-flex h-10 w-full items-center justify-center gap-2 rounded-full bg-[#0f2744] text-sm font-semibold text-white hover:bg-[#173a63] disabled:opacity-50"
      >
        {submitting ? <LoaderCircle className="size-4 animate-spin" /> : null}
        Lưu hồ sơ
      </button>
    </form>
  );
}
