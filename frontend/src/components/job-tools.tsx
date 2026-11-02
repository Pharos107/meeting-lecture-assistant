"use client";

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import { Bookmark, Sparkles, Users, X } from "lucide-react";

export type ToolId = "assistant" | "notes" | "speakers";

const PANEL_WIDTH_KEY = "job_panel_width";
const PANEL_DEFAULT_WIDTH = 340;
const PANEL_MIN_WIDTH = 300;
const RAIL_WIDTH = 52;
// Kéo rộng tới đâu thì cột chữ vẫn còn chừng này, kể cả khi panel đè lên chữ.
const TRANSCRIPT_MIN_WIDTH = 340;
const KEY_STEP_PX = 24;

function readPanelWidth() {
  try {
    const saved = Number(localStorage.getItem(PANEL_WIDTH_KEY));
    return saved >= PANEL_MIN_WIDTH ? saved : PANEL_DEFAULT_WIDTH;
  } catch {
    return PANEL_DEFAULT_WIDTH;
  }
}

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

/**
 * Panel của công cụ đang mở. Rộng từ 1280 px thì nằm cạnh chữ, hẹp hơn thì đè lên, điện thoại là tấm trượt từ đáy.
 * Từ 1024 px người dùng kéo mép trái để đổi độ rộng, các công cụ dùng chung một độ rộng.
 */
export function JobToolPanel({ tool, fill = false, onClose, children }: JobToolPanelProps) {
  const label = TOOLS.find((item) => item.id === tool)?.label;
  const panel = useRef<HTMLElement>(null);
  const drag = useRef<{ startX: number; startWidth: number } | null>(null);
  const [width, setWidth] = useState(readPanelWidth);
  const [maxWidth, setMaxWidth] = useState(PANEL_DEFAULT_WIDTH);
  // Giữ riêng độ rộng đã chọn: màn hẹp lại thì panel co theo, rộng ra thì trở về đúng cỡ cũ.
  const shownWidth = Math.min(width, maxWidth);

  useLayoutEffect(() => {
    const area = panel.current?.parentElement;
    if (!area) return;
    const measure = () => setMaxWidth(Math.max(PANEL_MIN_WIDTH, area.clientWidth - RAIL_WIDTH - TRANSCRIPT_MIN_WIDTH));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(area);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(PANEL_WIDTH_KEY, String(width));
    } catch {
      // Không ghi được thì panel về độ rộng mặc định ở lần mở sau.
    }
  }, [width]);

  function resize(next: number) {
    setWidth(Math.round(Math.min(Math.max(next, PANEL_MIN_WIDTH), maxWidth)));
  }

  function startDrag(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { startX: event.clientX, startWidth: shownWidth };
  }

  function moveDrag(event: PointerEvent<HTMLDivElement>) {
    if (drag.current) resize(drag.current.startWidth + drag.current.startX - event.clientX);
  }

  function resizeByKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowLeft") resize(shownWidth + KEY_STEP_PX);
    else if (event.key === "ArrowRight") resize(shownWidth - KEY_STEP_PX);
  }

  return (
    <>
      <button
        type="button"
        aria-label="Đóng panel"
        onClick={onClose}
        className="fixed inset-0 z-30 size-full bg-slate-900/40 lg:hidden"
      />
      <aside
        ref={panel}
        aria-label={label}
        style={{ "--panel-width": `${shownWidth}px` } as CSSProperties}
        className={`fixed inset-x-0 bottom-0 z-30 flex ${fill ? "h-[75dvh]" : "max-h-[75dvh]"} flex-col rounded-t-3xl bg-white shadow-2xl lg:absolute lg:inset-y-0 lg:left-auto lg:right-[52px] lg:h-auto lg:max-h-none lg:w-(--panel-width) lg:rounded-none lg:border-l lg:border-sky-100 xl:relative xl:right-0 xl:shrink-0 xl:shadow-none`}
      >
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Đổi độ rộng panel"
          aria-valuemin={PANEL_MIN_WIDTH}
          aria-valuemax={maxWidth}
          aria-valuenow={shownWidth}
          tabIndex={0}
          title="Kéo để đổi độ rộng, bấm đúp để về mặc định"
          onPointerDown={startDrag}
          onPointerMove={moveDrag}
          onPointerUp={() => (drag.current = null)}
          onPointerCancel={() => (drag.current = null)}
          onDoubleClick={() => resize(PANEL_DEFAULT_WIDTH)}
          onKeyDown={resizeByKey}
          className="group absolute inset-y-0 left-0 z-10 hidden w-2.5 cursor-col-resize touch-none select-none items-center outline-none lg:flex"
        >
          <span className="h-full w-0.5 group-hover:bg-blue-300 group-focus-visible:bg-blue-500 group-active:bg-blue-500" />
          <span className="absolute left-0.5 h-10 w-1 rounded-full bg-slate-200 group-hover:bg-blue-500 group-focus-visible:bg-blue-500 group-active:bg-blue-500" />
        </div>
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
        <div className={`min-h-0 flex-1 px-4 pb-4 ${fill ? "flex flex-col" : "scrollbar-thread overflow-y-auto"}`}>{children}</div>
      </aside>
    </>
  );
}
