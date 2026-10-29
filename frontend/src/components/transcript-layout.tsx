"use client";

import type { ReactNode } from "react";
import { AiActionPanel } from "@/components/ai-action-panel";
import { AudioPlayerBar } from "@/components/audio-player-bar";
import { SelectionToolbar } from "@/components/selection-toolbar";
import { SpeakerList } from "@/components/speaker-list";
import type { ExportFormat, MinutesTemplate, Segment, Speaker, TranscriptMode } from "@/components/types";
import { formatMs } from "@/lib/format";

export type TranscriptSelection = { segmentId: string; quote: string };

type TranscriptLayoutProps = {
  title: string;
  speakers: Speaker[];
  segments: Segment[];
  mode: TranscriptMode;
  currentMs: number;
  durationMs: number;
  playing: boolean;
  selection: TranscriptSelection | null;
  notice: string | null;
  aiDisabled?: boolean;
  banner?: ReactNode;
  sidebar?: ReactNode;
  emptyText?: string;
  onModeChange: (mode: TranscriptMode) => void;
  onTogglePlay: () => void;
  onSeek: (ms: number) => void;
  onRenameSpeaker: (label: string, name: string) => void;
  onSelect: (segmentId: string) => void;
  onMark: () => void;
  onUnmark: () => void;
  onCreateTask: () => void;
  onNormalize: () => void;
  onMinutes: (template: MinutesTemplate) => void;
  onExport: (format: ExportFormat) => void;
};

export function TranscriptLayout(props: TranscriptLayoutProps) {
  const player = (
    <AudioPlayerBar
      title={props.title}
      currentMs={props.currentMs}
      durationMs={props.durationMs}
      playing={props.playing}
      onToggle={props.onTogglePlay}
      onSeek={props.onSeek}
    />
  );

  return (
    // Màn hẹp: transcript lên trước, cột bên xuống dưới, trình phát dính ở đáy.
    <div className="flex flex-col-reverse gap-6 pb-28 lg:grid lg:grid-cols-[minmax(320px,38%)_1fr] lg:items-start lg:pb-0">
      <aside className="space-y-4 lg:sticky lg:top-20">
        <div className="hidden lg:block">{player}</div>
        {props.speakers.length > 0 ? <SpeakerList speakers={props.speakers} onRename={props.onRenameSpeaker} /> : null}
        <AiActionPanel
          notice={props.notice}
          disabled={props.aiDisabled}
          onNormalize={props.onNormalize}
          onMinutes={props.onMinutes}
          onExport={props.onExport}
        />
        {props.sidebar}
      </aside>

      <section className="rounded-3xl bg-white p-5 ring-1 ring-sky-100">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-slate-900">Transcript</h2>
          <div className="flex rounded-full bg-slate-100 p-1 text-sm">
            <ModeButton active={props.mode === "raw"} onClick={() => props.onModeChange("raw")}>
              Bản gốc
            </ModeButton>
            <ModeButton active={props.mode === "cleaned"} onClick={() => props.onModeChange("cleaned")}>
              Bản đã chuẩn hóa
            </ModeButton>
          </div>
        </div>
        {props.banner}

        {props.segments.length === 0 ? (
          <p className="mt-8 text-center text-sm text-slate-500">{props.emptyText ?? "Chưa có câu nào."}</p>
        ) : null}

        <ol className="mt-4 space-y-4">
          {props.segments.map((segment) => {
            const name =
              props.speakers.find((speaker) => speaker.label === segment.speakerLabel)?.name || segment.speakerLabel;
            const active = props.currentMs >= segment.startMs && props.currentMs < segment.endMs;
            const selected = props.selection?.segmentId === segment.id ? props.selection : null;
            return (
              <li
                key={segment.id}
                data-segment-id={segment.id}
                data-start-ms={segment.startMs}
                data-end-ms={segment.endMs}
                onMouseUp={() => props.onSelect(segment.id)}
                className={`rounded-2xl px-4 py-3 ${active ? "bg-blue-50/80" : "bg-slate-50"} ${
                  segment.marked ? "ring-1 ring-amber-300" : ""
                }`}
              >
                <div className="flex items-baseline justify-between gap-3 text-xs text-slate-500">
                  <span className="font-medium text-slate-700">{name || "Chưa rõ người nói"}</span>
                  <span>{formatMs(segment.startMs)}</span>
                </div>
                <div className="mt-2 text-sm leading-7 text-slate-800">
                  {props.mode === "raw" && !segment.textEdited && segment.words.length > 0 ? (
                    <RawWords segment={segment} currentMs={props.currentMs} onSeek={props.onSeek} />
                  ) : (
                    <p className="cursor-pointer" onClick={() => seekUnlessSelecting(segment.startMs, props.onSeek)}>
                      {shownText(segment, props.mode)}
                    </p>
                  )}
                </div>
                {selected ? (
                  <div className="mt-3">
                    <SelectionToolbar
                      quote={selected.quote}
                      onMark={props.onMark}
                      onUnmark={props.onUnmark}
                      onCreateTask={props.onCreateTask}
                    />
                  </div>
                ) : null}
              </li>
            );
          })}
        </ol>
      </section>

      <div className="fixed inset-x-0 bottom-0 z-20 px-4 pb-4 lg:hidden">
        <AudioPlayerBar
          title={props.title}
          currentMs={props.currentMs}
          durationMs={props.durationMs}
          playing={props.playing}
          docked
          onToggle={props.onTogglePlay}
          onSeek={props.onSeek}
        />
      </div>
    </div>
  );
}

export function shownText(segment: Segment, mode: TranscriptMode) {
  if (segment.textEdited) return segment.textEdited;
  if (mode === "cleaned" && segment.textCleaned) return segment.textCleaned;
  return segment.textRaw;
}

/** Click không kèm vùng bôi đen thì tua. Kiến trúc mục 2.7. */
function seekUnlessSelecting(ms: number, onSeek: (ms: number) => void) {
  const selection = typeof window !== "undefined" ? window.getSelection() : null;
  if (selection && !selection.isCollapsed && selection.toString().trim()) return;
  onSeek(ms);
}

function RawWords({
  segment,
  currentMs,
  onSeek,
}: {
  segment: Segment;
  currentMs: number;
  onSeek: (ms: number) => void;
}) {
  return (
    <p>
      {segment.words.map((word, index) => {
        const spoken = currentMs >= word.startMs && currentMs < word.endMs;
        return (
          <span key={`${word.startMs}-${index}`}>
            <span
              role="button"
              tabIndex={0}
              data-start-ms={word.startMs}
              data-end-ms={word.endMs}
              onClick={() => seekUnlessSelecting(word.startMs, onSeek)}
              onKeyDown={(event) => {
                if (event.key === "Enter") onSeek(word.startMs);
              }}
              className={`cursor-pointer rounded px-0.5 ${spoken ? "bg-blue-600 text-white" : "hover:bg-blue-100"}`}
            >
              {word.text}
            </span>{" "}
          </span>
        );
      })}
    </p>
  );
}

function ModeButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-3 py-1.5 ${active ? "bg-white font-medium text-slate-900 shadow-sm" : "text-slate-500"}`}
    >
      {children}
    </button>
  );
}
