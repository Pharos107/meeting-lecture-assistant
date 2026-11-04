"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Copy, Globe, Lock } from "lucide-react";
import { apiJson, ApiRequestError, type ShareState } from "@/lib/api";

const COPIED_MS = 2_000;

function messageOf(caught: unknown, fallback: string) {
  return caught instanceof ApiRequestError ? caught.message : fallback;
}

type ShareDialogProps = {
  jobId: string;
  title: string;
  /** Bản ghi đang ghi trực tiếp: người có liên kết theo dõi được chữ nháp ngay lúc nói. */
  live?: boolean;
  onClose: () => void;
};

export function ShareDialog({ jobId, title, live = false, onClose }: ShareDialogProps) {
  const [share, setShare] = useState<ShareState | null>(null);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const linkInput = useRef<HTMLInputElement>(null);
  const shareUrl = `/api/jobs/${jobId}/share`;
  const link = share?.url ? `${window.location.origin}${share.url}` : null;

  useEffect(() => {
    apiJson<ShareState>(shareUrl)
      .then(setShare)
      .catch((caught) => setError(messageOf(caught, "Không tải được trạng thái chia sẻ.")));
  }, [shareUrl]);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), COPIED_MS);
    return () => clearTimeout(timer);
  }, [copied]);

  async function toggle() {
    if (share?.enabled && !window.confirm("Tắt chia sẻ thì liên kết hiện tại ngừng hoạt động. Bật lại sẽ có liên kết mới. Tiếp tục?")) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (share?.enabled) {
        await apiJson<void>(shareUrl, { method: "DELETE" });
        setShare({ enabled: false, token: null, url: null });
      } else {
        setShare(await apiJson<ShareState>(shareUrl, { method: "PUT" }));
      }
    } catch (caught) {
      setError(messageOf(caught, "Không đổi được trạng thái chia sẻ."));
    } finally {
      setSaving(false);
    }
  }

  async function copy() {
    if (!link) return;
    setError(null);
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
    } catch {
      // Clipboard API chỉ có trên HTTPS hoặc localhost, còn Compose đang phục vụ HTTP.
      linkInput.current?.select();
      if (document.execCommand("copy")) setCopied(true);
      else setError("Trình duyệt không cho sao chép tự động. Liên kết đã được chọn, hãy nhấn Ctrl+C.");
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4" role="dialog" aria-modal="true" aria-labelledby="share-title">
      <div className="w-full max-w-md rounded-3xl bg-white p-6 shadow-2xl">
        <h2 id="share-title" className="truncate text-lg font-semibold text-slate-900">
          Chia sẻ “{title}”
        </h2>

        <div className="mt-4 flex items-center gap-3 rounded-2xl bg-slate-50 p-3">
          <span
            className={`flex size-9 shrink-0 items-center justify-center rounded-full ${
              share?.enabled ? "bg-blue-100 text-blue-700" : "bg-slate-200 text-slate-600"
            }`}
          >
            {share?.enabled ? <Globe className="size-4" /> : <Lock className="size-4" />}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-slate-900">
              {share?.enabled ? "Bất kỳ ai có liên kết" : "Chỉ mình bạn"}
            </p>
            <p className="text-xs text-slate-500">
              {share?.enabled
                ? live
                  ? "Theo dõi được chữ nháp ngay lúc nói, không cần đăng nhập."
                  : "Xem được mà không cần đăng nhập."
                : live
                  ? "Bật để người khác theo dõi buổi này trực tiếp."
                  : "Bật để tạo liên kết xem cho người khác."}
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={share?.enabled ?? false}
            aria-label="Chia sẻ bằng liên kết"
            disabled={share === null || saving}
            onClick={() => void toggle()}
            className={`relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
              share?.enabled ? "bg-blue-600" : "bg-slate-300"
            }`}
          >
            <span
              className={`absolute left-0.5 top-0.5 size-5 rounded-full bg-white shadow transition-transform ${
                share?.enabled ? "translate-x-5" : ""
              }`}
            />
          </button>
        </div>

        {link ? (
          <div className="mt-3 flex items-center gap-2">
            <input
              ref={linkInput}
              readOnly
              aria-label="Liên kết chia sẻ"
              value={link}
              onFocus={(event) => event.target.select()}
              className="min-w-0 flex-1 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 outline-none ring-blue-500 focus:ring-2"
            />
            <button
              type="button"
              onClick={() => void copy()}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-blue-600 px-3.5 py-2 text-white hover:bg-blue-700"
            >
              {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
              <span className="text-sm font-medium">{copied ? "Đã sao chép" : "Sao chép"}</span>
            </button>
          </div>
        ) : null}

        <p className="mt-3 text-xs leading-5 text-slate-500">
          {live
            ? "Người xem thấy chữ nháp trong lúc ghi, rồi bản chuẩn kèm tên người nói khi xong. Họ không nghe được âm thanh, không thấy lịch sử hỏi đáp."
            : "Người xem chỉ đọc được transcript và tên người nói, không nghe được âm thanh, không thấy đánh dấu, việc, hay lịch sử hỏi đáp."}
        </p>
        {error ? <p className="mt-3 text-sm text-rose-600">{error}</p> : null}

        <div className="mt-5 flex justify-end">
          <button type="button" onClick={onClose} className="rounded-full px-4 py-2 text-slate-600 hover:bg-slate-100">
            <span className="text-sm">Đóng</span>
          </button>
        </div>
      </div>
    </div>
  );
}
