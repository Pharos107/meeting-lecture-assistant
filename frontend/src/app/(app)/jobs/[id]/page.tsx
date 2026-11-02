"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RotateCcw, Square, Trash2 } from "lucide-react";
import { AudioPlayerBar } from "@/components/audio-player-bar";
import { ChatPanel, useJobChat } from "@/components/chat-panel";
import { ExportMenu } from "@/components/export-menu";
import { JobStatusBadge } from "@/components/job-status-badge";
import { JobToolPanel, JobToolRail, type ToolId } from "@/components/job-tools";
import { SpeakerList } from "@/components/speaker-list";
import { TaskDialog, type TaskDraft } from "@/components/task-dialog";
import { TranscriptLayout, type TranscriptSelection } from "@/components/transcript-layout";
import type { ExportFormat, Segment, Speaker } from "@/components/types";
import { useWorkspace } from "@/components/workspace-provider";
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
import { formatMs, stampToMs } from "@/lib/format";
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
type Selected = TranscriptSelection & { startMs: number; endMs: number };
type Progress = { stage: string; chunkIndex: number; chunkCount: number } | null;

const CANCELLABLE: JobStatus[] = ["queued", "capturing", "preprocessing", "transcribing"];
const NOTICE_MS = 5_000;
const JUMP_HIGHLIGHT_MS = 2_000;
const PLAYBACK_RATES = [1, 1.25, 1.5, 2, 0.75];
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
  if (!JOB_ID.test(params.id)) {
    return (
      <div className="py-16 text-center">
        <p className="text-sm text-rose-700">Không tìm thấy.</p>
        <Link href="/jobs" className="mt-4 inline-block text-sm text-blue-700 hover:underline">
          Về danh sách bản ghi
        </Link>
      </div>
    );
  }
  // Đổi bản ghi trong menu giữ nguyên route, nên key buộc dựng lại toàn bộ trạng thái của job.
  const jobId = params.id.toLowerCase();
  return <JobView key={jobId} jobId={jobId} />;
}

