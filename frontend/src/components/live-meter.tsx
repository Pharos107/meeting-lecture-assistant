"use client";

import { useEffect, useRef, useState } from "react";
import { LevelProbe } from "@/lib/live-capture";

/** Đầu đo mức âm của một stream. Trả null khi chưa có stream. */
export function useLevelProbe(stream: MediaStream | null) {
  const [probe, setProbe] = useState<LevelProbe | null>(null);
  useEffect(() => {
    if (!stream) {
      setProbe(null);
      return;
    }
    const next = new LevelProbe(stream);
    setProbe(next);
    return () => next.close();
  }, [stream]);
  return probe;
}

const SEGMENTS = 24;
// Từ vạch này trở lên là tiếng to, gần mức vỡ tiếng.
const HOT_FROM = 20;
// Dưới ngưỡng này coi như không có tiếng: ứng với khoảng -45 dBFS.
const SILENT_BELOW = 0.25;

/** Đồng hồ mức âm dạng vạch, cập nhật theo khung hình mà không render lại React. */
export function LevelMeter({ probe }: { probe: LevelProbe | null }) {
  const cells = useRef<(HTMLSpanElement | null)[]>([]);
  const [heard, setHeard] = useState(false);

  useEffect(() => {
    if (!probe) return;
    let frame = 0;
    let peak = 0;
    let loudSince: number | null = null;
    const tick = (now: number) => {
      const level = probe.read();
      // Kim rơi chậm để mắt kịp đọc.
      peak = Math.max(level, peak - 0.015);
      const lit = Math.round(peak * SEGMENTS);
      cells.current.forEach((cell, index) => {
        if (cell) cell.dataset.lit = index < lit ? (index >= HOT_FROM ? "hot" : "on") : "off";
      });
      if (level > SILENT_BELOW) {
        loudSince ??= now;
        if (now - loudSince > 300) setHeard(true);
      } else {
        loudSince = null;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [probe]);

  return (
    <div>
      <div className="flex h-3 gap-[3px]" aria-hidden="true">
        {Array.from({ length: SEGMENTS }, (_, index) => (
          <span
            key={index}
            ref={(node) => {
              cells.current[index] = node;
            }}
            data-lit="off"
            className="flex-1 rounded-[2px] bg-slate-200 transition-colors duration-75 data-[lit=hot]:bg-amber-500 data-[lit=on]:bg-blue-600"
          />
        ))}
      </div>
      <p className="mt-2 text-xs text-slate-500" aria-live="polite">
        {!probe ? "Chưa mở nguồn âm thanh." : heard ? "Đã nghe thấy tiếng." : "Chưa nghe thấy tiếng. Hãy nói thử hoặc bật âm thanh của tab."}
      </p>
    </div>
  );
}

export type TimelineSpan = { startMs: number; endMs: number; stable: boolean };

const SAMPLE_MS = 100;
const BAR_PX = 3;
const TICK_MS = 10_000;

/** Dải sóng âm cuộn theo thời gian ghi. Dưới mỗi đoạn đã thành câu có một vạch, câu đang mở tô xanh. */
export function LevelTimeline({
  probe,
  startedAt,
  spans,
  running,
}: {
  probe: LevelProbe | null;
  startedAt: number | null;
  spans: TimelineSpan[];
  running: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const spansRef = useRef(spans);
  spansRef.current = spans;
  const history = useRef<{ t: number; level: number }[]>([]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || startedAt == null) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    let frame = 0;
    // Lấy mẫu theo đồng hồ riêng: khung hình có thể thưa khi tab chạy nền, sóng vẫn liền.
    const sampler =
      running && probe
        ? window.setInterval(() => {
            history.current.push({ t: Date.now() - startedAt, level: probe.read() });
            if (history.current.length > 4000) history.current.splice(0, 1000);
          }, SAMPLE_MS)
        : 0;

    const draw = () => {
      const now = Date.now();
      const ratio = window.devicePixelRatio || 1;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
        canvas.width = Math.round(width * ratio);
        canvas.height = Math.round(height * ratio);
      }
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);

      const elapsed = running ? now - startedAt : history.current.at(-1)?.t ?? 0;
      const msPerPx = SAMPLE_MS / BAR_PX;
      const toX = (ms: number) => width - (elapsed - ms) / msPerPx;
      const waveTop = 18;
      const laneY = height - 6;
      const waveHeight = laneY - waveTop - 8;
      const middle = waveTop + waveHeight / 2;

      context.font = "11px Segoe UI, system-ui, sans-serif";
      context.textBaseline = "top";
      for (let tick = Math.floor(elapsed / TICK_MS) * TICK_MS; tick >= 0 && toX(tick) > -40; tick -= TICK_MS) {
        const x = Math.round(toX(tick)) + 0.5;
        context.fillStyle = "#e2e8f0";
        context.fillRect(x, waveTop, 1, waveHeight);
        context.fillStyle = "#94a3b8";
        const seconds = Math.round(tick / 1000);
        context.fillText(`${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`, x + 4, 2);
      }

      context.fillStyle = "#0f2744";
      for (const sample of history.current) {
        const x = toX(sample.t);
        if (x < -BAR_PX) continue;
        const bar = Math.max(1, sample.level * sample.level * waveHeight);
        context.globalAlpha = sample.level > SILENT_BELOW ? 0.85 : 0.25;
        context.fillRect(x - BAR_PX + 1, middle - bar / 2, BAR_PX - 1, bar);
      }
      context.globalAlpha = 1;

      context.fillStyle = "#e2e8f0";
      context.fillRect(0, laneY, width, 3);
      for (const span of spansRef.current) {
        const left = Math.max(0, toX(span.startMs));
        const right = Math.min(width, toX(Math.max(span.endMs, span.startMs + 200)));
        if (right <= 0 || left >= width) continue;
        context.fillStyle = span.stable ? "#64748b" : "#2563eb";
        context.fillRect(left, laneY, Math.max(2, right - left - 2), 3);
      }

      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      window.clearInterval(sampler);
    };
  }, [probe, startedAt, running]);

  // Canvas nằm tuyệt đối trong khung: kích thước bộ đệm theo devicePixelRatio không đẩy khung rộng ra.
  return (
    <div className="relative h-24 w-full min-w-0">
      <canvas
        ref={canvasRef}
        role="img"
        aria-label="Sóng âm của phần đang ghi. Vạch dưới sóng là những đoạn đã thành câu."
        className="absolute inset-0 size-full"
      />
    </div>
  );
}
