"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { Eye } from "lucide-react";
import { ReaderSettingsMenu } from "@/components/reader-settings";
import { SelectionPaint } from "@/components/selection-paint";
import { ApiRequestError, fetchShared, type SharedJob } from "@/lib/api";
import { formatMs } from "@/lib/format";
import { useReaderPrefs } from "@/lib/reader-prefs";

/** Trang công khai của liên kết chia sẻ: chỉ đọc, không cần đăng nhập. */
export function SharedTranscript({ token }: { token: string }) {
  const reader = useReaderPrefs();
  const [job, setJob] = useState<SharedJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const content = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchShared(token)
      .then((shared) => {
        setJob(shared);
        document.title = shared.title;
      })
      .catch((caught) => {
        if (caught instanceof ApiRequestError && caught.status === 404) setError("Liên kết không tồn tại hoặc đã bị tắt.");
        else setError(caught instanceof ApiRequestError ? caught.message : "Không tải được bản ghi.");
      });
  }, [token]);

  if (error) return <p className="py-20 text-center text-sm text-slate-600">{error}</p>;
  if (!job) return <p className="py-20 text-center text-sm text-slate-500">Đang tải bản ghi…</p>;

  return (
    <div style={reader.style} className="flex h-dvh flex-col bg-gradient-to-b from-sky-50 via-white to-white">
      <header className="flex items-center gap-3 border-b border-sky-100 bg-white px-4 py-2.5 sm:px-6">
        <Image src="/logo.png" alt="" width={32} height={32} className="size-8 shrink-0 object-contain" />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-bold tracking-tight text-[#0f2744]">{job.title}</h1>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
            <span className="inline-flex items-center gap-1 font-medium text-blue-700">
              <Eye className="size-3.5" />
              Chỉ xem
            </span>
            <span>{new Date(job.created_at).toLocaleString("vi-VN")}</span>
            {job.duration_ms != null ? <span>· {formatMs(job.duration_ms)}</span> : null}
          </div>
        </div>
        <ReaderSettingsMenu reader={reader} />
      </header>

      <main className="reader-surface scrollbar-soft min-h-0 flex-1 overflow-y-auto">
        <div ref={content} className="relative mx-auto w-full max-w-(--reader-width) px-4 pb-6 pt-3 sm:px-6">
          <SelectionPaint root={content} />
          {job.segments.length === 0 ? <p className="mt-8 text-center text-sm text-slate-500">Transcript trống.</p> : null}
          <ol className="mt-2 space-y-3">
            {job.segments.map((segment, index) => (
              <li key={index} className="rounded-2xl bg-slate-50 px-4 py-3">
                <div className="flex items-baseline justify-between gap-3 text-xs text-slate-500">
                  <span className="font-medium text-slate-700">{segment.speaker || "Chưa rõ người nói"}</span>
                  <span>{formatMs(segment.start_ms)}</span>
                </div>
                <p className="reader-text mt-2 text-slate-800">{segment.text}</p>
              </li>
            ))}
          </ol>
        </div>
      </main>
    </div>
  );
}
