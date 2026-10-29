"use client";

import { useRef, useState } from "react";

const ACCEPT = ".mp3,.wav,.m4a,.aac,.ogg,.opus,.flac,.mp4,.mkv,.webm,.mov";
const MAX_VOCAB = 800;
const MAX_TITLE = 200;

export type UploadRequest = {
  file: File;
  title: string;
  vocabulary: string;
  numSpeakers: number | null;
};

type AudioUploaderProps = {
  busy?: boolean;
  status?: string | null;
  progress?: number | null;
  error?: string | null;
  fieldErrors?: Record<string, string>;
  onSubmit?: (request: UploadRequest) => void;
  onCancel?: () => void;
};

export function AudioUploader({ busy = false, status, progress, error, fieldErrors = {}, onSubmit, onCancel }: AudioUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [vocabulary, setVocabulary] = useState("");
  const [speakers, setSpeakers] = useState("");
  const [dragging, setDragging] = useState(false);

  function takeFile(next: File | undefined) {
    if (!next || busy) return;
    setFile(next);
  }

  const speakersValue = speakers.trim() === "" ? null : Number(speakers);
  const speakersInvalid = speakersValue !== null && (!Number.isInteger(speakersValue) || speakersValue < 1 || speakersValue > 20);

  return (
    <form
      className="rounded-3xl bg-white p-6 shadow-[0_24px_60px_-28px_rgba(37,99,235,0.55)] ring-1 ring-sky-100"
      onSubmit={(event) => {
        event.preventDefault();
        if (!file || busy || speakersInvalid) return;
        onSubmit?.({ file, title: title.trim(), vocabulary: vocabulary.trim(), numSpeakers: speakersValue });
      }}
    >
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Tải file ghi âm</h2>
        <p className="mt-1 max-w-md text-sm leading-6 text-slate-500">
          Audio hoặc video. Trình duyệt nén sang Opus khi làm được. Trần file gốc 500 MB, bản Opus 64 MB, thời lượng 3 giờ.
        </p>
      </div>

      <button
        type="button"
        disabled={busy}
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
        className={`mt-5 flex w-full flex-col items-center rounded-2xl border border-dashed px-6 py-10 text-center transition disabled:cursor-not-allowed ${
          dragging ? "border-blue-500 bg-blue-50" : "border-sky-200 bg-sky-50/70"
        }`}
      >
        <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white text-blue-600 shadow-sm ring-1 ring-sky-100">
          <WaveIcon />
        </span>
        <span className="mt-3 max-w-full truncate text-sm font-medium text-slate-800">
          {file ? file.name : "Kéo file vào đây hoặc bấm để chọn"}
        </span>
        <span className="mt-1 text-xs text-slate-500">
          {file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : "mp3, wav, m4a, mp4, mkv, webm…"}
        </span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="sr-only"
        onChange={(event) => takeFile(event.target.files?.[0])}
      />
      {fieldErrors.file ? <p className="mt-2 text-xs text-rose-600">{fieldErrors.file}</p> : null}

      <label className="mt-5 block text-sm font-medium text-slate-700" htmlFor="title">
        Tiêu đề
        <input
          id="title"
          value={title}
          maxLength={MAX_TITLE}
          disabled={busy}
          placeholder={file ? file.name.replace(/\.[^.]+$/, "") : "Mặc định lấy tên file"}
          onChange={(event) => setTitle(event.target.value)}
          className="mt-2 w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm font-normal text-slate-800 outline-none ring-blue-500 focus:bg-white focus:ring-2"
        />
      </label>
      {fieldErrors.title ? <p className="mt-1 text-xs text-rose-600">{fieldErrors.title}</p> : null}

      <label className="mt-4 block text-sm font-medium text-slate-700" htmlFor="vocabulary">
        Thuật ngữ gợi ý
        <textarea
          id="vocabulary"
          value={vocabulary}
          maxLength={MAX_VOCAB}
          disabled={busy}
          placeholder="Tên riêng, thuật ngữ hay xuất hiện, cách nhau bằng dấu phẩy"
          onChange={(event) => setVocabulary(event.target.value)}
          rows={3}
          className="mt-2 w-full resize-none rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-normal text-slate-800 outline-none ring-blue-500 focus:bg-white focus:ring-2"
        />
      </label>
      <div className="mt-1 flex justify-between text-xs">
        <span className="text-rose-600">{fieldErrors.vocabulary ?? ""}</span>
        <span className="text-slate-400">
          {vocabulary.length}/{MAX_VOCAB}
        </span>
      </div>

      <label className="mt-3 block text-sm font-medium text-slate-700" htmlFor="num_speakers">
        Số người nói <span className="font-normal text-slate-400">(không bắt buộc)</span>
        <input
          id="num_speakers"
          inputMode="numeric"
          value={speakers}
          disabled={busy}
          placeholder="Tự đoán"
          onChange={(event) => setSpeakers(event.target.value.replace(/[^0-9]/g, ""))}
          className="mt-2 w-32 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm font-normal text-slate-800 outline-none ring-blue-500 focus:bg-white focus:ring-2"
        />
      </label>
      {speakersInvalid || fieldErrors.num_speakers ? (
        <p className="mt-1 text-xs text-rose-600">{fieldErrors.num_speakers ?? "Số người nói phải từ 1 đến 20."}</p>
      ) : null}

      {status ? (
        <div className="mt-5">
          <div className="flex justify-between text-xs text-slate-600">
            <span>{status}</span>
            {progress != null ? <span>{Math.round(progress * 100)}%</span> : null}
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-sky-100">
            <div
              className={`h-full rounded-full bg-blue-600 transition-[width] ${progress == null ? "w-1/3 animate-pulse" : ""}`}
              style={progress != null ? { width: `${Math.round(progress * 100)}%` } : undefined}
            />
          </div>
        </div>
      ) : null}
      {error ? <p className="mt-4 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p> : null}

      <div className="mt-5 flex gap-3">
        <button
          type="submit"
          disabled={!file || busy || speakersInvalid}
          className="flex-1 rounded-full bg-gradient-to-r from-blue-500 to-blue-600 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-500/30 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Đang xử lý…" : "Tạo job"}
        </button>
        {busy && onCancel ? (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-full border border-slate-200 px-5 py-3 text-sm font-medium text-slate-600 hover:bg-slate-50"
          >
            Hủy
          </button>
        ) : null}
      </div>
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
