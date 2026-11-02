"use client";

import Link from "next/link";
import { FileAudio, Mic, Plus } from "lucide-react";
import { JobStatusBadge } from "@/components/job-status-badge";
import { useWorkspace } from "@/components/workspace-provider";
import { formatMs } from "@/lib/format";

export default function JobsPage() {
  const { jobs, jobsLoading, jobsError, hasMoreJobs, loadMoreJobs, openUpload } = useWorkspace();

  return (
    <div className="mx-auto max-w-4xl px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[#0f2744]">Các bản ghi của bạn</h1>
          <p className="mt-1 text-sm text-slate-500">File đã tải lên và phiên nghe trực tiếp, mới nhất ở trên.</p>
        </div>
        <button
          type="button"
          onClick={openUpload}
          className="inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-blue-500 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-blue-500/25"
        >
          <Plus className="size-4" />
          Bản ghi mới
        </button>
      </div>

      {jobsError ? <p className="mt-6 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{jobsError}</p> : null}

      {jobsLoading ? (
        <p className="mt-10 text-center text-sm text-slate-500">Đang tải…</p>
      ) : jobs.length === 0 ? (
        <div className="mt-10 rounded-3xl border border-dashed border-sky-200 bg-white px-6 py-14 text-center">
          <p className="text-base font-medium text-slate-800">Tạo bản ghi đầu tiên</p>
          <p className="mt-1 text-sm text-slate-500">Tải một file ghi âm để nhận transcript có mốc thời gian và tên người nói.</p>
          <button
            type="button"
            onClick={openUpload}
            className="mt-4 rounded-full border border-sky-200 px-4 py-2 text-sm font-medium text-blue-700 hover:border-blue-300"
          >
            Chọn file
          </button>
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

      {hasMoreJobs ? (
        <div className="mt-4 text-center">
          <button
            type="button"
            onClick={() => void loadMoreJobs()}
            className="rounded-full border border-sky-200 bg-white px-4 py-2 text-sm text-slate-700 hover:border-blue-300"
          >
            Xem thêm
          </button>
        </div>
      ) : null}
    </div>
  );
}
