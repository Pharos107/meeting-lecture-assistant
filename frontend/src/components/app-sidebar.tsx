"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { AudioLines, FileAudio, LogOut, Menu, Mic, Plus, X } from "lucide-react";
import { useWorkspace, type UploadTask } from "@/components/workspace-provider";
import { ACTIVE_STATUSES, logout, STATUS_LABELS, type JobSummary } from "@/lib/api";
import type { AuthUser } from "@/lib/auth";
import { formatMs } from "@/lib/format";

type AppSidebarProps = {
  user: AuthUser | null;
  collapsed: boolean;
  onToggle: () => void;
};

const ICON_BUTTON = "flex size-10 shrink-0 items-center justify-center rounded-xl text-slate-600 hover:bg-sky-100";

export function AppSidebar({ user, collapsed, onToggle }: AppSidebarProps) {
  const pathname = usePathname();
  const { jobs, jobsLoading, jobsError, hasMoreJobs, loadMoreJobs, uploads, openUpload } = useWorkspace();

  if (collapsed) {
    return (
      <div className="flex h-full flex-col items-center gap-2 px-3 py-3">
        <button type="button" onClick={onToggle} aria-label="Mở menu" title="Mở menu" className={ICON_BUTTON}>
          <Menu className="size-5" />
        </button>
        <button
          type="button"
          onClick={openUpload}
          aria-label="Bản ghi mới"
          title="Bản ghi mới"
          className="flex size-10 items-center justify-center rounded-xl bg-blue-600 text-white hover:bg-blue-700"
        >
          <Plus className="size-5" />
        </button>
        <Link href="/live" aria-label="Ghi trực tiếp" title="Ghi trực tiếp" className={ICON_BUTTON}>
          <Mic className="size-5" />
        </Link>
        <Link href="/jobs" aria-label="Tất cả bản ghi" title="Tất cả bản ghi" className={ICON_BUTTON}>
          <FileAudio className="size-5" />
        </Link>
        <Link href="/voice-profiles" aria-label="Hồ sơ giọng" title="Hồ sơ giọng" className={ICON_BUTTON}>
          <AudioLines className="size-5" />
        </Link>
        <button
          type="button"
          onClick={() => void logout()}
          aria-label="Đăng xuất"
          title="Đăng xuất"
          className={`${ICON_BUTTON} mt-auto`}
        >
          <LogOut className="size-5" />
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 px-3 py-3">
        <button type="button" onClick={onToggle} aria-label="Thu gọn menu" title="Thu gọn menu" className={ICON_BUTTON}>
          <Menu className="size-5" />
        </button>
        <Link href="/jobs" className="flex min-w-0 items-center gap-2">
          <Image src="/logo.png" alt="" width={28} height={28} className="size-7 object-contain" />
          <span className="truncate text-sm font-semibold text-[#0f2744]">Trợ lý biên bản</span>
        </Link>
      </div>

      <div className="space-y-1 px-3">
        <button
          type="button"
          onClick={openUpload}
          className="flex w-full items-center gap-2 rounded-2xl bg-gradient-to-r from-blue-500 to-blue-600 px-3 py-2.5 text-sm font-semibold text-white shadow-lg shadow-blue-500/25"
        >
          <Plus className="size-4" />
          Bản ghi mới
        </button>
        <NavLink href="/live" active={pathname.startsWith("/live")} icon={<Mic className="size-4" />}>
          Ghi trực tiếp
        </NavLink>
      </div>

      <div className="mt-4 flex items-center justify-between px-5">
        <h2 className="text-xs font-semibold text-slate-400">Bản ghi gần đây</h2>
        <Link href="/jobs" className="text-xs text-blue-700 hover:underline">
          Tất cả
        </Link>
      </div>
      <div className="mt-1 min-h-0 flex-1 overflow-y-auto px-3 pb-2">
        {uploads.map((task) => (
          <UploadRow key={task.id} task={task} />
        ))}
        {jobsError ? <p className="px-2 py-2 text-xs text-rose-600">{jobsError}</p> : null}
        {!jobsLoading && !jobsError && jobs.length === 0 && uploads.length === 0 ? (
          <p className="px-2 py-2 text-xs leading-5 text-slate-500">Chưa có bản ghi nào.</p>
        ) : null}
        {jobs.map((job) => (
          <JobRow key={job.id} job={job} active={pathname === `/jobs/${job.id}`} />
        ))}
        {hasMoreJobs ? (
          <button
            type="button"
            onClick={() => void loadMoreJobs()}
            className="mt-1 w-full rounded-xl px-2 py-1.5 text-xs text-slate-600 hover:bg-sky-100"
          >
            Xem thêm
          </button>
        ) : null}
      </div>

      <div className="space-y-1 border-t border-sky-100 px-3 py-2">
        <NavLink href="/voice-profiles" active={pathname.startsWith("/voice-profiles")} icon={<AudioLines className="size-4" />} soon>
          Hồ sơ giọng
        </NavLink>
        <div className="flex items-center gap-2 px-2 py-1">
          <span className="min-w-0 flex-1 truncate text-sm text-slate-600">{user?.display_name}</span>
          <button
            type="button"
            onClick={() => void logout()}
            aria-label="Đăng xuất"
            title="Đăng xuất"
            className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100"
          >
            <LogOut className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

function NavLink({
  href,
  active,
  icon,
  soon = false,
  children,
}: {
  href: string;
  active: boolean;
  icon: React.ReactNode;
  soon?: boolean;
  children: string;
}) {
  return (
    <Link
      href={href}
      className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm ${
        active ? "bg-sky-100 font-medium text-blue-800" : "text-slate-600 hover:bg-sky-50"
      }`}
    >
      {icon}
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {soon ? <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">Sắp có</span> : null}
    </Link>
  );
}

function JobRow({ job, active }: { job: JobSummary; active: boolean }) {
  const running = ACTIVE_STATUSES.includes(job.status);
  const problem = job.status === "failed" || job.status === "cancelled";
  const date = new Date(job.created_at).toLocaleDateString("vi-VN");
  return (
    <Link
      href={`/jobs/${job.id}`}
      className={`block rounded-xl px-2.5 py-2 ${active ? "bg-sky-100" : "hover:bg-sky-50"}`}
      aria-current={active ? "page" : undefined}
    >
      <p className="truncate text-sm font-medium text-slate-800">{job.title}</p>
      <p className={`mt-0.5 flex items-center gap-1.5 truncate text-xs ${job.status === "failed" ? "text-rose-600" : "text-slate-500"}`}>
        {running ? <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-blue-600" /> : null}
        {running || problem ? STATUS_LABELS[job.status] : date}
        {!running && !problem && job.duration_ms != null ? ` · ${formatMs(job.duration_ms)}` : ""}
      </p>
    </Link>
  );
}

function UploadRow({ task }: { task: UploadTask }) {
  const { cancelUpload, dismissUpload } = useWorkspace();
  return (
    <div className="rounded-xl px-2.5 py-2">
      <div className="flex items-start gap-2">
        <p className="min-w-0 flex-1 truncate text-sm font-medium text-slate-800">{task.name}</p>
        <button
          type="button"
          onClick={() => (task.error ? dismissUpload(task.id) : cancelUpload(task.id))}
          aria-label={task.error ? "Bỏ qua" : "Hủy tải lên"}
          title={task.error ? "Bỏ qua" : "Hủy tải lên"}
          className="rounded-md p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
        >
          <X className="size-3.5" />
        </button>
      </div>
      {task.error ? (
        <p className="mt-0.5 text-xs leading-5 text-rose-600">{task.error}</p>
      ) : (
        <>
          <p className="mt-0.5 flex justify-between text-xs text-slate-500">
            <span>{task.status}</span>
            {task.progress != null ? <span>{Math.round(task.progress * 100)}%</span> : null}
          </p>
          <div className="mt-1 h-1 overflow-hidden rounded-full bg-sky-100">
            <div
              className={`h-full rounded-full bg-blue-600 transition-[width] ${task.progress == null ? "w-1/3 animate-pulse" : ""}`}
              style={task.progress != null ? { width: `${Math.round(task.progress * 100)}%` } : undefined}
            />
          </div>
        </>
      )}
    </div>
  );
}