function JobView({ jobId }: { jobId: string }) {
  const router = useRouter();
  const { refreshJobs } = useWorkspace();

  const [job, setJob] = useState<JobDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pass, setPass] = useState<number | null>(null);
  const [segments, setSegments] = useState<ApiSegment[]>([]);
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [visible, setVisible] = useState<Record<string, number>>({});
  const [highlights, setHighlights] = useState<Highlight[]>([]);
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [progress, setProgress] = useState<Progress>(null);
  const [selection, setSelection] = useState<Selected | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [tool, setTool] = useState<ToolId | null>(null);
  const [jumpedId, setJumpedId] = useState<string | null>(null);
  const [taskDraft, setTaskDraft] = useState<TaskDraft | null>(null);
  const [taskSaving, setTaskSaving] = useState(false);
  const [taskError, setTaskError] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement>(null);
  const [audioSrc, setAudioSrc] = useState<string | null>(null);
  const [currentMs, setCurrentMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [audioDurationMs, setAudioDurationMs] = useState(0);

  const chatShown = useRef(false);
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

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), NOTICE_MS);
    return () => clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    if (!jumpedId) return;
    const timer = setTimeout(() => setJumpedId(null), JUMP_HIGHLIGHT_MS);
    return () => clearTimeout(timer);
  }, [jumpedId]);

  const chat = useJobChat(jobId, setNotice);

  // Đã có lịch sử hỏi đáp thì mở sẵn trên màn đủ rộng. Điện thoại giữ transcript, vì panel là tấm che chữ.
  useEffect(() => {
    if (chat.messages.length === 0 || chatShown.current) return;
    chatShown.current = true;
    if (window.matchMedia("(min-width: 1280px)").matches) setTool((current) => current ?? "assistant");
  }, [chat.messages.length]);

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
          // Server gộp câu khi xong, nên số từ đã đếm cho chạy chữ không còn khớp với câu mới.
          void loadTranscript().then(() => setVisible({}));
          void refreshJobs();
          break;
        case "error":
          setProgress(null);
          void loadJob();
          void refreshJobs();
          break;
      }
    },
    [loadJob, loadTranscript, refreshJobs],
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

  /** Tua rồi đưa câu tại mốc đó ra giữa khung chữ, cho các điều khiển nằm ngoài transcript. */
  function jumpTo(ms: number) {
    seek(ms);
    const target = segments.filter((row) => row.start_ms <= ms).at(-1) ?? segments[0];
    if (!target) return;
    // Trên điện thoại panel là tấm che chữ, phải đóng thì mới thấy câu vừa tới.
    if (!window.matchMedia("(min-width: 1024px)").matches) setTool(null);
    setJumpedId(target.id);
    document
      .querySelector(`[data-segment-id="${CSS.escape(target.id)}"]`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function togglePlay() {
    const audio = audioRef.current;
    if (!audio || !audioSrc) {
      setNotice("Chưa có file nghe lại cho bản ghi này.");
      return;
    }
    if (audio.paused) void audio.play();
    else audio.pause();
  }

  function cycleRate() {
    const next = PLAYBACK_RATES[(PLAYBACK_RATES.indexOf(rate) + 1) % PLAYBACK_RATES.length];
    setRate(next);
    if (audioRef.current) audioRef.current.playbackRate = next;
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
      setNotice("Đánh dấu và tạo việc mở khi bản ghi sẵn sàng.");
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

  async function deleteHighlight(id: string) {
    try {
      await apiJson<void>(`/api/jobs/${jobId}/highlights/${id}`, { method: "DELETE" });
      setHighlights((current) => current.filter((row) => row.id !== id));
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

  // ----- Xuất file -----

  async function exportFile(format: ExportFormat) {
    try {
      const res = await apiFetch(`/api/jobs/${jobId}/exports`, {
        method: "POST",
        headers: { "Content-Type": "application/json; charset=utf-8" },
        body: JSON.stringify({ format, text: "auto", include_speakers: true }),
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
      void refreshJobs();
    } catch (caught) {
      setNotice(messageOf(caught, "Không hủy được bản ghi."));
    }
  }

  async function retryJob() {
    if (!window.confirm("Chạy lại sẽ xóa transcript bản chuẩn, các đánh dấu trên đó, và lịch sử hỏi đáp. Tiếp tục?")) return;
    try {
      setJob(await apiJson<JobDetail>(`/api/jobs/${jobId}/retry`, { method: "POST" }));
      await Promise.all([loadTranscript(), loadSide(), chat.reload()]);
      void refreshJobs();
    } catch (caught) {
      setNotice(messageOf(caught, "Không chạy lại được bản ghi."));
    }
  }

  async function deleteJob() {
    if (!window.confirm("Xóa bản ghi, transcript, và file âm thanh? Không hoàn tác được.")) return;
    try {
      await apiJson<void>(`/api/jobs/${jobId}`, { method: "DELETE" });
      await refreshJobs();
      router.push("/jobs");
    } catch (caught) {
      setNotice(messageOf(caught, "Không xóa được bản ghi."));
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
  const banner = (
    <>
      {job.status === "failed" && job.error_message ? (
        <p className="mb-3 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{job.error_message}</p>
      ) : null}
      {job.warnings.map((warning, index) => (
        <p key={`${warning.code}-${index}`} className="mb-3 rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {warning.message}
        </p>
      ))}
      {active ? (
        <div className="mb-3 rounded-2xl bg-blue-50 px-4 py-3 text-sm text-blue-900">
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
      ) : null}
    </>
  );

  const notesTool =
    highlights.length === 0 && actions.length === 0 ? (
      <p className="text-sm leading-6 text-slate-500">Bôi đen một đoạn trong transcript để đánh dấu hoặc tạo việc tại mốc đó.</p>
    ) : (
      <div className="space-y-4">
        {highlights.length > 0 ? (
          <section>
            <h3 className="text-xs font-semibold text-slate-400">Đoạn đã đánh dấu</h3>
            <ul className="mt-2 space-y-2 text-sm">
              {[...highlights]
                .sort((first, second) => first.start_ms - second.start_ms)
                .map((item) => (
                  <NoteRow key={item.id} ms={item.start_ms} label="Bỏ đánh dấu" onSeek={jumpTo} onDelete={() => void deleteHighlight(item.id)}>
                    {item.quote}
                  </NoteRow>
                ))}
            </ul>
          </section>
        ) : null}
        {actions.length > 0 ? (
          <section>
            <h3 className="text-xs font-semibold text-slate-400">Việc tại câu</h3>
            <ul className="mt-2 space-y-2 text-sm">
              {actions.map((item) => (
                <NoteRow key={item.id} ms={item.start_ms} label="Xóa việc" onSeek={jumpTo} onDelete={() => void deleteAction(item.id)}>
                  {item.task}
                  {item.owner ? <span className="text-slate-500"> · {item.owner}</span> : null}
                  {item.deadline ? <span className="text-slate-500"> · hạn {item.deadline}</span> : null}
                </NoteRow>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    );

  const speakersTool =
    speakers.length > 0 ? (
      <SpeakerList speakers={speakers} onRename={renameSpeaker} />
    ) : (
      <p className="text-sm leading-6 text-slate-500">Người nói hiện sau khi nhận dạng xong.</p>
    );

  return (
    <div className="relative flex h-full flex-col overflow-hidden lg:flex-row">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="border-b border-sky-100 bg-white">
          <div className="mx-auto flex w-full max-w-3xl items-center gap-3 px-4 py-2.5 sm:px-6">
            <div className="min-w-0 flex-1">
              <h1 className="truncate text-lg font-bold tracking-tight text-[#0f2744]">{job.title}</h1>
              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
                <JobStatusBadge status={job.status} />
                <span>{new Date(job.created_at).toLocaleString("vi-VN")}</span>
                {job.duration_ms != null ? <span>· {formatMs(job.duration_ms)}</span> : null}
                {job.diarization_device === "cpu" ? <span>· người nói chạy trên CPU</span> : null}
                {pass === 1 ? <span>· bản nháp</span> : null}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
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
              <ExportMenu disabled={!canEdit} onExport={(format) => void exportFile(format)} />
              <button
                type="button"
                onClick={() => void deleteJob()}
                aria-label="Xóa bản ghi"
                title="Xóa bản ghi"
                className="rounded-full p-2 text-rose-600 hover:bg-rose-50"
              >
                <Trash2 className="size-4" />
              </button>
            </div>
          </div>
        </header>

        <audio
          ref={audioRef}
          src={audioSrc ?? undefined}
          preload="metadata"
          onTimeUpdate={(event) => setCurrentMs(Math.round(event.currentTarget.currentTime * 1000))}
          onLoadedMetadata={(event) => {
            event.currentTarget.playbackRate = rate;
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
          speakers={speakers}
          segments={shownSegments}
          currentMs={currentMs}
          selection={selection}
          jumpedId={jumpedId}
          banner={banner}
          emptyText={active ? "Chữ sẽ hiện ở đây khi đoạn đầu tiên nhận dạng xong." : "Transcript trống."}
          onSeek={seek}
          onSelect={readSelection}
          onMark={() => void mark()}
          onUnmark={() => void unmark()}
          onCreateTask={openTask}
        />

        <AudioPlayerBar
          currentMs={currentMs}
          durationMs={durationMs}
          playing={playing}
          rate={rate}
          marks={highlights.map((item) => item.start_ms)}
          onToggle={togglePlay}
          onSeek={jumpTo}
          onCycleRate={cycleRate}
        />
      </div>

      {tool ? (
        <JobToolPanel tool={tool} fill={tool === "assistant"} onClose={() => setTool(null)}>
          {tool === "assistant" ? (
            <ChatPanel
              chat={chat}
              canAsk={canEdit}
              durationMs={durationMs}
              onSeekStamp={(stamp) => {
                const ms = stampToMs(stamp);
                if (ms !== null) jumpTo(ms);
              }}
            />
          ) : tool === "notes" ? (
            notesTool
          ) : (
            speakersTool
          )}
        </JobToolPanel>
      ) : null}
      <JobToolRail
        active={tool}
        badges={{ notes: highlights.length + actions.length }}
        onToggle={(next) => setTool((current) => (current === next ? null : next))}
      />

      {notice ? (
        <p
          role="status"
          className="absolute bottom-32 left-1/2 z-40 max-w-[90%] -translate-x-1/2 rounded-full bg-slate-900 px-4 py-2 text-center text-sm text-white shadow-lg lg:bottom-20"
        >
          {notice}
        </p>
      ) : null}

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

function NoteRow({
  ms,
  label,
  onSeek,
  onDelete,
  children,
}: {
  ms: number;
  label: string;
  onSeek: (ms: number) => void;
  onDelete: () => void;
  children: React.ReactNode;
}) {
  return (
    <li className="flex items-start gap-2">
      <button
        type="button"
        onClick={() => onSeek(ms)}
        className="rounded bg-sky-50 px-1.5 font-mono text-xs text-blue-700 hover:bg-sky-100"
      >
        {formatMs(ms)}
      </button>
      <span className="min-w-0 flex-1 text-slate-700">{children}</span>
      <button type="button" aria-label={label} title={label} onClick={onDelete} className="text-slate-400 hover:text-rose-600">
        <Trash2 className="size-4" />
      </button>
    </li>
  );
}

function HeaderButton({ children, icon, onClick }: { children: string; icon: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
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
