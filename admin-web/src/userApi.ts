import type { BatchCreateMailboxesResult, CreditSummary, UserApiKey, UserAuthCodeInfo, UserMailbox, UserProfile } from "./userTypes";

type ApiEnvelope<T> = {
  ok?: boolean;
  code?: number | string;
  data?: T;
  detail?: { code?: string; message?: string } | Array<{ msg?: string; loc?: Array<string | number> }>;
  message?: string;
};

export class UserApiError extends Error {
  status: number;
  code: string;

  constructor(message: string, status: number, code = "REQUEST_FAILED") {
    super(message);
    this.name = "UserApiError";
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/user-api${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  let payload: ApiEnvelope<T> | T | null = null;
  try {
    payload = await response.json();
  } catch {
    // 非 JSON 响应统一转为可读错误。
  }

  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload
      ? (payload as ApiEnvelope<T>).detail
      : undefined;
    const detailMessage = Array.isArray(detail)
      ? detail.find((item) => item.msg)?.msg
      : detail?.message;
    const detailCode = Array.isArray(detail) ? undefined : detail?.code;
    if (response.status === 401) {
      window.dispatchEvent(new Event("user-unauthorized"));
    }
    throw new UserApiError(
      detailMessage || (payload && typeof payload === "object" && "message" in payload ? String((payload as ApiEnvelope<T>).message) : "请求失败，请稍后重试") || `请求失败（HTTP ${response.status}）`,
      response.status,
      detailCode || String(payload && typeof payload === "object" && "code" in payload ? (payload as ApiEnvelope<T>).code : "REQUEST_FAILED"),
    );
  }

  return payload as T;
}

function unwrap<T>(payload: ApiEnvelope<T> | T): T {
  if (payload && typeof payload === "object" && "data" in payload && payload.data !== undefined) {
    return payload.data as T;
  }
  return payload as T;
}

function asList<T>(payload: unknown): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (payload && typeof payload === "object") {
    const value = payload as { items?: unknown; records?: unknown; list?: unknown; data?: unknown };
    if (Array.isArray(value.items)) return value.items as T[];
    if (Array.isArray(value.records)) return value.records as T[];
    if (Array.isArray(value.list)) return value.list as T[];
    if (Array.isArray(value.data)) return value.data as T[];
  }
  return [];
}

export const userApi = {
  registrationConfig: async () => unwrap(await request<ApiEnvelope<{ enabled: boolean; code_ttl_seconds: number; code_cooldown_seconds: number }> | { enabled: boolean; code_ttl_seconds: number; code_cooldown_seconds: number }>("/auth/registration-config", { cache: "no-store" })),
  sendRegisterCode: async (email: string) => unwrap(await request<ApiEnvelope<{ ttl_seconds: number; cooldown_seconds: number }> | { ttl_seconds: number; cooldown_seconds: number }>("/auth/register-code", {
    method: "POST",
    body: JSON.stringify({ email: String(email || "").trim() }),
  })),
  register: async (username: string, email: string, password: string, code: string) => unwrap(await request<ApiEnvelope<UserProfile> | UserProfile>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, email, password, code }),
  })),
  me: async () => unwrap(await request<ApiEnvelope<UserProfile> | UserProfile>("/me")),
  login: (username: string, password: string) =>
    request<ApiEnvelope<{ username?: string }> | { username?: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<ApiEnvelope<{ ok: boolean }> | { ok: boolean }>("/auth/logout", { method: "POST" }),
  changePassword: (currentPassword: string, newPassword: string) =>
    request<ApiEnvelope<unknown> | unknown>("/auth/password", {
      method: "PUT",
      body: JSON.stringify({ currentPassword, newPassword }),
    }),
  revokeAllSessions: () =>
    request<ApiEnvelope<unknown> | unknown>("/auth/sessions/revoke-all", { method: "POST" }),
  apiKeys: async () => asList<UserApiKey>(unwrap(await request<ApiEnvelope<unknown> | unknown>("/api-keys"))),
  createApiKey: async (name: string) =>
    unwrap(await request<ApiEnvelope<UserApiKey> | UserApiKey>("/api-keys", {
      method: "POST",
      body: JSON.stringify({ name }),
    })),
  regenerateApiKey: async (id: string | number) =>
    unwrap(await request<ApiEnvelope<UserApiKey> | UserApiKey>(`/api-keys/${encodeURIComponent(String(id))}/regenerate`, {
      method: "POST",
    })),
  revokeApiKey: (id: string | number) =>
    request<ApiEnvelope<unknown> | unknown>(`/api-keys/${encodeURIComponent(String(id))}`, { method: "DELETE" }),
  authCode: async () =>
    unwrap(await request<ApiEnvelope<UserAuthCodeInfo> | UserAuthCodeInfo>("/auth-code", { cache: "no-store" })),
  setAuthCode: async (userAuthCode: string) =>
    unwrap(await request<ApiEnvelope<UserAuthCodeInfo> | UserAuthCodeInfo>("/auth-code", {
      method: "PUT",
      body: JSON.stringify({ userAuthCode }),
    })),
  credits: async () => {
    const data = unwrap(await request<ApiEnvelope<unknown> | unknown>("/credits"));
    const record = (data && typeof data === "object" ? data : {}) as {
      balance?: number;
      credits?: number;
      credit_balance?: number;
      creditBalance?: number;
      transactions?: CreditSummary["transactions"];
      items?: CreditSummary["transactions"];
      records?: CreditSummary["transactions"];
    };
    return {
      balance: Number(record.balance ?? record.credits ?? record.credit_balance ?? record.creditBalance ?? 0),
      transactions: record.transactions || record.items || record.records || [],
    } satisfies CreditSummary;
  },
  mailboxes: async (keyword = "", purpose = "", status = "", verificationStatus = "") => {
    const params = new URLSearchParams({ limit: "100", offset: "0" });
    if (keyword.trim()) params.set("keyword", keyword.trim());
    if (purpose.trim()) params.set("purpose", purpose.trim());
    if (status.trim()) params.set("status", status.trim());
    if (verificationStatus.trim()) params.set("verification_status", verificationStatus.trim());
    return asList<UserMailbox>(unwrap(await request<ApiEnvelope<unknown> | unknown>(`/mailboxes?${params.toString()}`)));
  },
  createMailboxesBatch: async (data: { count: number; purpose: string; domain?: string }) =>
    unwrap(await request<ApiEnvelope<BatchCreateMailboxesResult> | BatchCreateMailboxesResult>("/mailboxes/batch", {
      method: "POST",
      headers: { "Idempotency-Key": window.crypto.randomUUID() },
      body: JSON.stringify({
        count: data.count,
        purpose: data.purpose,
        domain: data.domain?.trim() || undefined,
      }),
    })),
};
