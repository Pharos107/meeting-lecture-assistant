"use client";

import Image from "next/image";
import { useCallback, useEffect, useRef, useState } from "react";
import { Eye, LoaderCircle } from "lucide-react";
import { LiveTranscript } from "@/components/live-transcript";
import { ReaderSettingsMenu } from "@/components/reader-settings";
import { SelectionPaint } from "@/components/selection-paint";
import type { LiveLine } from "@/components/types";
import { ApiRequestError, fetchShared, type SharedJob } from "@/lib/api";
import { formatMs } from "@/lib/format";
import { useReaderPrefs } from "@/lib/reader-prefs";

// Bản chuẩn của một buổi vài chục phút xong trong vài phút: hỏi lại thưa là đủ.
const PROCESSING_POLL_MS = 3000;

type SharedDraft = { segment_id: string; start_ms: number; end_ms: number; text: string; stable: boolean };

/** Chữ nháp của phiên đang ghi, nhận qua SSE công khai. Hết phiên thì gọi `onEnded`. */
function useSharedLive(token: string, enabled: boolean, onEnded: () => void) {
  const [lines, setLines] = useState<Map<string, LiveLine>>(new Map());
  const onEndedRef = useRef(onEnded);
  onEndedRef.current = onEnded;

  useEffect(() => {
    if (!enabled) return;
    const source = new EventSource(`/api/shared/${encodeURIComponent(token)}/live`);
    const put = (draft: SharedDraft, instant: boolean) =>
      setLines((current) => {
        const next = new Map(current);
        if (draft.stable && !draft.text) next.delete(draft.segment_id);
        else next.set(draft.segment_id, { id: draft.segment_id, text: draft.text, stable: draft.stable, startMs: draft.start_ms, instant });
        return next;
      });
    source.addEventListener("snapshot", (event) => {
      const { segments } = JSON.parse((event as MessageEvent<string>).data) as { segments: SharedDraft[] };
      segments.forEach((segment) => put(segment, true));
    });
    source.addEventListener("draft", (event) => put(JSON.parse((event as MessageEvent<string>).data) as SharedDraft, false));
    source.addEventListener("ended", () => {
      source.close();
      onEndedRef.current();
    });
    // Rớt mạng thì EventSource tự nối lại. Phiên đã hết thì máy chủ trả 404: hỏi lại trạng thái của bản ghi.
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) onEndedRef.current();
    };
    return () => source.close();
  }, [token, enabled]);

  return [...lines.values()].sort((a, b) => (a.startMs ?? 0) - (b.startMs ?? 0));
}

/** Trang công khai của liên kết chia sẻ: chỉ đọc, không cần đăng nhập. Bản ghi đang ghi thì theo dõi trực tiếp. */
export function SharedTranscript({ token }: { token: string }) {
  const reader = useReaderPrefs();
  const [job, setJob] = useState<SharedJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  // `ended` tới ngay lúc chủ bấm dừng, có thể trước khi job rời `capturing`: coi như đang tạo bản chuẩn.
  const [liveEnded, setLiveEnded] = useState(false);
  const content = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    fetchShared(token)
      .then((shared) => {
        setJob(shared);
        document.title = shared.title;
      })
      .catch((caught) => {
        if (caught instanceof ApiRequestError && caught.status === 404) setError("Liên kết không tồn tại hoặc đã bị tắt.");
        else setError(caught instanceof ApiRequestError ? caught.message : "Không tải được bản ghi.");
      });
  }, [token]);

  useEffect(load, [load]);

  const state = job?.state === "live" && liveEnded ? "processing" : job?.state;

  useEffect(() => {
    if (state !== "processing") return;
    const timer = window.setInterval(load, PROCESSING_POLL_MS);
    return () => window.clearInterval(timer);
  }, [state, load]);

  const liveLines = useSharedLive(token, state === "live", () => {
    setLiveEnded(true);
    load();
  });

  if (error) return <p className="py-20 text-center text-sm text-slate-600">{error}</p>;
  if (!job) return <p className="py-20 text-center text-sm text-slate-500">Đang tải bản ghi…</p>;

  const live = state === "live";

  return (
    <div style={reader.style} className="flex h-dvh flex-col bg-gradient-to-b from-sky-50 via-white to-white">
      <header className="flex items-center gap-3 border-b border-sky-100 bg-white px-4 py-2.5 sm:px-6">
        <Image src="/logo.png" alt="" width={32} height={32} className="size-8 shrink-0 object-contain" />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-bold tracking-tight text-[#0f2744]">{job.title}</h1>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-slate-500">
            {live ? (
              <span className="inline-flex items-center gap-1.5 font-medium text-rose-700">
                <span className="size-2 rounded-full bg-rose-600 motion-safe:animate-pulse" />
                Đang ghi trực tiếp
              </span>
            ) : state === "processing" ? (
              <span className="inline-flex items-center gap-1.5 font-medium text-blue-700">
                <LoaderCircle className="size-3.5 animate-spin" />
                Đang tạo bản chuẩn
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 font-medium text-blue-700">
                <Eye className="size-3.5" />
                Chỉ xem
              </span>
            )}
            <span>{new Date(job.created_at).toLocaleString("vi-VN")}</span>
            {job.state === "ready" && job.duration_ms != null ? <span>{formatMs(job.duration_ms)}</span> : null}
          </div>
        </div>
        <ReaderSettingsMenu reader={reader} />
      </header>

      {live ? (
        <>
          <LiveTranscript lines={liveLines} emptyText="Chữ nháp hiện ở đây khi có người nói." />
          <p className="border-t border-sky-100 bg-white px-4 py-2 text-xs text-slate-500 sm:px-6">
            Đây là bản nháp đang ghi. Khi buổi kết thúc, trang tự chuyển sang bản chuẩn có tên người nói.
          </p>
        </>
      ) : (
        <main className="reader-surface scrollbar-soft min-h-0 flex-1 overflow-y-auto">
          <div ref={content} className="relative mx-auto w-full max-w-(--reader-width) px-4 pb-6 pt-3 sm:px-6">
            <SelectionPaint root={content} />
            {state === "processing" ? (
              <p className="mb-3 rounded-2xl bg-blue-50 px-4 py-3 text-sm text-blue-900">
                Buổi ghi đã kết thúc. Đang hiện bản nháp, bản chuẩn có tên người nói thay vào khi xong.
              </p>
            ) : null}
            {job.segments.length === 0 ? <p className="mt-8 text-center text-sm text-slate-500">Transcript trống.</p> : null}
            <ol className="mt-2 space-y-3">
              {job.segments.map((segment, index) => (
                <li key={index} className="rounded-2xl bg-slate-50 px-4 py-3">
                  <div className="flex items-baseline justify-between gap-3 text-xs text-slate-500">
                    <span className="font-medium text-slate-700">{segment.speaker || "Chưa rõ người nói"}</span>
                    <span>{formatMs(segment.start_ms)}</span>
                  </div>
                  <p className="reader-text mt-2 text-slate-800">{segment.text}</p>
                </li>
              ))}
            </ol>
          </div>
        </main>
      )}
    </div>
  );
}
