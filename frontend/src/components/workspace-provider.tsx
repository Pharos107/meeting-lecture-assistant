"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { UploadRequest } from "@/components/audio-uploader";
import { ACTIVE_STATUSES, apiJson, ApiRequestError, uploadJob, type JobSummary } from "@/lib/api";
import { compressToOpus, isOpusFile, OPUS_LIMIT_BYTES, ORIGINAL_LIMIT_BYTES } from "@/lib/ffmpeg-compressor";

type Page = { items: JobSummary[]; next_cursor: string | null };

export type UploadTask = {
  id: string;
  name: string;
  status: string;
  progress: number | null;
  error: string | null;
};

type Workspace = {
  jobs: JobSummary[];
  jobsLoading: boolean;
  jobsError: string | null;
  hasMoreJobs: boolean;
  refreshJobs: () => Promise<void>;
  loadMoreJobs: () => Promise<void>;
  uploads: UploadTask[];
  uploadOpen: boolean;
  openUpload: () => void;
  closeUpload: () => void;
  startUpload: (request: UploadRequest) => void;
  cancelUpload: (id: string) => void;
  dismissUpload: (id: string) => void;
};

const POLL_MS = 5_000;
const WorkspaceContext = createContext<Workspace | null>(null);

export function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace cần WorkspaceProvider");
  return value;
}

/** Trả lỗi nếu file vượt trần, để hộp thoại báo trước khi đóng. */
export function uploadLimitError(file: File) {
  const limit = isOpusFile(file) ? OPUS_LIMIT_BYTES : ORIGINAL_LIMIT_BYTES;
  return file.size > limit ? "File vượt quá kích thước cho phép." : null;
}

/** Nén sang Opus nếu WASM chạy được. Lỗi thì dùng file gốc. */
async function prepare(file: File, onProgress: (ratio: number) => void, signal: AbortSignal): Promise<File> {
  if (isOpusFile(file)) return file;
  try {
    const compressed = await compressToOpus(file, onProgress, signal);
    if (compressed.size <= OPUS_LIMIT_BYTES && compressed.size < file.size) return compressed;
  } catch (caught) {
    if (signal.aborted) throw caught;
    console.warn("Nén trên trình duyệt lỗi, tải file gốc.", caught);
  }
  return file;
}

function uploadErrorMessage(caught: unknown) {
  if (!(caught instanceof ApiRequestError)) return "Không tạo được bản ghi. Thử lại sau.";
  return (caught.fields && Object.values(caught.fields)[0]) || caught.message;
}

