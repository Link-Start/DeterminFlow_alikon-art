function detailMessage(body: unknown): string | null {
  if (!body || typeof body !== "object" || !("detail" in body)) {
    return null;
  }
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  return null;
}

function uninstallErrorMessage(body: unknown, status: number): string {
  return detailMessage(body)
    ?? (status === 404
      ? "该 Skill 已不存在。"
      : status === 403
        ? "没有权限卸载该 Skill。"
        : "卸载失败，请稍后重试。");
}

export async function uninstallLocalSkill(skillId: string): Promise<void> {
  const response = await fetch(`/api/skills/${encodeURIComponent(skillId)}`, {
    method: "DELETE",
  });
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    throw new Error(uninstallErrorMessage(body, response.status));
  }
  if (!body || typeof body !== "object" || !("success" in body) || body.success !== true) {
    throw new Error("未能确认卸载结果，请刷新后重试。");
  }
}
