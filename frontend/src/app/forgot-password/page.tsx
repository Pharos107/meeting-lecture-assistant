"use client";

import { useState } from "react";
import Link from "next/link";
import { Mail, ArrowRight, ArrowLeft, Loader2, CheckCircle2 } from "lucide-react";
import { AuthShell } from "@/components/auth-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);

  const validate = (): boolean => {
    const trimmedEmail = email.trim();
    if (!trimmedEmail) {
      setFieldError("Vui lòng nhập email.");
      return false;
    }
    if (!EMAIL_REGEX.test(trimmedEmail)) {
      setFieldError("Vui lòng nhập địa chỉ email hợp lệ.");
      return false;
    }
    setFieldError(null);
    return true;
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (isSubmitting) return;

    if (!validate()) return;

    setIsSubmitting(true);
    // Simulate short network delay for pleasant UX, then show neutral confirmation
    await new Promise((resolve) => setTimeout(resolve, 600));
    setIsSubmitting(false);
    setIsSubmitted(true);
  };

  return (
    <AuthShell>
      {isSubmitted ? (
        <div className="space-y-5 text-center py-2 animate-in fade-in duration-300">
          <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
            <CheckCircle2 className="size-6" />
          </div>

          <div className="space-y-2">
            <h2 className="text-base font-semibold text-[#0f2744]">
              Đã ghi nhận yêu cầu
            </h2>
            <p className="text-xs sm:text-sm text-slate-600 leading-relaxed px-2">
              Nếu email này có tài khoản, hướng dẫn đặt lại mật khẩu sẽ được gửi.
            </p>
          </div>

          <div className="pt-2">
            <Button asChild className="w-full h-11 rounded-full bg-blue-600 hover:bg-blue-700 text-white font-medium text-sm shadow-md shadow-blue-500/20">
              <Link href="/login" className="flex items-center justify-center gap-2">
                <ArrowLeft className="size-4" />
                <span>Quay lại đăng nhập</span>
              </Link>
            </Button>
          </div>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div className="text-center space-y-1 mb-2">
            <h2 className="text-sm sm:text-base font-semibold text-[#0f2744]">
              Quên mật khẩu?
            </h2>
            <p className="text-xs text-slate-500">
              Nhập email của bạn để nhận hướng dẫn đặt lại mật khẩu
            </p>
          </div>

          {/* Email Field */}
          <div className="space-y-1.5">
            <Label htmlFor="email" className="text-xs font-medium text-slate-700 sr-only">
              Email
            </Label>
            <div className="relative">
              <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 size-4 text-slate-400 pointer-events-none" />
              <Input
                id="email"
                type="email"
                autoComplete="email"
                placeholder="Email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (fieldError) setFieldError(null);
                }}
                disabled={isSubmitting}
                className={`h-11 rounded-xl bg-white border-slate-200 pl-10 pr-3 text-sm placeholder:text-slate-400 text-slate-800 shadow-sm transition-all focus-visible:border-blue-500 focus-visible:ring-3 focus-visible:ring-blue-500/20 ${
                  fieldError ? "border-rose-300 ring-2 ring-rose-500/20" : ""
                }`}
              />
            </div>
            {fieldError && (
              <p className="text-xs text-rose-600 pl-1">{fieldError}</p>
            )}
          </div>

          {/* Submit Button */}
          <div className="pt-1">
            <Button
              type="submit"
              disabled={isSubmitting}
              className="w-full h-11 rounded-full bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white font-medium text-sm shadow-md shadow-blue-500/20 transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-70 disabled:cursor-not-allowed"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  <span>Đang gửi...</span>
                </>
              ) : (
                <>
                  <span>Gửi hướng dẫn đặt lại mật khẩu</span>
                  <ArrowRight className="size-4" />
                </>
              )}
            </Button>
          </div>

          {/* Back to Login link */}
          <div className="pt-3 text-center">
            <Link
              href="/login"
              className="inline-flex items-center gap-1.5 text-xs sm:text-sm text-slate-600 hover:text-blue-600 font-medium transition-colors"
            >
              <ArrowLeft className="size-3.5" />
              <span>Quay lại đăng nhập</span>
            </Link>
          </div>
        </form>
      )}
    </AuthShell>
  );
}
