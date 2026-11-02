"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowUp, Square, Trash2 } from "lucide-react";
import { apiJson, ApiRequestError, askJob, type ChatEvent, type ChatMessage } from "@/lib/api";
import { stampToMs } from "@/lib/format";

const SUGGESTIONS = [
  "Trong buổi này có những nội dung gì?",
  "Có những nhiệm vụ gì cần đề ra?",
  "Đã chốt những quyết định nào?",
  "Còn vấn đề nào bỏ ngỏ?",
];
// Model có thể ghi một mốc hoặc một khoảng, như [12:04] hay [12:04 - 12:30].
const ANSWER_TOKENS = /(\[\d{1,3}:\d{2}(?::\d{2})?(?:\s*[-–]\s*\d{1,3}:\d{2}(?::\d{2})?)?\]|\*\*[^*\n]+\*\*)/;
const LIST_MARK = /^(\s*)[*-] /gm;
// Còn cách đáy chừng này thì chữ mới vẫn tự kéo xuống. Người dùng cuộn lên đọc thì giữ nguyên.
const STICK_BOTTOM_PX = 60;

function localMessage(role: ChatMessage["role"], content: string, status: ChatMessage["status"]): ChatMessage {
  return { id: crypto.randomUUID(), role, content, status, created_at: new Date().toISOString() };
}

export type JobChat = ReturnType<typeof useJobChat>;

/** Ở trang job, không ở panel: đóng panel không được ngắt câu trả lời đang chạy. */
export function useJobChat(jobId: string, onNotice: (message: string) => void) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [asking, setAsking] = useState(false);
  const controller = useRef<AbortController | null>(null);

  const reload = useCallback(async () => {
    const page = await apiJson<{ items: ChatMessage[] }>(`/api/jobs/${jobId}/chat/messages`);
    setMessages(page.items);
  }, [jobId]);

  useEffect(() => {
    reload().catch(() => setMessages([]));
    return () => controller.current?.abort();
  }, [reload]);

  async function ask(question: string) {
    if (asking) return;
    const answer = localMessage("assistant", "", "streaming");
    const patchAnswer = (patch: (current: ChatMessage) => ChatMessage) =>
      setMessages((current) => current.map((row) => (row.id === answer.id ? patch(row) : row)));
    const onEvent = (event: ChatEvent) => {
      if (event.type === "delta") patchAnswer((row) => ({ ...row, content: row.content + event.text }));
      else if (event.type === "done") patchAnswer((row) => ({ ...row, status: "done" }));
      else if (event.type === "error") {
        patchAnswer((row) => ({ ...row, status: "failed", error_code: event.code }));
        onNotice(event.message);
      }
    };

    const abort = new AbortController();
    controller.current = abort;
    setMessages((current) => [...current, localMessage("user", question, "done"), answer]);
    setAsking(true);
    try {
      await askJob(jobId, question, onEvent, abort.signal);
    } catch (caught) {
      if (abort.signal.aborted) {
        patchAnswer((row) => ({ ...row, status: "stopped" }));
      } else {
        await reload().catch(() => undefined);
        onNotice(caught instanceof ApiRequestError ? caught.message : "Không gửi được câu hỏi.");
      }
    } finally {
      setAsking(false);
    }
  }

  async function clear() {
    if (!window.confirm("Xóa toàn bộ lịch sử hỏi đáp của bản ghi này?")) return;
    try {
      await apiJson<void>(`/api/jobs/${jobId}/chat/messages`, { method: "DELETE" });
      setMessages([]);
    } catch (caught) {
      onNotice(caught instanceof ApiRequestError ? caught.message : "Không xóa được lịch sử.");
    }
  }

  return { messages, asking, reload, ask, clear, stop: () => controller.current?.abort() };
}

type ChatPanelProps = {
  chat: JobChat;
  canAsk: boolean;
  durationMs: number;
  onSeekStamp: (stamp: string) => void;
};

