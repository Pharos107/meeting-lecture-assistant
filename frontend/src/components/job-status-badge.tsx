import { ACTIVE_STATUSES, STATUS_LABELS, type JobStatus } from "@/lib/api";

const TONES: Partial<Record<JobStatus, string>> = {
  ready: "bg-emerald-50 text-emerald-700 ring-emerald-100",
  failed: "bg-rose-50 text-rose-700 ring-rose-100",
  cancelled: "bg-slate-100 text-slate-500 ring-slate-200",
};

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const active = ACTIVE_STATUSES.includes(status);
  const tone = TONES[status] ?? "bg-blue-50 text-blue-700 ring-blue-100";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${tone}`}>
      {active ? <span className="size-1.5 animate-pulse rounded-full bg-current" /> : null}
      {STATUS_LABELS[status]}
    </span>
  );
}
