export interface AccountStatus {
  configured: boolean;
  signed_in: boolean;
}

export const ACCOUNT_STATUS_EVENT = "determinflow:account-status";
export const ACCOUNT_LOGIN_EVENT = "determinflow:account-login-pending";
let loginFlight: Promise<AccountStatus> | null = null;
let confirmedLoginFlight: Promise<AccountStatus> | null = null;
let cancelFlight: Promise<AccountStatus> | null = null;
let loginAttempt: { id: string; controller: AbortController } | null = null;
let pendingCancellation: string | null = null;
let accountGeneration = 0;

export function isAccountLoginPending(): boolean {
  return confirmedLoginFlight !== null || loginFlight !== null || cancelFlight !== null;
}

export function isAccountLoginCancelling(): boolean { return cancelFlight !== null; }

function publishLoginPending(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent<boolean>(ACCOUNT_LOGIN_EVENT, { detail: isAccountLoginPending() }));
  }
}

export function publishAccountStatus(status: AccountStatus): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent<AccountStatus>(ACCOUNT_STATUS_EVENT, {
      detail: status,
    }));
  }
}

export class AccountApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly statusCode = 0,
  ) {
    super(message);
    this.name = "AccountApiError";
  }
}

async function requestAccount(
  path: string,
  init?: RequestInit,
  timeoutMs = 10_000,
): Promise<AccountStatus> {
  const controller = new AbortController();
  const cancelled = () => controller.abort(new AccountApiError("cancelled", "登录已取消"));
  const timer = setTimeout(() => controller.abort(new AccountApiError(
    "request_timeout", "账号请求超时，请重试",
  )), timeoutMs);
  const aborted = new Promise<never>((_resolve, reject) => {
    controller.signal.addEventListener("abort", () => reject(controller.signal.reason), { once: true });
  });
  init?.signal?.addEventListener("abort", cancelled, { once: true });
  if (init?.signal?.aborted) cancelled();
  try {
    return await Promise.race([
      readAccountResponse(path, { ...init, signal: controller.signal }), aborted,
    ]);
  } catch (error) {
    if (controller.signal.aborted) throw controller.signal.reason;
    if (error instanceof TypeError) throw new AccountApiError("network_unavailable", "暂时无法连接账号服务，请重试");
    throw error;
  } finally {
    clearTimeout(timer);
    init?.signal?.removeEventListener("abort", cancelled);
  }
}

async function readAccountResponse(path: string, init?: RequestInit): Promise<AccountStatus> {
  const response = await fetch(path, init);
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new AccountApiError(
      "invalid_response",
      "账号服务返回了无效响应",
      response.status,
    );
  }
  if (!response.ok) {
    const envelope = body && typeof body === "object"
      ? body as Record<string, unknown>
      : {};
    const detail = envelope.detail;
    if (detail && typeof detail === "object") {
      const record = detail as Record<string, unknown>;
      throw new AccountApiError(
        typeof record.code === "string" ? record.code : "request_failed",
        typeof record.message === "string" ? record.message : "账号请求失败",
        response.status,
      );
    }
    throw new AccountApiError(
      "request_failed",
      typeof detail === "string" ? detail : "账号请求失败",
      response.status,
    );
  }
  if (!body || typeof body !== "object") {
    throw new AccountApiError("invalid_response", "账号服务返回了无效响应", response.status);
  }
  const record = body as Record<string, unknown>;
  if (typeof record.configured !== "boolean" || typeof record.signed_in !== "boolean") {
    throw new AccountApiError("invalid_response", "账号服务返回了无效响应", response.status);
  }
  return {
    configured: record.configured,
    signed_in: record.signed_in,
  };
}

export function fetchAccountStatus(): Promise<AccountStatus> {
  return requestAccount("/api/account/status");
}

export function loginAccount(): Promise<AccountStatus> {
  if (cancelFlight) return cancelFlight.then(() => loginAccount());
  if (pendingCancellation) return cancelAccountLogin().then(() => loginAccount());
  if (loginFlight) return loginFlight;
  const generation = accountGeneration;
  const attempt = { id: crypto.randomUUID(), controller: new AbortController() };
  loginAttempt = attempt;
  const flight = requestAccount("/api/account/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ attempt_id: attempt.id }),
    signal: attempt.controller.signal,
  }, 190_000).then((status) => {
    if (generation !== accountGeneration) throw new AccountApiError("cancelled", "登录已取消");
    publishAccountStatus(status);
    return status;
  }).catch((error) => {
    if (error instanceof AccountApiError && error.code === "request_timeout") {
      void cancelAccountLogin().catch(() => {});
    }
    throw error;
  }).finally(() => {
    if (loginFlight === flight) loginFlight = null;
    if (loginAttempt === attempt) loginAttempt = null;
    publishLoginPending();
  });
  loginFlight = flight;
  publishLoginPending();
  return flight;
}

/** Share the confirmation and browser wait across the header and all embedded features. */
export function requestAccountLogin(confirm: () => Promise<boolean>): Promise<AccountStatus> {
  if (cancelFlight) return cancelFlight.then(() => requestAccountLogin(confirm));
  if (confirmedLoginFlight) return confirmedLoginFlight;
  if (loginFlight) return loginFlight;
  const generation = accountGeneration;
  const flight = Promise.resolve().then(confirm).then((accepted) => {
    if (!accepted || generation !== accountGeneration) throw new AccountApiError("cancelled", "登录已取消");
    return loginAccount();
  }).finally(() => {
    if (confirmedLoginFlight === flight) confirmedLoginFlight = null;
    publishLoginPending();
  });
  confirmedLoginFlight = flight;
  publishLoginPending();
  return flight;
}

export function cancelAccountLogin(): Promise<AccountStatus> {
  if (cancelFlight) return cancelFlight;
  accountGeneration += 1;
  const generation = accountGeneration;
  const attempt = loginAttempt;
  const attemptId = attempt?.id ?? pendingCancellation;
  pendingCancellation = attemptId;
  attempt?.controller.abort();
  const flight = (attemptId ? requestAccount("/api/account/login/cancel", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ attempt_id: attemptId }),
  }) : fetchAccountStatus()).then((status) => {
    if (pendingCancellation === attemptId) pendingCancellation = null;
    // A cancelled signed-out login did not change identity. Do not reset embeds.
    // A success that won the server-side race must still be reflected everywhere.
    if (generation === accountGeneration && status.signed_in) publishAccountStatus(status);
    return status;
  }).finally(() => {
    if (cancelFlight === flight) cancelFlight = null;
    publishLoginPending();
  });
  cancelFlight = flight;
  publishLoginPending();
  return flight;
}

export async function logoutAccount(): Promise<AccountStatus> {
  accountGeneration += 1;
  const status = await requestAccount("/api/account/logout", { method: "POST" });
  pendingCancellation = null;
  publishAccountStatus(status);
  return status;
}
