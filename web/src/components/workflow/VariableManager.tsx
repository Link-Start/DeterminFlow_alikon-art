/**
 * VariableManager - 工作流变量管理面板
 *
 * 编辑器侧边栏组件，支持：
 * - 增删改查 text/textarea/select 类型变量
 * - select 类型支持动态增删选项行
 * - 深色科技风格，与 NodeConfigPanel 一致
 */
import { useState, useEffect, useRef } from "react";
import { X, Plus, Trash2, Variable, GripVertical, Link } from "lucide-react";
import type { WorkflowVariable } from "../../types";

interface VariableManagerProps {
  variables: WorkflowVariable[];
  onClose: () => void;
  onUpdate?: (variables: WorkflowVariable[]) => void;
  /** 变量→节点引用映射（可选，用于显示引用计数） */
  varRefs?: Record<string, string[]>;
  /** 输出变量改名回调：oldKey、newKey、source_node_id */
  onOutputVarRename?: (oldKey: string, newKey: string, nodeId: string) => void;
  /** 是否只读模式 */
  isReadOnly?: boolean;
}

interface EditingVariable extends WorkflowVariable {
  isNew?: boolean;
}

const EMPTY_VARIABLE: WorkflowVariable = {
  key: "",
  name: "",
  type: "text",
  default: "",
  required: false,
  description: "",
  options: [],
  hidden: false,
};

function validateKey(key: string): string | null {
  if (!key.trim()) return "变量标识不能为空";
  if (!/^[a-zA-Z_]\w*$/.test(key)) return "标识只能包含字母、数字、下划线，且以字母或下划线开头";
  return null;
}

function getSourceNodeLabel(variable: WorkflowVariable): string {
  const label = "_sourceNodeLabel" in variable ? variable._sourceNodeLabel : undefined;
  return typeof label === "string" ? label : variable.source_node_id || "";
}

