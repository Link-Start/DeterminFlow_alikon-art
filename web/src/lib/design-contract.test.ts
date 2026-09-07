import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, extname, join, relative } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const SOURCE_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const PROJECT_ROOT = join(SOURCE_ROOT, "..", "..");
const LITERAL_COLOR_EXCEPTION = "lib/brand-colors.ts";
const RAW_PALETTE = /(bg|text|border|ring|outline|shadow|from|via|to|fill|stroke|placeholder|divide|caret|decoration|accent)-(slate|gray|zinc|neutral|stone|indigo|blue|sky|cyan|teal|emerald|green|lime|yellow|amber|orange|red|rose|pink|fuchsia|purple|violet)-\d{2,3}(?:\/\d{1,3})?/g;
const RAW_COLOR_LITERAL = /(?:#[0-9a-f]{3,8}\b|rgba?\s*\(|hsla?\s*\()(?!var\()/gi;

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    if (![".ts", ".tsx"].includes(extname(entry.name))) return [];
    if (entry.name.endsWith(".test.ts") || entry.name.endsWith(".test.tsx")) return [];
    return [path];
  });
}

test("product UI only uses semantic brand colors", () => {
  const violations: string[] = [];

  for (const file of sourceFiles(SOURCE_ROOT)) {
    const source = readFileSync(file, "utf8");
    const path = relative(SOURCE_ROOT, file);
    const paletteMatches = [...source.matchAll(RAW_PALETTE)].map((match) => match[0]);
    if (paletteMatches.length > 0) {
      violations.push(`${path}: raw palette utilities ${[...new Set(paletteMatches)].join(", ")}`);
    }

    if (path !== LITERAL_COLOR_EXCEPTION) {
      const literalMatches = [...source.matchAll(RAW_COLOR_LITERAL)].map((match) => match[0]);
      if (literalMatches.length > 0) {
        violations.push(`${path}: raw color literals ${[...new Set(literalMatches)].join(", ")}`);
      }
    }
  }

  assert.deepEqual(violations, [], `Design contract violations:\n${violations.join("\n")}`);
});

test("dark theme keeps the approved blue-slate surface hierarchy", () => {
  const css = readFileSync(join(SOURCE_ROOT, "index.css"), "utf8");
  const design = readFileSync(join(PROJECT_ROOT, "DESIGN.md"), "utf8");

  for (const token of [
    "--background: 221.74 48.94% 9.22%;",
    "--card: 217.24 47.54% 11.96%;",
    "--secondary: 216.32 44.19% 16.86%;",
    "--border: 213.06 33.79% 28.43%;",
    "--input: 213.46 27.37% 37.25%;",
  ]) {
    assert.ok(css.includes(token), `Missing approved dark theme token: ${token}`);
  }

  assert.ok(!css.includes("--background: 220 48.84% 8.43%;"), "Obsolete near-black canvas token is still present");
  assert.ok(!css.includes("--background: 217.24 46.03% 12.35%;"), "Over-light dark canvas token is still present");
  assert.ok(!css.includes("--background: 216.92 46.43% 10.98%;"), "Flat dark canvas token is still present");
  assert.ok(!css.includes("--background: 216 49.02% 10%;"), "Unaligned dark canvas token is still present");
  assert.ok(!css.includes("--background: 225.71 48.84% 8.43%;"), "Over-dark canvas token is still present");
  assert.ok(!css.includes("--card: 216.36 47.83% 13.53%;"), "Over-light surface token is still present");
  assert.ok(!css.includes("--secondary: 215.12 44.09% 18.24%;"), "Over-light raised surface token is still present");

  for (const color of ["#0C1323", "#101B2D", "#18273E", "#253A55", "#304661", "#455C79"]) {
    assert.ok(design.includes(color), `DESIGN.md is missing approved surface color: ${color}`);
  }
});

test("chat content uses the global canvas instead of a page-local surface", () => {
  const chat = readFileSync(join(SOURCE_ROOT, "pages", "ChatPage.tsx"), "utf8");

  assert.ok(
    chat.includes('flex min-h-0 min-w-0 flex-1 flex-col bg-background" role="main" aria-label="聊天区域"'),
    "Chat content must inherit the global canvas hierarchy",
  );
});

test("prompt section preview keeps adjacent identities distinct", () => {
  const preview = readFileSync(join(SOURCE_ROOT, "components", "orchestration", "PreviewPanel.tsx"), "utf8");

  for (const tone of ["node-agent", "node-tool", "node-script", "node-api", "node-approval"]) {
    assert.ok(preview.includes(`bg-${tone}/[0.08]`), `Prompt section palette is missing ${tone}`);
  }

  assert.ok(preview.includes("enabledSections.map((sec, index)"), "Prompt section colors must follow display order");
  assert.ok(preview.includes("getSectionTone(index)"), "Adjacent prompt sections must rotate through the palette");
  assert.match(preview, /tone\.marker.*aria-hidden="true"/, "Prompt section identity marker must remain decorative");
});

test("orchestration light theme promotes structural borders", () => {
  const css = readFileSync(join(SOURCE_ROOT, "index.css"), "utf8");
  const page = readFileSync(join(SOURCE_ROOT, "pages", "OrchestrationPage.tsx"), "utf8");

  assert.ok(page.includes("orchestration-workbench"), "Orchestration page must scope its workbench border treatment");
  assert.match(
    css,
    /\[data-theme="light"\] \.orchestration-workbench\s*{\s*--border: var\(--theme-surface-strong\);\s*}/,
    "Light orchestration borders must use the strong semantic surface token",
  );
});

test("global notifications stay opaque and below the application header", () => {
  const provider = readFileSync(join(SOURCE_ROOT, "components", "ui", "toast-provider.tsx"), "utf8");

  assert.ok(provider.includes('className="fixed top-16 right-4'), "Toast stack must start below the header");
  assert.ok(provider.includes('"bg-card border-success text-success"'), "Success toast must use an opaque surface");
  assert.ok(provider.includes('"bg-card border-destructive text-destructive"'), "Error toast must use an opaque surface");
  assert.ok(provider.includes('"bg-card border-warning text-warning"'), "Warning toast must use an opaque surface");
  assert.equal(provider.includes("bg-success/10"), false, "Success toast must not reveal page content");
  assert.equal(provider.includes("bg-destructive/10"), false, "Error toast must not reveal page content");
  assert.equal(provider.includes("bg-warning/10"), false, "Warning toast must not reveal page content");
});
