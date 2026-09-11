import { createContext } from "react";

// A deep link opens one card without hiding or unmounting the other categories.
export const SettingsSectionTargetContext = createContext<string | null>(null);
