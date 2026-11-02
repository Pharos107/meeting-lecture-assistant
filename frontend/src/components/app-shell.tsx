"use client";

import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Menu, Plus } from "lucide-react";
import { AppSidebar } from "@/components/app-sidebar";
import { UploadDialog } from "@/components/upload-dialog";
import { useWorkspace, WorkspaceProvider } from "@/components/workspace-provider";
import { ensureSession } from "@/lib/api";
import { getCurrentUser, type AuthUser } from "@/lib/auth";

const SIDEBAR_KEY = "sidebar_open";

/** Khung sau đăng nhập, đặt ở layout để chuyển trang không ngắt việc tải lên. Không có phiên hợp lệ thì về /login. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let alive = true;
    ensureSession().then((ok) => {
      if (!alive) return;
      if (!ok) {
        router.replace("/login");
        return;
      }
      setUser(getCurrentUser());
      setReady(true);
    });
    return () => {
      alive = false;
    };
  }, [router]);

  if (!ready) return <p className="py-20 text-center text-sm text-slate-500">Đang kiểm tra phiên đăng nhập…</p>;

  return (
    <WorkspaceProvider>
      <Frame user={user}>{children}</Frame>
    </WorkspaceProvider>
  );
}

function readSidebarPrefs() {
  try {
    return { job: false, other: true, ...JSON.parse(localStorage.getItem(SIDEBAR_KEY) ?? "{}") };
  } catch {
    return { job: false, other: true };
  }
}

function Frame({ user, children }: { user: AuthUser | null; children: React.ReactNode }) {
  const pathname = usePathname();
  const { openUpload } = useWorkspace();
  // Đang đọc một bản ghi thì menu thu gọn để nhường chỗ cho chữ. Mỗi loại trang nhớ lựa chọn riêng.
  const [prefs, setPrefs] = useState<{ job: boolean; other: boolean }>(readSidebarPrefs);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const kind = /^\/jobs\/[^/]+$/.test(pathname) ? "job" : "other";

  useEffect(() => setDrawerOpen(false), [pathname]);

  function toggleSidebar() {
    const next = { ...prefs, [kind]: !prefs[kind] };
    setPrefs(next);
    try {
      localStorage.setItem(SIDEBAR_KEY, JSON.stringify(next));
    } catch {
      // Không ghi được thì lựa chọn chỉ giữ tới khi tải lại trang.
    }
  }

  return (
    <div className="flex h-dvh overflow-hidden bg-gradient-to-b from-sky-50 via-white to-white">
      <aside
        className={`hidden shrink-0 border-r border-sky-100 bg-white/85 transition-[width] lg:block ${
          prefs[kind] ? "w-72" : "w-16"
        }`}
      >
        <AppSidebar user={user} collapsed={!prefs[kind]} onToggle={toggleSidebar} />
      </aside>

      {drawerOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Đóng menu"
            onClick={() => setDrawerOpen(false)}
            className="absolute inset-0 size-full bg-slate-900/40"
          />
          <aside className="relative h-full w-72 max-w-[85vw] bg-white shadow-2xl">
            <AppSidebar user={user} collapsed={false} onToggle={() => setDrawerOpen(false)} />
          </aside>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-sky-100 bg-white/85 px-3 py-2 lg:hidden">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            aria-label="Mở menu"
            className="flex size-10 items-center justify-center rounded-xl text-slate-600 hover:bg-sky-100"
          >
            <Menu className="size-5" />
          </button>
          <Image src="/logo.png" alt="" width={28} height={28} className="size-7 object-contain" />
          <span className="min-w-0 flex-1 truncate text-sm font-semibold text-[#0f2744]">Trợ lý biên bản</span>
          <button
            type="button"
            onClick={openUpload}
            aria-label="Bản ghi mới"
            className="flex size-10 items-center justify-center rounded-xl bg-blue-600 text-white"
          >
            <Plus className="size-5" />
          </button>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>

      <UploadDialog />
    </div>
  );
}
