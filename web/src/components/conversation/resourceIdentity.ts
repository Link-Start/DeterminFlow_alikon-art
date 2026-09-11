import { createElement } from "react";
import { RESOURCE_IDENTITY_STYLES } from "../../lib/brand-colors";
import type { MentionResourceType } from "../../types";

type ResourceIdentityType = MentionResourceType | "file";

// Shared vector shapes keep React history and native contentEditable tokens consistent.
const ICON_PATHS: Record<ResourceIdentityType, string[]> = {
  file: ["m21 11-8 8a6 6 0 0 1-8.5-8.5l8-8a4 4 0 0 1 5.7 5.7l-8 8a2 2 0 0 1-2.8-2.8l7.5-7.5"],
  prompt: ["M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z", "M14 2v6h6M8 13h8M8 17h6"],
  agent: ["M12 8V4H9M4 8h16v12H4ZM1 12v4m22-4v4M8 12v2m8-2v2M9 17h6"],
  skill: ["M12 5C8 2 5 3 2 3v16c4-1 7-1 10 2 3-3 6-3 10-2V3c-3 0-6-1-10 2Zm0 0v16"],
  rule: ["M12 2 3 6v6c0 5 9 10 9 10s9-5 9-10V6ZM8 12l3 3 5-6"],
  workflow: ["M3 3h6v6H3Zm12 12h6v6h-6ZM6 9v9h9M9 6h9v9"],
  session: ["M21 15a4 4 0 0 1-4 4H7l-5 3V6a4 4 0 0 1 4-4h11a4 4 0 0 1 4 4ZM7 8h10M7 12h7"],
};

export function resourceChipClass(type: ResourceIdentityType): string {
  return `mx-1 inline-flex max-w-[min(18rem,75vw)] items-center gap-1 rounded-full border px-2 py-0.5 align-baseline text-xs leading-5 text-foreground ${RESOURCE_IDENTITY_STYLES[type].chip}`;
}

export function ResourceIdentityIcon({ type }: { type: ResourceIdentityType }) {
  return createElement("svg", {
    width: 13, height: 13, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round",
    className: `shrink-0 ${RESOURCE_IDENTITY_STYLES[type].icon}`,
    "aria-hidden": true, "data-resource-icon": type,
  }, ICON_PATHS[type].map((d, key) => createElement("path", { d, key })));
}

export function createResourceIdentityIcon(type: ResourceIdentityType): SVGSVGElement {
  const namespace = "http://www.w3.org/2000/svg";
  const icon = document.createElementNS(namespace, "svg");
  const attributes = {
    width: "13", height: "13", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    "stroke-width": "1.8", "stroke-linecap": "round", "stroke-linejoin": "round",
    class: `shrink-0 ${RESOURCE_IDENTITY_STYLES[type].icon}`,
    "aria-hidden": "true", "data-resource-icon": type,
  };
  for (const [key, value] of Object.entries(attributes)) icon.setAttribute(key, value);
  for (const d of ICON_PATHS[type]) {
    const path = document.createElementNS(namespace, "path");
    path.setAttribute("d", d);
    icon.append(path);
  }
  return icon;
}
