"use client";

import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { Bookmark, BookmarkX, ListTodo } from "lucide-react";

const SELECTION_GAP_PX = 6;

type SelectionToolbarProps = {
  /** Vùng chọn còn chữ chưa đánh dấu. */
  canMark?: boolean;
  /** Vùng chọn có chữ đã đánh dấu. */
  canUnmark?: boolean;
  onMark: () => void;
  onUnmark: () => void;
  onCreateTask: () => void;
};

export function SelectionToolbar({ canMark = true, canUnmark = true, onMark, onUnmark, onCreateTask }: SelectionToolbarProps) {
  return (
    <div
      // Giữ vùng bôi đen khi bấm nút, và không để câu cha đọc lại vùng chọn lúc thả chuột.
      onMouseDown={(event) => event.preventDefault()}
      onMouseUp={(event) => event.stopPropagation()}
      className="flex w-max items-center gap-0.5 rounded-full border border-sky-100 bg-white p-1 text-xs font-medium text-slate-700 shadow-lg shadow-sky-900/10"
    >
      {canMark ? (
        <ToolbarButton icon={<Bookmark className="size-3.5 text-(--reader-mark)" />} onClick={onMark}>
          Đánh dấu
        </ToolbarButton>
      ) : null}
      {canUnmark ? (
        <ToolbarButton icon={<BookmarkX className="size-3.5 text-slate-400" />} onClick={onUnmark}>
          Bỏ đánh dấu
        </ToolbarButton>
      ) : null}
      <ToolbarButton icon={<ListTodo className="size-3.5 text-blue-600" />} onClick={onCreateTask}>
        Tạo việc
      </ToolbarButton>
    </div>
  );
}

type FloatingSelectionToolbarProps = SelectionToolbarProps & {
  /** Khung cuộn chứa chữ. Trên đầu khung không đủ chỗ thì thanh nằm dưới vùng chọn. */
  boundary: RefObject<HTMLElement | null>;
  /** Đổi mỗi lần bôi đen lại, kể cả trong cùng một câu. */
  selection: object;
};

/** Thanh nổi cạnh vùng bôi đen. Đặt trong thẻ câu nên cuộn theo chữ, và không đẩy các câu bên dưới. */
export function FloatingSelectionToolbar({ boundary, selection, ...actions }: FloatingSelectionToolbarProps) {
  const box = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    const element = box.current;
    const card = element?.offsetParent;
    if (!element || !card) return;
    const place = () => {
      const native = window.getSelection();
      if (!native || native.rangeCount === 0 || native.isCollapsed) return;
      const range = native.getRangeAt(0).getBoundingClientRect();
      const frame = card.getBoundingClientRect();
      const above = range.top - element.offsetHeight - SELECTION_GAP_PX;
      const fitsAbove = above >= (boundary.current?.getBoundingClientRect().top ?? 0);
      const centered = range.left + range.width / 2 - element.offsetWidth / 2 - frame.left;
      setPosition({
        left: Math.max(0, Math.min(centered, frame.width - element.offsetWidth)),
        top: (fitsAbove ? above : range.bottom + SELECTION_GAP_PX) - frame.top,
      });
    };
    place();
    // Đổi độ rộng panel làm chữ xuống dòng khác, vùng chọn theo đó mà dời đi.
    const observer = new ResizeObserver(place);
    observer.observe(card);
    return () => observer.disconnect();
  }, [boundary, selection]);

  return (
    <div ref={box} style={position ?? { right: 16, top: 8 }} className="absolute z-20">
      <SelectionToolbar {...actions} />
    </div>
  );
}

function ToolbarButton({ children, icon, onClick }: { children: string; icon: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 hover:bg-sky-50 hover:text-blue-700"
    >
      {icon}
      {children}
    </button>
  );
}
