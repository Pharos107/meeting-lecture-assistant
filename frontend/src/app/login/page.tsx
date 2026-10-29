"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Mail, Lock, Eye, EyeOff, ArrowRight, Loader2, AlertCircle, Info } from "lucide-react";
import { AuthShell } from "@/components/auth-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { loginApi, saveAuthSession } from "@/lib/auth";
import { startSessionTimer } from "@/lib/api";

function GoogleIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" {...props}>
      <path
        fill="#4285F4"
        d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.82-2.4 3.68v3.05h3.88c2.27-2.09 3.665-5.17 3.665-9.17z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.25v3.15C3.26 21.36 7.33 24 12 24z"
      />
      <path
        fill="#FBBC05"
        d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.58H1.25C.45 8.18 0 9.99 0 12s.45 3.82 1.25 5.42l4.03-3.15z"
      />
      <path
        fill="#EA4335"
        d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.33 0 3.26 2.64 1.25 6.58l4.03 3.15c.95-2.83 3.6-4.98 6.72-4.98z"
      />
    </svg>
  );
}

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function LoginPage() {
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);

  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({});
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [googleNotice, setGoogleNotice] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const validate = (): boolean => {
    const errors: { email?: string; password?: string } = {};

    const trimmedEmail = email.trim();
    if (!trimmedEmail) {
      errors.email = "Vui lòng nhập email.";
    } else if (!EMAIL_REGEX.test(trimmedEmail)) {
      errors.email = "Vui lòng nhập địa chỉ email hợp lệ.";
    }

    if (!password) {
      errors.password = "Vui lòng nhập mật khẩu.";
    } else if (password.length < 8 || password.length > 128) {
      errors.password = "Mật khẩu phải từ 8 đến 128 ký tự.";
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (isSubmitting) return;

    setGeneralError(null);
    setGoogleNotice(null);

    if (!validate()) return;

    setIsSubmitting(true);
    try {
      const result = await loginApi({ email, password });

      if (result.data) {
        saveAuthSession({
          accessToken: result.data.access_token,
          refreshToken: result.data.refresh_token,
          user: result.data.user,
          rememberMe,
        });
        startSessionTimer(result.data.expires_in);
        router.push("/jobs");
      } else if (result.error) {
        if (result.error.fields) {
          setFieldErrors({
            email: result.error.fields.email,
            password: result.error.fields.password,
          });
        }
        setGeneralError(result.error.message);
      }
    } catch {
      setGeneralError("Không kết nối được máy chủ.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthShell>
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {generalError && (
          <div
            role="alert"
            className="flex items-start gap-2.5 p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium animate-in fade-in duration-200"
          >
            <AlertCircle className="size-4 shrink-0 text-rose-500 mt-0.5" />
            <span className="leading-tight">{generalError}</span>
          </div>
        )}

        {googleNotice && (
          <div
            role="status"
            className="flex items-start gap-2.5 p-3 rounded-xl bg-blue-50 border border-blue-200 text-blue-800 text-xs font-medium animate-in fade-in duration-200"
          >
            <Info className="size-4 shrink-0 text-blue-600 mt-0.5" />
            <span className="leading-tight">{googleNotice}</span>
          </div>
        )}

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
                if (fieldErrors.email) {
                  setFieldErrors((prev) => ({ ...prev, email: undefined }));
                }
              }}
              disabled={isSubmitting}
              className={`h-11 rounded-xl bg-white border-slate-200 pl-10 pr-3 text-sm placeholder:text-slate-400 text-slate-800 shadow-sm transition-all focus-visible:border-blue-500 focus-visible:ring-3 focus-visible:ring-blue-500/20 ${
                fieldErrors.email ? "border-rose-300 ring-2 ring-rose-500/20" : ""
              }`}
            />
          </div>
          {fieldErrors.email && (
            <p className="text-xs text-rose-600 pl-1">{fieldErrors.email}</p>
          )}
        </div>

        {/* Password Field */}
        <div className="space-y-1.5">
          <Label htmlFor="password" className="text-xs font-medium text-slate-700 sr-only">
            Mật khẩu
          </Label>
          <div className="relative">
            <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 size-4 text-slate-400 pointer-events-none" />
            <Input
              id="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              placeholder="Mật khẩu"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                if (fieldErrors.password) {
                  setFieldErrors((prev) => ({ ...prev, password: undefined }));
                }
              }}
              disabled={isSubmitting}
              className={`h-11 rounded-xl bg-white border-slate-200 pl-10 pr-10 text-sm placeholder:text-slate-400 text-slate-800 shadow-sm transition-all focus-visible:border-blue-500 focus-visible:ring-3 focus-visible:ring-blue-500/20 ${
                fieldErrors.password ? "border-rose-300 ring-2 ring-rose-500/20" : ""
              }`}
            />
            <button
              type="button"
              tabIndex={-1}
              onClick={() => setShowPassword(!showPassword)}
              aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
              className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 focus:outline-none transition-colors"
            >
              {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </div>
          {fieldErrors.password && (
            <p className="text-xs text-rose-600 pl-1">{fieldErrors.password}</p>
          )}
        </div>

        {/* Remember me & Forgot Password */}
        <div className="flex items-center justify-between pt-1">
          <div className="flex items-center gap-2">
            <Checkbox
              id="remember"
              checked={rememberMe}
              onCheckedChange={(checked) => setRememberMe(Boolean(checked))}
              disabled={isSubmitting}
              className="rounded-md border-slate-300 data-checked:bg-blue-600 data-checked:border-blue-600"
            />
            <Label
              htmlFor="remember"
              className="text-xs sm:text-sm text-slate-600 cursor-pointer select-none font-normal"
            >
              Ghi nhớ đăng nhập
            </Label>
          </div>
          <Link
            href="/forgot-password"
            className="text-xs sm:text-sm text-blue-600 hover:text-blue-700 hover:underline font-medium transition-colors"
          >
            Quên mật khẩu?
          </Link>
        </div>

        {/* Main Submit Button */}
        <Button
          type="submit"
          disabled={isSubmitting}
          className="w-full h-11 rounded-full bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white font-medium text-sm shadow-md shadow-blue-500/20 transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-70 disabled:cursor-not-allowed"
        >
          {isSubmitting ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              <span>Đang đăng nhập...</span>
            </>
          ) : (
            <>
              <span>Đăng nhập</span>
              <ArrowRight className="size-4" />
            </>
          )}
        </Button>

        {/* Divider HOẶC */}
        <div className="relative py-2">
          <div className="absolute inset-0 flex items-center">
            <span className="w-full border-t border-slate-200" />
          </div>
          <div className="relative flex justify-center text-xs uppercase">
            <span className="bg-white px-3 text-slate-400 font-semibold tracking-wider">
              HOẶC
            </span>
          </div>
        </div>

        {/* Secondary Google Button */}
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            setGeneralError(null);
            setGoogleNotice("Đăng nhập Google chưa có trong bản này.");
          }}
          disabled={isSubmitting}
          className="w-full h-11 rounded-full border border-slate-200 bg-white hover:bg-slate-50 active:bg-slate-100 text-slate-700 font-medium text-sm flex items-center justify-center gap-2.5 shadow-xs transition-colors cursor-pointer"
        >
          <GoogleIcon />
          <span>Đăng nhập bằng Google</span>
        </Button>

        {/* Register link */}
        <div className="pt-2 text-center text-xs text-slate-500">
          Chưa có tài khoản?{" "}
          <Link
            href="/register"
            className="text-blue-600 hover:text-blue-700 font-medium hover:underline transition-colors"
          >
            Đăng ký ngay
          </Link>
        </div>
      </form>
    </AuthShell>
  );
}
