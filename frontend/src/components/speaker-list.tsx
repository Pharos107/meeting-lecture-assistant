"use client";

import type { Speaker } from "@/components/types";

const COLORS = ["#2563eb", "#0f766e", "#c2410c", "#7c3aed", "#be123c"];

type SpeakerListProps = {
  speakers: Speaker[];
  onRename: (label: string, name: string) => void;
};

export function SpeakerList({ speakers, onRename }: SpeakerListProps) {
  return (
    <section className="rounded-3xl bg-white p-4 ring-1 ring-sky-100">
      <h2 className="text-sm font-semibold text-slate-900">Người nói</h2>
      <ul className="mt-3 space-y-3">
        {speakers.map((speaker, index) => (
          <li key={speaker.label} className="flex items-center gap-3">
            <span
              className="h-3 w-3 shrink-0 rounded-full"
              style={{ background: COLORS[index % COLORS.length] }}
              aria-hidden="true"
            />
            <div className="min-w-0 flex-1">
              <label className="block text-[11px] text-slate-400" htmlFor={`speaker-${speaker.label}`}>
                {speaker.label}
                {speaker.source === "voice_profile" ? " · hồ sơ giọng" : ""}
                {speaker.source === "manual" ? " · sửa tay" : ""}
              </label>
              <input
                id={`speaker-${speaker.label}`}
                value={speaker.name}
                onChange={(event) => onRename(speaker.label, event.target.value)}
                className="mt-0.5 w-full rounded-xl border border-transparent bg-slate-50 px-2 py-1.5 text-sm text-slate-800 outline-none focus:border-blue-200 focus:bg-white"
              />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
