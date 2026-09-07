export interface SchemaActionView {
  value: string;
  description: string;
}

export interface SchemaFieldView {
  name: string;
  path: string;
  typeLabel: string;
  required: boolean;
  description: string;
  allowedValues: string[];
  constraints: string[];
  children: SchemaFieldView[];
}

export interface ToolSchemaView {
  name: string;
  description: string;
  actionDescription: string;
  actions: SchemaActionView[];
  fields: SchemaFieldView[];
  parameterCount: number;
  requiredCount: number;
  rawParameters: unknown;
}

export interface ToolDefinitionSource {
  name: string;
  description?: string;
  parameters?: Record<string, {
    type?: string;
    description?: string;
    required?: boolean;
  }>;
  schema?: unknown;
}

const ACTION_PROPERTY = "action";
const MAX_DEPTH = 12;

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function formatLiteral(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value === null) return "null";
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values)];
}

function pointerSegments(ref: string): string[] | null {
  if (ref === "#") return [];
  if (!ref.startsWith("#/")) return null;
  return ref
    .slice(2)
    .split("/")
    .map((segment) => segment.replace(/~1/g, "/").replace(/~0/g, "~"));
}

function lookupPointer(root: unknown, ref: string): unknown {
  const segments = pointerSegments(ref);
  if (!segments) return undefined;
  let current: unknown = root;
  for (const segment of segments) {
    if (Array.isArray(current) && /^\d+$/.test(segment)) {
      current = current[Number(segment)];
      continue;
    }
    if (!isObject(current) || !(segment in current)) return undefined;
    current = current[segment];
  }
  return current;
}

function overlaySchema(base: unknown, overlay: JsonObject): JsonObject {
  const next = isObject(base) ? { ...base } : {};
  for (const [key, value] of Object.entries(overlay)) {
    if (key === "$ref") continue;
    if (value !== undefined) next[key] = value;
  }
  return next;
}

function mergeAllOf(nodes: unknown[], root: unknown, stack: string[]): JsonObject {
  const merged: JsonObject = {};
  const required: string[] = [];
  const properties: JsonObject = {};
  for (const node of nodes) {
    const resolved = resolveSchema(node, root, stack);
    if (!isObject(resolved)) continue;
    Object.assign(merged, resolved);
    if (isObject(resolved.properties)) Object.assign(properties, resolved.properties);
    if (Array.isArray(resolved.required)) {
      for (const name of resolved.required) {
        if (typeof name === "string") required.push(name);
      }
    }
  }
  if (Object.keys(properties).length > 0) merged.properties = properties;
  if (required.length > 0) merged.required = uniqueStrings(required);
  return merged;
}

function resolveSchema(schema: unknown, root: unknown, stack: string[]): unknown {
  if (!isObject(schema)) return schema;
  if (Array.isArray(schema.allOf) && schema.allOf.length > 0) {
    const { allOf, ...rest } = schema;
    return overlaySchema(mergeAllOf(allOf, root, stack), rest);
  }
  const ref = asString(schema.$ref);
  if (!ref) return schema;
  if (stack.includes(ref)) {
    return overlaySchema({ type: "object", description: asString(schema.description) }, schema);
  }
  const target = lookupPointer(root, ref);
  if (target === undefined) return overlaySchema({ type: "unknown" }, schema);
  return overlaySchema(resolveSchema(target, root, [...stack, ref]), schema);
}

function collectTypes(schema: unknown, root: unknown, stack: string[]): string[] {
  const resolved = resolveSchema(schema, root, stack);
  if (resolved === true) return ["any"];
  if (resolved === false) return ["never"];
  if (!isObject(resolved)) return ["unknown"];

  if (Array.isArray(resolved.type)) {
    return resolved.type.filter((item): item is string => typeof item === "string");
  }
  if (typeof resolved.type === "string") return [resolved.type];
  if ("const" in resolved) {
    if (resolved.const === null) return ["null"];
    if (typeof resolved.const === "object") return ["object"];
    return [typeof resolved.const];
  }

  const unions = [resolved.anyOf, resolved.oneOf]
    .filter((value): value is unknown[] => Array.isArray(value));
  if (unions.length > 0) {
    return uniqueStrings(unions.flatMap((nodes) => nodes.flatMap((node) => collectTypes(node, root, stack))));
  }
  if (isObject(resolved.properties) || resolved.additionalProperties !== undefined) return ["object"];
  if (resolved.items !== undefined || resolved.prefixItems !== undefined) return ["array"];
  if (Array.isArray(resolved.enum) && resolved.enum.length > 0) {
    return uniqueStrings(resolved.enum.map((item) => (item === null ? "null" : typeof item)));
  }
  if (asString(resolved.$ref)) return [asString(resolved.$ref).split("/").pop() || "ref"];
  return ["unknown"];
}