export function ChatPanel({ chat, canAsk, durationMs, onSeekStamp }: ChatPanelProps) {
  const [draft, setDraft] = useState("");
  const list = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const { messages, asking } = chat;

  useLayoutEffect(() => {
    if (stick.current && list.current) list.current.scrollTop = list.current.scrollHeight;
  }, [messages]);

  function send(question: string) {
    const text = question.trim();
    if (!text || asking || !canAsk) return;
    stick.current = true;
    setDraft("");
    void chat.ask(text);
  }

  return (
    <>
      <div
        ref={list}
        onScroll={(event) => {
          const box = event.currentTarget;
          stick.current = box.scrollHeight - box.scrollTop - box.clientHeight < STICK_BOTTOM_PX;
        }}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto"
      >
        {messages.length === 0 ? (
          canAsk ? (
            <div className="space-y-2">
              <p className="text-sm leading-6 text-slate-500">Hỏi về nội dung của bản ghi này, hoặc chọn một câu gợi ý:</p>
              {SUGGESTIONS.map((question) => (
                <button
                  key={question}
                  type="button"
                  onClick={() => send(question)}
                  className="block w-full rounded-2xl border border-sky-100 bg-sky-50 px-3 py-2 text-left text-sm text-slate-800 hover:border-blue-200"
                >
                  {question}
                </button>
              ))}
            </div>
          ) : (
            <p className="text-sm leading-6 text-slate-500">Trợ lý mở khi bản ghi sẵn sàng.</p>
          )
        ) : (
          messages.map((message) =>
            message.role === "user" ? (
              <p key={message.id} className="ml-6 whitespace-pre-wrap rounded-2xl bg-blue-600 px-3 py-2 text-sm text-white">
                {message.content}
              </p>
            ) : (
              <Answer key={message.id} message={message} durationMs={durationMs} onSeekStamp={onSeekStamp} />
            ),
          )
        )}
      </div>

      <form
        className="mt-3 shrink-0"
        onSubmit={(event) => {
          event.preventDefault();
          send(draft);
        }}
      >
        <div className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-slate-50 p-2 focus-within:border-blue-300 focus-within:bg-white">
          <textarea
            value={draft}
            maxLength={2000}
            rows={2}
            disabled={!canAsk}
            aria-label="Câu hỏi"
            placeholder="Hỏi về nội dung bản ghi"
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                send(draft);
              }
            }}
            className="min-w-0 flex-1 resize-none bg-transparent text-sm text-slate-800 outline-none disabled:cursor-not-allowed"
          />
          {asking ? (
            <button
              type="button"
              onClick={chat.stop}
              aria-label="Dừng trả lời"
              title="Dừng trả lời"
              className="flex size-8 shrink-0 items-center justify-center rounded-full bg-slate-900 text-white"
            >
              <Square className="size-3.5" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!canAsk || !draft.trim()}
              aria-label="Gửi câu hỏi"
              title="Gửi câu hỏi"
              className="flex size-8 shrink-0 items-center justify-center rounded-full bg-blue-600 text-white disabled:opacity-40"
            >
              <ArrowUp className="size-4" />
            </button>
          )}
        </div>
        <div className="mt-1.5 flex items-start justify-between gap-2 text-[11px] leading-4 text-slate-400">
          <p>Câu hỏi và transcript được gửi tới dịch vụ AI mỗi lần hỏi.</p>
          {messages.length > 0 && !asking ? (
            <button
              type="button"
              onClick={() => void chat.clear()}
              aria-label="Xóa lịch sử hỏi đáp"
              title="Xóa lịch sử hỏi đáp"
              className="shrink-0 text-slate-400 hover:text-rose-600"
            >
              <Trash2 className="size-3.5" />
            </button>
          ) : null}
        </div>
      </form>
    </>
  );
}

function Answer({
  message,
  durationMs,
  onSeekStamp,
}: {
  message: ChatMessage;
  durationMs: number;
  onSeekStamp: (stamp: string) => void;
}) {
  return (
    <div className="text-sm leading-6 text-slate-800">
      <p className="whitespace-pre-wrap">
        {message.content
          .replace(LIST_MARK, "$1• ")
          .split(ANSWER_TOKENS)
          .map((part, index) => {
            if (index % 2 === 0) return part;
            if (part.startsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
            const label = part.slice(1, -1);
            const stamp = label.split(/\s*[-–]\s*/)[0];
            const ms = stampToMs(stamp);
            // Mốc do model ghi nên có thể vượt thời lượng. Khi đó giữ nguyên là chữ.
            if (ms === null || ms > durationMs) return part;
            return (
              <button
                key={index}
                type="button"
                onClick={() => onSeekStamp(stamp)}
                className="rounded bg-sky-50 px-1 font-mono text-xs text-blue-700 hover:bg-sky-100"
              >
                {label}
              </button>
            );
          })}
      </p>
      {message.status === "streaming" && !message.content ? <p className="text-slate-400">Đang đọc transcript…</p> : null}
      {message.status === "stopped" ? <p className="mt-1 text-xs text-slate-400">Đã dừng.</p> : null}
      {message.status === "failed" ? <p className="mt-1 text-xs text-rose-600">Câu trả lời bị gián đoạn.</p> : null}
    </div>
  );
}
