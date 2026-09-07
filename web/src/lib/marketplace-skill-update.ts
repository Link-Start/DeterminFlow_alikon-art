import { MarketplaceApiError } from "./skill-marketplace-http";

export type MarketplaceSkillUpdateStatus =
  | "checking"
  | "available"
  | "current"
  | "unavailable"
  | "missing"
  | "failed";

const MISSING_CODES = new Set(["not_found"]);

export function marketplaceSkillUpdateStatusFromSkill(skill: {
  installation?: { status?: string; update_available?: boolean | null } | null;
}): Extract<MarketplaceSkillUpdateStatus, "available" | "current" | "unavailable"> {
  const installation = skill.installation;
  if (installation?.status !== "installed" || typeof installation.update_available !== "boolean") {
    return "unavailable";
  }
  return installation.update_available ? "available" : "current";
}

export function marketplaceSkillUpdateStatusFromError(error: unknown): "missing" | "failed" {
  return error instanceof MarketplaceApiError && MISSING_CODES.has(error.code)
    ? "missing"
    : "failed";
}

export function marketplaceSkillUpdateLabel(status: MarketplaceSkillUpdateStatus): string {
  return {
    checking: "检查更新",
    available: "可更新",
    current: "已是最新",
    unavailable: "无法更新",
    missing: "资源已下架",
    failed: "重试检查",
  }[status];
}

export function marketplaceSkillUpdateCanRetry(status: MarketplaceSkillUpdateStatus): boolean {
  return status === "failed";
}

export function marketplaceSkillUpdateIsBusy(status: MarketplaceSkillUpdateStatus): boolean {
  return status === "checking";
}

export function marketplaceSkillUpdateIsDisabled(status: MarketplaceSkillUpdateStatus): boolean {
  return status === "checking" || status === "current" || status === "unavailable" || status === "missing";
}
