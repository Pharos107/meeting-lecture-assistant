"use client";

import { RotateCcw, RotateCw } from "lucide-react";
import { formatMs } from "@/lib/format";

const SKIP_MS = 5_000;

type AudioPlayerBarProps = {
  currentMs: number;
  durationMs: number;
  playing: boolean;
  rate?: number;
  marks?: number[];
  onToggle: () => void;
  onSeek: (ms: number) => void;
  onCycleRate?: () => void;
};

export function AudioPlayerBar({
  currentMs,
  durationMs,
  playing,
  rate = 1,
  marks = [],
  onToggle,
  onSeek,
  onCycleRate,
}: AudioPlayerBarProps) {
  const ratio = durationMs > 0 ? Math.min(1, currentMs / durationMs) : 0;

  return (
    <div className="flex items-center gap-2 border-t border-sky-100 bg-white px-3 py-2 sm:gap-3 sm:px-4">
      <button
        type="button"
        onClick={() => onSeek(Math.max(0, currentMs - SKIP_MS))}
        aria-label="Lùi 5 giây"
        title="Lùi 5 giây"
        className="hidden rounded-full p-1.5 text-slate-500 hover:bg-sky-50 sm:block"
      >
        <RotateCcw className="size-4" />
      </button>
      <button
        type="button"
        onClick={onToggle}
        aria-label={playing ? "Tạm dừng" : "Phát"}
        className="flex size-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-blue-700 text-white"
      >
        {playing ? <PauseIcon /> : <PlayIcon />}
      </button>
      <button
        type="button"
        onClick={() => onSeek(Math.min(durationMs, currentMs + SKIP_MS))}
        aria-label="Tới 5 giây"
        title="Tới 5 giây"
        className="hidden rounded-full p-1.5 text-slate-500 hover:bg-sky-50 sm:block"
      >
        <RotateCw className="size-4" />
      </button>
      <span className="shrink-0 text-xs tabular-nums text-slate-500">{formatMs(currentMs)}</span>
      <label className="relative flex min-w-0 flex-1 items-center">
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
        {durationMs > 0
          ? marks.map((ms, index) => (
              <span
                key={`${ms}-${index}`}
                aria-hidden="true"
                className="pointer-events-none absolute top-1/2 h-3 w-0.5 -translate-y-1/2 rounded-full bg-amber-400"
                style={{ left: `${(Math.min(ms, durationMs) / durationMs) * 100}%` }}
              />
            ))
          : null}
      </label>
      <span className="shrink-0 text-xs tabular-nums text-slate-500">{formatMs(durationMs)}</span>
      {onCycleRate ? (
        <button
          type="button"
          onClick={onCycleRate}
          aria-label={`Tốc độ phát ${rate} lần`}
          title="Đổi tốc độ phát"
          className="shrink-0 rounded-lg border border-slate-200 px-1.5 py-0.5 text-xs tabular-nums text-slate-600 hover:border-blue-300"
        >
          {rate}x
        </button>
      ) : null}
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
