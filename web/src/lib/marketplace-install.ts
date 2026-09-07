import { MarketplaceApiError } from "./skill-marketplace-http";
import type { MarketplaceSkill } from "./skill-marketplace";

export const SHA256_PATTERN = /^[0-9a-f]{64}$/;
export const VERSION_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const SKILL_ID_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export interface TrustedInstallPin {
  slug: string;
  displayName: string;
  version: string;
  expected_version_id: string;
  expected_sha256: string;
}

export function readTrustedInstallPin(skill: MarketplaceSkill): TrustedInstallPin {
  const slug = skill.slug;
  const displayName = skill.name || skill.resource.display_name || slug;
  const version = skill.version || skill.resource.release.version;
  const expected_version_id = skill.version_id || skill.resource.version_id || "";
  const expected_sha256 = skill.sha256 || skill.payload.sha256 || "";
  if (
    !slug
    || !version
    || !VERSION_ID_PATTERN.test(expected_version_id)
    || !SHA256_PATTERN.test(expected_sha256)
  ) {
    throw new MarketplaceApiError("invalid_integrity", "Skill 缺少可信完整性信息");
  }
  return {
    slug,
    displayName,
    version,
    expected_version_id,
    expected_sha256,
  };
}

export function readCompletedInstall(result: unknown, expectedSkillId?: string): {
  installed: true;
  skill_id: string;
  enabled: true;
} {
  if (result == null || typeof result !== "object" || Array.isArray(result)) {
    throw new MarketplaceApiError("invalid_response", "安装未完成");
  }
  const body = result as Record<string, unknown>;
  const skillId = typeof body.skill_id === "string" ? body.skill_id : "";
  if (body.installed !== true || body.enabled !== true || skillId.length > 64
    || !SKILL_ID_PATTERN.test(skillId) || (expectedSkillId !== undefined && skillId !== expectedSkillId)) {
    throw new MarketplaceApiError("invalid_response", "安装未完成");
  }
  return { installed: true, skill_id: skillId, enabled: true };
}

export function readCompletedUpdate(result: unknown, expectedSkillId: string): { installed: true; updated: true; skill_id: string; enabled: boolean } {
  const body = result as Record<string, unknown> | null;
  if (!body || body.updated !== true || body.installed !== true || typeof body.enabled !== "boolean"
    || body.skill_id !== expectedSkillId || !SKILL_ID_PATTERN.test(expectedSkillId)) {
    throw new MarketplaceApiError("invalid_response", "更新未完成");
  }
  return { installed: true, updated: true, skill_id: expectedSkillId, enabled: body.enabled };
}

export async function prepareMarketplaceInstall(
  fetchSkill: (slug: string) => Promise<MarketplaceSkill>,
  method: "skill.install" | "skill.installPinned" | "skill.updatePinned",
  payload: Record<string, unknown>,
): Promise<{
  confirmPayload: { slug: string; display_name: string; version: string };
  invokePayload: { slug: string; expected_version_id: string; expected_sha256: string };
}> {
  const skill = await fetchSkill(String(payload.slug ?? ""));
  const trusted = readTrustedInstallPin(skill);
  if (method !== "skill.install") {
    const expectedVersionId = String(payload.expected_version_id ?? "");
    const expectedSha256 = String(payload.expected_sha256 ?? "");
    if (
      expectedVersionId !== trusted.expected_version_id
      || expectedSha256 !== trusted.expected_sha256
    ) {
      throw new MarketplaceApiError(
        "version_changed",
        "资源版本已变化，请刷新详情后重新确认安装",
      );
    }
  }
  if (method === "skill.updatePinned" && (skill.installation?.status !== "installed" || skill.installation.update_available !== true)) {
    throw new MarketplaceApiError("update_unavailable", "暂无可更新版本，请刷新详情");
  }
  return {
    confirmPayload: {
      slug: trusted.slug,
      display_name: trusted.displayName,
      version: trusted.version,
    },
    invokePayload: {
      slug: trusted.slug,
      expected_version_id: trusted.expected_version_id,
      expected_sha256: trusted.expected_sha256,
    },
  };
}
