"use client";

import { useRef, useState } from "react";

const ACCEPT = ".mp3,.wav,.m4a,.aac,.ogg,.opus,.flac,.mp4,.mkv,.webm,.mov";
const MAX_VOCAB = 800;

type AudioUploaderProps = {
  onCreate?: (fileName: string, vocabulary: string) => void;
};

export function AudioUploader({ onCreate }: AudioUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [vocabulary, setVocabulary] = useState("Lê Hải Đăng, pyannote, biên bản");
  const [dragging, setDragging] = useState(false);

  function takeFile(file: File | undefined) {
    if (!file) return;
    setFileName(file.name);
  }

  return (
    <form
      className="rounded-3xl bg-white p-6 shadow-[0_24px_60px_-28px_rgba(37,99,235,0.55)] ring-1 ring-sky-100"
      onSubmit={(event) => {
        event.preventDefault();
        if (fileName) onCreate?.(fileName, vocabulary.trim());
      }}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Tải file ghi âm</h2>
          <p className="mt-1 max-w-md text-sm leading-6 text-slate-500">
            Audio hoặc video. Trình duyệt nén sang Opus khi làm được. Trần file gốc 500 MB, bản Opus 64 MB.
          </p>
        </div>
      </div>

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          takeFile(event.dataTransfer.files[0]);
        }}
        className={`mt-5 flex w-full flex-col items-center rounded-2xl border border-dashed px-6 py-10 text-center transition ${
          dragging ? "border-blue-500 bg-blue-50" : "border-sky-200 bg-sky-50/70"
        }`}
      >
        <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white text-blue-600 shadow-sm ring-1 ring-sky-100">
          <WaveIcon />
        </span>
        <span className="mt-3 text-sm font-medium text-slate-800">
          {fileName ?? "Kéo file vào đây hoặc bấm để chọn"}
        </span>
        <span className="mt-1 text-xs text-slate-500">mp3, wav, m4a, mp4, mkv, webm…</span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="sr-only"
        onChange={(event) => takeFile(event.target.files?.[0])}
      />

      <label className="mt-5 block text-sm font-medium text-slate-700" htmlFor="vocabulary">
        Thuật ngữ gợi ý
        <textarea
          id="vocabulary"
          value={vocabulary}
          maxLength={MAX_VOCAB}
          onChange={(event) => setVocabulary(event.target.value)}
          rows={3}
          className="mt-2 w-full resize-none rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-normal text-slate-800 outline-none ring-blue-500 focus:bg-white focus:ring-2"
        />
      </label>
      <div className="mt-1 text-right text-xs text-slate-400">
        {vocabulary.length}/{MAX_VOCAB}
      </div>

      <button
        type="submit"
        disabled={!fileName}
        className="mt-4 w-full rounded-full bg-gradient-to-r from-blue-500 to-blue-600 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-500/30 disabled:cursor-not-allowed disabled:opacity-50"
      >
        Tạo job
      </button>
    </form>
  );
}

function WaveIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden="true">
      <path d="M3 11h2M7 7v8M11 4v14M15 8v6M19 11h-2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
