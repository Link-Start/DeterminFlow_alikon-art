# Core 与 Extension 架构

## 边界

Core 拥有 Agent Runtime、Workflow、Automation、Tool/MCP、Workspace、Prompt 组装机制和 Web Shell。Core 只定义 Extension 可以使用的端口，不包含长期记忆或小说领域实现。

Extension 可以贡献：

- FastAPI Router 与 ASGI Middleware
- Agent Tool Factory 与 Tool Group
- Prompt Context Provider
- Session Lifecycle Hook
- Memory provider 与 memory scope authorizer
- Agent、Prompt、Skill/Rule Bundle、Workflow、Script Library 资源
- Health Check 与 build-time Frontend 页面

Workflow Node 类型由 Core 独占，Extension 只能组合现有 Node 的 Workflow 模板。

## 启动流程

```text
extensions.json / DETERMINFLOW_EXTENSIONS
  -> discover manifests and Python entry points
  -> validate Extension API version
  -> resolve dependencies topologically
  -> build namespaced resource snapshots and validate declarations transactionally
  -> initialize Core services
  -> run forward-only migrate and verify commands
  -> start Extension lifecycle hooks
  -> run Extension health checks
  -> mark Extension running
  -> register Extension tools
  -> reload layered resources from running Extensions
  -> build Agent graphs from active contributions
```

关闭时 Extension 按依赖顺序逆序停止，然后 Core 关闭 Session、Cron 和 MCP 资源。

生命周期状态如下：

| 状态 | 含义 |
|---|---|
| `disabled` | 已发现但未启用 |
| `discovered` / `loaded` | 已进入启用拓扑，声明已通过校验 |
| `starting` | 正在执行启动和健康检查 |
| `running` | 唯一可以激活工具、路由、中间件和资源的状态 |
| `degraded` | 本扩展加载、注册、启动或健康检查失败 |
| `blocked` | 依赖扩展未进入 `running` |

默认的非严格模式会隔离单个 Extension 的错误并让 Core 继续启动；`config/extensions.json` 中的 `strict_startup=true` 用于 CI 或开发期快速失败。注册、迁移、启动或工具安装中断时，Host 会撤销该 Extension 已安装的 Tool，并调用 `stop()` 清理。

## 资源流

输入：Core JSON、启用 Extension 的资源、用户 override。

处理：Host 先用 Plugin Prefix 生成显式资源 ID mapping 和只读运行快照，再由
`LayeredJsonConfig` 按 owner 合并并检测冲突。Skill/Rule Bundle 保留 owner 与只读
来源元数据。

输出：Agent、Prompt、Skill、Rule 和预设短语使用的 resolved config。

修改 Extension 默认资源时，写入 `config/extension-overrides/`。关闭 Extension 后，其默认资源和 override 都不进入 resolved config，但合法 override 会保留并在 Extension 再次运行时恢复；已从 Extension 删除的资源 override 会被清理。

## Workflow 与 Script

Extension Workflow 是不可变模板，启动时 provision 到运行目录。用户修改后的定义不会被 Extension 更新覆盖，运行 Task 继续使用自身 Snapshot。上游已删除且用户未修改的脚本会同步删除；用户修改过的脚本会保留，并在 `.extension.json` 的 `orphaned_files` 中记录。

只有 owner 处于 `running` 的 Workflow 才能创建、编辑或执行。Extension 不可用时仍可读取既有 Task 和 Run 历史，避免故障期间丢失诊断入口。

### 节点失败恢复

失败恢复属于 Core 编排能力，与 Agent、Script、Approval 或 Subprocess 插件实现无关。每个节点可配置首次失败后的 `auto_retry_count`、固定 `auto_retry_interval_seconds` 和重试耗尽后的 `fail_auto_skip`。默认均关闭；自动重试最多 20 次、间隔最多 86,400 秒。重试复用原 Task 的 definition snapshot（定义快照）、参数、workspace（工作空间）和首次冻结的节点输入，已完成节点、并行分支与循环迭代不会重跑。Subprocess 内部状态继续保留在父节点 `child_states`，由父 Subprocess 节点负责恢复调度。

失败节点详情提供原地“重试”和“跳过”。两个 mutation 都要求客户端提交当前 `expected_attempt_count`，用 CAS（比较并交换）拒绝过期或并发操作；对应接口为 `POST /api/workflows/{workflow_id}/tasks/{task_id}/nodes/{node_id}/retry|skip`。自动等待使用持久化 `retry_waiting`，人工操作或进程恢复使用 `resume_pending`，启动恢复器会继续到期重试和中断中的任务。每次尝试保留 trigger、时间、Session 与错误历史，累计 Token 不因重试清零。该能力提供 at-least-once（至少一次）执行保证；有外部副作用的插件仍必须自行保证幂等。

Script Library 使用按 owner 合并的只读 Plugin 目录；重复 `(group, script)` 会在
启动时拒绝。Task 创建时冻结 owner、revision、entrypoint 与文件摘要，执行前再次
核验，避免 Plugin 更新或文件漂移改变已创建 Task 的执行代码。

## 用户消息附加信息

Core 可以在新一轮真实用户消息前附加 `config/user_injection_config.json` 中启用的
Sections。`USER_MESSAGE_INJECTION_ENABLED` 是系统级总开关，默认开启以兼容现有行为；
关闭后，Core 不读取或附加任何 Section，也不生成对应的注入元数据，但保留已有 Section
配置供以后重新启用。

该开关只控制 Core 管理的用户消息附加信息。历史消息、工具调用结果、System Prompt，
以及 Extension 通过 `model_context` 传入的产品上下文都不受影响。

### 用户原话与产品上下文

