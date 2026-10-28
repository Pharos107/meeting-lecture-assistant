"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { AudioUploader, type UploadRequest } from "@/components/audio-uploader";
import { ApiRequestError, uploadJob } from "@/lib/api";
import { compressToOpus, isOpusFile, OPUS_LIMIT_BYTES, ORIGINAL_LIMIT_BYTES } from "@/lib/ffmpeg-compressor";

export default function NewJobPage() {
  return (
    <AppShell>
      <NewJob />
    </AppShell>
  );
}

function NewJob() {
  const router = useRouter();
  const abortRef = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  /** Nén sang Opus nếu WASM chạy được. Lỗi thì dùng file gốc. */
  async function prepare(file: File, signal: AbortSignal): Promise<File> {
    if (isOpusFile(file)) return file;
    setStatus("Đang nén sang Opus trên trình duyệt");
    setProgress(0);
    try {
      const compressed = await compressToOpus(file, setProgress, signal);
      if (compressed.size <= OPUS_LIMIT_BYTES && compressed.size < file.size) return compressed;
    } catch (caught) {
      if (signal.aborted) throw caught;
      console.warn("Nén trên trình duyệt lỗi, tải file gốc.", caught);
    }
    return file;
  }

  async function submit(request: UploadRequest) {
    setError(null);
    setFieldErrors({});
    const limit = isOpusFile(request.file) ? OPUS_LIMIT_BYTES : ORIGINAL_LIMIT_BYTES;
    if (request.file.size > limit) {
      setFieldErrors({ file: "File vượt quá kích thước cho phép." });
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    try {
      const file = await prepare(request.file, controller.signal);
      const form = new FormData();
      form.append("file", file, file.name);
      form.append("title", request.title || request.file.name.replace(/\.[^.]+$/, "").slice(0, 200));
      if (request.vocabulary) form.append("vocabulary", request.vocabulary);
      if (request.numSpeakers != null) form.append("num_speakers", String(request.numSpeakers));
      setStatus("Đang tải lên");
      setProgress(0);
      const created = await uploadJob(form, setProgress, controller.signal);
      setStatus("Đã tạo job, đang mở trang kết quả");
      router.push(`/jobs/${created.job_id}`);
    } catch (caught) {
      setStatus(null);
      setProgress(null);
      setBusy(false);
      if (controller.signal.aborted) return;
      if (caught instanceof ApiRequestError) {
        setError(caught.message);
        if (caught.fields) setFieldErrors(caught.fields);
      } else {
        setError("Không tạo được job. Thử lại sau.");
      }
    }
  }

  function cancel() {
    abortRef.current?.abort();
    setBusy(false);
    setStatus(null);
    setProgress(null);
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
      <AudioUploader
        busy={busy}
        status={status}
        progress={progress}
        error={error}
        fieldErrors={fieldErrors}
        onSubmit={(request) => void submit(request)}
        onCancel={cancel}
      />
      <div className="space-y-3 rounded-3xl bg-white/80 p-5 text-sm leading-6 text-slate-600 ring-1 ring-sky-100">
        <h2 className="font-semibold text-slate-900">Sau khi tạo job</h2>
        <p>Máy chủ chuẩn hóa âm thanh, cắt theo khoảng lặng, rồi nhận dạng từng đoạn khoảng 20–30 giây. Chữ hiện dần trên trang job.</p>
        <p>Xong phần chữ, hệ thống gán người nói. Bạn đổi tên người nói, sửa câu, đánh dấu, và xuất file khi job sẵn sàng.</p>
        <p>Thuật ngữ gợi ý giúp viết đúng tên riêng. Đây là gợi ý cho model, không phải danh sách bắt buộc.</p>
      </div>
    </div>
  );
}
