"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { FileAudio, Mic, Plus } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { JobStatusBadge } from "@/components/job-status-badge";
import { ACTIVE_STATUSES, apiJson, ApiRequestError, type JobSummary } from "@/lib/api";
import { formatMs } from "@/lib/format";

type Page = { items: JobSummary[]; next_cursor: string | null };

const POLL_MS = 5_000;

export default function JobsPage() {
  return (
    <AppShell>
      <JobList />
    </AppShell>
  );
}

function JobList() {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadFirst = useCallback(async (initial: boolean) => {
    try {
      const page = await apiJson<Page>("/api/jobs?limit=20");
      if (initial) {
        setJobs(page.items);
        setCursor(page.next_cursor);
      } else {
        // Lượt hỏi lại chỉ cập nhật trạng thái và thêm job mới, giữ các trang đã tải thêm.
        setJobs((current) => {
          const fresh = new Map(page.items.map((job) => [job.id, job]));
          const known = new Set(current.map((job) => job.id));
          const added = page.items.filter((job) => !known.has(job.id));
          return [...added, ...current.map((job) => fresh.get(job.id) ?? job)];
        });
      }
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "Không tải được danh sách job.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadFirst(true);
  }, [loadFirst]);

  const hasActive = jobs.some((job) => ACTIVE_STATUSES.includes(job.status));
  useEffect(() => {
    if (!hasActive) return;
    const timer = setInterval(() => void loadFirst(false), POLL_MS);
    return () => clearInterval(timer);
  }, [hasActive, loadFirst]);

  async function loadMore() {
    if (!cursor) return;
    try {
      const page = await apiJson<Page>(`/api/jobs?limit=20&cursor=${encodeURIComponent(cursor)}`);
      setJobs((current) => [...current, ...page.items.filter((job) => !current.some((row) => row.id === job.id))]);
      setCursor(page.next_cursor);
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "Không tải được danh sách job.");
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[#0f2744]">Các job của bạn</h1>
          <p className="mt-1 text-sm text-slate-500">File đã tải lên và phiên nghe trực tiếp, mới nhất ở trên.</p>
        </div>
        <Link
          href="/jobs/new"
          className="inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-blue-500 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-blue-500/25"
        >
          <Plus className="size-4" />
          Tải file mới
        </Link>
      </div>

      {error ? <p className="mt-6 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p> : null}

      {loading ? (
        <p className="mt-10 text-center text-sm text-slate-500">Đang tải…</p>
      ) : jobs.length === 0 ? (
        <div className="mt-10 rounded-3xl border border-dashed border-sky-200 bg-white px-6 py-14 text-center">
          <p className="text-base font-medium text-slate-800">Chưa có job nào</p>
          <p className="mt-1 text-sm text-slate-500">Tải một file ghi âm để nhận transcript có mốc thời gian và tên người nói.</p>
        </div>
      ) : (
        <ul className="mt-6 divide-y divide-sky-50 overflow-hidden rounded-3xl bg-white ring-1 ring-sky-100">
          {jobs.map((job) => (
            <li key={job.id}>
              <Link href={`/jobs/${job.id}`} className="flex items-center gap-4 px-5 py-4 hover:bg-sky-50/60">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-2xl bg-sky-50 text-blue-600">
                  {job.source === "live" ? <Mic className="size-5" /> : <FileAudio className="size-5" />}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-slate-900">{job.title}</p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {new Date(job.created_at).toLocaleString("vi-VN")}
                    {job.duration_ms != null ? ` · ${formatMs(job.duration_ms)}` : ""}
                    {job.warnings.length > 0 ? ` · ${job.warnings.length} cảnh báo` : ""}
                  </p>
                </div>
                <JobStatusBadge status={job.status} />
              </Link>
            </li>
          ))}
        </ul>
      )}

      {cursor ? (
        <div className="mt-4 text-center">
          <button
            type="button"
            onClick={() => void loadMore()}
            className="rounded-full border border-sky-200 bg-white px-4 py-2 text-sm text-slate-700 hover:border-blue-300"
          >
            Xem thêm
          </button>
        </div>
      ) : null}
    </div>
  );
}