/** Danh sách bản ghi và tiến trình tải lên, sống qua các lần chuyển trang trong layout. */
export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [uploads, setUploads] = useState<UploadTask[]>([]);
  const [uploadOpen, setUploadOpen] = useState(false);

  const controllers = useRef(new Map<string, AbortController>());
  // Nén chiếm nhiều RAM, nên các file chạy lần lượt.
  const uploadQueue = useRef<Promise<void>>(Promise.resolve());

  const loadFirst = useCallback(async (initial: boolean) => {
    try {
      const page = await apiJson<Page>("/api/jobs?limit=20");
      if (initial) {
        setJobs(page.items);
        setCursor(page.next_cursor);
      } else {
        // Lượt hỏi lại chỉ cập nhật bản ghi đã biết và thêm bản mới, giữ các trang đã tải thêm.
        // Bản nằm trong trang đầu trước đó mà giờ không còn là bản vừa bị xóa.
        setJobs((current) => {
          const fresh = new Map(page.items.map((job) => [job.id, job]));
          const known = new Set(current.map((job) => job.id));
          const added = page.items.filter((job) => !known.has(job.id));
          const oldest = page.items.at(-1)?.created_at;
          const kept = current.filter(
            (job) => fresh.has(job.id) || (page.next_cursor !== null && oldest !== undefined && job.created_at < oldest),
          );
          return [...added, ...kept.map((job) => fresh.get(job.id) ?? job)];
        });
      }
      setJobsError(null);
    } catch (caught) {
      setJobsError(caught instanceof ApiRequestError ? caught.message : "Không tải được danh sách bản ghi.");
    } finally {
      setJobsLoading(false);
    }
  }, []);

  const refreshJobs = useCallback(() => loadFirst(false), [loadFirst]);
  const openUpload = useCallback(() => setUploadOpen(true), []);
  const closeUpload = useCallback(() => setUploadOpen(false), []);

  useEffect(() => {
    void loadFirst(true);
  }, [loadFirst]);

  const hasActive = jobs.some((job) => ACTIVE_STATUSES.includes(job.status));
  useEffect(() => {
    if (!hasActive) return;
    const timer = setInterval(() => void loadFirst(false), POLL_MS);
    return () => clearInterval(timer);
  }, [hasActive, loadFirst]);

  const loadMoreJobs = useCallback(async () => {
    if (!cursor) return;
    try {
      const page = await apiJson<Page>(`/api/jobs?limit=20&cursor=${encodeURIComponent(cursor)}`);
      setJobs((current) => [...current, ...page.items.filter((job) => !current.some((row) => row.id === job.id))]);
      setCursor(page.next_cursor);
    } catch (caught) {
      setJobsError(caught instanceof ApiRequestError ? caught.message : "Không tải được danh sách bản ghi.");
    }
  }, [cursor]);

  const patchUpload = useCallback((id: string, patch: Partial<UploadTask>) => {
    setUploads((current) => current.map((task) => (task.id === id ? { ...task, ...patch } : task)));
  }, []);

  const dismissUpload = useCallback((id: string) => {
    controllers.current.delete(id);
    setUploads((current) => current.filter((task) => task.id !== id));
  }, []);

  const cancelUpload = useCallback(
    (id: string) => {
      controllers.current.get(id)?.abort();
      dismissUpload(id);
    },
    [dismissUpload],
  );

  const startUpload = useCallback(
    (request: UploadRequest) => {
      const id = crypto.randomUUID();
      const controller = new AbortController();
      controllers.current.set(id, controller);
      const name = request.title || request.file.name.replace(/\.[^.]+$/, "");
      setUploads((current) => [{ id, name, status: "Đang chờ", progress: null, error: null }, ...current]);

      const run = async () => {
        if (controller.signal.aborted) return;
        try {
          if (!isOpusFile(request.file)) patchUpload(id, { status: "Đang nén", progress: 0 });
          const file = await prepare(request.file, (progress) => patchUpload(id, { progress }), controller.signal);
          const form = new FormData();
          form.append("file", file, file.name);
          form.append("title", name.slice(0, 200));
          if (request.vocabulary) form.append("vocabulary", request.vocabulary);
          if (request.numSpeakers != null) form.append("num_speakers", String(request.numSpeakers));
          patchUpload(id, { status: "Đang tải lên", progress: 0 });
          await uploadJob(form, (progress) => patchUpload(id, { progress }), controller.signal);
          await loadFirst(false);
          dismissUpload(id);
        } catch (caught) {
          if (controller.signal.aborted) return;
          patchUpload(id, { status: "Lỗi", progress: null, error: uploadErrorMessage(caught) });
        }
      };
      uploadQueue.current = uploadQueue.current.then(run);
    },
    [dismissUpload, loadFirst, patchUpload],
  );

  // Nén và tải lên chạy trong tab này, tải lại trang sẽ mất tiến trình.
  const uploading = uploads.some((task) => !task.error);
  useEffect(() => {
    if (!uploading) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [uploading]);

  const value = useMemo<Workspace>(
    () => ({
      jobs,
      jobsLoading,
      jobsError,
      hasMoreJobs: cursor !== null,
      refreshJobs,
      loadMoreJobs,
      uploads,
      uploadOpen,
      openUpload,
      closeUpload,
      startUpload,
      cancelUpload,
      dismissUpload,
    }),
    [
      jobs,
      jobsLoading,
      jobsError,
      cursor,
      refreshJobs,
      loadMoreJobs,
      uploads,
      uploadOpen,
      openUpload,
      closeUpload,
      startUpload,
      cancelUpload,
      dismissUpload,
    ],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}
