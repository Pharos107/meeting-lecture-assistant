"use client";

import type { ReactNode } from "react";
import { SelectionToolbar } from "@/components/selection-toolbar";
import type { Segment, Speaker } from "@/components/types";
import { formatMs } from "@/lib/format";

export type TranscriptSelection = { segmentId: string; quote: string };

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
  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <div className="scrollbar-soft min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-4 pb-6 pt-3 sm:px-6">
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
              return (
                <li
                  key={segment.id}
                  data-segment-id={segment.id}
                  data-start-ms={segment.startMs}
                  data-end-ms={segment.endMs}
                  onMouseUp={() => props.onSelect(segment.id)}
                  className={`rounded-2xl px-4 py-3 transition-shadow ${active ? "bg-blue-50/80" : "bg-slate-50"} ${
                    props.jumpedId === segment.id ? "ring-2 ring-blue-400" : segment.marked ? "ring-1 ring-amber-300" : ""
                  }`}
                >
                  <div className="flex items-baseline justify-between gap-3 text-xs text-slate-500">
                    <span className="font-medium text-slate-700">{name || "Chưa rõ người nói"}</span>
                    <span>{formatMs(segment.startMs)}</span>
                  </div>
                  <div className="mt-2 text-sm leading-7 text-slate-800">
                    {!segment.textEdited && segment.words.length > 0 ? (
                      <RawWords segment={segment} currentMs={props.currentMs} onSeek={props.onSeek} />
                    ) : (
                      <p className="cursor-pointer" onClick={() => seekUnlessSelecting(segment.startMs, props.onSeek)}>
                        {shownText(segment)}
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
        </div>
      </div>
    </section>
  );
}

export function shownText(segment: Segment) {
  return segment.textEdited || segment.textRaw;
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
