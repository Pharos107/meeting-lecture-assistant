"use client";

import { Fragment, useRef, type ReactNode } from "react";
import { SelectionPaint } from "@/components/selection-paint";
import { FloatingSelectionToolbar } from "@/components/selection-toolbar";
import type { Segment, SegmentMark, Speaker, Word } from "@/components/types";
import { formatMs } from "@/lib/format";

export type TranscriptSelection = { segmentId: string; quote: string; startMs: number; endMs: number };

type TranscriptLayoutProps = {
  speakers: Speaker[];
  segments: Segment[];
  currentMs: number;
  selection: TranscriptSelection | null;
  /** Câu vừa được nhảy tới từ ngoài transcript, tô viền một lúc để mắt tìm thấy. */
  jumpedId?: string | null;
  banner?: ReactNode;
  emptyText?: string;
  onSeek: (ms: number) => void;
  onSelect: (segmentId: string) => void;
  onMark: () => void;
  onUnmark: () => void;
  onCreateTask: () => void;
};

/** Cột giữa của trang job: phần chữ tự cuộn, tiêu đề và trình phát đứng yên. */
export function TranscriptLayout(props: TranscriptLayoutProps) {
  const scroller = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  return (
    <section className="reader-surface flex min-h-0 flex-1 flex-col">
      <div ref={scroller} className="scrollbar-soft min-h-0 flex-1 overflow-y-auto">
        <div ref={content} className="relative mx-auto w-full max-w-(--reader-width) px-4 pb-6 pt-3 sm:px-6">
          <SelectionPaint root={content} />
          {props.banner}

          {props.segments.length === 0 ? (
            <p className="mt-8 text-center text-sm text-slate-500">{props.emptyText ?? "Chưa có câu nào."}</p>
          ) : null}

          <ol className="mt-2 space-y-3">
            {props.segments.map((segment) => {
              const name =
                props.speakers.find((speaker) => speaker.label === segment.speakerLabel)?.name || segment.speakerLabel;
              const active = props.currentMs >= segment.startMs && props.currentMs < segment.endMs;
              const selected = props.selection?.segmentId === segment.id ? props.selection : null;
              const coverage = selected ? markCoverage(segment, selected) : null;
              return (
                <li
                  key={segment.id}
                  data-segment-id={segment.id}
                  data-start-ms={segment.startMs}
                  data-end-ms={segment.endMs}
                  onMouseUp={() => props.onSelect(segment.id)}
                  className={`relative rounded-2xl px-4 py-3 transition-shadow ${active ? "bg-blue-50/80" : "bg-slate-50"} ${
                    props.jumpedId === segment.id ? "ring-2 ring-blue-400" : ""
                  }`}
                >
                  <div className="flex items-baseline justify-between gap-3 text-xs text-slate-500">
                    <span className="font-medium text-slate-700">{name || "Chưa rõ người nói"}</span>
                    <span>{formatMs(segment.startMs)}</span>
                  </div>
                  <div className="reader-text mt-2 text-slate-800">
                    {hasWordTiming(segment) ? (
                      <RawWords segment={segment} currentMs={props.currentMs} onSeek={props.onSeek} />
                    ) : (
                      <p className="cursor-pointer" onClick={() => seekUnlessSelecting(segment.startMs, props.onSeek)}>
                        <MarkedText text={shownText(segment)} marks={segment.marks} />
                      </p>
                    )}
                  </div>
                  {selected && coverage ? (
                    <FloatingSelectionToolbar
                      boundary={scroller}
                      selection={selected}
                      canMark={coverage.unmarked}
                      canUnmark={coverage.marked}
                      onMark={props.onMark}
                      onUnmark={props.onUnmark}
                      onCreateTask={props.onCreateTask}
                    />
                  ) : null}
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </section>
  );
}

export function shownText(segment: Segment) {
  return segment.textEdited || segment.textRaw;
}

function hasWordTiming(segment: Segment) {
  return !segment.textEdited && segment.words.length > 0;
}

function wordIsMarked(word: Word, marks: SegmentMark[]) {
  return marks.some((mark) => word.startMs < mark.endMs && word.endMs > mark.startMs);
}

/** Các khoảng [đầu, cuối) của đoạn đã đánh dấu trong chữ, cho câu không có mốc từng từ. */
function markedRanges(text: string, marks: SegmentMark[]) {
  const ranges = marks.flatMap((mark) => {
    const start = text.indexOf(mark.quote);
    return start < 0 ? [] : [[start, start + mark.quote.length] as const];
  });
  const merged: [number, number][] = [];
  for (const [start, end] of [...ranges].sort((first, second) => first[0] - second[0])) {
    const last = merged[merged.length - 1];
    if (last && start <= last[1]) last[1] = Math.max(last[1], end);
    else merged.push([start, end]);
  }
  return merged;
}

/** Vùng chọn có chữ đã đánh dấu không, và còn chữ chưa đánh dấu không. */
function markCoverage(segment: Segment, selection: TranscriptSelection) {
  if (hasWordTiming(segment)) {
    const words = segment.words.filter((word) => word.startMs < selection.endMs && word.endMs > selection.startMs);
    const marked = words.filter((word) => wordIsMarked(word, segment.marks)).length;
    return { marked: marked > 0, unmarked: marked < words.length };
  }
  const text = shownText(segment);
  const start = text.indexOf(selection.quote);
  const end = start + selection.quote.length;
  const ranges = markedRanges(text, segment.marks);
  return {
    marked: ranges.some(([first, last]) => first < end && last > start),
    unmarked: !ranges.some(([first, last]) => first <= start && last >= end),
  };
}

/** Các từ liền nhau cùng trạng thái, để cả cụm đã đánh dấu tô thành một dải. */
function wordRuns(segment: Segment) {
  const runs: { marked: boolean; words: Word[] }[] = [];
  for (const word of segment.words) {
    const marked = wordIsMarked(word, segment.marks);
    const last = runs[runs.length - 1];
    if (last && last.marked === marked) last.words.push(word);
    else runs.push({ marked, words: [word] });
  }
  return runs;
}

/** Click không kèm vùng bôi đen thì tua. Kiến trúc mục 2.7. */
function seekUnlessSelecting(ms: number, onSeek: (ms: number) => void) {
  const selection = typeof window !== "undefined" ? window.getSelection() : null;
  if (selection && !selection.isCollapsed && selection.toString().trim()) return;
  onSeek(ms);
}

function MarkedText({ text, marks }: { text: string; marks: SegmentMark[] }) {
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const [start, end] of markedRanges(text, marks)) {
    parts.push(text.slice(cursor, start));
    parts.push(
      <mark key={start} className="reader-mark">
        {text.slice(start, end)}
      </mark>,
    );
    cursor = end;
  }
  parts.push(text.slice(cursor));
  return <>{parts}</>;
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
      {wordRuns(segment).map((run, runIndex) => {
        const words = run.words.map((word, index) => {
          const spoken = currentMs >= word.startMs && currentMs < word.endMs;
          return (
            <Fragment key={`${word.startMs}-${index}`}>
              {index > 0 ? " " : null}
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
              </span>
            </Fragment>
          );
        });
        return (
          <Fragment key={runIndex}>
            {run.marked ? <mark className="reader-mark">{words}</mark> : words}{" "}
          </Fragment>
        );
      })}
    </p>
  );
}