function typeLabelFrom(schema: unknown, root: unknown, stack: string[]): string {
  const resolved = resolveSchema(schema, root, stack);
  const unique = uniqueStrings(collectTypes(resolved, root, stack));
  const withoutNull = unique.filter((type) => type !== "null");
  const nullable = unique.includes("null") && withoutNull.length > 0;
  let label = (nullable ? withoutNull : unique).join(" | ") || "unknown";

  if (withoutNull.length === 1 && withoutNull[0] === "array") {
    const items = isObject(resolved) ? resolved.items ?? resolved.prefixItems : undefined;
    if (Array.isArray(items) && items.length > 0) {
      label = `tuple<${items.map((item) => typeLabelFrom(item, root, stack)).join(", ")}>`;
    } else if (items !== undefined) {
      label = `array<${typeLabelFrom(items, root, stack)}>`;
    } else {
      label = "array";
    }
  }

  return nullable ? `${label} | null` : label;
}

function isNullSchema(schema: unknown, root: unknown, stack: string[]): boolean {
  const types = collectTypes(schema, root, stack);
  return types.length === 1 && types[0] === "null";
}

function collectEnumValues(schema: unknown, root: unknown, stack: string[]): unknown[] {
  const resolved = resolveSchema(schema, root, stack);
  if (!isObject(resolved)) return [];
  if (Array.isArray(resolved.enum)) return resolved.enum;
  if ("const" in resolved) return [resolved.const];
  const nodes = Array.isArray(resolved.oneOf)
    ? resolved.oneOf
    : Array.isArray(resolved.anyOf)
      ? resolved.anyOf
      : [];
  if (nodes.length === 0) return [];
  const valueNodes = nodes.filter((node) => !isNullSchema(node, root, stack));
  if (valueNodes.length === 0) return [];
  const branches = valueNodes.map((node) => collectEnumValues(node, root, stack));
  if (branches.some((branch) => branch.length === 0)) return [];
  return branches.flat();
}

function descriptionForValue(schema: unknown, value: unknown, root: unknown, stack: string[]): string {
  const resolved = resolveSchema(schema, root, stack);
  if (!isObject(resolved)) return "";
  const unions = [resolved.anyOf, resolved.oneOf]
    .filter((value): value is unknown[] => Array.isArray(value));
  for (const nodes of unions) {
    for (const node of nodes) {
      const item = resolveSchema(node, root, stack);
      if (!isObject(item)) continue;
      if ("const" in item && Object.is(item.const, value)) return asString(item.description);
      if (Array.isArray(item.enum) && item.enum.includes(value)) return asString(item.description);
    }
  }
  return "";
}

function constraintTexts(schema: unknown, root: unknown, stack: string[]): string[] {
  const resolved = resolveSchema(schema, root, stack);
  if (!isObject(resolved)) return [];
  const parts: string[] = [];
  if ("default" in resolved) parts.push(`默认 ${formatLiteral(resolved.default)}`);
  if (typeof resolved.minimum === "number") parts.push(`≥ ${resolved.minimum}`);
  if (typeof resolved.exclusiveMinimum === "number") parts.push(`> ${resolved.exclusiveMinimum}`);
  if (typeof resolved.maximum === "number") parts.push(`≤ ${resolved.maximum}`);
  if (typeof resolved.exclusiveMaximum === "number") parts.push(`< ${resolved.exclusiveMaximum}`);
  if (typeof resolved.minLength === "number") parts.push(`长度 ≥ ${resolved.minLength}`);
  if (typeof resolved.maxLength === "number") parts.push(`长度 ≤ ${resolved.maxLength}`);
  if (typeof resolved.minItems === "number") parts.push(`至少 ${resolved.minItems} 项`);
  if (typeof resolved.maxItems === "number") parts.push(`至多 ${resolved.maxItems} 项`);
  if (typeof resolved.minProperties === "number") parts.push(`至少 ${resolved.minProperties} 个字段`);
  if (typeof resolved.maxProperties === "number") parts.push(`至多 ${resolved.maxProperties} 个字段`);
  if (typeof resolved.multipleOf === "number") parts.push(`倍数 ${resolved.multipleOf}`);
  if (resolved.uniqueItems === true) parts.push("元素唯一");
  if (resolved.additionalProperties === true) parts.push("可含其他字段");
  if (typeof resolved.pattern === "string" && resolved.pattern) parts.push(`匹配 ${resolved.pattern}`);
  if (typeof resolved.format === "string" && resolved.format) parts.push(`格式 ${resolved.format}`);
  return parts;
}

