export function parseApiError(error: unknown, fallback = "请求失败"): string {
  const raw = error instanceof Error ? error.message : String(error ?? "");
  const match = raw.match(/^API Error (\d+):\s*([\s\S]*)$/);
  if (!match) return raw.trim() || fallback;
  const status = Number(match[1]);
  const body = match[2].trim();
  let detail = body;
  try {
    const parsed = JSON.parse(body) as { detail?: unknown; message?: unknown };
    if (typeof parsed.detail === "string") detail = parsed.detail;
    else if (Array.isArray(parsed.detail)) {
      detail = parsed.detail
        .map((item) => {
          if (typeof item === "string") return item;
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: unknown }).msg);
          }
          return "";
        })
        .filter(Boolean)
        .join("；");
    } else if (typeof parsed.message === "string") {
      detail = parsed.message;
    }
  } catch {
    // Keep the raw body when it is not JSON.
  }
  if ((status === 401 || status === 403) && !detail) {
    return "需要有效的管理令牌才能保存插件配置";
  }
  return detail || raw || fallback;
}

export function isPluginAuthError(error: unknown): boolean {
  const raw = error instanceof Error ? error.message : String(error ?? "");
  return /^API Error (401|403):/.test(raw);
}
