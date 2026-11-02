"use client";

import type { ReactNode } from "react";
import { Bookmark, Sparkles, Users, X } from "lucide-react";

export type ToolId = "assistant" | "notes" | "speakers";

const TOOLS: { id: ToolId; label: string; icon: ReactNode }[] = [
  { id: "assistant", label: "Trợ lý AI", icon: <Sparkles className="size-5" /> },
  { id: "notes", label: "Đánh dấu và việc", icon: <Bookmark className="size-5" /> },
  { id: "speakers", label: "Người nói", icon: <Users className="size-5" /> },
];

type JobToolRailProps = {
  active: ToolId | null;
  badges: Partial<Record<ToolId, number>>;
  onToggle: (tool: ToolId) => void;
};

/** Dãy biểu tượng công cụ của job: bên phải trên desktop, dưới trình phát trên điện thoại. */
export function JobToolRail({ active, badges, onToggle }: JobToolRailProps) {
  return (
    <nav
      aria-label="Công cụ của bản ghi"
      className="flex shrink-0 justify-around border-t border-sky-100 bg-white px-2 py-1 lg:w-[52px] lg:flex-col lg:justify-start lg:gap-2 lg:border-l lg:border-t-0 lg:py-3"
    >
      {TOOLS.map((tool) => {
        const badge = badges[tool.id];
        return (
          <button
            key={tool.id}
            type="button"
            onClick={() => onToggle(tool.id)}
            aria-label={tool.label}
            aria-pressed={active === tool.id}
            className={`group relative flex size-10 items-center justify-center rounded-xl lg:mx-auto ${
              active === tool.id ? "bg-blue-600 text-white" : "text-slate-600 hover:bg-sky-100"
            }`}
          >
            {tool.icon}
            {badge ? (
              <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-amber-400 px-1 text-[11px] font-semibold text-slate-900">
                {badge}
              </span>
            ) : null}
            <span className="pointer-events-none absolute right-full z-30 mr-2 hidden whitespace-nowrap rounded-lg bg-slate-900 px-2 py-1 text-xs text-white lg:group-hover:block">
              {tool.label}
            </span>
          </button>
        );
      })}
    </nav>
  );
}

type JobToolPanelProps = {
  tool: ToolId;
  /** Nội dung tự cuộn và cần chiếm trọn chiều cao panel, như khung chat. */
  fill?: boolean;
  onClose: () => void;
  children: ReactNode;
};

/** Panel của công cụ đang mở. Rộng từ 1280 px thì nằm cạnh chữ, hẹp hơn thì đè lên, điện thoại là tấm trượt từ đáy. */
export function JobToolPanel({ tool, fill = false, onClose, children }: JobToolPanelProps) {
  const label = TOOLS.find((item) => item.id === tool)?.label;
  return (
    <>
      <button
        type="button"
        aria-label="Đóng panel"
        onClick={onClose}
        className="fixed inset-0 z-30 size-full bg-slate-900/40 lg:hidden"
      />
      <aside
        aria-label={label}
        className={`fixed inset-x-0 bottom-0 z-30 flex ${fill ? "h-[75dvh]" : "max-h-[75dvh]"} flex-col rounded-t-3xl bg-white shadow-2xl lg:absolute lg:inset-y-0 lg:left-auto lg:right-[52px] lg:h-auto lg:max-h-none lg:w-[340px] lg:rounded-none lg:border-l lg:border-sky-100 xl:static xl:shrink-0 xl:shadow-none`}
      >
        <div className="flex items-center justify-between px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-900">{label}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={`Đóng ${label}`}
            className="rounded-full p-1 text-slate-500 hover:bg-slate-100"
          >
            <X className="size-4" />
          </button>
        </div>
        <div className={`min-h-0 flex-1 px-4 pb-4 ${fill ? "flex flex-col" : "overflow-y-auto"}`}>{children}</div>
      </aside>
    </>
  );
}
