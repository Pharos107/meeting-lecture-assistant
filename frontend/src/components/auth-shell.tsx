"use client";

import Image from "next/image";
import { Mic, FileText, ListOrdered, CheckSquare, Sparkles } from "lucide-react";
import { Card } from "@/components/ui/card";

export function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative min-h-screen w-full flex items-center justify-center p-4 sm:p-6 lg:p-10 overflow-hidden">
      {/* Background ambient lighting */}
      <div className="absolute inset-0 pointer-events-none -z-10">
        <div className="absolute -top-32 -left-32 w-96 h-96 bg-blue-300/30 rounded-full blur-3xl" />
        <div className="absolute top-1/4 right-0 w-[500px] h-[500px] bg-sky-200/40 rounded-full blur-3xl" />
        <div className="absolute -bottom-32 left-1/3 w-[600px] h-[600px] bg-indigo-100/50 rounded-full blur-3xl" />
      </div>

      <div className="w-full max-w-7xl grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12 items-center">
        {/* Left column: Visual workspace & 4 floating feature cards */}
        <div className="hidden lg:flex lg:col-span-7 flex-col justify-between relative min-h-[660px] rounded-3xl p-8 overflow-hidden bg-gradient-to-br from-white/40 via-sky-50/50 to-blue-100/30 border border-white/70 shadow-xl backdrop-blur-sm">
          {/* Subtle Window & Desk Illustration Background */}
          <div className="absolute inset-0 pointer-events-none -z-10">
            {/* Window vertical & horizontal mullions */}
            <div className="absolute top-0 bottom-0 left-1/3 w-[1px] bg-slate-300/40" />
            <div className="absolute top-0 bottom-0 left-2/3 w-[1px] bg-slate-300/40" />
            <div className="absolute top-1/3 left-0 right-0 h-[1px] bg-slate-300/35" />
            <div className="absolute top-2/3 left-0 right-0 h-[1px] bg-slate-300/35" />

            {/* Sunlight beam */}
            <div className="absolute -top-20 -left-20 w-[600px] h-[700px] bg-gradient-to-br from-white/70 via-sky-100/30 to-transparent rotate-12 blur-2xl opacity-60" />

            {/* Desk horizon & warm ambiance */}
            <div className="absolute bottom-0 left-0 right-0 h-40 bg-gradient-to-t from-slate-200/50 via-slate-100/20 to-transparent" />
            <div className="absolute bottom-6 left-12 right-12 h-1 bg-slate-300/40 rounded-full blur-[1px]" />
          </div>

          {/* Floating Card 1: Chuyển đổi Giọng nói → Văn bản */}
          <div className="relative self-start max-w-xs w-full bg-white/85 backdrop-blur-md rounded-2xl p-4 border border-white/90 shadow-[0_10px_25px_-5px_rgba(37,99,235,0.12)] transition-transform duration-300 hover:scale-[1.02]">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center size-10 rounded-xl bg-blue-600 text-white shadow-md shadow-blue-500/30 shrink-0">
                <Mic className="size-5" />
              </div>
              <div>
                <p className="font-semibold text-sm text-[#0f2744]">Chuyển đổi</p>
                <p className="text-xs font-medium text-blue-600">Giọng nói → Văn bản</p>
              </div>
            </div>
            {/* Audio Waveform visualization */}
            <div className="mt-3.5 flex items-center justify-between gap-1.5 h-7 px-2 py-1 bg-blue-50/80 rounded-lg">
              {[35, 75, 50, 95, 60, 100, 75, 85, 45, 90, 65, 80, 55, 95, 70, 40].map((h, i) => (
                <div
                  key={i}
                  className="w-1 bg-gradient-to-t from-blue-600 to-sky-400 rounded-full shrink-0"
                  style={{ height: `${h}%` }}
                />
              ))}
            </div>
          </div>

          {/* Floating Card 2: Tóm tắt nội dung chính */}
          <div className="relative self-end max-w-xs w-full mr-4 bg-white/85 backdrop-blur-md rounded-2xl p-4 border border-white/90 shadow-[0_10px_25px_-5px_rgba(37,99,235,0.12)] transition-transform duration-300 hover:scale-[1.02]">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center size-10 rounded-xl bg-sky-500 text-white shadow-md shadow-sky-500/30 shrink-0">
                <FileText className="size-5" />
              </div>
              <div>
                <p className="font-semibold text-sm text-[#0f2744]">Tóm tắt</p>
                <p className="text-xs text-slate-500">nội dung chính</p>
              </div>
            </div>
            {/* Summary bullet lines mockup */}
            <div className="mt-3.5 space-y-2 px-1">
              <div className="flex items-center gap-2">
                <span className="size-2 rounded-full bg-sky-500 shrink-0" />
                <div className="h-2 w-4/5 rounded bg-sky-100" />
              </div>
              <div className="flex items-center gap-2">
                <span className="size-2 rounded-full bg-sky-400 shrink-0" />
                <div className="h-2 w-3/5 rounded bg-sky-100" />
              </div>
              <div className="flex items-center gap-2">
                <span className="size-2 rounded-full bg-sky-300 shrink-0" />
                <div className="h-2 w-2/3 rounded bg-sky-100" />
              </div>
            </div>
          </div>

          {/* Floating Card 3: Trích xuất biên bản */}
          <div className="relative self-start max-w-xs w-full ml-4 bg-white/85 backdrop-blur-md rounded-2xl p-4 border border-white/90 shadow-[0_10px_25px_-5px_rgba(37,99,235,0.12)] transition-transform duration-300 hover:scale-[1.02]">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center size-10 rounded-xl bg-indigo-600 text-white shadow-md shadow-indigo-500/30 shrink-0">
                <ListOrdered className="size-5" />
              </div>
              <div>
                <p className="font-semibold text-sm text-[#0f2744]">Trích xuất</p>
                <p className="text-xs text-slate-500">biên bản</p>
              </div>
            </div>
            {/* Minutes item lines mockup */}
            <div className="mt-3.5 space-y-2 px-1">
              <div className="flex items-center gap-2">
                <span className="size-2 rounded-full bg-indigo-500 shrink-0" />
                <div className="h-2 w-5/6 rounded bg-indigo-100" />
              </div>
              <div className="flex items-center gap-2">
                <span className="size-2 rounded-full bg-indigo-400 shrink-0" />
                <div className="h-2 w-1/2 rounded bg-indigo-100" />
              </div>
            </div>
          </div>

          {/* Floating Card 4: Hỗ trợ cuộc họp / bài giảng */}
          <div className="relative self-end max-w-xs w-full bg-white/85 backdrop-blur-md rounded-2xl p-4 border border-white/90 shadow-[0_10px_25px_-5px_rgba(37,99,235,0.12)] transition-transform duration-300 hover:scale-[1.02]">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center size-10 rounded-xl bg-blue-700 text-white shadow-md shadow-blue-700/30 shrink-0">
                <CheckSquare className="size-5" />
              </div>
              <div>
                <p className="font-semibold text-sm text-[#0f2744]">Hỗ trợ</p>
                <p className="text-xs text-slate-500">cuộc họp / bài giảng</p>
              </div>
            </div>
            {/* Checklist mockup */}
            <div className="mt-3.5 space-y-2 px-1">
              <div className="flex items-center gap-2">
                <span className="text-blue-600 text-xs font-bold shrink-0">✓</span>
                <div className="h-2 w-4/5 rounded bg-blue-100" />
              </div>
              <div className="flex items-center gap-2">
                <span className="text-blue-600 text-xs font-bold shrink-0">✓</span>
                <div className="h-2 w-3/4 rounded bg-blue-100" />
              </div>
              <div className="flex items-center gap-2">
                <span className="text-blue-600 text-xs font-bold shrink-0">✓</span>
                <div className="h-2 w-2/3 rounded bg-blue-100" />
              </div>
            </div>
          </div>

          {/* Bottom badge */}
          <div className="mt-4 flex items-center justify-between text-xs text-slate-500 pt-3 border-t border-slate-200/50">
            <span className="flex items-center gap-1.5 font-medium text-slate-600">
              <Sparkles className="size-3.5 text-blue-600" />
              Độ chính xác cao & Xử lý thời gian thực
            </span>
            <span>Phiên bản 1.3</span>
          </div>
        </div>

        {/* Right column: Auth Card */}
        <div className="w-full flex justify-center lg:col-span-5">
          <Card className="w-full max-w-[460px] bg-white/95 backdrop-blur-xl rounded-3xl border border-white/80 shadow-2xl p-6 sm:p-8 lg:p-9 ring-1 ring-slate-100">
            {/* Header: Logo, Title, Subtitle */}
            <div className="flex flex-col items-center text-center">
              <div className="relative size-18 sm:size-20 mb-3 drop-shadow-sm">
                <Image
                  src="/logo.png"
                  alt="Logo Hệ thống Trợ lý Tự động"
                  width={80}
                  height={80}
                  priority
                  className="w-full h-full object-contain"
                />
              </div>
              <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-[#0f2744]">
                Hệ thống Trợ lý Tự động
              </h1>
              <p className="text-xs sm:text-sm text-slate-500 mt-1.5 max-w-sm leading-relaxed">
                Chuyển đổi, Tóm tắt và Trích xuất Biên bản Cuộc họp / Bài giảng Tiếng Việt
              </p>
            </div>

            {/* Form body injected as children */}
            <div className="mt-6">
              {children}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
