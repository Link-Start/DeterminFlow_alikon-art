import type { MarketplaceBridgeMethod } from "./marketplace-bridge-protocol";

// Reads may time out safely. Writes must retain their actual result once invoked.
const READ_METHODS = new Set<MarketplaceBridgeMethod>([
  "status", "skills.list", "skills.page", "skills.get", "skills.preview",
  "reviews.list", "reviews.page", "localSkills.list", "localSkills.preview",
  "localSkills.previewPrepared", "submissions.list", "author.resources.page",
  "author.versions.page", "feedback.page", "publishDraft.get",
  "notification.show", "skill.openInstalled",
]);

export function isMarketplaceWrite(method: MarketplaceBridgeMethod): boolean {
  return !READ_METHODS.has(method);
}

export interface MarketplaceConfirmationContext {
  requestId: string;
  signal: AbortSignal;
}

export function waitForConfirmation(result: Promise<boolean>, signal: AbortSignal): Promise<boolean> {
  if (signal.aborted) return Promise.resolve(false);
  return new Promise((resolve, reject) => {
    const cancel = () => resolve(false);
    signal.addEventListener("abort", cancel, { once: true });
    result.then(resolve, reject).finally(() => signal.removeEventListener("abort", cancel));
  });
}
