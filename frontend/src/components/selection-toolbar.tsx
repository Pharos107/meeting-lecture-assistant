"use client";

type SelectionToolbarProps = {
  quote: string;
  onMark: () => void;
  onUnmark: () => void;
  onCreateTask: () => void;
};

export function SelectionToolbar({ quote, onMark, onUnmark, onCreateTask }: SelectionToolbarProps) {
  return (
    <div
      // Giữ vùng bôi đen khi bấm nút, và không để câu cha đọc lại vùng chọn lúc thả chuột.
      onMouseDown={(event) => event.preventDefault()}
      onMouseUp={(event) => event.stopPropagation()}
      className="flex flex-wrap items-center gap-2 rounded-2xl bg-slate-900 px-3 py-2 text-white shadow-lg"
    >
      <p className="mr-1 max-w-[220px] truncate text-xs text-slate-300">“{quote}”</p>
      <ToolbarButton onClick={onMark}>Đánh dấu</ToolbarButton>
      <ToolbarButton onClick={onUnmark}>Bỏ đánh dấu</ToolbarButton>
      <ToolbarButton onClick={onCreateTask}>Tạo việc</ToolbarButton>
    </div>
  );
}

function ToolbarButton({ children, onClick }: { children: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-full bg-white/10 px-3 py-1 text-xs font-medium hover:bg-white/20"
    >
      {children}
    </button>
  );
}
