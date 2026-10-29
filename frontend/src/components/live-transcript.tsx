"use client";

import type { LiveLine } from "@/components/types";

type LiveTranscriptProps = {
  lines: LiveLine[];
  listening?: boolean;
};

export function LiveTranscript({ lines, listening = true }: LiveTranscriptProps) {
  return (
    <section className="rounded-3xl bg-white p-5 ring-1 ring-sky-100">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-900">Bản nháp trực tiếp</h2>
        <span className="inline-flex items-center gap-2 rounded-full bg-rose-50 px-3 py-1 text-xs font-medium text-rose-700">
          <span className={`h-2 w-2 rounded-full bg-rose-500 ${listening ? "animate-pulse" : ""}`} />
          {listening ? "Đang nghe" : "Đã dừng"}
        </span>
      </div>
      <ol className="mt-4 space-y-3">
        {lines.map((line) => (
          <li
            key={line.id}
            className={`rounded-2xl px-4 py-3 text-sm leading-6 ${
              line.stable ? "bg-slate-50 text-slate-800" : "bg-blue-50 text-blue-900 ring-1 ring-blue-100"
            }`}
          >
            {!line.stable ? <span className="mb-1 block text-[11px] font-medium text-blue-500">Đang cập nhật</span> : null}
            {line.text}
          </li>
        ))}
      </ol>
    </section>
  );
}
