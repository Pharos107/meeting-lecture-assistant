"use client";

import type { MinutesTemplate } from "@/components/types";

type Stamped = { timestamp: string; text: string };
type Action = { timestamp: string; owner: string; task: string; deadline: string };
type Concept = { timestamp: string; term: string; explanation: string };

export type MeetingMinutes = { objective: string; open_issues: Stamped[]; decisions: Stamped[]; actions: Action[] };
export type LectureNotes = { overview: string; concepts: Concept[]; examples: Stamped[]; exam_notes: Stamped[] };

type MinutesViewProps = {
  template: MinutesTemplate;
  result: MeetingMinutes | LectureNotes;
  onSeekStamp: (stamp: string) => void;
};

/** "MM:SS" hoặc "HH:MM:SS" sang mili giây. Số phút được phép vượt 59. */
export function stampToMs(stamp: string): number | null {
  const parts = stamp.split(":").map((part) => Number(part));
  if (parts.length < 2 || parts.some((part) => !Number.isFinite(part))) return null;
  return parts.reduce((total, part) => total * 60 + part, 0) * 1000;
}

export function MinutesView({ template, result, onSeekStamp }: MinutesViewProps) {
  return (
    <section className="rounded-3xl bg-white p-4 ring-1 ring-sky-100">
      <h2 className="text-sm font-semibold text-slate-900">
        {template === "meeting" ? "Biên bản cuộc họp" : "Ghi chú bài giảng"}
      </h2>
      {template === "meeting" ? (
        <MeetingBody minutes={result as MeetingMinutes} onSeekStamp={onSeekStamp} />
      ) : (
        <LectureBody notes={result as LectureNotes} onSeekStamp={onSeekStamp} />
      )}
    </section>
  );
}

function MeetingBody({ minutes, onSeekStamp }: { minutes: MeetingMinutes; onSeekStamp: (stamp: string) => void }) {
  return (
    <div className="mt-2 space-y-3 text-sm text-slate-700">
      {minutes.objective ? <p>{minutes.objective}</p> : null}
      <StampedList title="Vấn đề còn mở" items={minutes.open_issues} onSeekStamp={onSeekStamp} />
      <StampedList title="Quyết định" items={minutes.decisions} onSeekStamp={onSeekStamp} />
      {minutes.actions?.length ? (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Việc cần làm</h3>
          <ul className="mt-1 space-y-1.5">
            {minutes.actions.map((item, index) => (
              <li key={index}>
                <Stamp value={item.timestamp} onSeekStamp={onSeekStamp} /> {item.task}
                {item.owner ? <span className="text-slate-500"> · {item.owner}</span> : null}
                {item.deadline ? <span className="text-slate-500"> · hạn {item.deadline}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function LectureBody({ notes, onSeekStamp }: { notes: LectureNotes; onSeekStamp: (stamp: string) => void }) {
  return (
    <div className="mt-2 space-y-3 text-sm text-slate-700">
      {notes.overview ? <p>{notes.overview}</p> : null}
      {notes.concepts?.length ? (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Khái niệm</h3>
          <ul className="mt-1 space-y-1.5">
            {notes.concepts.map((item, index) => (
              <li key={index}>
                <Stamp value={item.timestamp} onSeekStamp={onSeekStamp} /> <strong>{item.term}</strong>: {item.explanation}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <StampedList title="Ví dụ" items={notes.examples} onSeekStamp={onSeekStamp} />
      <StampedList title="Dặn dò ôn tập" items={notes.exam_notes} onSeekStamp={onSeekStamp} />
    </div>
  );
}

function StampedList({ title, items, onSeekStamp }: { title: string; items: Stamped[]; onSeekStamp: (stamp: string) => void }) {
  if (!items?.length) return null;
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</h3>
      <ul className="mt-1 space-y-1.5">
        {items.map((item, index) => (
          <li key={index}>
            <Stamp value={item.timestamp} onSeekStamp={onSeekStamp} /> {item.text}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Stamp({ value, onSeekStamp }: { value: string; onSeekStamp: (stamp: string) => void }) {
  if (!value) return null;
  return (
    <button
      type="button"
      onClick={() => onSeekStamp(value)}
      className="rounded bg-sky-50 px-1.5 font-mono text-xs text-blue-700 hover:bg-sky-100"
    >
      {value}
    </button>
  );
}
