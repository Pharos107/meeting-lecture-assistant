export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  refresh_token: string;
  user: AuthUser;
}

export interface ApiError {
  code: string;
  message: string;
  fields?: Record<string, string>;
}

export interface ApiResponse<T> {
  data?: T;
  error?: ApiError;
}

// In-memory access token storage
let inMemoryAccessToken: string | null = null;
let inMemoryUser: AuthUser | null = null;

export function getAccessToken(): string | null {
  return inMemoryAccessToken;
}

export function setAccessToken(token: string | null): void {
  inMemoryAccessToken = token;
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("refresh_token") || sessionStorage.getItem("refresh_token");
}

export function getCurrentUser(): AuthUser | null {
  if (inMemoryUser) return inMemoryUser;
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem("user") || sessionStorage.getItem("user");
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function saveAuthSession({
  accessToken,
  refreshToken,
  user,
  rememberMe,
}: {
  accessToken: string;
  refreshToken: string;
  user: AuthUser;
  rememberMe: boolean;
}): void {
  inMemoryAccessToken = accessToken;
  inMemoryUser = user;

  if (typeof window === "undefined") return;

  const serializedUser = JSON.stringify(user);
  if (rememberMe) {
    localStorage.setItem("refresh_token", refreshToken);
    localStorage.setItem("user", serializedUser);
    sessionStorage.removeItem("refresh_token");
    sessionStorage.removeItem("user");
  } else {
    sessionStorage.setItem("refresh_token", refreshToken);
    sessionStorage.setItem("user", serializedUser);
    localStorage.removeItem("refresh_token");
    localStorage.removeItem("user");
  }
}

export function clearAuthSession(): void {
  inMemoryAccessToken = null;
  inMemoryUser = null;
  if (typeof window === "undefined") return;
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("user");
  sessionStorage.removeItem("refresh_token");
  sessionStorage.removeItem("user");
}

export async function loginApi({
  email,
  password,
}: {
  email: string;
  password: string;
}): Promise<ApiResponse<AuthResponse>> {
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json; charset=utf-8",
      },
      body: JSON.stringify({
        email: email.trim().toLowerCase(),
        password,
      }),
    });

    const json = await res.json().catch(() => null);

    if (res.ok && json && json.access_token) {
      return { data: json as AuthResponse };
    }

    if (res.status === 401) {
      return {
        error: {
          code: "unauthorized",
          message: "Email hoặc mật khẩu không chính xác.",
        },
      };
    }

    if (json && json.error) {
      return {
        error: {
          code: json.error.code || "unknown_error",
          message: json.error.message || "Đã xảy ra lỗi khi đăng nhập.",
          fields: json.error.fields,
        },
      };
    }

    return {
      error: {
        code: "server_unavailable",
        message: "Không kết nối được máy chủ.",
      },
    };
  } catch {
    return {
      error: {
        code: "network_error",
        message: "Không kết nối được máy chủ.",
      },
    };
  }
}

export async function registerApi({
  email,
  password,
  display_name,
}: {
  email: string;
  password: string;
  display_name: string;
}): Promise<ApiResponse<AuthResponse>> {
  try {
    const res = await fetch("/api/auth/register", {
      method: "POST",
      headers: {
        "Content-Type": "application/json; charset=utf-8",
      },
      body: JSON.stringify({
        email: email.trim().toLowerCase(),
        password,
        display_name: display_name.trim(),
      }),
    });

    const json = await res.json().catch(() => null);

    if ((res.status === 201 || res.ok) && json && json.access_token) {
      return { data: json as AuthResponse };
    }

    if (json && json.error) {
      return {
        error: {
          code: json.error.code || "validation",
          message: json.error.message || "Đã xảy ra lỗi khi đăng ký.",
          fields: json.error.fields,
        },
      };
    }

    return {
      error: {
        code: "server_unavailable",
        message: "Không kết nối được máy chủ.",
      },
    };
  } catch {
    return {
      error: {
        code: "network_error",
        message: "Không kết nối được máy chủ.",
      },
    };
  }
}
