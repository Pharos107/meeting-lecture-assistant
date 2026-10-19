"use client";

import type { ExportFormat, MinutesTemplate } from "@/components/types";

type AiActionPanelProps = {
  notice?: string | null;
  onNormalize: () => void;
  onMinutes: (template: MinutesTemplate) => void;
  onExport: (format: ExportFormat) => void;
};

const EXPORTS: { format: ExportFormat; label: string }[] = [
  { format: "md", label: "Markdown" },
  { format: "docx", label: "DOCX" },
  { format: "pdf", label: "PDF" },
  { format: "srt", label: "SRT" },
  { format: "vtt", label: "VTT" },
];

export function AiActionPanel({ notice, onNormalize, onMinutes, onExport }: AiActionPanelProps) {
  return (
    <section className="rounded-3xl bg-white p-4 ring-1 ring-sky-100">
      <h2 className="text-sm font-semibold text-slate-900">Hậu kỳ</h2>
      <p className="mt-1 text-xs leading-5 text-slate-500">Chỉ chạy khi bạn bấm. Job phải ở trạng thái sẵn sàng.</p>
      <button
        type="button"
        onClick={onNormalize}
        className="mt-3 w-full rounded-full bg-slate-900 px-4 py-2.5 text-sm font-medium text-white"
      >
        Chuẩn hóa văn bản
      </button>
      <div className="mt-3 grid grid-cols-1 gap-2">
        <button
          type="button"
          onClick={() => onMinutes("meeting")}
          className="rounded-2xl border border-sky-100 bg-sky-50 px-3 py-2 text-left text-sm text-slate-800"
        >
          Biên bản cuộc họp
        </button>
        <button
          type="button"
          onClick={() => onMinutes("lecture")}
          className="rounded-2xl border border-sky-100 bg-sky-50 px-3 py-2 text-left text-sm text-slate-800"
        >
          Ghi chú bài giảng
        </button>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {EXPORTS.map((item) => (
          <button
            key={item.format}
            type="button"
            onClick={() => onExport(item.format)}
            className="rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 hover:border-blue-300 hover:text-blue-700"
          >
            {item.label}
          </button>
        ))}
      </div>
      {notice ? <p className="mt-3 text-xs text-blue-700">{notice}</p> : null}
    </section>
  );
}
