"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, RotateCcw, Square, Trash2 } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { JobStatusBadge } from "@/components/job-status-badge";
import { MinutesView, stampToMs, type LectureNotes, type MeetingMinutes } from "@/components/minutes-view";
import { TaskDialog, type TaskDraft } from "@/components/task-dialog";
import { TranscriptLayout, type TranscriptSelection } from "@/components/transcript-layout";
import type { ExportFormat, MinutesTemplate, Segment, Speaker, TranscriptMode } from "@/components/types";
import {
  ACTIVE_STATUSES,
  apiFetch,
  apiJson,
  ApiRequestError,
  readError,
  STATUS_LABELS,
  streamJobEvents,
  type ApiSegment,
  type JobDetail,
  type JobEvent,
  type JobStatus,
  type Transcript,
} from "@/lib/api";
import { formatMs } from "@/lib/format";
import { AdaptiveTypewriter } from "@/lib/typewriter-queue";

type Highlight = { id: string; segment_id: string; quote: string; start_ms: number; end_ms: number };
type ActionItem = {
  id: string;
  segment_id: string | null;
  start_ms: number;
  owner: string;
  task: string;
  deadline: string;
  source: string;
};
type LlmRun = {
  run_id: string;
  task: "clean" | "summarize";
  status: "running" | "done" | "failed";
  template?: MinutesTemplate | null;
  result?: MeetingMinutes | LectureNotes | null;
  error_code?: string;
  error_message?: string;
};
type Selected = TranscriptSelection & { startMs: number; endMs: number };
type Progress = { stage: string; chunkIndex: number; chunkCount: number } | null;

const CANCELLABLE: JobStatus[] = ["queued", "capturing", "preprocessing", "transcribing"];
const LLM_POLL_MS = 2_000;
// id trên URL đi thẳng vào đường dẫn API, nên chỉ nhận đúng dạng UUID mà server cấp.
const JOB_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const RECONNECT_MS = 3_000;
/** Số từ đã hiện của câu đang chạy chữ. Câu không có trong map thì hiện đủ. */
const ALL_WORDS = Number.MAX_SAFE_INTEGER;

