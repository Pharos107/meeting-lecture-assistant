"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Download } from "lucide-react";
import type { ExportFormat } from "@/components/types";

const GROUPS: { title: string; items: { format: ExportFormat; label: string }[] }[] = [
  {
    title: "Tài liệu",
    items: [
      { format: "docx", label: "Word (DOCX)" },
      { format: "pdf", label: "PDF" },
      { format: "md", label: "Markdown" },
    ],
  },
  {
    title: "Phụ đề",
    items: [
      { format: "srt", label: "SRT" },
      { format: "vtt", label: "VTT" },
    ],
  },
];

export function ExportMenu({ disabled = false, onExport }: { disabled?: boolean; onExport: (format: ExportFormat) => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        disabled={disabled}
        aria-label="Xuất file"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex h-9 items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Download className="size-4" />
        <span className="hidden text-sm font-medium @xl:inline">Xuất file</span>
        <ChevronDown className="size-4" />
      </button>
      {open ? (
        <div className="absolute right-0 z-30 mt-2 w-48 rounded-2xl bg-white p-2 shadow-xl ring-1 ring-sky-100">
          {GROUPS.map((group) => (
            <div key={group.title} className="py-1">
              <p className="px-2 pb-1 text-xs text-slate-400">{group.title}</p>
              {group.items.map((item) => (
                <button
                  key={item.format}
                  type="button"
                  onClick={() => {
                    setOpen(false);
                    onExport(item.format);
                  }}
                  className="block w-full rounded-lg px-2 py-1.5 text-left text-sm text-slate-700 hover:bg-sky-50"
                >
                  {item.label}
                </button>
              ))}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
