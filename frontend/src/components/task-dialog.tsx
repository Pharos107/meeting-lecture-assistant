"use client";

import { useState } from "react";
import { formatMs } from "@/lib/format";

export type TaskDraft = { segmentId: string; startMs: number; task: string };

type TaskDialogProps = {
  draft: TaskDraft;
  saving: boolean;
  error: string | null;
  onSave: (values: { task: string; owner: string; deadline: string }) => void;
  onClose: () => void;
};

export function TaskDialog({ draft, saving, error, onSave, onClose }: TaskDialogProps) {
  const [task, setTask] = useState(draft.task);
  const [owner, setOwner] = useState("");
  const [deadline, setDeadline] = useState("");

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4" role="dialog" aria-modal="true">
      <form
        className="w-full max-w-md rounded-3xl bg-white p-6 shadow-2xl"
        onSubmit={(event) => {
          event.preventDefault();
          if (task.trim()) onSave({ task: task.trim(), owner: owner.trim(), deadline: deadline.trim() });
        }}
      >
        <h2 className="text-lg font-semibold text-slate-900">Tạo việc tại {formatMs(draft.startMs)}</h2>
        <label className="mt-4 block text-sm font-medium text-slate-700">
          Việc cần làm
          <textarea
            value={task}
            maxLength={500}
            rows={3}
            autoFocus
            onChange={(event) => setTask(event.target.value)}
            className="mt-1.5 w-full resize-none rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-normal outline-none ring-blue-500 focus:bg-white focus:ring-2"
          />
        </label>
        <div className="mt-3 grid grid-cols-2 gap-3">
          <label className="block text-sm font-medium text-slate-700">
            Người phụ trách
            <input
              value={owner}
              maxLength={200}
              onChange={(event) => setOwner(event.target.value)}
              className="mt-1.5 w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-normal outline-none ring-blue-500 focus:bg-white focus:ring-2"
            />
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Hạn chót
            <input
              value={deadline}
              maxLength={200}
              onChange={(event) => setDeadline(event.target.value)}
              className="mt-1.5 w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-normal outline-none ring-blue-500 focus:bg-white focus:ring-2"
            />
          </label>
        </div>
        {error ? <p className="mt-3 text-sm text-rose-600">{error}</p> : null}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-full px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">
            Đóng
          </button>
          <button
            type="submit"
            disabled={saving || !task.trim()}
            className="rounded-full bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            {saving ? "Đang lưu…" : "Lưu việc"}
          </button>
        </div>
      </form>
    </div>
  );
}
