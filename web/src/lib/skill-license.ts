const COMMUNITY_LICENSE = "LicenseRef-DF-Community-1.0";

const LICENSE_HREFS: Record<string, string> = {
  [COMMUNITY_LICENSE]: `https://determinflow.com/marketplace/terms?license=${COMMUNITY_LICENSE}`,
  MIT: "https://opensource.org/license/mit",
  "Apache-2.0": "https://www.apache.org/licenses/LICENSE-2.0",
  "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
  "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
};

export interface SkillLicenseSource {
  license?: string;
  provenance?: {
    source?: { kind?: string };
    package?: { license?: string };
  } | null;
}

export interface SkillUsageAuthorization {
  id: string;
  label: string;
  href: string | null;
}

function normalizedLicense(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export function skillContentLicense(skill: SkillLicenseSource): string | null {
  const declared = normalizedLicense(skill.license);
  return declared || null;
}

export function skillUsageAuthorization(skill: SkillLicenseSource): SkillUsageAuthorization | null {
  if (skill.provenance?.source?.kind !== "marketplace") {
    return null;
  }
  const id = normalizedLicense(skill.provenance.package?.license);
  if (!id) {
    return null;
  }
  return {
    id,
    label: id === COMMUNITY_LICENSE ? "社区使用授权 1.0" : id,
    href: LICENSE_HREFS[id] ?? null,
  };
}
