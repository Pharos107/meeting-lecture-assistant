"use client";

import { Fragment, useRef, useState, type ReactNode } from "react";
import { Pencil } from "lucide-react";
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
  /** Bật nút sửa câu. Chỉ bật khi job cho sửa: `ready`, hoặc `failed` với pass 1. */
  editable?: boolean;
  /** Lưu chữ sửa của một câu, `null` là về bản gốc. Trả true khi đã lưu. */
  onSaveText?: (segmentId: string, text: string | null) => Promise<boolean>;
};

/** Cột giữa của trang job: phần chữ tự cuộn, tiêu đề và trình phát đứng yên. */
export function TranscriptLayout(props: TranscriptLayoutProps) {
  const scroller = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(segmentId: string, text: string | null) {
    if (!props.onSaveText) return;
    setSaving(true);
    const saved = await props.onSaveText(segmentId, text);
    setSaving(false);
    if (saved) setEditingId(null);
  }

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
              const editing = editingId === segment.id;
              const selected = !editing && props.selection?.segmentId === segment.id ? props.selection : null;
              const coverage = selected ? markCoverage(segment, selected) : null;
              return (
                <li
                  key={segment.id}
                  data-segment-id={segment.id}
                  data-start-ms={segment.startMs}
                  data-end-ms={segment.endMs}
                  onMouseUp={() => {
                    if (!editing) props.onSelect(segment.id);
                  }}
                  className={`group relative rounded-2xl px-4 py-3 transition-shadow ${active ? "bg-blue-50/80" : "bg-slate-50"} ${
                    props.jumpedId === segment.id ? "ring-2 ring-blue-400" : ""
                  }`}
                >
                  <div className="flex items-baseline justify-between gap-3 text-xs text-slate-500">
                    <span className="font-medium text-slate-700">{name || "Chưa rõ người nói"}</span>
                    <span className="flex items-center gap-2">
                      {segment.textEdited ? (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800">
                          Đã sửa
                        </span>
                      ) : null}
                      {props.editable && props.onSaveText && !editing ? (
                        <button
                          type="button"
                          onClick={() => setEditingId(segment.id)}
                          aria-label="Sửa câu"
                          title="Sửa câu"
                          className="flex size-6 items-center justify-center rounded-full text-slate-500 opacity-0 transition-opacity hover:bg-slate-200 hover:text-slate-800 focus-visible:opacity-100 group-hover:opacity-100 pointer-coarse:opacity-100"
                        >
                          <Pencil className="size-3.5" />
                        </button>
                      ) : null}
                      <span>{formatMs(segment.startMs)}</span>
                    </span>
                  </div>
                  <div className="reader-text mt-2 text-slate-800">
                    {editing ? (
                      <SegmentEditor
                        segment={segment}
                        saving={saving}
                        onCancel={() => setEditingId(null)}
                        onSave={(text) => void save(segment.id, text)}
                      />
                    ) : hasWordTiming(segment) ? (
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

/** Gộp khoảng trắng như chữ của Whisper. Trả `null` khi chữ trùng bản gốc, để không lưu bản sửa thừa. */
export function editedTextFor(segment: Segment, draft: string): string | null {
  const text = draft.replace(/\s+/g, " ").trim();
  return text === segment.textRaw.trim() ? null : text;
}

function SegmentEditor({
  segment,
  saving,
  onCancel,
  onSave,
}: {
  segment: Segment;
  saving: boolean;
  onCancel: () => void;
  onSave: (text: string | null) => void;
}) {
  const [draft, setDraft] = useState(shownText(segment));
  const next = editedTextFor(segment, draft);
  const empty = !draft.trim();
  const unchanged = next === (segment.textEdited || null);

  function submit() {
    if (saving || empty) return;
    if (unchanged) onCancel();
    else onSave(next);
  }

  return (
    <div>
      <textarea
        autoFocus
        value={draft}
        disabled={saving}
        aria-label="Chữ của câu"
        onChange={(event) => setDraft(event.target.value)}
        onFocus={(event) => {
          const end = event.currentTarget.value.length;
          event.currentTarget.setSelectionRange(end, end);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onCancel();
          } else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            submit();
          }
        }}
        className="block min-h-20 w-full resize-y rounded-xl border border-slate-300 bg-white px-3 py-2 text-[length:inherit] leading-[inherit] text-slate-800 outline-none field-sizing-content focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:opacity-60"
      />
      {empty ? <p className="mt-1 text-xs text-rose-600">Câu không được để trống.</p> : null}
      <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
        <button
          type="button"
          onClick={submit}
          disabled={saving || empty}
          className="h-8 rounded-full bg-blue-600 px-4 font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? "Đang lưu…" : "Lưu"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={saving}
          className="h-8 rounded-full px-3 text-slate-600 hover:bg-slate-200 disabled:opacity-50"
        >
          Hủy
        </button>
        {segment.textEdited ? (
          <button
            type="button"
            onClick={() => onSave(null)}
            disabled={saving}
            title={`Bản gốc: ${segment.textRaw}`}
            className="h-8 rounded-full px-3 text-slate-600 hover:bg-slate-200 disabled:opacity-50"
          >
            Về bản gốc
          </button>
        ) : null}
        <span className="ml-auto text-xs text-slate-500">Ctrl + Enter để lưu, Esc để hủy</span>
      </div>
      {!segment.textEdited && segment.words.length > 0 ? (
        <p className="mt-1 text-xs text-slate-500">
          Câu đã sửa hiện thành một khối, bấm vào sẽ tua về đầu câu thay vì từng từ.
        </p>
      ) : null}
    </div>
  );
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
