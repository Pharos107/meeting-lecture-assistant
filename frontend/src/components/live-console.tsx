"use client";

import { useEffect, useState } from "react";
import { LoaderCircle, Share2, Square } from "lucide-react";
import { ChatPanel, useJobChat } from "@/components/chat-panel";
import { JobToolPanel, JobToolRail, type ToolId } from "@/components/job-tools";
import { LevelTimeline } from "@/components/live-meter";
import { LiveTranscript } from "@/components/live-transcript";
import { ReaderSettingsMenu } from "@/components/reader-settings";
import { ShareDialog } from "@/components/share-dialog";
import type { LiveLine } from "@/components/types";
import { formatMs, stampToMs } from "@/lib/format";
import type { LevelProbe, LiveDraft } from "@/lib/live-capture";
import { useReaderPrefs } from "@/lib/reader-prefs";

const NOTICE_MS = 4000;

type LiveConsoleProps = {
  jobId: string;
  title: string;
  sourceLabel: string;
  probe: LevelProbe | null;
  startedAt: number | null;
  now: number;
  drafts: LiveDraft[];
  connected: boolean;
  stopping: boolean;
  degraded: string | null;
  confirmStop: boolean;
  onStop: () => void;
};

/** Màn hình trong lúc ghi: sóng âm, bản nháp, chia sẻ, cài đặt hiển thị, và trợ lý hỏi trên các câu đã chốt. */
export function LiveConsole(props: LiveConsoleProps) {
  const reader = useReaderPrefs();
  const [tool, setTool] = useState<ToolId | null>(null);
  const [shareOpen, setShareOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [focusMs, setFocusMs] = useState<number | null>(null);
  const chat = useJobChat(props.jobId, setToast);
  const { drafts, stopping } = props;

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), NOTICE_MS);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const lines: LiveLine[] = drafts.map((draft) => ({
    id: draft.segment_id,
    text: draft.text,
    stable: draft.stable,
    startMs: draft.start_ms,
  }));
  const closed = drafts.filter((draft) => draft.stable).length;
  const elapsed = props.startedAt ? props.now - props.startedAt : 0;
  const status = stopping ? "Đang chốt bản ghi" : props.connected ? "Đang ghi" : "Mất kết nối, đang nối lại";

  return (
    <div style={reader.style} className="relative flex h-full flex-col overflow-hidden lg:flex-row">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="@container border-b border-sky-100 bg-white">
          <div className="flex items-center gap-3 px-4 py-3 sm:px-6">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-xs font-medium">
                <span
                  className={`size-2 rounded-full ${
                    stopping ? "bg-slate-400" : props.connected ? "bg-rose-600 motion-safe:animate-pulse" : "bg-amber-500"
                  }`}
                />
                <span className={stopping ? "text-slate-500" : props.connected ? "text-rose-700" : "text-amber-700"}>{status}</span>
              </div>
              <h1 className="mt-0.5 truncate text-lg font-bold tracking-tight text-[#0f2744]">{props.title}</h1>
              <p className="truncate text-xs text-slate-500">{props.sourceLabel}</p>
            </div>
            <span className="text-3xl font-light tabular-nums tracking-tight text-[#0f2744] @2xl:text-4xl" aria-label="Thời gian đã ghi">
              {formatMs(elapsed)}
            </span>
            <div className="flex shrink-0 items-center gap-1.5">
              <button
                type="button"
                onClick={() => setShareOpen(true)}
                aria-label="Chia sẻ"
                title="Chia sẻ để người khác theo dõi trực tiếp"
                className="inline-flex h-9 items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 text-slate-700 transition-colors hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700"
              >
                <Share2 className="size-4" />
                <span className="hidden text-sm @3xl:inline">Chia sẻ</span>
              </button>
              <ReaderSettingsMenu reader={reader} />
              <button
                type="button"
                disabled={stopping}
                onClick={props.onStop}
                className={`inline-flex h-9 items-center gap-2 rounded-full px-4 text-sm font-semibold text-white disabled:opacity-60 ${
                  props.confirmStop ? "bg-rose-700 ring-4 ring-rose-200" : "bg-rose-600 transition-colors hover:bg-rose-700 hover:shadow-md hover:shadow-rose-500/30"
                }`}
              >
                {stopping ? <LoaderCircle className="size-4 animate-spin" /> : <Square className="size-3.5 fill-current" />}
                {stopping ? "Đang dừng" : props.confirmStop ? "Bấm lần nữa để dừng" : "Dừng ghi"}
              </button>
            </div>
          </div>
          <div className="px-4 pb-2 sm:px-6">
            <LevelTimeline
              probe={props.probe}
              startedAt={props.startedAt}
              running={!stopping}
              spans={drafts.map((draft) => ({ startMs: draft.start_ms, endMs: draft.end_ms, stable: draft.stable }))}
            />
          </div>
        </header>

        {props.degraded ? (
          <p className="border-b border-amber-100 bg-amber-50 px-4 py-2 text-sm text-amber-800 sm:px-6">{props.degraded}</p>
        ) : null}

        <LiveTranscript
          lines={lines}
          listening={!stopping}
          focusMs={focusMs}
          emptyText={props.connected ? "Chữ nháp hiện ở đây sau vài giây nói." : "Đang kết nối máy chủ…"}
        />

        <footer className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-sky-100 bg-white px-4 py-2 text-xs text-slate-500 sm:px-6">
          <span>
            Câu đã chốt <span className="font-semibold tabular-nums text-slate-700">{closed}</span>
          </span>
          <span>{props.degraded ? "Bản nháp chỉ hiện câu khi câu kết thúc" : "Bản nháp cập nhật theo lời nói"}</span>
          <span className="sm:ml-auto">Khi dừng, hệ thống nhận dạng lại toàn bộ bản thu và gán người nói.</span>
        </footer>
      </div>

      {tool ? (
        <JobToolPanel tool={tool} fill onClose={() => setTool(null)}>
          <ChatPanel
            chat={chat}
            canAsk={closed > 0 && !stopping}
            durationMs={elapsed}
            onSeekStamp={(stamp) => setFocusMs(stampToMs(stamp))}
          />
          {closed === 0 ? <p className="mt-2 text-xs text-slate-500">Trợ lý trả lời được khi đã có câu chốt đầu tiên.</p> : null}
          {stopping ? <p className="mt-2 text-xs text-slate-500">Hỏi tiếp ở trang bản ghi khi bản chuẩn xong.</p> : null}
        </JobToolPanel>
      ) : null}
      <JobToolRail
        active={tool}
        badges={{}}
        only={["assistant"]}
        onToggle={(next) => setTool((current) => (current === next ? null : next))}
      />

      {toast ? (
        <p
          role="status"
          className="absolute bottom-20 left-1/2 z-40 max-w-[90%] -translate-x-1/2 rounded-full bg-slate-900 px-4 py-2 text-center text-sm text-white shadow-lg"
        >
          {toast}
        </p>
      ) : null}

      {shareOpen ? <ShareDialog jobId={props.jobId} title={props.title} live onClose={() => setShareOpen(false)} /> : null}
    </div>
  );
}
