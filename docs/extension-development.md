# Extension 开发指南

## Manifest

```toml
[extension]
id = "example-tools"                 # 扩展唯一标识
name = "Example Tools"               # 展示名称
version = "1.0.0"                    # 扩展版本
api_version = "1"                    # Extension API 版本
backend = "example.backend:create"   # 可选 Python entrypoint
frontend = "example-tools"           # 可选前端模块 ID
dependencies = []                     # 必需 Extension ID 完整列表
capabilities = ["agent.tools"]       # 能力声明，仅用于审计

[resource_namespace]
prefix = "example"                   # 开发者默认 Prefix，安装时可高级覆盖

[resources]
agents = "resources/agents.json"
prompts = "resources/prompts.json"
skill_bundles = "resources/skill-bundles"
rule_bundles = "resources/rule-bundles"
workflows = "resources/workflows"
script_libraries = "resources/script-library"
```

`dependencies` 当前只接受 Extension ID，Host 会自动启用传递依赖并检测环。

第三方 Python 包使用 `determinflow.extensions` Entry Point 时，名称必须与
`manifest.extension_id` 相同；未启用的 Entry Point 不会被 import。历史包使用的
`ai_company.extensions` 仍受支持，但新项目不应继续采用旧名称。

## Backend

```python
class ExampleExtension:
    def register(self, registrar):
        registrar.add_router(router)
        registrar.add_tool_contributor(register_tools)
        registrar.add_health_check(check_dependency)
        registrar.add_memory_provider(provider)
        registrar.add_memory_scope_authorizer(authorizer)

    async def start(self, runtime):
        self.workflow = runtime.workflow_runtime

    async def stop(self):
        pass


def create():
    return ExampleExtension()
```

`register()` 只能声明贡献，不应连接数据库、启动任务或访问网络。I/O 初始化放在 `start()`，资源释放放在可重复调用的 `stop()`；即使启动只完成了一部分，Host 也可能调用 `stop()` 做回滚。

Manifest 只接受 Core 已声明的资源类型，资源路径必须位于当前 Extension 目录内。Tool contributor 获得的是 owner-scoped registry（所有者受限注册表），即使省略 `owner` 也会自动归属当前 Extension，停止或降级时可完整回滚；尝试冒充其他 owner 会失败。

Extension 不应 import `src.web_server`、`src.agent.session_manager` 或 `src.workflow.manager` 等内部实现。需要的新能力应先以 Protocol/Facade 添加到 `src.extension_api`。

Core 账号会话属于敏感的产品级内部服务，不是通用 Extension API。Host 只向官方来源的
`public-api` Plugin 注入 `account_session`；第三方 Plugin 即使使用相同 ID 或能力声明也不会
获得该服务。普通 Extension 不应读取、复制或持久化 Core 的访问令牌和续期令牌。

`runtime.workflow_runtime` 只暴露工作流查询、创建任务、运行、停止、任务快照和 Token 汇总；工作流编辑和 Manager 内部状态不属于 Extension API。健康检查返回 `HealthCheckResult`，失败时扩展进入 `degraded`，不会拖垮非严格模式下的 Core。降级扩展的 Prompt Context 与 Session Hook 不会执行。

Plugin 源文件使用本地资源 ID。Host 会按 Manifest 默认 Prefix 或安装时覆盖值构建
显式映射和运行快照；不要在代码中自行拼接、裁剪 Prefix。跨资源引用使用：

```python
runtime.resolve_resource("prompt", "writer")
runtime.resolve_resource(
    "workflow",
    "build",
    plugin_id="workflow-provider",
)
```

跨 Plugin owner 必须先列入当前 Manifest 的 `dependencies`，否则解析失败关闭。
Prompt 正文、脚本正文、Workflow node ID、公开 API 与数据库标识不参与自动改写。
Prefix 只在最终资源 ID 和 Plugin 详情中弱展示。

只有完成可选 lifecycle、`start()` 和全部健康检查、进入 `running` 后，Host 才注册该 Extension 的 Tool，并开放路由、中间件和资源层。Workflow Node 属于 Core，不是 Plugin Extension API。依赖失败时下游进入 `blocked`；注册阶段的 JSON 语法、section 形状、资源 ID 或 Workflow 冲突在非严格模式下只降级责任 Extension。

Skill/Rule Bundle 与 Script Library 是 Plugin 只读资源。Script Task 会冻结并在执行前
核验 Plugin revision 和文件摘要。需要修改时发布新的 Plugin commit，不要从运行时
写入 Plugin checkout。每个 Script Library 目录必须只依赖其目录内文件、Python 标准库和
`[installation].requirements` 声明的第三方包，不得导入 Core `src` 或 Plugin Backend
package、组级 helper 或兄弟脚本；预检会静态拒绝该耦合，Plugin 测试还应逐目录复制到
隔离安装布局并启动全部入口。数据库升级使用 Manifest `[lifecycle]` 的幂等
`migrate_command` 与 `verify_command`，不在 `register()` 或模块 import 时执行。

## Prompt 与 Session Hooks

Prompt Context Provider 输入 `PromptContextRequest`，输出 `PromptContribution`。
长期记忆只应写入稳定使用规则；按回合召回的历史记忆进入 `model_context`，不是
系统提示词。

