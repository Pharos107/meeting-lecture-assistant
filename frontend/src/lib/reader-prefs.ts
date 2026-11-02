import { useEffect, useMemo, useState, type CSSProperties } from "react";

const STORAGE_KEY = "reader_prefs";

export const FONT_SIZE_MIN = 12;
export const FONT_SIZE_MAX = 24;

// Chỉ dùng phông có sẵn trên máy: trang không tải asset ngoài vì COEP, và phông phải có dấu tiếng Việt.
export const READER_FONTS = [
  { id: "segoe", label: "Segoe UI", stack: '"Segoe UI", system-ui, sans-serif' },
  { id: "arial", label: "Arial", stack: "Arial, Helvetica, sans-serif" },
  { id: "tahoma", label: "Tahoma", stack: "Tahoma, Verdana, sans-serif" },
  { id: "times", label: "Times New Roman", stack: '"Times New Roman", Times, serif' },
  { id: "georgia", label: "Georgia", stack: 'Georgia, "Times New Roman", serif' },
  { id: "consolas", label: "Consolas", stack: 'Consolas, "Courier New", monospace' },
];

export const SELECTION_COLORS = [
  { value: "#bfdbfe", label: "Xanh dương" },
  { value: "#fef08a", label: "Vàng" },
  { value: "#bbf7d0", label: "Xanh lá" },
  { value: "#fbcfe8", label: "Hồng" },
  { value: "#ddd6fe", label: "Tím" },
];

export const MARK_COLORS = [
  { value: "#fbbf24", label: "Vàng" },
  { value: "#60a5fa", label: "Xanh dương" },
  { value: "#34d399", label: "Xanh lá" },
  { value: "#f472b6", label: "Hồng" },
  { value: "#a78bfa", label: "Tím" },
];

export const READER_ALIGNS = [
  { value: "left", label: "Trái" },
  { value: "center", label: "Giữa" },
  { value: "justify", label: "Đều hai bên" },
] as const;

export const READER_WIDTHS = [
  { value: "column", label: "Vừa đọc" },
  { value: "full", label: "Toàn trang" },
] as const;

export type ReaderPrefs = {
  size: number;
  font: string;
  align: (typeof READER_ALIGNS)[number]["value"];
  width: (typeof READER_WIDTHS)[number]["value"];
  selection: string;
  mark: string;
};

export const READER_DEFAULTS: ReaderPrefs = {
  size: 14,
  font: "segoe",
  align: "left",
  width: "column",
  selection: SELECTION_COLORS[0].value,
  mark: MARK_COLORS[0].value,
};

function pick<T>(saved: unknown, allowed: readonly T[], fallback: T) {
  return allowed.includes(saved as T) ? (saved as T) : fallback;
}

function readPrefs(): ReaderPrefs {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    const size = Number(saved.size);
    return {
      size: size >= FONT_SIZE_MIN && size <= FONT_SIZE_MAX ? size : READER_DEFAULTS.size,
      font: pick(saved.font, READER_FONTS.map((font) => font.id), READER_DEFAULTS.font),
      align: pick(saved.align, READER_ALIGNS.map((align) => align.value), READER_DEFAULTS.align),
      width: pick(saved.width, READER_WIDTHS.map((width) => width.value), READER_DEFAULTS.width),
      selection: pick(saved.selection, SELECTION_COLORS.map((color) => color.value), READER_DEFAULTS.selection),
      mark: pick(saved.mark, MARK_COLORS.map((color) => color.value), READER_DEFAULTS.mark),
    };
  } catch {
    return READER_DEFAULTS;
  }
}

function readerStyle(prefs: ReaderPrefs) {
  return {
    "--reader-size": `${prefs.size}px`,
    "--reader-font": READER_FONTS.find((font) => font.id === prefs.font)?.stack,
    "--reader-align": prefs.align,
    "--reader-width": prefs.width === "full" ? "100%" : "48rem",
    "--reader-selection": prefs.selection,
    "--reader-mark": prefs.mark,
  } as CSSProperties;
}

export type ReaderControls = ReturnType<typeof useReaderPrefs>;

/** Cài đặt đọc lưu theo trình duyệt. `style` gắn vào khung trang để mọi phần bên trong dùng chung biến. */
export function useReaderPrefs() {
  const [prefs, setPrefs] = useState(readPrefs);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch {
      // Không ghi được thì cài đặt chỉ giữ tới khi tải lại trang.
    }
  }, [prefs]);

  const style = useMemo(() => readerStyle(prefs), [prefs]);
  return {
    prefs,
    style,
    update: (patch: Partial<ReaderPrefs>) => setPrefs((current) => ({ ...current, ...patch })),
    reset: () => setPrefs(READER_DEFAULTS),
  };
}
