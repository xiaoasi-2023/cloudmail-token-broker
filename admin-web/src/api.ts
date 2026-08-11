import type {
  AdminUser,
  CloudMailInstance,
  CreditAdjustResult,
  CreditRule,
  DomainPayload,
  InstancePayload,
  MailboxRecord,
  MailDomain,
  Overview,
  PopAuthCodeResult,
  RequestLog,
} from "./types";

type ApiEnvelope<T> = { ok: boolean; data: T; username?: string };

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(message: string, status: number, code = "REQUEST_FAILED") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/admin-api${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  let payload: ApiEnvelope<T> | { detail?: { code?: string; message?: string } } | null = null;
  try {
    payload = await response.json();
  } catch {
    // 非 JSON 错误也转换为统一错误，避免页面失去反馈。
  }

  if (!response.ok) {
    const detail = payload && "detail" in payload ? payload.detail : undefined;
    if (response.status === 401) {
      window.dispatchEvent(new Event("admin-unauthorized"));
    }
    throw new ApiError(detail?.message || `请求失败（HTTP ${response.status}）`, response.status, detail?.code);
  }

  return payload as T;
}

export const api = {
  session: () => request<{ ok: boolean; authenticated: boolean; username: string }>("/auth/session"),
  login: (username: string, password: string) =>
    request<{ ok: boolean; username: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  overview: async () => (await request<ApiEnvelope<Overview>>("/overview")).data,
  instances: async () => (await request<ApiEnvelope<CloudMailInstance[]>>("/instances")).data,
  createInstance: (data: InstancePayload) =>
    request<ApiEnvelope<CloudMailInstance>>("/instances", { method: "POST", body: JSON.stringify(data) }),
  updateInstance: (id: number, data: Partial<InstancePayload>) =>
    request<ApiEnvelope<CloudMailInstance>>(`/instances/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteInstance: (id: number) => request(`/instances/${id}`, { method: "DELETE" }),
  testInstance: (id: number) => request<ApiEnvelope<{ latency_ms?: number; message?: string; status?: string }>>(`/instances/${id}/test`, { method: "POST" }),
  domains: async (instanceId?: number) => {
    const query = instanceId ? `?instance_id=${instanceId}` : "";
    return (await request<ApiEnvelope<MailDomain[]>>(`/domains${query}`)).data;
  },
  createDomain: (data: DomainPayload) =>
    request<ApiEnvelope<MailDomain>>("/domains", { method: "POST", body: JSON.stringify(data) }),
  updateDomain: (id: number, data: Partial<DomainPayload>) =>
    request<ApiEnvelope<MailDomain>>(`/domains/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteDomain: (id: number) => request(`/domains/${id}`, { method: "DELETE" }),
  clearDomainCooldown: (id: number) => request(`/domains/${id}/clear-cooldown`, { method: "POST" }),
  mailboxes: async (limit = 100, offset = 0, keyword = "", purpose = "") => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (keyword.trim()) params.set("keyword", keyword.trim());
    if (purpose.trim()) params.set("purpose", purpose.trim());
    return (await request<ApiEnvelope<MailboxRecord[]>>(`/mailboxes?${params.toString()}`)).data;
  },
  requestLogs: async (limit = 100, offset = 0) =>
    (await request<ApiEnvelope<RequestLog[]>>(`/request-logs?limit=${limit}&offset=${offset}`)).data,
  users: async () => (await request<ApiEnvelope<AdminUser[]>>("/users")).data,
  updateUser: (id: number, enabled: boolean) =>
    request<ApiEnvelope<AdminUser>>(`/users/${id}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
  resetUserAuthCode: (id: number) =>
    request<ApiEnvelope<{ user_id: number; configured: boolean }>>(`/users/${id}/reset-auth-code`, { method: "POST" }),
  adjustUserCredits: (id: number, amount: number, reason: string) =>
    request<ApiEnvelope<CreditAdjustResult>>(`/users/${id}/credits/adjust`, {
      method: "POST",
      body: JSON.stringify({ amount, reason }),
    }),
  creditRules: async () => (await request<ApiEnvelope<CreditRule>>("/credit-rules")).data,
  updateCreditRules: async (data: Pick<CreditRule, "cost_points" | "initial_user_points">) =>
    (await request<ApiEnvelope<CreditRule>>("/credit-rules", { method: "PUT", body: JSON.stringify(data) })).data,
  setAdminPopAuthCode: (authCode: string) =>
    request<ApiEnvelope<PopAuthCodeResult>>("/pop-auth-code", { method: "PUT", body: JSON.stringify({ auth_code: authCode }) }),
};