Session Lifecycle Hook 的 `on_session_end(session)` 用于异步归档。Hook 失败不会阻断 Core shutdown。不要在 shutdown 时用最后几条用户消息直接 retain。

## Memory provider 与 scope authorizer

`registrar.add_memory_provider(provider)` 注册供应商无关的长期记忆后端。
`registrar.add_memory_scope_authorizer(authorizer)` 登记当前 owner 下的可信回调：

```python
async def authorize(self, *, external_ref: str, memory_scope: str) -> bool: ...
```

Core 在自动召回、主动 memory tool、后台 extract/retain 前调用该回调。失败只关闭
该次记忆动作，不影响前台聊天。后台不得使用前台 grant。契约见
[memory-contracts.md](memory-contracts.md)。

Agent 通过 `extension_options["<provider-id>"] = {"enabled": true, "scope": "user"}`
opt-in。缺少可信 `memory_scope` 时不得回退 global bank。主动 tool 通过
`runtime.get_service("memory")` 访问同一授权服务。

## Frontend

`frontend/index.tsx` 默认导出 `FrontendExtension`：

```tsx
const extension = {
  id: "example-tools",
  pages: [{ id: "example", label: "Example", icon: Wrench, component: ExamplePage }],
};

export default extension;
```

Frontend 是 build-time module。新增或删除前端 Extension 后必须重新构建 `web`。

`extension.id` 必须等于 manifest 的 `frontend`，页面 ID 不得与 Core Tab 或其他 Extension 页面重复。模块仅在后端状态为 `running` 时动态加载；加载或契约校验失败会显示在 Extensions 诊断页，不影响 Core 页面。

## 外部解析工具

Plugin 只通过 `runtime.session_runtime`（`ExtensionSessionRuntime`）的
`ensure_detached`、`invoke` 与 `resume_tools` 使用 detached conversation；
不要 import Core 内部 Session 实现，也不要把产品模块回流进 Core。调用方不得把
`max_turns` 改成传输重试开关；当前 Agent Definition 的 `max_turns` 保持原值。

需要浏览器批准或其他异步决策的工具应返回 Core 的 pending tool resolution
标记。Core 会保留原始 Assistant `tool_call_id`、停止 `tools → llm` 路由并冷存储
detached session；标记本身不会写入模型上下文，也不会发出 `tool_end`。Extension
取得最终结果后必须通过 `ExtensionSessionRuntime.resume_tools()` 一次性解析当前轮次的全部 pending ID。Core 随后写入与原调用匹配的
ToolMessage 并继续同一模型轮次，不得用新 HumanMessage 或 SystemMessage 模拟工具结果。

`invoke()` 在供应商失败时必须把异常传播给 Plugin，不得把上一轮 assistant 正文当成
成功结果。公开 `error` 事件只携带安全文案和结构化 `provider_error_code`
（`provider_quota_exhausted`、`provider_auth_failed`、`provider_permission_denied`、
`provider_bad_request`），不得回传原始供应商报文。调用被取消时，Core 会把持久状态从
`streaming` 结算为终态，并释放 listener/consumer，避免会话卡在流式中。

`resume_tools(session_id, resolutions, event_callback, invocation_context)` 的调用
形状保持不变。工具结果一旦被接受，会作为 `accepted_tool_resume` 批次持久化；其中
只保存 canonical JSON 结果、tool_call_id、工具名、run_id 和剩余轮次，不保存
`invocation_context` 或 grant 等短期凭据。同一组精确 resolutions 在模型后续失败、
调用方在新工具启动前取消或冷加载后可以安全续答：已写入的 ToolMessage 不会重复
追加。最终 assistant 结果或下一组 pending 审批已落盘但响应丢失时，原批次重放
对应结果或 `tool_pending` 事件，不再 invoke。下一组工具结果被接受后才替换旧批次，
不允许把两组结果混合提交。结果接收和终态检查点必须严格落盘后才能继续执行或交付。
续答执行期间预先保存不可恢复标记；受控失败且尚未启动新工具时才恢复可续答状态。
若进程在执行期间退出，或新工具启动后取消或失败，不能证明副作用状态时拒绝再次
resume，并保留原会话记录，不能通过 ensure 隐式删除并重建会话。

## 验证

每个 Extension 至少验证：

1. Extension 关闭时 Core 能启动，且不出现扩展路由和工具。
2. Extension 启用时 manifest、资源和依赖能解析。
3. Extension 的数据库、网络或外部服务不可用时状态为 `degraded`，Core 仍可运行。
4. 所有资源 ID 无冲突。
5. Extension 关闭或降级时，历史 Workflow 可读但所有写入和执行入口返回不可用。
6. `python -m pytest -q`、`npm run lint`、`npm run test:extensions` 与 `npm run build` 通过。


## Optional persistent workspace integration

Core exposes `add_workspace_provider` / `add_workspace_scope_authorizer` and the
`workspace` public runtime service. This integration defaults off and requires a
healthy active provider plus explicit Agent opt-in; it does not change coding-tool
permissions. See [workspace contracts](workspace-contracts.md) for the storage,
authorization, versioned commit, context loading and materialization interfaces.