`ExtensionSessionRuntime.invoke()`把一轮输入分成两个
持久化通道：`content` 是展示与编辑权威，必须保存用户原话；可选 `model_context` 是调用
产品提供的不可变 JSON 快照，保留显式 `null`，不得包含授权凭据。Core 只校验它是最大
64 KiB 的 JSON 对象，不解释产品字段。供应商额度/鉴权/权限/非法请求属于永久性失败，
Core 不在传输层重试；公开事件只给 `provider_error_code`，不回传原始供应商报文。取消
调用必须结算持久状态并释放 detached listener，不能留下 `streaming`。

detached 会话在接收下一条用户原话时重新组装当前 Agent 提示词，并保留历史消息。工具返回、
审批恢复、无新原话的操作观察和仍阻塞新消息的待确认轮次沿用已有提示词；不在一轮中途切换。

调用模型前，Core 临时把快照放进 `<PRODUCT_CONTEXT>`，把原话放进 `<USER_MESSAGE>`；
Core 自己的附加 Section 仍位于 `<SYSTEM_INJECTION>`。这些标记只存在于 LangChain 入模消息，
不会覆盖 `record` 或 `context.messages` 中的原始 `content`。重启、冷加载和未压缩上下文恢复时，
Core 根据持久化的 `model_context` 与 `injection_meta` 重建相同入模消息。

已安装、启用且 Agent opt-in 的 memory provider 可以把按真实用户回合召回的低信任记忆
合并进 `model_context`，不改展示原文。会话沉寂或未处理长度触发的异步抽取由 Core
持久任务状态驱动，供应商适配仍留在插件；详见
[memory-contracts.md](memory-contracts.md)。

Web 会话默认只在用户气泡显示 `content`，并把产品上下文与系统附加信息放入默认折叠的“系统注入信息”。
旧 detached 会话仍可读取历史伪用户 JSON 包装；前端只提取其中的 `user_message` 作为气泡正文，
其余字段进入系统注入信息，不批量改写历史会话文件。

Prompt 检查面板优先展示热会话已经绑定的工具。detached 会话冷卸载后不再保留
`session.tools`；检查面板只根据当前 AgentDefinition 与工具注册表重新解析工具清单，
不创建模型客户端、不编译 Graph，也不改变会话驻留状态。检查面板的“入模消息”直接从当前
`lc_messages` 生成，只保留模型协议实际接收的字段；不得使用展示权威 `record` 或 Core 内部追踪
元数据冒充入模上下文。工具定义保留与 `bind_tools` 相同转换路径产生的完整 Schema。
独立“系统提示词”页面只展示选中会话的 System Prompt 与其工具定义，不重复展示会话元信息、
入模消息或原始工具 JSON。工具展开区把 `bind_tools` 的标准 JSON Schema 转译为工具用途、
action 语义、参数类型、必填状态、允许值和约束；产品特定说明仍由 Plugin 的 Schema 提供，
Core 不猜测参数含义。工具清单使用紧凑的通用折叠行，折叠态只承担工具识别与契约数量摘要，
展开态再呈现结构化操作和参数；Core 不按工具名、Plugin 或产品来源切换专属展示。

工具调用的入参校验失败由 ToolNode 返回结构化字段规则，不回显原始输入、内部注入参数或
自定义异常正文。模型可以修正后重试；同一用户轮次重复相同工具与相同无效参数时，Core 仅在
ToolNode 入口跳过该次调用并返回 `tool_arguments_repeated`，同批其他调用继续执行并保留各自结果。
整批均被重复参数保护拦截时，下一次模型请求不再提供工具，让模型根据已有结果总结完成与未完成项；
若模型仍输出调用，配对记录 `tool_recovery_stopped` 并结束，避免空转。新用户轮次不继承该限制，业务失败也不按参数
错误去重。工具执行期异常（网关拒绝、超时等）保持原异常传播和会话安全失败，不得误分类为
字段反馈，也不得在错误处理中二次抛出 AttributeError 遮盖原因；取消不得被吞掉。
最后一个模型轮次只用于回答，不再提供工具；模型仍输出调用时，配对记录“未执行”。
等待外部确认的工具维持 pending 状态，不进入失败收尾。

流式工具参数按协议字典读取调用 ID、索引及参数片段。工具回调、图节点返回的跳过结果和
中断收尾共同保证一个调用只有一个终态；前端展示及持久化记录均不能将未知结果标为完成。
检查面板的参数摘要从正式 Schema 生成，保留联合类型、可空性、数组元素及约束。

## 前端

Core Web Shell 不打包官方 Plugin 的产品前端。可安装 Plugin 需要轻量可视化配置时，
使用 manifest `[page]` 声明的静态页面并在 Plugin 管理详情中加载；常规配置优先使用
Core 根据 `settings.schema.json` 生成的通用表单。复杂产品工作台保持独立部署，
通过稳定的 Plugin API 与 Core 集成。

仓库内共同开发的本地 Extension 仍可由 Vite 在构建时发现
`extensions/*/frontend/index.tsx`，但不会预先执行模块。浏览器请求
`/api/extensions` 后只动态加载后端处于 `running` 的页面和 Agent Editor
contribution，并拒绝 Extension ID、页面 ID 或 Core Tab ID 冲突。

Core Web Shell 为每个顶层页面声明唯一滚动模式：工作台页面使用 `contained`，只允许页面内部面板
滚动；文档页面使用 `document`，由 Shell 提供唯一页面滚动容器。顶层页面不得重复计算视口高度。
共享 `ScrollArea` 负责收敛 Radix 内层固有尺寸和滚动链，页面不得再复制相同的内部选择器补丁。

Core 的 Extensions 页面展示 manifest、依赖、能力、运行状态和降级原因；第一版不提供运行时启停。

Plugin 静态页面不作为安全沙箱；Plugin Backend 与 Core 同进程、同权限运行。
