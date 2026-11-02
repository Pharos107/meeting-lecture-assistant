"use client";

import { useEffect, useState, type RefObject } from "react";

type Band = { left: number; top: number; width: number; height: number };

const BAND_PAD_X = 2;
const BAND_PAD_Y = 1;

/** Khung chữ của từng dòng trong vùng chọn, gộp các từ cùng dòng thành một dải. Tọa độ tính theo `root`. */
function readBands(root: HTMLElement | null): Band[] {
  const selection = window.getSelection();
  if (!root || !selection || selection.rangeCount === 0 || selection.isCollapsed) return [];
  const range = selection.getRangeAt(0);
  if (!range.intersectsNode(root)) return [];

  // Rect của cả vùng chọn có luôn hộp của thẻ được chọn trọn, nên phải đi qua từng đoạn chữ.
  const common = range.commonAncestorContainer;
  const start = common.nodeType === Node.TEXT_NODE ? common.parentNode : common;
  const walker = document.createTreeWalker(root.contains(start) && start ? start : root, NodeFilter.SHOW_TEXT);
  const frame = root.getBoundingClientRect();
  const lines: { left: number; right: number; top: number; bottom: number }[] = [];
  const piece = document.createRange();

  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    // Chỉ tô lời nói. Hàng tên và mốc giờ nằm hai đầu thẻ, tô vào sẽ thành một dải dài hết thẻ.
    if (!range.intersectsNode(node) || !node.parentElement?.closest(".reader-text")) continue;
    piece.selectNodeContents(node);
    if (node === range.startContainer) piece.setStart(node, range.startOffset);
    if (node === range.endContainer) piece.setEnd(node, range.endOffset);
    for (const rect of Array.from(piece.getClientRects())) {
      if (rect.width < 1) continue;
      const line = lines[lines.length - 1];
      if (line && rect.top < line.bottom && rect.bottom > line.top) {
        line.left = Math.min(line.left, rect.left);
        line.right = Math.max(line.right, rect.right);
        line.top = Math.min(line.top, rect.top);
        line.bottom = Math.max(line.bottom, rect.bottom);
      } else {
        lines.push({ left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom });
      }
    }
  }

  return lines.map((line) => ({
    left: line.left - frame.left - BAND_PAD_X,
    top: line.top - frame.top - BAND_PAD_Y,
    width: line.right - line.left + BAND_PAD_X * 2,
    height: line.bottom - line.top + BAND_PAD_Y * 2,
  }));
}

/**
 * Vẽ vùng bôi đen thành dải liền từng dòng, bo góc. `::selection` không bo góc được và không tô phần
 * padding của từng từ, nên `.reader-surface` để nó trong suốt. `root` phải là phần tử có position.
 */
export function SelectionPaint({ root }: { root: RefObject<HTMLElement | null> }) {
  const [bands, setBands] = useState<Band[]>([]);

  useEffect(() => {
    let frame = 0;
    const paint = () => {
      frame = 0;
      setBands(readBands(root.current));
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(paint);
    };
    document.addEventListener("selectionchange", schedule);
    // Đổi độ rộng panel hay cỡ chữ làm chữ xuống dòng khác.
    const observer = new ResizeObserver(schedule);
    if (root.current) observer.observe(root.current);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("selectionchange", schedule);
      observer.disconnect();
    };
  }, [root]);

  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 z-10 mix-blend-multiply">
      {bands.map((band, index) => (
        <span key={index} style={band} className="absolute rounded-md bg-(--reader-selection)" />
      ))}
    </div>
  );
}
