"use client";

import { useCallback, useEffect, useState } from "react";
import { AudioLines, LoaderCircle, Trash2 } from "lucide-react";
import { VoiceEnrollCard } from "@/components/voice-enroll-card";
import { ApiRequestError, MAX_VOICE_PROFILES, deleteVoiceProfile, listVoiceProfiles, type VoiceProfile } from "@/lib/api";
import { formatMs } from "@/lib/format";

const POLL_MS = 3_000;

function initials(name: string) {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const picked = words.length > 1 ? [words[0], words[words.length - 1]] : words;
  return picked.map((word) => word[0]?.toUpperCase() ?? "").join("") || "?";
}

function ProfileBadge({ profile }: { profile: VoiceProfile }) {
  if (profile.status === "processing") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 ring-1 ring-blue-100">
        <span className="size-1.5 animate-pulse rounded-full bg-current" />
        Đang xử lý
      </span>
    );
  }
  if (profile.status === "failed") {
    return <span className="rounded-full bg-rose-50 px-2.5 py-1 text-xs font-medium text-rose-700 ring-1 ring-rose-100">Lỗi</span>;
  }
  if (profile.stale) {
    return <span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800 ring-1 ring-amber-100">Cần thu lại</span>;
  }
  return <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 ring-1 ring-emerald-100">Sẵn sàng</span>;
}

function ProfileRow({ profile, onDeleted }: { profile: VoiceProfile; onDeleted: (id: string, error?: string) => void }) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function remove() {
    setDeleting(true);
    try {
      await deleteVoiceProfile(profile.id);
      onDeleted(profile.id);
    } catch (error) {
      setDeleting(false);
      setConfirming(false);
      onDeleted("", error instanceof ApiRequestError ? error.message : "Không xóa được hồ sơ.");
    }
  }

  const note =
    profile.status === "failed"
      ? profile.error_message || "Không tính được vector giọng. Hãy thu lại."
      : profile.stale
        ? "Hồ sơ ghi bằng bản nhận diện người nói cũ nên không được dùng để gán tên. Xóa rồi thu lại."
        : null;

  return (
    <li className="flex items-start gap-4 px-5 py-4">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-2xl bg-sky-50 text-sm font-semibold text-blue-700">
        {initials(profile.display_name)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="truncate text-sm font-semibold text-slate-900">{profile.display_name}</p>
          <ProfileBadge profile={profile} />
        </div>
        <p className="mt-0.5 text-xs text-slate-500">
          {new Date(profile.created_at).toLocaleString("vi-VN")}
          {profile.duration_ms != null ? ` · mẫu ${formatMs(profile.duration_ms)}` : ""}
        </p>
        {note ? (
          <p className={`mt-1.5 text-xs ${profile.status === "failed" ? "text-rose-700" : "text-amber-800"}`}>{note}</p>
        ) : null}
      </div>
      {confirming ? (
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={() => void remove()}
            disabled={deleting}
            className="inline-flex h-8 items-center gap-1.5 rounded-full bg-rose-600 px-3 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-60"
          >
            {deleting ? <LoaderCircle className="size-3.5 animate-spin" /> : null}
            Xóa
          </button>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            disabled={deleting}
            className="h-8 rounded-full border border-slate-200 px-3 text-xs text-slate-700 hover:border-slate-300"
          >
            Giữ lại
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          aria-label={`Xóa hồ sơ ${profile.display_name}`}
          className="shrink-0 rounded-full p-2 text-slate-400 hover:bg-rose-50 hover:text-rose-600"
        >
          <Trash2 className="size-4" />
        </button>
      )}
    </li>
  );
}

export default function VoiceProfilesPage() {
  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { items } = await listVoiceProfiles();
      setProfiles(items);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "Không tải được hồ sơ giọng.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const processing = profiles.some((profile) => profile.status === "processing");
  useEffect(() => {
    if (!processing) return;
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [processing, load]);

  const full = profiles.length >= MAX_VOICE_PROFILES;

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-[#0f2744]">Hồ sơ giọng</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-500">
          Lưu giọng của những người hay họp cùng. Bản ghi mới sẽ tự gắn tên khi giọng trong buổi khớp với hồ sơ. Tên bạn đã sửa tay
          không bị thay.
        </p>
      </div>

      {error ? <p className="mt-6 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p> : null}

      <div className="mt-6 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_400px]">
        <section aria-labelledby="voice-list">
          <div className="mb-2 flex items-baseline justify-between px-1">
            <h2 id="voice-list" className="text-sm font-semibold text-slate-700">
              Đã lưu
            </h2>
            <span className="text-xs tabular-nums text-slate-500">
              {profiles.length}/{MAX_VOICE_PROFILES}
            </span>
          </div>
          {loading ? (
            <p className="rounded-3xl bg-white px-6 py-10 text-center text-sm text-slate-500 ring-1 ring-sky-100">Đang tải…</p>
          ) : profiles.length === 0 ? (
            <div className="rounded-3xl border border-dashed border-sky-200 bg-white px-6 py-12 text-center">
              <AudioLines className="mx-auto size-8 text-sky-300" />
              <p className="mt-3 text-base font-medium text-slate-800">Chưa có hồ sơ nào</p>
              <p className="mt-1 text-sm text-slate-500">Thu khoảng 30 giây giọng nói ở khung bên cạnh để tạo hồ sơ đầu tiên.</p>
            </div>
          ) : (
            <ul className="divide-y divide-sky-50 overflow-hidden rounded-3xl bg-white ring-1 ring-sky-100">
              {profiles.map((profile) => (
                <ProfileRow
                  key={profile.id}
                  profile={profile}
                  onDeleted={(id, message) => {
                    if (message) setError(message);
                    else setProfiles((current) => current.filter((item) => item.id !== id));
                  }}
                />
              ))}
            </ul>
          )}
        </section>

        <div className="lg:sticky lg:top-6">
          <VoiceEnrollCard disabled={full} onCreated={() => void load()} />
        </div>
      </div>
    </div>
  );
}