function requiredNames(schema: unknown): Set<string> {
  if (!isObject(schema) || !Array.isArray(schema.required)) return new Set();
  return new Set(schema.required.filter((name): name is string => typeof name === "string" && name.length > 0));
}

function objectProperties(schema: unknown, root: unknown, stack: string[]): JsonObject {
  const resolved = resolveSchema(schema, root, stack);
  if (!isObject(resolved)) return {};
  if (isObject(resolved.properties)) return resolved.properties;
  const unions = [resolved.anyOf, resolved.oneOf]
    .filter((value): value is unknown[] => Array.isArray(value));
  if (unions.length === 1) {
    const objectNodes = unions[0]
      .map((node) => resolveSchema(node, root, stack))
      .filter((node): node is JsonObject => isObject(node) && isObject(node.properties));
    if (objectNodes.length === unions[0].length) {
      const merged: JsonObject = {};
      for (const node of objectNodes) {
        Object.assign(merged, node.properties);
      }
      return merged;
    }
  }
  return {};
}

function readField(
  name: string,
  schema: unknown,
  required: boolean,
  root: unknown,
  path: string,
  depth: number,
  stack: string[],
): SchemaFieldView {
  const fieldPath = path ? `${path}.${name}` : name;
  const ref = isObject(schema) ? asString(schema.$ref) : "";
  if (ref && stack.includes(ref)) {
    return {
      name,
      path: fieldPath,
      typeLabel: ref.split("/").pop() || "object",
      required,
      description: isObject(schema) ? asString(schema.description) : "",
      allowedValues: [],
      constraints: [],
      children: [],
    };
  }
  const nextStack = ref ? [...stack, ref] : stack;
  const resolved = resolveSchema(schema, root, stack);
  const children: SchemaFieldView[] = [];
  if (depth < MAX_DEPTH) {
    const properties = objectProperties(resolved, root, nextStack);
    const requiredSet = requiredNames(resolved);
    for (const [childName, childSchema] of Object.entries(properties)) {
      children.push(readField(
        childName,
        childSchema,
        requiredSet.has(childName),
        root,
        fieldPath,
        depth + 1,
        nextStack,
      ));
    }
    if (isObject(resolved)) {
      const itemNodes = Array.isArray(resolved.prefixItems)
        ? resolved.prefixItems
        : Array.isArray(resolved.items)
          ? resolved.items
          : resolved.items !== undefined
            ? [resolved.items]
            : [];
      if (!isObject(resolved.properties) && itemNodes.length > 0 && collectTypes(resolved, root, stack).includes("array")) {
        itemNodes.forEach((item, index) => {
          const itemName = itemNodes.length === 1 ? "元素" : String(index);
          const itemResolved = resolveSchema(item, root, stack);
          if (isObject(itemResolved) && (isObject(itemResolved.properties) || itemResolved.items !== undefined)) {
            children.push(readField(itemName, item, false, root, fieldPath, depth + 1, nextStack));
          }
        });
      }
      if (isObject(resolved.additionalProperties)) {
        children.push(readField("*", resolved.additionalProperties, false, root, fieldPath, depth + 1, nextStack));
      }
    }
  }

  return {
    name,
    path: fieldPath,
    typeLabel: typeLabelFrom(resolved, root, stack),
    required,
    description: isObject(resolved) ? asString(resolved.description) : "",
    allowedValues: uniqueStrings(collectEnumValues(resolved, root, stack).map(formatLiteral)),
    constraints: constraintTexts(resolved, root, stack),
    children,
  };
}

function synthesizeParameters(parameters: NonNullable<ToolDefinitionSource["parameters"]>): JsonObject {
  const properties: JsonObject = {};
  const required: string[] = [];
  for (const [name, info] of Object.entries(parameters)) {
    properties[name] = {
      type: info.type || "string",
      description: info.description || "",
    };
    if (info.required) required.push(name);
  }
  return {
    type: "object",
    properties,
    required,
  };
}

