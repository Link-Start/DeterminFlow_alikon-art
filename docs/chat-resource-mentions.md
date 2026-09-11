# 对话中的资源引用

在共享对话输入框输入 `@`，左侧选择 Prompt、Agent、Skill、Rule、Workflow 或会话，
右侧展开具体资源。也可直接输入资源名称，跨类型检索二级菜单内容；左侧保留匹配的类型，
右侧显示当前类型的匹配资源。选中后在原位置插入引用标签，可和文字、文件或其他引用混排。
资源名称用于展示，实际引用包含资源类型和唯一 ID。

输入框左下角加号在光标处插入 `@` 并打开资源面板。一级菜单最上方的“文件附件”
直接打开原有文件选择，不展开二级菜单。选择文件后替换当前 `@` 检索片段，取消选择则保留原输入。
不同资源类型使用独立图标和轻量配色，输入框与发送后的消息保持一致，文件附件使用中性色。

## 读取语义

引用不会导出快照、复制资源正文、切换 Agent 或启动 Workflow。模型收到的是当前资源的读取方式，
按用户指令决定后续操作；读取时得到资源的当前内容，已删除的资源由读取工具报告不存在。

| 类型 | 读取方式 |
| --- | --- |
| Prompt | `get_system_prompt(agent_type=...)`，读取完整提示词模板 |
| Agent | `get_agent_definition(agent_type=...)` |
| Skill | `get_skills(skill_id=...)`；配套文件继续用 `resource_path` |
| Rule | `get_rules(rule_id=...)` |
| Workflow | `get_workflow(workflow_id=...)` |
| 会话 | `get_session_messages(session_id=...)`，分页读取现有可见历史 |

Prompt 目录与编排页共用模板列表，当前内置模板为 `compressor`、`main`、`subagent`；
不单列模板内部的 section。新增或删除自定义模板会同步反映在目录和搜索结果中。

当前会话没有对应读取工具时，资源仍可搜索，但不可插入。目录检查不会给会话增加工具或启动模型。
会话历史读取保留主会话边界，Sub Agent 不能借引用读取其他会话；返回值不包含隐藏系统消息或
`model_context`。长消息按字符继续读取，返回的 `next_offset`、`next_content_offset` 指向下一页。

## 交互

- 一级菜单为窄列，选中行显示向右箭头；悬停、点击或键盘选择在右侧展开二级菜单，一级菜单保留。
- 上下方向键在当前列移动，右方向键进入资源列，左方向键回到类型列；Enter 进入类型或插入资源。
  选中“文件附件”时 Enter 打开文件选择，右方向键不执行操作。
  面板打开期间 Enter 不发送消息。Esc 回到类型列，再按一次关闭；Tab 关闭并继续正常焦点导航。
- 未选类型时直接输入可同时搜索类型名称和具体资源；明确进入类型后输入则在该类型内搜索。
  中文输入法选词期间不截获方向键或 Enter。
- 两列底边固定在输入框外侧上方，按实际内容向上撑开，达到可用高度后滚动；窄屏下两列共同收窄。
  菜单沿用下方快捷操作的紧凑字号。
- 引用标签可以删除；点击面板外关闭，关闭面板、移动光标、切换会话不会误插入过期搜索结果。
- 历史消息继续显示引用标签，编辑保留正文中仍存在的引用，失败恢复保留原引用元数据。

## 接口与消息格式

`GET /api/sessions/{session_id}/mention-resources` 按 `resource_type` 查询，
支持 `q`、`offset` 和 `limit`（默认 50，最多 100），返回 `items`、`total`、`has_more`。
没有检索词时只请求正在查看的类型；直接检索时并行查询六类目录，沿用原有防抖、分页和过期请求隔离。
Workflow 目录省略任务历史扫描。

消息继续使用原 `content + attachments` 协议，文件附件格式保持不变：

```json
{"name":"report.md","absolute_path":"/workspace/report.md"}
```

资源引用使用另一种附件元数据，正文在标签位置包含同一个 `reference_text`：

```json
{
  "name": "代码审查",
  "resource_type": "skill",
  "resource_id": "code-review",
  "reference_text": "Skill「代码审查」（get_skills(skill_id=\"code-review\")）"
}
```

`attachments` 仅用于界面显示和历史恢复，不作为模型的额外指令。服务端校验类型、字段长度和正文
匹配，不把资源引用存入 `absolute_path`。现有持久化格式无需数据库迁移，也不注册新链接协议。

## 验证

后端相关回归：

```sh
.venv/bin/python -m pytest tests/test_resource_mentions.py tests/test_workspace_attachments.py tests/test_chat_stream_protocol.py tests/test_extension_contracts.py tests/test_tool_resolution.py tests/test_workspace_tools.py -q
```

前端运行 `npm test`（含对话与设计约束测试）、`npm run build` 和 `npm run lint`。
输入框 DOM 交互测试使用仅用于开发的 Happy DOM，覆盖实际键盘事件和异步请求交错，不启动浏览器。
自动化测试与构建不代替浏览器或用户操作验收。
