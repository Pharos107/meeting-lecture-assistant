"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Settings2 } from "lucide-react";
import {
  FONT_SIZE_MAX,
  FONT_SIZE_MIN,
  MARK_COLORS,
  READER_ALIGNS,
  READER_FONTS,
  READER_WIDTHS,
  SELECTION_COLORS,
  type ReaderControls,
} from "@/lib/reader-prefs";

export function ReaderSettingsMenu({ reader }: { reader: ReaderControls }) {
  const { prefs, update, reset } = reader;
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        aria-label="Cài đặt hiển thị"
        title="Cài đặt hiển thị"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className={`flex size-9 items-center justify-center rounded-full ${
          open ? "bg-sky-100 text-blue-700" : "text-slate-600 hover:bg-sky-50"
        }`}
      >
        <Settings2 className="size-4" />
      </button>
      {open ? (
        <div className="scrollbar-thread absolute right-0 z-30 mt-2 max-h-[calc(100dvh-5rem)] w-72 max-w-[calc(100vw-2rem)] space-y-3.5 overflow-y-auto rounded-2xl bg-white p-3.5 text-xs text-slate-700 shadow-xl ring-1 ring-sky-100">
          <Field label="Cỡ chữ" hint={`${prefs.size} px`}>
            <input
              type="range"
              aria-label="Cỡ chữ"
              min={FONT_SIZE_MIN}
              max={FONT_SIZE_MAX}
              value={prefs.size}
              onChange={(event) => update({ size: Number(event.target.value) })}
              className="w-full cursor-pointer accent-blue-600"
            />
          </Field>
          <Field label="Phông chữ">
            <select
              aria-label="Phông chữ"
              value={prefs.font}
              onChange={(event) => update({ font: event.target.value })}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-2 py-1.5 outline-none ring-blue-500 focus:ring-2"
            >
              {READER_FONTS.map((font) => (
                <option key={font.id} value={font.id}>
                  {font.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Căn chữ">
            <Segmented
              label="Căn chữ"
              value={prefs.align}
              options={READER_ALIGNS}
              onChange={(align) => update({ align })}
            />
          </Field>
          <Field label="Độ rộng cột chữ">
            <Segmented
              label="Độ rộng cột chữ"
              value={prefs.width}
              options={READER_WIDTHS}
              onChange={(width) => update({ width })}
            />
          </Field>
          <Field label="Màu bôi đen">
            <Swatches
              label="Màu bôi đen"
              value={prefs.selection}
              options={SELECTION_COLORS}
              onChange={(selection) => update({ selection })}
            />
          </Field>
          <Field label="Màu đánh dấu">
            <Swatches
              label="Màu đánh dấu"
              value={prefs.mark}
              options={MARK_COLORS}
              onChange={(mark) => update({ mark })}
            />
          </Field>
          <div className="flex items-center justify-between gap-2 border-t border-sky-100 pt-2.5 text-slate-400">
            <span>Lưu trên trình duyệt này</span>
            <button type="button" onClick={reset} className="rounded-full px-2 py-1 text-blue-700 hover:bg-sky-50">
              Khôi phục
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 flex justify-between gap-2 font-medium text-slate-500">
        <span>{label}</span>
        {hint ? <span className="tabular-nums text-slate-700">{hint}</span> : null}
      </div>
      {children}
    </div>
  );
}

type Option<T> = { value: T; label: string };

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly Option<T>[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="grid auto-cols-fr grid-flow-col gap-0.5 rounded-xl bg-slate-100 p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
          className={`whitespace-nowrap rounded-lg px-1.5 py-1 ${
            option.value === value ? "bg-white text-blue-700 shadow-sm" : "text-slate-600 hover:text-slate-900"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function Swatches({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: readonly Option<string>[];
  onChange: (value: string) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex gap-2.5 px-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-label={option.label}
          title={option.label}
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
          style={{ backgroundColor: option.value }}
          className={`size-6 rounded-full ring-offset-2 ${
            option.value === value ? "ring-2 ring-blue-500" : "ring-1 ring-slate-200 hover:ring-slate-400"
          }`}
        />
      ))}
    </div>
  );
}