function sleep(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

function messageOf(caught: unknown, fallback: string) {
  return caught instanceof ApiRequestError ? caught.message : fallback;
}

export default function JobPage() {
  const params = useParams<{ id: string }>();
  const valid = JOB_ID.test(params.id);
  return (
    <AppShell>
      {valid ? (
        <JobView jobId={params.id.toLowerCase()} />
      ) : (
        <div className="py-16 text-center">
          <p className="text-sm text-rose-700">Không tìm thấy.</p>
          <Link href="/jobs" className="mt-4 inline-block text-sm text-blue-700 hover:underline">
            Về danh sách job
          </Link>
        </div>
      )}
    </AppShell>
  );
}

function JobView({ jobId }: { jobId: string }) {
  const router = useRouter();

  const [job, setJob] = useState<JobDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pass, setPass] = useState<number | null>(null);
  const [segments, setSegments] = useState<ApiSegment[]>([]);
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [visible, setVisible] = useState<Record<string, number>>({});
  const [highlights, setHighlights] = useState<Highlight[]>([]);
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [minutes, setMinutes] = useState<LlmRun | null>(null);
  const [progress, setProgress] = useState<Progress>(null);
  const [mode, setMode] = useState<TranscriptMode>("raw");
  const [selection, setSelection] = useState<Selected | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [llmBusy, setLlmBusy] = useState(false);
  const [taskDraft, setTaskDraft] = useState<TaskDraft | null>(null);
  const [taskSaving, setTaskSaving] = useState(false);
  const [taskError, setTaskError] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement>(null);
  const [audioSrc, setAudioSrc] = useState<string | null>(null);
  const [currentMs, setCurrentMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [audioDurationMs, setAudioDurationMs] = useState(0);

  const passRef = useRef<number | null>(null);
  const knownIds = useRef(new Set<string>());
  const renameTimers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const typewriterRef = useRef<AdaptiveTypewriter<string> | null>(null);

  if (typewriterRef.current === null) {
    typewriterRef.current = new AdaptiveTypewriter<string>((segmentId) => {
      setVisible((current) => {
        const shown = current[segmentId];
        if (shown === undefined || shown === ALL_WORDS) return current;
        return { ...current, [segmentId]: shown + 1 };
      });
    });
  }
  useEffect(() => () => typewriterRef.current?.dispose(), []);

  // ----- Tải dữ liệu -----

  const loadJob = useCallback(async () => {
    const detail = await apiJson<JobDetail>(`/api/jobs/${jobId}`);
    setJob(detail);
    return detail;
  }, [jobId]);

  const loadTranscript = useCallback(async () => {
    const transcript = await apiJson<Transcript>(`/api/jobs/${jobId}/transcript`);
    passRef.current = transcript.pass;
    setPass(transcript.pass);
    setSegments(transcript.segments);
    knownIds.current = new Set(transcript.segments.map((segment) => segment.id));
    setSpeakers(
      transcript.speakers.map((speaker) => ({ label: speaker.label, name: speaker.display_name, source: speaker.source })),
    );
  }, [jobId]);

  const loadSide = useCallback(async () => {
    const [highlightPage, actionPage] = await Promise.all([
      apiJson<{ items: Highlight[] }>(`/api/jobs/${jobId}/highlights`),
      apiJson<{ items: ActionItem[] }>(`/api/jobs/${jobId}/actions`),
    ]);
    setHighlights(highlightPage.items);
    setActions(actionPage.items);
    try {
      setMinutes(await apiJson<LlmRun>(`/api/jobs/${jobId}/llm/summarize`));
    } catch {
      setMinutes(null);
    }
  }, [jobId]);

  useEffect(() => {
    Promise.all([loadJob(), loadTranscript(), loadSide()]).catch((caught) =>
      setLoadError(messageOf(caught, "Không tải được job.")),
    );
  }, [loadJob, loadTranscript, loadSide]);

  // ----- SSE: chạy khi job còn đang xử lý -----

  const handleEvent = useCallback(
    (event: JobEvent) => {
      switch (event.type) {
        case "stage":
          setProgress((current) => ({ stage: event.stage, chunkIndex: current?.chunkIndex ?? -1, chunkCount: current?.chunkCount ?? 0 }));
          setJob((current) => (current ? { ...current, status: event.stage as JobStatus } : current));
          break;
        case "chunk": {
          setProgress({ stage: "transcribing", chunkIndex: event.chunk_index, chunkCount: event.chunk_count });
          const fresh = event.segments.filter((segment) => !knownIds.current.has(segment.id));
          if (fresh.length === 0) break;
          fresh.forEach((segment) => knownIds.current.add(segment.id));
          // Job live đang hiện pass 1: chuyển sang pass 2 khi pass 2 có câu đầu tiên.
          const switching = passRef.current !== null && passRef.current < 2;
          passRef.current = 2;
          setPass(2);
          setSegments((current) => (switching ? fresh : [...current, ...fresh]));
          setVisible((current) => {
            const next = { ...current };
            fresh.forEach((segment) => {
              next[segment.id] = segment.words.length > 0 ? 0 : ALL_WORDS;
            });
            return next;
          });
          const items = fresh.flatMap((segment) => segment.words.map(() => segment.id));
          typewriterRef.current?.enqueueChunk(items, event.expected_next_chunk_ms);
          break;
        }
        case "speakers":
          void loadTranscript();
          break;
        case "warning":
          setJob((current) =>
            current ? { ...current, warnings: [...current.warnings, { code: event.code, message: event.message }] } : current,
          );
          break;
        case "done":
          typewriterRef.current?.markStreamComplete();
          setProgress(null);
          void loadJob();
          void loadTranscript();
          break;
        case "error":
          setProgress(null);
          void loadJob();
          break;
      }
    },
    [loadJob, loadTranscript],
  );

  const active = job ? ACTIVE_STATUSES.includes(job.status) : false;
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    (async () => {
      let seq = 0;
      while (!controller.signal.aborted) {
        try {
          seq = await streamJobEvents(jobId, { afterSeq: seq, signal: controller.signal, onEvent: handleEvent });
          const detail = await loadJob();
          if (!ACTIVE_STATUSES.includes(detail.status)) break;
        } catch {
          if (controller.signal.aborted) break;
        }
        await sleep(RECONNECT_MS, controller.signal);
      }
    })();
    return () => controller.abort();
  }, [active, jobId, handleEvent, loadJob]);

  // ----- Nghe lại bằng media token -----

  const loadMedia = useCallback(async () => {
    try {
      const token = await apiJson<{ url: string }>(`/api/jobs/${jobId}/media-token`, { method: "POST" });
      setAudioSrc(token.url);
    } catch {
      setAudioSrc(null);
    }
  }, [jobId]);

  const hasAudio = job?.duration_ms != null;
  useEffect(() => {
    if (hasAudio) void loadMedia();
  }, [hasAudio, loadMedia]);

  function onAudioError() {
    // Token sống 5 phút. Hết hạn thì xin token mới và giữ vị trí đang nghe.
    const audio = audioRef.current;
    const resumeAt = audio?.currentTime ?? 0;
    void loadMedia().then(() => {
      if (audioRef.current) audioRef.current.currentTime = resumeAt;
    });
  }

  function seek(ms: number) {
    setCurrentMs(ms);
    const audio = audioRef.current;
    if (audio && audioSrc) audio.currentTime = ms / 1000;
  }

  function togglePlay() {
    const audio = audioRef.current;
    if (!audio || !audioSrc) {
      setNotice("Chưa có file nghe lại cho job này.");
      return;
    }
    if (audio.paused) void audio.play();
    else audio.pause();
  }

  // ----- Người nói -----

  function renameSpeaker(label: string, name: string) {
    setSpeakers((current) => current.map((speaker) => (speaker.label === label ? { ...speaker, name } : speaker)));
    const timers = renameTimers.current;
    const pending = timers.get(label);
    if (pending) clearTimeout(pending);
    timers.set(
      label,
      setTimeout(async () => {
        timers.delete(label);
        try {
          const saved = await apiJson<{ label: string; display_name: string; source: Speaker["source"] }>(
            `/api/jobs/${jobId}/speakers/${encodeURIComponent(label)}`,
            { method: "PATCH", body: JSON.stringify({ display_name: name }) },
          );
          setSpeakers((current) =>
            current.map((speaker) => (speaker.label === label ? { ...speaker, source: saved.source } : speaker)),
          );
        } catch (caught) {
          setNotice(messageOf(caught, "Không đổi được tên người nói."));
        }
      }, 600),
    );
  }

  // ----- Vùng chọn, đánh dấu, việc -----

  const canEdit = job?.status === "ready" || (job?.status === "failed" && pass === 1);

  function readSelection(segmentId: string) {
    const native = window.getSelection();
    const quote = native?.toString().trim() ?? "";
    if (!native || native.isCollapsed || !quote) {
      setSelection(null);
      return;
    }
    const root = document.querySelector(`[data-segment-id="${CSS.escape(segmentId)}"]`);
    const range = native.getRangeAt(0);
    if (!root || !root.contains(range.startContainer) || !root.contains(range.endContainer)) {
      setSelection(null);
      return;
    }
    if (!canEdit) {
      setSelection(null);
      setNotice("Đánh dấu và tạo việc mở khi job sẵn sàng.");
      return;
    }
    const segment = segments.find((row) => row.id === segmentId);
    if (!segment) return;
    let startMs = segment.start_ms;
    let endMs = segment.end_ms;
    const words = Array.from(root.querySelectorAll<HTMLElement>("[data-start-ms][data-end-ms]")).filter((element) =>
      range.intersectsNode(element),
    );
    if (words.length > 0) {
      const first = Number(words[0].dataset.startMs);
      const last = Number(words[words.length - 1].dataset.endMs);
      if (first < last) {
        startMs = Math.max(first, segment.start_ms);
        endMs = Math.min(last, segment.end_ms);
      }
    }
    if (startMs >= endMs) {
      startMs = segment.start_ms;
      endMs = segment.end_ms;
    }
    setSelection({ segmentId, quote: quote.slice(0, 500), startMs, endMs });
  }

  function clearSelection() {
    window.getSelection()?.removeAllRanges();
    setSelection(null);
  }

  async function mark() {
    if (!selection) return;
    try {
      const row = await apiJson<Highlight>(`/api/jobs/${jobId}/highlights`, {
        method: "POST",
        body: JSON.stringify({
          segment_id: selection.segmentId,
          quote: selection.quote,
          start_ms: selection.startMs,
          end_ms: selection.endMs,
        }),
      });
      setHighlights((current) => [...current, row]);
      setNotice("Đã đánh dấu.");
      clearSelection();
    } catch (caught) {
      setNotice(messageOf(caught, "Không đánh dấu được."));
    }
  }

  async function unmark() {
    if (!selection) return;
    const targets = highlights.filter(
      (row) => row.segment_id === selection.segmentId && row.start_ms < selection.endMs && row.end_ms > selection.startMs,
    );
    try {
      await Promise.all(
        targets.map((row) => apiJson<void>(`/api/jobs/${jobId}/highlights/${row.id}`, { method: "DELETE" })),
      );
      const removed = new Set(targets.map((row) => row.id));
      setHighlights((current) => current.filter((row) => !removed.has(row.id)));
      setNotice(targets.length ? "Đã bỏ đánh dấu." : "Đoạn này chưa được đánh dấu.");
      clearSelection();
    } catch (caught) {
      setNotice(messageOf(caught, "Không bỏ được đánh dấu."));
    }
  }

  function openTask() {
    if (!selection) return;
    const segment = segments.find((row) => row.id === selection.segmentId);
    setTaskError(null);
    setTaskDraft({ segmentId: selection.segmentId, startMs: segment?.start_ms ?? selection.startMs, task: selection.quote });
  }

  async function saveTask(values: { task: string; owner: string; deadline: string }) {
    if (!taskDraft) return;
    setTaskSaving(true);
    try {
      const row = await apiJson<ActionItem>(`/api/jobs/${jobId}/actions`, {
        method: "POST",
        body: JSON.stringify({ segment_id: taskDraft.segmentId, ...values }),
      });
      setActions((current) => [...current, row]);
      setTaskDraft(null);
      clearSelection();
      setNotice("Đã tạo việc.");
    } catch (caught) {
      setTaskError(messageOf(caught, "Không lưu được việc."));
    } finally {
      setTaskSaving(false);
    }
  }

  async function deleteAction(id: string) {
    try {
      await apiJson<void>(`/api/jobs/${jobId}/actions/${id}`, { method: "DELETE" });
      setActions((current) => current.filter((row) => row.id !== id));
    } catch (caught) {
      setNotice(messageOf(caught, "Không xóa được việc."));
    }
  }

  // ----- LLM và xuất file -----

  async function runLlm(body: { task: "clean" | "summarize"; template?: MinutesTemplate }) {
    if (llmBusy) return;
    setLlmBusy(true);
    setNotice(body.task === "clean" ? "Đang chuẩn hóa văn bản…" : "Đang lập biên bản…");
    try {
      await apiJson(`/api/jobs/${jobId}/llm`, { method: "POST", body: JSON.stringify(body) });
      let run: LlmRun;
      do {
        await sleep(LLM_POLL_MS);
        run = await apiJson<LlmRun>(`/api/jobs/${jobId}/llm/${body.task}`);
      } while (run.status === "running");
      if (run.status === "failed") {
        setNotice(run.error_message ?? "Tác vụ LLM thất bại.");
      } else if (body.task === "clean") {
        await loadTranscript();
        setMode("cleaned");
        setNotice("Đã chuẩn hóa văn bản.");
      } else {
        setMinutes(run);
        setNotice("Đã lập biên bản.");
      }
    } catch (caught) {
      setNotice(messageOf(caught, "Không chạy được tác vụ LLM."));
    } finally {
      setLlmBusy(false);
    }
  }

  async function exportFile(format: ExportFormat) {
    try {
      const res = await apiFetch(`/api/jobs/${jobId}/exports`, {
        method: "POST",
        headers: { "Content-Type": "application/json; charset=utf-8" },
        body: JSON.stringify({ format, text: mode === "raw" ? "raw" : "auto", include_speakers: true }),
      });
      if (!res.ok) throw await readError(res);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = fileNameFrom(res.headers.get("Content-Disposition")) ?? `${job?.title ?? "transcript"}.${format}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setNotice(messageOf(caught, "Không xuất được file."));
    }
  }

  // ----- Hủy, chạy lại, xóa -----

  async function cancelJob() {
    try {
      setJob(await apiJson<JobDetail>(`/api/jobs/${jobId}/cancel`, { method: "POST" }));
      setProgress(null);
    } catch (caught) {
      setNotice(messageOf(caught, "Không hủy được job."));
    }
  }

  async function retryJob() {
    if (!window.confirm("Chạy lại sẽ xóa transcript bản chuẩn và các đánh dấu trên đó. Tiếp tục?")) return;
    try {
      setJob(await apiJson<JobDetail>(`/api/jobs/${jobId}/retry`, { method: "POST" }));
      await Promise.all([loadTranscript(), loadSide()]);
    } catch (caught) {
      setNotice(messageOf(caught, "Không chạy lại được job."));
    }
  }

  async function deleteJob() {
    if (!window.confirm("Xóa job, transcript, và file âm thanh? Không hoàn tác được.")) return;
    try {
      await apiJson<void>(`/api/jobs/${jobId}`, { method: "DELETE" });
      router.push("/jobs");
    } catch (caught) {
      setNotice(messageOf(caught, "Không xóa được job."));
    }
  }

  // ----- Dựng dữ liệu cho layout -----

  const shownSegments: Segment[] = useMemo(() => {
    const marked = new Set(highlights.map((row) => row.segment_id));
    return segments.flatMap((segment) => {
      const shown = visible[segment.id] ?? ALL_WORDS;
      if (shown === 0) return [];
      const words = segment.words.slice(0, shown).map((word) => ({ text: word.text, startMs: word.start_ms, endMs: word.end_ms }));
      const partial = shown < segment.words.length;
      return [
        {
          id: segment.id,
          speakerLabel: segment.speaker_label ?? "",
          startMs: segment.start_ms,
          endMs: segment.end_ms,
          textRaw: partial ? words.map((word) => word.text).join(" ") : segment.text_raw,
          textCleaned: segment.text_cleaned ?? null,
          textEdited: segment.text_edited ?? null,
          words,
          marked: marked.has(segment.id),
        },
      ];
    });
  }, [segments, visible, highlights]);

  if (loadError) {
    return (
      <div className="py-16 text-center">
        <p className="text-sm text-rose-700">{loadError}</p>
        <Link href="/jobs" className="mt-4 inline-block text-sm text-blue-700 hover:underline">
          Về danh sách job
        </Link>
      </div>
    );
  }
  if (!job) return <p className="py-16 text-center text-sm text-slate-500">Đang tải job…</p>;

  const durationMs = job.duration_ms ?? audioDurationMs;
  const banner = active ? (
    <div className="mt-4 rounded-2xl bg-blue-50 px-4 py-3 text-sm text-blue-900">
      <div className="flex justify-between gap-3">
        <span>{STATUS_LABELS[job.status]}</span>
        {progress && progress.chunkCount > 0 ? (
          <span>
            Đoạn {progress.chunkIndex + 1}/{progress.chunkCount}
          </span>
        ) : null}
      </div>
      {progress && progress.chunkCount > 0 ? (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-blue-100">
          <div
            className="h-full rounded-full bg-blue-600 transition-[width]"
            style={{ width: `${Math.round(((progress.chunkIndex + 1) / progress.chunkCount) * 100)}%` }}
          />
        </div>
      ) : null}
      {pass === 1 ? <p className="mt-1 text-xs text-blue-700">Đang hiện bản nháp. Bản chuẩn thay vào khi có câu đầu tiên.</p> : null}
    </div>
  ) : null;

  const sidebar = (
    <>
      {minutes?.status === "done" && minutes.result && minutes.template ? (
        <MinutesView
          template={minutes.template}
          result={minutes.result}
          onSeekStamp={(stamp) => {
            const ms = stampToMs(stamp);
            if (ms !== null) seek(ms);
          }}
        />
      ) : null}
      {actions.length > 0 ? (
        <section className="rounded-3xl bg-white p-4 ring-1 ring-sky-100">
          <h2 className="text-sm font-semibold text-slate-900">Việc tại câu</h2>
          <ul className="mt-2 space-y-2 text-sm">
            {actions.map((item) => (
              <li key={item.id} className="flex items-start gap-2">
                <button
                  type="button"
                  onClick={() => seek(item.start_ms)}
                  className="rounded bg-sky-50 px-1.5 font-mono text-xs text-blue-700 hover:bg-sky-100"
                >
                  {formatMs(item.start_ms)}
                </button>
                <span className="min-w-0 flex-1 text-slate-700">
                  {item.task}
                  {item.owner ? <span className="text-slate-500"> · {item.owner}</span> : null}
                  {item.deadline ? <span className="text-slate-500"> · hạn {item.deadline}</span> : null}
                </span>
                <button
                  type="button"
                  aria-label="Xóa việc"
                  onClick={() => void deleteAction(item.id)}
                  className="text-slate-400 hover:text-rose-600"
                >
                  <Trash2 className="size-4" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Link href="/jobs" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-blue-700">
            <ArrowLeft className="size-3.5" />
            Danh sách job
          </Link>
          <h1 className="mt-1 truncate text-2xl font-bold tracking-tight text-[#0f2744]">{job.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <JobStatusBadge status={job.status} />
            <span>{new Date(job.created_at).toLocaleString("vi-VN")}</span>
            {job.duration_ms != null ? <span>· {formatMs(job.duration_ms)}</span> : null}
            {job.diarization_device === "cpu" ? <span>· người nói chạy trên CPU</span> : null}
            {pass === 1 ? <span>· bản nháp</span> : null}
          </div>
        </div>
        <div className="flex gap-2">
          {CANCELLABLE.includes(job.status) ? (
            <HeaderButton onClick={() => void cancelJob()} icon={<Square className="size-4" />}>
              Hủy
            </HeaderButton>
          ) : null}
          {job.status === "failed" ? (
            <HeaderButton onClick={() => void retryJob()} icon={<RotateCcw className="size-4" />}>
              Chạy lại
            </HeaderButton>
          ) : null}
          <HeaderButton onClick={() => void deleteJob()} icon={<Trash2 className="size-4" />} danger>
            Xóa
          </HeaderButton>
        </div>
      </div>

      {job.status === "failed" && job.error_message ? (
        <p className="mb-4 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{job.error_message}</p>
      ) : null}
      {job.warnings.map((warning, index) => (
        <p key={`${warning.code}-${index}`} className="mb-4 rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {warning.message}
        </p>
      ))}

      <audio
        ref={audioRef}
        src={audioSrc ?? undefined}
        preload="metadata"
        onTimeUpdate={(event) => setCurrentMs(Math.round(event.currentTarget.currentTime * 1000))}
        onLoadedMetadata={(event) => {
          const seconds = event.currentTarget.duration;
          if (Number.isFinite(seconds)) setAudioDurationMs(Math.round(seconds * 1000));
        }}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onError={onAudioError}
        className="hidden"
      />

      <TranscriptLayout
        title={job.title}
        speakers={speakers}
        segments={shownSegments}
        mode={mode}
        currentMs={currentMs}
        durationMs={durationMs}
        playing={playing}
        selection={selection}
        notice={notice}
        aiDisabled={!canEdit || llmBusy}
        banner={banner}
        sidebar={sidebar}
        emptyText={active ? "Chữ sẽ hiện ở đây khi đoạn đầu tiên nhận dạng xong." : "Transcript trống."}
        onModeChange={setMode}
        onTogglePlay={togglePlay}
        onSeek={seek}
        onRenameSpeaker={renameSpeaker}
        onSelect={readSelection}
        onMark={() => void mark()}
        onUnmark={() => void unmark()}
        onCreateTask={openTask}
        onNormalize={() => void runLlm({ task: "clean" })}
        onMinutes={(template) => void runLlm({ task: "summarize", template })}
        onExport={(format) => void exportFile(format)}
      />

      {taskDraft ? (
        <TaskDialog
          draft={taskDraft}
          saving={taskSaving}
          error={taskError}
          onSave={(values) => void saveTask(values)}
          onClose={() => setTaskDraft(null)}
        />
      ) : null}
    </div>
  );
}

function HeaderButton({
  children,
  icon,
  danger = false,
  onClick,
}: {
  children: string;
  icon: React.ReactNode;
  danger?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-full border bg-white px-3 py-1.5 text-sm ${
        danger ? "border-rose-100 text-rose-600 hover:bg-rose-50" : "border-slate-200 text-slate-700 hover:bg-slate-50"
      }`}
    >
      {icon}
      {children}
    </button>
  );
}

function fileNameFrom(header: string | null) {
  if (!header) return null;
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (encoded) return decodeURIComponent(encoded[1]);
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1] : null;
}
