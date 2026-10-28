"use client";

import { formatMs } from "@/lib/format";

type AudioPlayerBarProps = {
  title: string;
  currentMs: number;
  durationMs: number;
  playing: boolean;
  docked?: boolean;
  onToggle: () => void;
  onSeek: (ms: number) => void;
};

export function AudioPlayerBar({
  title,
  currentMs,
  durationMs,
  playing,
  docked = false,
  onToggle,
  onSeek,
}: AudioPlayerBarProps) {
  const ratio = durationMs > 0 ? Math.min(1, currentMs / durationMs) : 0;

  return (
    <div
      className={`rounded-3xl bg-white p-4 ring-1 ring-sky-100 ${
        docked ? "shadow-[0_-12px_40px_-20px_rgba(15,23,42,0.45)]" : "shadow-sm"
      }`}
    >
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onToggle}
          aria-label={playing ? "Tạm dừng" : "Phát"}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-blue-700 text-white"
        >
          {playing ? <PauseIcon /> : <PlayIcon />}
        </button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-slate-900">{title}</p>
          <p className="text-xs text-slate-500">
            {formatMs(currentMs)} / {formatMs(durationMs)}
          </p>
        </div>
      </div>
      <label className="mt-3 block">
        <span className="sr-only">Tua</span>
        <input
          type="range"
          min={0}
          max={durationMs}
          value={Math.min(currentMs, durationMs)}
          onChange={(event) => onSeek(Number(event.target.value))}
          className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-sky-100 accent-blue-600"
          style={{
            background: `linear-gradient(90deg, #2563eb ${ratio * 100}%, #e0f2fe ${ratio * 100}%)`,
          }}
        />
      </label>
    </div>
  );
}

function PlayIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M5 3.5v9l8-4.5-8-4.5z" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M4 3h3v10H4zM9 3h3v10H9z" />
    </svg>
  );
}
