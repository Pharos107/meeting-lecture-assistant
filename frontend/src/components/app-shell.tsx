"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { LogOut } from "lucide-react";
import { ensureSession, logout } from "@/lib/api";
import { getCurrentUser, type AuthUser } from "@/lib/auth";

const NAV = [
  { href: "/jobs", label: "Danh sách job" },
  { href: "/jobs/new", label: "Tải file" },
  { href: "/live", label: "Nghe trực tiếp" },
  { href: "/voice-profiles", label: "Hồ sơ giọng" },
];

/** Khung trang sau đăng nhập. Không có phiên hợp lệ thì chuyển về /login. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
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

  return (
    <div className="min-h-screen bg-gradient-to-b from-sky-50 via-white to-white">
      <header className="sticky top-0 z-30 border-b border-sky-100 bg-white/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3 sm:px-6">
          <Link href="/jobs" className="flex shrink-0 items-center gap-2">
            <Image src="/logo.png" alt="" width={32} height={32} className="size-8 object-contain" />
            <span className="hidden text-sm font-semibold text-[#0f2744] sm:inline">Trợ lý biên bản</span>
          </Link>
          <nav className="flex min-w-0 flex-1 gap-1 overflow-x-auto text-sm">
            {NAV.map((item) => {
              const active =
                item.href === "/jobs"
                  ? pathname === "/jobs" || (pathname.startsWith("/jobs/") && pathname !== "/jobs/new")
                  : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`shrink-0 rounded-full px-3 py-1.5 ${
                    active ? "bg-blue-600 font-medium text-white" : "text-slate-600 hover:bg-sky-100"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          {user ? <span className="hidden truncate text-sm text-slate-500 md:inline">{user.display_name}</span> : null}
          <button
            type="button"
            onClick={() => void logout()}
            className="flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100"
          >
            <LogOut className="size-4" />
            <span className="hidden sm:inline">Đăng xuất</span>
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        {ready ? children : <p className="py-20 text-center text-sm text-slate-500">Đang kiểm tra phiên đăng nhập…</p>}
      </main>
    </div>
  );
}
