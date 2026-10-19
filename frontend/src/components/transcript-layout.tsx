"use client";

import { AiActionPanel } from "@/components/ai-action-panel";
import { AudioPlayerBar } from "@/components/audio-player-bar";
import { SelectionToolbar } from "@/components/selection-toolbar";
import { SpeakerList } from "@/components/speaker-list";
import type { ExportFormat, MinutesTemplate, Segment, Speaker, TranscriptMode } from "@/components/types";
import { formatMs } from "@/lib/format";

type TranscriptLayoutProps = {
  title: string;
  speakers: Speaker[];
  segments: Segment[];
  mode: TranscriptMode;
  currentMs: number;
  durationMs: number;
  playing: boolean;
  selectedId: string | null;
  notice: string | null;
  onModeChange: (mode: TranscriptMode) => void;
  onTogglePlay: () => void;
  onSeek: (ms: number) => void;
  onRenameSpeaker: (label: string, name: string) => void;
  onSelect: (segmentId: string, quote: string) => void;
  onMark: () => void;
  onUnmark: () => void;
  onCreateTask: () => void;
  onNormalize: () => void;
  onMinutes: (template: MinutesTemplate) => void;
  onExport: (format: ExportFormat) => void;
};

export function TranscriptLayout(props: TranscriptLayoutProps) {
  const selected = props.segments.find((segment) => segment.id === props.selectedId) ?? null;
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
    <div className="lg:grid lg:grid-cols-[minmax(320px,38%)_1fr] lg:items-start lg:gap-6">
      <aside className="hidden space-y-4 lg:sticky lg:top-6 lg:block">
        {player}
        <SpeakerList speakers={props.speakers} onRename={props.onRenameSpeaker} />
        <AiActionPanel
          notice={props.notice}
          onNormalize={props.onNormalize}
          onMinutes={props.onMinutes}
          onExport={props.onExport}
        />
      </aside>

      <section className="rounded-3xl bg-white p-5 pb-28 ring-1 ring-sky-100 lg:pb-5">
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

        <ol className="mt-4 space-y-4">
          {props.segments.map((segment) => {
            const name = props.speakers.find((speaker) => speaker.label === segment.speakerLabel)?.name || segment.speakerLabel;
            const active = props.currentMs >= segment.startMs && props.currentMs < segment.endMs;
            return (
              <li
                key={segment.id}
                data-segment-id={segment.id}
                data-start-ms={segment.startMs}
                className={`rounded-2xl px-4 py-3 ${active ? "bg-blue-50/80" : "bg-slate-50"} ${
                  segment.marked ? "ring-1 ring-amber-300" : ""
                }`}
              >
                <div className="flex items-baseline justify-between gap-3 text-xs text-slate-500">
                  <span className="font-medium text-slate-700">{name}</span>
                  <span>{formatMs(segment.startMs)}</span>
                </div>
                <div className="mt-2 text-sm leading-7 text-slate-800">
                  {props.mode === "raw" && !segment.textEdited ? (
                    <RawWords segment={segment} currentMs={props.currentMs} onSeek={props.onSeek} onSelect={props.onSelect} />
                  ) : (
                    <button
                      type="button"
                      className="text-left"
                      onClick={() => props.onSeek(segment.startMs)}
                      onMouseUp={() => props.onSelect(segment.id, shownText(segment, props.mode))}
                    >
                      {shownText(segment, props.mode)}
                    </button>
                  )}
                </div>
                {selected?.id === segment.id ? (
                  <div className="mt-3">
                    <SelectionToolbar
                      quote={shownText(segment, props.mode)}
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

function shownText(segment: Segment, mode: TranscriptMode) {
  if (segment.textEdited) return segment.textEdited;
  if (mode === "cleaned" && segment.textCleaned) return segment.textCleaned;
  return segment.textRaw;
}

function RawWords({
  segment,
  currentMs,
  onSeek,
  onSelect,
}: {
  segment: Segment;
  currentMs: number;
  onSeek: (ms: number) => void;
  onSelect: (segmentId: string, quote: string) => void;
}) {
  return (
    <p onMouseUp={() => onSelect(segment.id, segment.textRaw)}>
      {segment.words.map((word, index) => {
        const spoken = currentMs >= word.startMs && currentMs < word.endMs;
        return (
          <button
            key={`${word.startMs}-${index}`}
            type="button"
            data-end-ms={word.endMs}
            onClick={() => onSeek(word.startMs)}
            className={`mr-1 rounded px-0.5 ${spoken ? "bg-blue-600 text-white" : "hover:bg-blue-100"}`}
          >
            {word.text}
          </button>
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
