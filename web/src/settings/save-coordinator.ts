import { parseApiError } from "./parse-api-error";
import type { CategorySaveResult, SettingsCategoryStore } from "./types";

export function messageFromUnknown(error: unknown, fallback = "保存失败"): string {
  if (error instanceof Error && error.message.trim()) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return fallback;
}

export function nextDraftAfterSave<T>(args: {
  savedDraft: T;
  currentDraft: T;
  equal: (left: T, right: T) => boolean;
}): { baseline: T; dirty: boolean } {
  return {
    baseline: args.savedDraft,
    dirty: !args.equal(args.savedDraft, args.currentDraft),
  };
}

export function summarizeCategorySaves(results: CategorySaveResult[]): {
  saved: CategorySaveResult[];
  failed: CategorySaveResult[];
  allSucceeded: boolean;
  anySucceeded: boolean;
  anyFailed: boolean;
} {
  const saved = results.filter((result) => result.ok);
  const failed = results.filter((result) => !result.ok);
  return {
    saved,
    failed,
    allSucceeded: results.length > 0 && failed.length === 0,
    anySucceeded: saved.length > 0,
    anyFailed: failed.length > 0,
  };
}

export function saveOutcomeCopy(results: CategorySaveResult[]): {
  tone: "success" | "warning" | "danger";
  text: string;
} | null {
  if (results.length === 0) return null;
  const summary = summarizeCategorySaves(results);
  if (summary.allSucceeded) {
    return {
      tone: "success",
      text: results.length === 1 ? `已保存 ${results[0].title}` : `已保存 ${results.length} 个分类`,
    };
  }
  const failedTitles = summary.failed.map((item) => item.title).join("、");
  if (summary.anySucceeded) {
    return {
      tone: "warning",
      text: `${failedTitles} 保存失败，其余已保存`,
    };
  }
  return {
    tone: "danger",
    text: `${failedTitles} 保存失败`,
  };
}

export async function saveDirtyCategories(
  stores: SettingsCategoryStore[],
): Promise<CategorySaveResult[]> {
  const results: CategorySaveResult[] = [];
  for (const store of stores) {
    if (!store.dirty) continue;
    try {
      await store.save();
      results.push({ id: store.id, title: store.title, ok: true });
    } catch (error) {
      results.push({
        id: store.id,
        title: store.title,
        ok: false,
        error: parseApiError(error, messageFromUnknown(error)),
      });
    }
  }
  return results;
}

export function dirtyStores(stores: SettingsCategoryStore[]): SettingsCategoryStore[] {
  return stores.filter((store) => store.dirty);
}
