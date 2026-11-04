"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
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

// Thu gọn hay mở rộng đều dùng một khung: biểu tượng đứng yên trong cột 40 px, chữ chỉ mờ đi.
// Khung aside co lại và cắt phần chữ, nên không có bước đổi bố cục giữa chừng.
const EASE = "duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none";
// Hàng co về đúng ô biểu tượng khi thu gọn, để viền và nền của nút không bị khung cắt dở.
const row = (collapsed: boolean) =>
  `flex h-10 items-center gap-3 overflow-hidden rounded-xl text-sm transition-[width,background-color] ${EASE} ${collapsed ? "w-10" : "w-full"}`;
const ICON_SLOT = "flex size-10 shrink-0 items-center justify-center";
const FADE = "transition-opacity duration-200 motion-reduce:transition-none";

export function AppSidebar({ user, collapsed, onToggle }: AppSidebarProps) {
  const pathname = usePathname();
  const { jobs, jobsLoading, jobsError, hasMoreJobs, loadMoreJobs, uploads, openUpload } = useWorkspace();
  const label = `${FADE} min-w-0 flex-1 truncate whitespace-nowrap text-left ${collapsed ? "opacity-0" : "opacity-100"}`;
  const initial = user?.display_name?.trim().charAt(0).toUpperCase() || "?";

  return (
    <div className="flex h-full w-72 max-w-[85vw] flex-col">
      <div className="flex items-center gap-3 px-3 py-3">
        <button
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? "Mở rộng menu" : "Thu gọn menu"}
          aria-expanded={!collapsed}
          title={collapsed ? "Mở rộng menu" : "Thu gọn menu"}
          className={`${ICON_SLOT} rounded-xl text-slate-600 hover:bg-sky-100`}
        >
          <Menu className="size-5" />
        </button>
        <Link href="/jobs" tabIndex={collapsed ? -1 : undefined} className={`flex min-w-0 items-center gap-2 ${FADE} ${collapsed ? "pointer-events-none opacity-0" : ""}`}>
          <Image src="/logo.png" alt="" width={28} height={28} className="size-7 object-contain" />
          <span className="truncate whitespace-nowrap text-sm font-semibold text-[#0f2744]">Trợ lý biên bản</span>
        </Link>
      </div>

      <nav aria-label="Điều hướng" className="space-y-1 px-3">
        <button
          type="button"
          onClick={openUpload}
          title={collapsed ? "Bản ghi mới" : undefined}
          className={`${row(collapsed)} border border-sky-200 bg-white font-medium text-[#0f2744] hover:border-blue-300 hover:bg-sky-50`}
        >
          <span className={`${ICON_SLOT} -m-px text-blue-600`}>
            <Plus className="size-5" />
          </span>
          <span className={label}>Bản ghi mới</span>
        </button>
        <NavItem href="/live" active={pathname.startsWith("/live")} icon={<Mic className="size-5" />} collapsed={collapsed} labelClass={label}>
          Ghi trực tiếp
        </NavItem>
        <NavItem href="/jobs" active={pathname === "/jobs"} icon={<FileAudio className="size-5" />} collapsed={collapsed} labelClass={label}>
          Tất cả bản ghi
        </NavItem>
      </nav>

      {/* Danh sách chỉ đọc được khi mở rộng. Lúc thu gọn nó vẫn giữ chỗ nhưng ẩn, để bố cục không nhảy. */}
      <section
        aria-label="Bản ghi gần đây"
        inert={collapsed}
        className={`${FADE} mt-4 flex min-h-0 flex-1 flex-col ${collapsed ? "invisible opacity-0" : "opacity-100"}`}
      >
        <h2 className="px-5 text-xs font-semibold text-slate-400">Bản ghi gần đây</h2>
        <div className="scrollbar-soft mt-1 min-h-0 flex-1 overflow-y-auto px-3 pb-2">
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
      </section>

      <div className="space-y-1 border-t border-sky-100 px-3 py-2">
        <NavItem
          href="/voice-profiles"
          active={pathname.startsWith("/voice-profiles")}
          icon={<AudioLines className="size-5" />}
          collapsed={collapsed}
          labelClass={label}
        >
          Hồ sơ giọng
        </NavItem>
        <div className={row(collapsed)}>
          <span className={ICON_SLOT} title={collapsed ? user?.display_name : undefined}>
            <span className="flex size-7 items-center justify-center rounded-full bg-sky-100 text-xs font-semibold text-blue-800">{initial}</span>
          </span>
          <span className={`${label} text-slate-600`}>{user?.display_name}</span>
        </div>
        <button
          type="button"
          onClick={() => void logout()}
          title={collapsed ? "Đăng xuất" : undefined}
          className={`${row(collapsed)} text-slate-600 hover:bg-slate-100`}
        >
          <span className={ICON_SLOT}>
            <LogOut className="size-5" />
          </span>
          <span className={label}>Đăng xuất</span>
        </button>
      </div>
    </div>
  );
}

function NavItem({
  href,
  active,
  icon,
  collapsed,
  labelClass,
  children,
}: {
  href: string;
  active: boolean;
  icon: ReactNode;
  collapsed: boolean;
  labelClass: string;
  children: string;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      title={collapsed ? children : undefined}
      className={`${row(collapsed)} relative ${active ? "bg-blue-50 font-medium text-blue-800" : "text-slate-600 hover:bg-sky-50"}`}
    >
      {/* Vạch bên trái chỉ có ở trang đang mở, kể cả khi thu gọn. */}
      {active ? <span aria-hidden="true" className="absolute inset-y-2 left-0 w-[3px] rounded-full bg-blue-600" /> : null}
      <span className={ICON_SLOT}>{icon}</span>
      <span className={labelClass}>{children}</span>
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
      className={`relative block rounded-xl px-2.5 py-2 ${active ? "bg-blue-50" : "hover:bg-sky-50"}`}
      aria-current={active ? "page" : undefined}
    >
      {active ? <span aria-hidden="true" className="absolute inset-y-2 left-0 w-[3px] rounded-full bg-blue-600" /> : null}
      <p className={`truncate text-sm font-medium ${active ? "text-blue-900" : "text-slate-800"}`}>{job.title}</p>
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
