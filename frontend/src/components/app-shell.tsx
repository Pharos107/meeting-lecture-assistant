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

const SIDEBAR_KEY = "sidebar_expanded";
// Khóa cũ lưu riêng cho trang bản ghi và các trang khác. Đọc phần "other" một lần để giữ lựa chọn cũ.
const LEGACY_SIDEBAR_KEY = "sidebar_open";

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

function readSidebarExpanded() {
  try {
    const saved = localStorage.getItem(SIDEBAR_KEY);
    if (saved !== null) return saved === "1";
    const legacy = JSON.parse(localStorage.getItem(LEGACY_SIDEBAR_KEY) ?? "{}");
    return typeof legacy.other === "boolean" ? legacy.other : true;
  } catch {
    return true;
  }
}

function Frame({ user, children }: { user: AuthUser | null; children: React.ReactNode }) {
  const pathname = usePathname();
  const { openUpload } = useWorkspace();
  // Một lựa chọn cho mọi trang: chuyển trang không tự thu gọn hay mở rộng menu.
  const [expanded, setExpanded] = useState(readSidebarExpanded);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => setDrawerOpen(false), [pathname]);

  function toggleSidebar() {
    const next = !expanded;
    setExpanded(next);
    try {
      localStorage.setItem(SIDEBAR_KEY, next ? "1" : "0");
    } catch {
      // Không ghi được thì lựa chọn chỉ giữ tới khi tải lại trang.
    }
  }

  return (
    <div className="flex h-dvh overflow-hidden bg-gradient-to-b from-sky-50 via-white to-white">
      <aside
        className={`hidden shrink-0 overflow-hidden border-r border-sky-100 bg-white/85 transition-[width] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] will-change-[width] motion-reduce:transition-none lg:block ${
          expanded ? "w-72" : "w-16"
        }`}
      >
        <AppSidebar user={user} collapsed={!expanded} onToggle={toggleSidebar} />
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