function readParametersSchema(tool: ToolDefinitionSource): unknown {
  if (isObject(tool.schema)) {
    if (isObject(tool.schema.function) && tool.schema.function.parameters !== undefined) {
      return tool.schema.function.parameters;
    }
    if (tool.schema.parameters !== undefined) return tool.schema.parameters;
    if (tool.schema.type === "object" || isObject(tool.schema.properties)) return tool.schema;
  }
  if (tool.parameters && Object.keys(tool.parameters).length > 0) {
    return synthesizeParameters(tool.parameters);
  }
  return undefined;
}

function unionObjectVariants(schema: unknown, root: unknown, stack: string[]): JsonObject[] {
  const resolved = resolveSchema(schema, root, stack);
  if (!isObject(resolved)) return [];
  const nodes = Array.isArray(resolved.oneOf)
    ? resolved.oneOf
    : Array.isArray(resolved.anyOf)
      ? resolved.anyOf
      : [];
  if (nodes.length === 0) return [];
  const objects = nodes
    .map((node) => resolveSchema(node, root, stack))
    .filter((node): node is JsonObject => isObject(node) && isObject(node.properties));
  return objects.length === nodes.length ? objects : [];
}

function variantLabel(schema: JsonObject, root: unknown, stack: string[], index: number): string {
  const action = schema.properties && isObject(schema.properties)
    ? schema.properties[ACTION_PROPERTY]
    : undefined;
  const values = collectEnumValues(action, root, stack);
  if (values.length === 1) return formatLiteral(values[0]);
  const title = asString(schema.title);
  if (title) return title;
  return `分支 ${index + 1}`;
}

export function readToolSchemaView(tool: ToolDefinitionSource): ToolSchemaView {
  const rawParameters = readParametersSchema(tool);
  const root = rawParameters;
  const resolved = resolveSchema(rawParameters, root, []);
  const variants = unionObjectVariants(resolved, root, []);
  const actionSource = isObject(resolved) && isObject(resolved.properties)
    ? resolved.properties[ACTION_PROPERTY]
    : undefined;
  const actionValues = collectEnumValues(actionSource, root, []);
  const resolvedAction = resolveSchema(actionSource, root, []);
  const actionDescription = isObject(resolvedAction)
    ? asString(resolvedAction.description)
    : "";
  const actions: SchemaActionView[] = actionValues.map((value) => ({
    value: formatLiteral(value),
    description: descriptionForValue(actionSource, value, root, []),
  }));

  let fields: SchemaFieldView[] = [];
  if (variants.length > 0 && !(isObject(resolved) && isObject(resolved.properties))) {
    fields = variants.map((variant, index) => {
      const label = variantLabel(variant, root, [], index);
      const path = `${index}:${label}`;
      return {
        name: label,
        path,
        typeLabel: "object",
        required: false,
        description: asString(variant.description),
        allowedValues: [],
        constraints: [],
        children: Object.entries(isObject(variant.properties) ? variant.properties : {}).map(([name, child]) => (
          readField(name, child, requiredNames(variant).has(name), root, path, 1, [])
        )),
      };
    });
  } else {
    const properties = objectProperties(resolved, root, []);
    const required = requiredNames(resolved);
    fields = Object.entries(properties)
      .filter(([name]) => !(actions.length > 0 && name === ACTION_PROPERTY))
      .map(([name, child]) => readField(name, child, required.has(name), root, "", 0, []));
  }

  const topLevelNames = isObject(resolved) && isObject(resolved.properties)
    ? Object.keys(resolved.properties)
    : fields.map((field) => field.name);
  const required = requiredNames(resolved);

  return {
    name: tool.name,
    description: asString(tool.description) || (
      isObject(tool.schema)
      && isObject(tool.schema.function)
        ? asString(tool.schema.function.description)
        : ""
    ),
    actionDescription,
    actions,
    fields,
    parameterCount: topLevelNames.length || fields.length,
    requiredCount: required.size,
    rawParameters,
  };
}

export function summarizeToolContract(view: ToolSchemaView): string {
  const parts: string[] = [];
  if (view.actions.length > 0) parts.push(`${view.actions.length} 个操作`);
  if (view.fields.length > 0) parts.push(`${view.fields.length} 个参数`);
  else if (view.parameterCount > 0 && view.actions.length > 0) {
    const remaining = view.parameterCount - 1;
    if (remaining > 0) parts.push(`${remaining} 个参数`);
  }
  if (parts.length === 0) return "无参数";
  return parts.join(" · ");
}