export default function VariableManager({
  variables,
  onClose,
  onUpdate,
  varRefs,
  onOutputVarRename,
  isReadOnly = false,
}: VariableManagerProps) {
  const [list, setList] = useState<WorkflowVariable[]>(variables);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<EditingVariable>({ ...EMPTY_VARIABLE });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [width, setWidth] = useState(340);
  const [isResizing, setIsResizing] = useState(false);

  const handleResizeMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
  };

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing) return;
      setWidth(Math.max(280, Math.min(700, e.clientX)));
    };
    const handleMouseUp = () => setIsResizing(false);
    if (isResizing) {
      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    }
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [isResizing]);

  const handleAdd = () => {
    if (isReadOnly) return;
    const newVar: EditingVariable = {
      ...EMPTY_VARIABLE,
      key: "",
      isNew: true,
    };
    setEditingId("__new__");
    setEditForm(newVar);
    setErrors({});
  };

  const handleEdit = (v: WorkflowVariable) => {
    if (isReadOnly) return;
    setEditingId(v.key);
    setEditForm({ ...v });
    setErrors({});
  };

  const handleCancel = () => {
    setEditingId(null);
    setErrors({});
  };

  const [deleteConfirm, setDeleteConfirm] = useState<{ key: string; refMsg: string } | null>(null);
  const deleteConfirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (deleteConfirm && deleteConfirmRef.current) {
      deleteConfirmRef.current.focus();
    }
  }, [deleteConfirm]);

  const handleDelete = (key: string) => {
    if (isReadOnly || !onUpdate) return;
    const refNodes = varRefs?.[key] || [];
    const refMsg = refNodes.length > 0
      ? `当前被 ${refNodes.length} 个节点引用：${refNodes.join("、")}`
      : "当前未被任何节点引用";
    setDeleteConfirm({ key, refMsg });
  };

  const confirmDelete = () => {
    if (!deleteConfirm || !onUpdate) return;
    const updated = list.filter((v) => v.key !== deleteConfirm.key);
    setList(updated);
    onUpdate(updated);
    setDeleteConfirm(null);
  };

  const handleSaveEdit = () => {
    if (isReadOnly || !onUpdate) return;
    const errs: Record<string, string> = {};
    const keyErr = validateKey(editForm.key);
    if (keyErr) errs.key = keyErr;

    // 检查 key 唯一性（排除自身）
    const isDuplicate = editForm.isNew
      ? list.some((v) => v.key === editForm.key)
      : list.some((v) => v.key === editForm.key && v.key !== editingId);
    if (isDuplicate) errs.key = "标识已存在";

    if (!editForm.name.trim()) errs.name = "展示名不能为空";
    if (editForm.type === "select" && editForm.options.length === 0) {
      errs.options = "选择器类型至少需要一个选项";
    }

    if (Object.keys(errs).length > 0) {
      setErrors(errs);
      return;
    }

    // 保留原有来源信息（source_type / source_node_id）不被编辑覆盖
    const originalVar = editForm.isNew ? null : list.find((v) => v.key === editingId);
    const savedVar: WorkflowVariable = {
      key: editForm.key,
      name: editForm.name,
      type: editForm.type,
      default: editForm.default,
      required: editForm.required,
      description: editForm.description,
      options: editForm.options,
      source_type: originalVar?.source_type || editForm.source_type || "input",
      source_node_id: originalVar?.source_node_id || editForm.source_node_id || "",
      hidden: editForm.hidden || false,
    };

    let updated: WorkflowVariable[];
    if (editForm.isNew) {
      updated = [...list, savedVar];
    } else {
      updated = list.map((v) => (v.key === editingId ? savedVar : v));
    }

    // 输出变量 key 变更：同步回源节点
    if (savedVar.source_type === "output" && savedVar.source_node_id
        && editingId && editingId !== savedVar.key && onOutputVarRename) {
      onOutputVarRename(editingId, savedVar.key, savedVar.source_node_id);
    }

    setList(updated);
    onUpdate(updated);
    setEditingId(null);
    setErrors({});
  };

  const addOption = () => {
    setEditForm((prev) => ({
      ...prev,
      options: [...prev.options, { name: "", value: "" }],
    }));
  };

  const updateOption = (idx: number, field: "name" | "value", val: string) => {
    setEditForm((prev) => {
      const opts = [...prev.options];
      opts[idx] = { ...opts[idx], [field]: val };
      return { ...prev, options: opts };
    });
  };

  const removeOption = (idx: number) => {
    setEditForm((prev) => ({
      ...prev,
      options: prev.options.filter((_, i) => i !== idx),
    }));
  };

  return (
    <>
    {/* 删除确认对话框 */}
    {deleteConfirm && (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
        onClick={() => setDeleteConfirm(null)}
        onKeyDown={(e) => { if (e.key === "Escape") setDeleteConfirm(null); }}
        role="dialog"
        aria-modal="true"
        aria-label="确认删除变量"
      >
        <div
          className="bg-secondary border border-primary/20 rounded-lg p-5 max-w-md w-full mx-4 shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        >
          <h3 className="text-sm font-semibold text-foreground mb-2">确认删除变量</h3>
          <p className="text-xs text-muted-foreground mb-1">
            确认删除变量 <span className="font-mono text-foreground">"{deleteConfirm.key}"</span> 吗？
          </p>
          <p className="text-xs text-muted-foreground mb-4">已使用此变量的节点占位符将失效。{deleteConfirm.refMsg}</p>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setDeleteConfirm(null)}
              className="px-3 py-1.5 rounded text-xs bg-muted hover:bg-muted-foreground text-foreground transition-colors cursor-pointer"
            >
              取消
            </button>
            <button
              ref={deleteConfirmRef}
              type="button"
              onClick={confirmDelete}
              className="px-3 py-1.5 rounded text-xs bg-destructive hover:bg-destructive text-white transition-colors cursor-pointer"
            >
              删除
            </button>
          </div>
        </div>
      </div>
    )}
    <div
      className="h-full bg-card border-l border-primary/20 overflow-y-auto flex flex-col shadow-2xl relative"
      style={{ width: `${width}px`, minWidth: "280px", maxWidth: "700px" }}
    >
      {/* Resize Handle */}
      <div
        onMouseDown={handleResizeMouseDown}
        role="separator"
        aria-orientation="vertical"
        aria-label="拖拽调整面板宽度"
        className={`absolute left-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-primary/50 transition-colors z-10 group ${
          isResizing ? "bg-primary/60" : ""
        }`}
      >
        <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
          <GripVertical size={16} className="text-primary" aria-hidden="true" />
        </div>
      </div>

      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-primary/10 shrink-0">
        <div>
          <div className="flex items-center gap-2">
            <Variable size={16} className="text-primary" aria-hidden="true" />
            <h3 className="text-sm font-semibold text-foreground">{isReadOnly ? "变量查看" : "变量管理"}</h3>
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            {isReadOnly ? "查看工作流中定义的所有变量" : ("定义变量后在节点属性中使用 " + "{{key}}" + " 引用")}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          {!isReadOnly && (
            <button
              type="button"
              onClick={handleAdd}
              aria-label="新增变量"
              className="p-1.5 rounded-lg hover:bg-primary/10 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            >
              <Plus size={16} aria-hidden="true" />
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭变量管理"
            className="p-1.5 rounded-lg hover:bg-primary/10 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      {/* Variable List */}
      <div className="flex-1 p-3 space-y-2 overflow-y-auto">
        {list.length === 0 && !editingId && (
          <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
            <Variable size={32} className="mb-3 opacity-30" aria-hidden="true" />
            <p className="text-sm">暂无变量</p>
            <p className="text-xs mt-1 opacity-60">点击 + 按钮创建第一个变量</p>
          </div>
        )}

        {list.map((v) => (
          <div key={v.key}>
            {editingId === v.key ? (
              <div className="p-3 rounded-lg bg-background border border-primary/30 space-y-3">
                <VariableEditForm
                  form={editForm}
                  errors={errors}
                  onChange={setEditForm}
                  onSave={handleSaveEdit}
                  onCancel={handleCancel}
                  addOption={addOption}
                  updateOption={updateOption}
                  removeOption={removeOption}
                  setErrors={setErrors}
                />
              </div>
            ) : (
              <div
                role="button"
                tabIndex={0}
                onClick={() => handleEdit(v)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); handleEdit(v); } }}
                className="flex items-center gap-3 p-3 rounded-lg bg-background border border-primary/10 hover:border-primary/30 cursor-pointer transition-all group focus-visible:ring-2 focus-visible:ring-primary/30"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-foreground truncate">{v.name}</span>
                    <span className="text-xs px-1.5 py-0.5 rounded bg-primary/10 text-primary">
                      {v.type === "select" ? "选择器" : v.type === "file" ? "文件" : v.type === "textarea" ? "文本段" : v.type === "list" ? "列表" : v.type === "dict" ? "字典" : "文本"}
                    </span>
                    {v.required && (
                      <span className="text-xs text-destructive">*</span>
                    )}
                    {v.hidden && (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-warning/10 text-warning border border-warning/20">
                        隐藏
                      </span>
                    )}
                  </div>
                  {/* 输入/输出变量来源标识 */}
                  {v.source_type === "output" && (
                    <div className="flex items-center gap-1 mt-0.5">
                      <span className="text-xs px-1.5 py-0.5 rounded bg-warning/10 text-warning border border-warning/20">
                        输出变量
                      </span>
                      {v.source_node_id && (
                        <span className="text-xs text-muted-foreground">
                          来自：{getSourceNodeLabel(v)}
                        </span>
                      )}
                    </div>
                  )}
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-xs text-muted-foreground font-mono">{`{{${v.key}}}`}</span>
                    {varRefs && (
                      <span className={`text-xs flex items-center gap-0.5 ${
                        (varRefs[v.key]?.length || 0) > 0
                          ? "text-success/70"
                          : "text-muted-foreground/50"
                      }`}>
                        <Link size={10} aria-hidden="true" />
                        {varRefs[v.key]?.length || 0} 个节点引用
                      </span>
                    )}
                  </div>
                </div>
                {/* 输出变量不可手动删除（由节点配置管理） */}
                {!isReadOnly && v.source_type !== "output" && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(v.key);
                    }}
                    aria-label={`删除变量 ${v.key}`}
                    className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100 transition-all cursor-pointer"
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                )}
              </div>
            )}
          </div>
        ))}

        {/* New variable form */}
        {editingId === "__new__" && (
          <div className="p-3 rounded-lg bg-background border border-primary/30 space-y-3">
            <VariableEditForm
              form={editForm}
              errors={errors}
              onChange={setEditForm}
              onSave={handleSaveEdit}
              onCancel={handleCancel}
              addOption={addOption}
              updateOption={updateOption}
              removeOption={removeOption}
              setErrors={setErrors}
            />
          </div>
        )}
      </div>

    </div>
    </>
  );
}

