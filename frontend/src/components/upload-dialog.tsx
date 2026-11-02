"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { AudioUploader } from "@/components/audio-uploader";
import { uploadLimitError, useWorkspace } from "@/components/workspace-provider";

/** Tạo bản ghi ngay trên trang đang xem. Bấm bắt đầu thì việc nén và tải lên chạy nền. */
export function UploadDialog() {
  const { uploadOpen, closeUpload, startUpload } = useWorkspace();
  const [fileError, setFileError] = useState<string | null>(null);

  useEffect(() => {
    if (!uploadOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeUpload();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [uploadOpen, closeUpload]);

  if (!uploadOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-label="Tạo bản ghi mới"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) closeUpload();
      }}
    >
      <div className="relative w-full max-w-lg">
        <button
          type="button"
          onClick={closeUpload}
          aria-label="Đóng"
          className="absolute right-4 top-4 z-10 rounded-full p-1.5 text-slate-500 hover:bg-slate-100"
        >
          <X className="size-5" />
        </button>
        <AudioUploader
          fieldErrors={fileError ? { file: fileError } : {}}
          onSubmit={(request) => {
            const error = uploadLimitError(request.file);
            setFileError(error);
            if (error) return;
            startUpload(request);
            closeUpload();
          }}
        />
      </div>
    </div>
  );
}
