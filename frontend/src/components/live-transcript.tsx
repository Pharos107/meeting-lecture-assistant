"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowDown } from "lucide-react";
import type { LiveLine } from "@/components/types";
import { formatMs } from "@/lib/format";

// Bản nháp mới tới sau khoảng 2 giây: viết hết phần mới trong chừng này để chữ chạy liền, không dồn cục.
const TYPE_BUDGET_MS = 1600;
const MIN_CHARS_PER_S = 18;
const MAX_CHARS_PER_S = 160;

function showAtOnce() {
  if (typeof window === "undefined") return false;
  // Tab ẩn thì trình duyệt dừng requestAnimationFrame: hiện đủ chữ thay vì để câu đứng giữa chừng.
  return document.visibilityState === "hidden" || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Số ký tự đầu giống nhau, lùi về ranh giới từ để không viết lại nửa chữ. */
function keptLength(shown: string[], target: string[]) {
  let same = 0;
  while (same < shown.length && same < target.length && shown[same] === target[same]) same += 1;
  if (same === shown.length || same === target.length) return same;
  while (same > 0 && target[same - 1] !== " ") same -= 1;
  return same;
}

/** Chữ hiện dần từng ký tự về phía `text`. Model sửa đuôi câu thì chỉ phần khác nhau được viết lại. */
function TypedText({ text, instant, onGrow }: { text: string; instant: boolean; onGrow: () => void }) {
  const [shown, setShown] = useState(() => (instant ? text : ""));
  const shownRef = useRef(shown);
  const onGrowRef = useRef(onGrow);
  onGrowRef.current = onGrow;

  useEffect(() => {
    const target = Array.from(text);
    const current = Array.from(shownRef.current);
    if (instant || showAtOnce()) {
      shownRef.current = text;
      setShown(text);
      onGrowRef.current();
      return;
    }
    let count = keptLength(current, target);
    if (count < current.length) {
      shownRef.current = target.slice(0, count).join("");
      setShown(shownRef.current);
    }
    const rate = Math.min(MAX_CHARS_PER_S, Math.max(MIN_CHARS_PER_S, ((target.length - count) * 1000) / TYPE_BUDGET_MS));
    let frame = 0;
    let last = performance.now();
    let carry = 0;
    const step = (now: number) => {
      carry += ((now - last) / 1000) * rate;
      last = now;
      const add = Math.floor(carry);
      if (add > 0) {
        carry -= add;
        count = Math.min(target.length, count + add);
        shownRef.current = target.slice(0, count).join("");
        setShown(shownRef.current);
        onGrowRef.current();
      }
      if (count < target.length) frame = requestAnimationFrame(step);
    };
    if (count < target.length) frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [text, instant]);

  return <>{shown}</>;
}

type LiveTranscriptProps = {
  lines: LiveLine[];
  listening?: boolean;
  emptyText?: string;
  /** Câu vừa được trợ lý dẫn tới: cuộn tới và tô viền một lúc. */
  focusMs?: number | null;
};

/** Chữ nháp theo dòng thời gian. Câu đang mở nhạt hơn và có con trỏ, câu đã chốt đậm như bản đọc. */
export function LiveTranscript({
  lines,
  listening = true,
  emptyText = "Chữ nháp hiện ở đây khi có người nói.",
  focusMs = null,
}: LiveTranscriptProps) {
  const scroller = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);
  const followingRef = useRef(following);
  followingRef.current = following;
  const focused = focusMs == null ? null : [...lines].reverse().find((line) => (line.startMs ?? 0) <= focusMs + 999) ?? lines[0];

  const keepBottom = () => {
    const node = scroller.current;
    if (node && followingRef.current) node.scrollTop = node.scrollHeight;
  };

  useEffect(keepBottom, [lines.length, following]);

  useEffect(() => {
    if (!focused) return;
    setFollowing(false);
    scroller.current?.querySelector(`[data-line-id="${focused.id}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focusMs, focused]);

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div
        ref={scroller}
        onScroll={(event) => {
          const node = event.currentTarget;
          setFollowing(node.scrollHeight - node.scrollTop - node.clientHeight < 48);
        }}
        className="reader-surface scrollbar-soft min-h-0 flex-1 overflow-y-auto"
      >
        <div className="mx-auto w-full max-w-(--reader-width) px-4 py-6 sm:px-6">
          {lines.length === 0 ? (
            <p className="py-10 text-center text-sm text-slate-500">{emptyText}</p>
          ) : (
            <ol className="space-y-4">
              {lines.map((line) => {
                const open = !line.stable;
                return (
                  <li
                    key={line.id}
                    data-line-id={line.id}
                    className={`grid grid-cols-[3.25rem_1fr] gap-3 rounded-xl transition-colors ${
                      focused?.id === line.id ? "bg-blue-50 ring-1 ring-blue-200" : ""
                    }`}
                  >
                    <span className={`pt-[0.3em] text-right text-xs tabular-nums ${open ? "text-blue-600" : "text-slate-400"}`}>
                      {line.startMs != null ? formatMs(line.startMs) : ""}
                    </span>
                    <p className={`reader-text ${open ? "text-slate-500" : "text-[#0f2744]"}`}>
                      <TypedText text={line.text} instant={Boolean(line.instant)} onGrow={keepBottom} />
                      {open && listening ? (
                        <span
                          aria-hidden="true"
                          className="ml-0.5 inline-block h-[1.1em] w-[2px] translate-y-[0.2em] bg-blue-600 motion-safe:animate-pulse"
                        />
                      ) : null}
                    </p>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </div>
      {/* Đọc chữ nháp cho trình đọc màn hình theo câu đã chốt, không theo từng ký tự đang gõ. */}
      <p className="sr-only" aria-live="polite">
        {lines.filter((line) => line.stable).at(-1)?.text ?? ""}
      </p>
      {!following && lines.length > 0 ? (
        <button
          type="button"
          onClick={() => setFollowing(true)}
          className="absolute bottom-4 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-[#0f2744] px-4 py-2 text-xs font-medium text-white shadow-lg"
        >
          <ArrowDown className="size-3.5" />
          Về câu mới nhất
        </button>
      ) : null}
    </div>
  );
}