// ============ Variable Edit Form ============

interface VariableEditFormProps {
  form: EditingVariable;
  errors: Record<string, string>;
  onChange: (updater: (prev: EditingVariable) => EditingVariable) => void;
  onSave: () => void;
  onCancel: () => void;
  addOption: () => void;
  updateOption: (idx: number, field: "name" | "value", val: string) => void;
  removeOption: (idx: number) => void;
  setErrors: (errs: Record<string, string>) => void;
}

function VariableEditForm({
  form,
  errors,
  onChange,
  onSave,
  onCancel,
  addOption,
  updateOption,
  removeOption,
  setErrors,
}: VariableEditFormProps) {
  const inputClass =
    "w-full px-2.5 py-1.5 rounded bg-card border border-primary/20 text-foreground text-xs focus:outline-none focus:border-primary/50 transition-colors";

  const handleTypeChange = (type: "text" | "textarea" | "select" | "file" | "list" | "dict") => {
    onChange((prev) => ({
      ...prev,
      type,
      options: type === "select" && prev.options.length === 0 ? [] : prev.options,
    }));
    setErrors({});
  };

  return (
    <>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">
            {form.isNew ? "新增变量" : "编辑变量"}
          </span>
          {/* 输出变量来源标签 */}
          {form.source_type === "output" && (
            <span className="text-xs px-1.5 py-0.5 rounded bg-warning/10 text-warning border border-warning/20">
              输出变量
              {form.source_node_id && ` · 来自节点`}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={onSave}
            aria-label="保存变量"
            className="px-3 py-1 rounded text-xs font-medium bg-primary hover:bg-primary text-white transition-colors cursor-pointer"
          >
            保存
          </button>
          <button
            type="button"
            onClick={onCancel}
            aria-label="取消编辑"
            className="px-3 py-1 rounded text-xs bg-primary/10 hover:bg-primary/20 text-muted-foreground transition-colors cursor-pointer"
          >
            取消
          </button>
        </div>
      </div>

      {/* Type selector */}
      <div className="flex gap-1.5 flex-wrap">
        {(["text", "textarea", "select", "file", "list", "dict"] as const).map((t) => (
          <button
            key={t}
            onClick={() => handleTypeChange(t)}
            className={`py-1.5 rounded text-xs font-medium transition-colors ${
              form.type === t
                ? "bg-primary text-white px-2"
                : "bg-card text-muted-foreground hover:text-muted-foreground px-2"
            }`}
          >
            {t === "text" ? "文本" : t === "textarea" ? "文本段" : t === "select" ? "选择器" : t === "list" ? "列表" : t === "dict" ? "字典" : "文件"}
          </button>
        ))}
      </div>

      {/* Key */}
      <div>
        <label htmlFor="var-edit-key" className="block text-xs text-muted-foreground mb-1">标识 (key)</label>
        <input
          id="var-edit-key"
          type="text"
          value={form.key}
          onChange={(e) => {
            onChange((prev) => ({ ...prev, key: e.target.value }));
            setErrors({});
          }}
          className={`${inputClass} ${errors.key ? "border-destructive/50" : ""}`}
          placeholder="例如: repo_url"
          disabled={form.source_type === "output"}
        />
        {errors.key && (
          <p className="text-xs text-destructive mt-0.5">{errors.key}</p>
        )}
        {form.source_type === "output" && (
          <p className="text-xs text-warning/70 mt-0.5">
            输出变量由节点配置管理，标识不可修改
          </p>
        )}
        {form.source_type !== "output" && (
          <p className="text-xs text-muted-foreground mt-0.5">
            在节点属性中使用 {"{{key}}"} 引用，只能使用字母、数字、下划线
          </p>
        )}
      </div>

      {/* 输出变量：来源节点信息 */}
      {form.source_type === "output" && form.source_node_id && (
        <div className="p-2 rounded bg-warning/5 border border-warning/10">
          <p className="text-xs text-warning/80">
            此变量由节点 <span className="font-mono text-foreground">{form.source_node_id}</span> 运行时自动填充
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            节点执行完成后，其最后一轮回复文本将写入此变量，供后续节点通过 {"{{" + form.key + "}}"} 引用
          </p>
        </div>
      )}

      {/* Name */}
      <div>
        <label htmlFor="var-edit-name" className="block text-xs text-muted-foreground mb-1">展示名</label>
        <input
          id="var-edit-name"
          type="text"
          value={form.name}
          onChange={(e) => {
            onChange((prev) => ({ ...prev, name: e.target.value }));
            setErrors({});
          }}
          className={`${inputClass} ${errors.name ? "border-destructive/50" : ""}`}
          placeholder="例如: 仓库地址"
        />
        {errors.name && (
          <p className="text-xs text-destructive mt-0.5">{errors.name}</p>
        )}
      </div>

      {/* Default */}
      <div>
        <label htmlFor="var-edit-default" className="block text-xs text-muted-foreground mb-1">默认值 (可选)</label>
        {form.type === "select" ? (
          <select
            id="var-edit-default"
            value={form.default}
            onChange={(e) => onChange((prev) => ({ ...prev, default: e.target.value }))}
            className={`${inputClass} appearance-none`}
          >
            <option value="">无默认值</option>
            {form.options.map((opt, i) => (
              <option key={i} value={opt.value}>
                {opt.name || opt.value || `选项 ${i + 1}`}
              </option>
            ))}
          </select>
        ) : form.type === "textarea" || form.type === "list" || form.type === "dict" ? (
          <textarea
            id="var-edit-default"
            value={form.default}
            onChange={(e) => onChange((prev) => ({ ...prev, default: e.target.value }))}
            rows={3}
            className={`${inputClass} resize-y min-h-[60px]`}
            placeholder={form.type === "list" ? '例如: ["a", "b", "c"]' : form.type === "dict" ? '例如: {"key": "value"}' : "留空表示无默认值"}
          />
        ) : (
          <input
            id="var-edit-default"
            type="text"
            value={form.default}
            onChange={(e) => onChange((prev) => ({ ...prev, default: e.target.value }))}
            className={inputClass}
            placeholder="留空表示无默认值"
          />
        )}
      </div>

      {/* Required */}
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={form.required}
          onChange={(e) => onChange((prev) => ({ ...prev, required: e.target.checked }))}
          className="w-3.5 h-3.5 rounded border-primary/30 bg-card accent-primary"
        />
        <span className="text-xs text-muted-foreground">必填</span>
      </label>

      {/* Hidden */}
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={form.hidden || false}
          onChange={(e) => onChange((prev) => ({ ...prev, hidden: e.target.checked }))}
          className="w-3.5 h-3.5 rounded border-primary/30 bg-card accent-primary"
        />
        <span className="text-xs text-muted-foreground">隐藏（填参页面默认折叠）</span>
      </label>

      {/* Description */}
      <div>
        <label htmlFor="var-edit-desc" className="block text-xs text-muted-foreground mb-1">说明 (可选)</label>
        <textarea
          id="var-edit-desc"
          value={form.description}

          onChange={(e) => onChange((prev) => ({ ...prev, description: e.target.value }))}
          rows={2}
          className={`${inputClass} resize-none`}
          placeholder="变量用途说明"
        />
      </div>

      {/* Select Options */}
      {form.type === "select" && (
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs text-muted-foreground">
              选项列表 <span className="text-destructive">*</span>
            </label>
            <button
              type="button"
              onClick={addOption}
              aria-label="添加选项"
              className="flex items-center gap-0.5 text-xs text-primary hover:text-primary transition-colors cursor-pointer"
            >
              <Plus size={12} aria-hidden="true" />
              添加
            </button>
          </div>
          {errors.options && (
            <p className="text-xs text-destructive mb-1">{errors.options}</p>
          )}
          <div className="space-y-1.5 max-h-32 overflow-y-auto">
            {form.options.map((opt, idx) => (
              <div key={idx} className="flex items-center gap-1">
                <input
                  type="text"
                  value={opt.name}
                  onChange={(e) => updateOption(idx, "name", e.target.value)}
                  className={`flex-1 px-2 py-1 rounded bg-card border border-primary/20 text-foreground text-xs focus:outline-none focus:border-primary/50`}
                  placeholder="展示名"
                />
                <input
                  type="text"
                  value={opt.value}
                  onChange={(e) => updateOption(idx, "value", e.target.value)}
                  className={`flex-1 px-2 py-1 rounded bg-card border border-primary/20 text-foreground text-xs focus:outline-none focus:border-primary/50`}
                  placeholder="填充值"
                />
                <button
                  type="button"
                  onClick={() => removeOption(idx)}
                  aria-label={`删除选项 ${idx + 1}`}
                  className="p-1 text-muted-foreground hover:text-destructive transition-colors shrink-0 cursor-pointer"
                >
                  <Trash2 size={12} aria-hidden="true" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
