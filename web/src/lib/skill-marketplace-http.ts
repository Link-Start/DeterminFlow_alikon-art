export class MarketplaceApiError extends Error {
  readonly retry_after_seconds?: number;

  constructor(public readonly code: string, message: string, retryAfterSeconds?: number) {
    super(message);
    this.name = "MarketplaceApiError";
    if (retryAfterSeconds != null) this.retry_after_seconds = retryAfterSeconds;
  }
}

function parseRetryAfterSeconds(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 3600) {
    return value;
  }
  if (typeof value === "string" && /^\d+$/.test(value)) {
    const seconds = Number(value);
    if (seconds >= 1 && seconds <= 3600) return seconds;
  }
  return undefined;
}

function readRetryAfterSeconds(envelope: Record<string, unknown>, response: Response): number | undefined {
  const detail = envelope.detail;
  const nested = detail && typeof detail === "object" && !Array.isArray(detail)
    ? (detail as Record<string, unknown>).retry_after_seconds
    : undefined;
  for (const candidate of [envelope.retry_after_seconds, nested, response.headers.get("Retry-After")]) {
    const seconds = parseRetryAfterSeconds(candidate);
    if (seconds !== undefined) return seconds;
  }
  return undefined;
}

export async function requestJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效响应");
  }
  if (!response.ok) {
    const envelope = body && typeof body === "object" ? body as Record<string, unknown> : {};
    const detail = envelope.detail;
    const retryAfter = readRetryAfterSeconds(envelope, response);
    if (detail && typeof detail === "object") {
      const record = detail as Record<string, unknown>;
      throw new MarketplaceApiError(
        typeof record.code === "string" ? record.code : "request_failed",
        typeof record.message === "string" ? record.message : "请求失败",
        retryAfter,
      );
    }
    throw new MarketplaceApiError(
      typeof envelope.code === "string" ? envelope.code : "request_failed",
      typeof detail === "string" ? detail : "请求失败",
      retryAfter,
    );
  }
  return body as T;
}
