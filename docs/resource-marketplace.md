# 资源广场本地客户端

Core 桌面客户端通过本机 API `/api/resource-marketplace` 连接官网资源广场。
“资源广场”页签是官网 `/embed/marketplace` 的安全薄宿主，可见目录与作者界面由官网提供；
Core 账号 API 统一负责登录，本机资源广场 API 负责安装、投稿、收藏、评价、举报、正文预览和生命周期变更。
目录浏览、分页发现、详情、公开评价、正文预览、安装和本机更新不需要登录；收藏列表、评分、删除自己的评价、投稿、查看我的投稿、举报、审核与下架需要已登录的桌面会话。

`/api/resource-marketplace/status` 返回 `embed_url`。默认由 `DETERMINFLOW_MARKETPLACE_URL`
拼接 `/embed/marketplace`，也可用 `DETERMINFLOW_MARKETPLACE_EMBED_URL` 单独覆盖。地址必须是
HTTPS，或在显式允许本机 HTTP 时使用 loopback；不得包含凭据或 fragment。

安装、更新、提交审核、生命周期变更和删除自己的评价会先经过 Core 外层确认对话框；取消返回稳定错误 `cancelled`，不会调用后端。
举报可见评价由嵌入页确认目标，不额外弹出 Core 确认。
嵌入页加载失败时，宿主提供重试和“在浏览器打开”。

安装请求必须携带详情中的 `expected_version_id` 和 `expected_sha256`。Core 在下载前核对
当前版本，再校验下载字节的 SHA-256；版本变化返回 `409 version_changed`，需刷新详情后
重新确认，不会自动安装新版本。下载内容不符返回 `integrity_mismatch`，不会留下安装目录。
下载成功不等于安装完成；只有原子写入安装目录、记录来源并持久化启用和自动注入配置后，本机才返回
`installed: true`。真实安装与投稿会写隐私安全的结构化操作日志，字段仅限 `operation`、
`result`、`error_code` 和 `duration_ms`，不含 token、正文、用户 ID、URL 或异常 repr。
Bridge v1 通过新增的可选能力 `skill.installPinned` 承载这两个字段；新版嵌入页在旧宿主上
提示更新客户端后安装。保留的 `skill.install` 兼容入口也会先读取可信详情、显示版本确认，
再调用相同的后端校验接口。

本机目录、分页与详情的 `installation` 字段包含 `status`、`version` 和 `enabled`。
状态分别为 `available`（可安装）、`installed`（同一资源已安装）、`builtin`（Core 已内置）
和 `conflict`（本地存在同名但来源不同的资源）。该状态由 Core 根据本地来源记录计算，
官网公开接口不提供本机状态。普通安装继续拒绝覆盖任何同名资源。

同来源的已安装资源增加可选字段 `update_available`，只在能够比较版本时返回布尔值；`version` 仍代表本地版本。Skills 页的更新入口通过 `marketplace_skill` 定位广场，并在受信任嵌入地址的 `skill` 参数中传递 slug。详情只有在宿主声明 `skill.updatePinned` 且存在更新时才显示“更新”。

`POST /api/resource-marketplace/skills/{slug}/update` 使用相同版本 ID 和摘要锁定请求。Core 重新获取可信详情、确认目标后，验证同一广场、资源、发布者，以及比本地更新的语义版本。下载前后均检查本地来源、路径和原文字节，拒绝改动、符号链接或额外文件；只原子替换已安装的 `SKILL.md`。启用、自动注入、作用范围、优先级与分组沿用原配置。写入或重新加载失败时恢复旧文件与来源记录。

完成回执同时包含 `updated: true`、`installed: true` 和实际 `enabled` 状态；更新禁用的 Skill 不会将其启用。旧客户端不声明新能力时继续显示已安装入口。

`GET /api/resource-marketplace/catalog/skills` 提供服务端分页，查询字段为
`q`、`category`、`sort`、`page`、`page_size`、`favorites`。默认第 1 页、每页 24 条；
页码为 1 到 100000，每页 1 到 100 条。`favorites=true` 只代理当前登录账号的收藏，
并沿用现有账号续期；`favorites=false` 或省略时保持匿名公开目录，不会把私有列表
当作公开结果缓存。公开目录不含已弃用资源；收藏列表仍包含已收藏的已发布弃用项。

`GET /api/resource-marketplace/skills/:slug/reviews/page` 匿名分页公开可见评价，
默认第 1 页、每页 20 条，页码与每页数量沿用上述公共校验。公开评价字段为
`id`、`author_label`、`rating`、`body`、`created_at`、`updated_at`，不含账号 ID
或隐藏审核说明。保留 `GET /api/resource-marketplace/skills/:slug/reviews` 作为
可见评价前 50 条的兼容入口。可选 bridge 方法 `reviews.page` 承载新分页；旧宿主
仍可使用 `reviews.list`。

`DELETE /api/resource-marketplace/skills/:slug/review` 只删除当前账号自己的评价
和评分，请求体为 `{review_id, expected_updated_at}`，按精确修订时间做 CAS。
可选 bridge 方法 `review.delete` 会先弹出确认，明确说明将删除评分和正文。
`POST /api/resource-marketplace/skills/:slug/reviews/:review_id/report` 举报一条
当前可见的公开评价，请求体为 `{expected_updated_at, reason, details}`；不能举报
自己的评价。可选 bridge 方法 `review.report` 不额外确认。保留 `review.save` 与
`report.create`。当前账号自己的评价可带 `id`、`visibility`（`visible`|`hidden`）
和写给作者看的 `moderation_reason`；这些字段不会出现在公开评价列表中。

官网 429 返回 `code: rate_limited`、可读说明、`retry_after_seconds`（1 到 3600
的正整数）和 `Retry-After` 头。Core 会把它们传到本机 HTTP `detail` 与 bridge
错误对象的可选 `retry_after_seconds` 字段。评价相关成功与失败响应均 `no-store`。

`GET /api/resource-marketplace/skills/:slug/preview` 使用与安装相同的
`expected_version_id` 和 `expected_sha256` 读取只读 UTF-8 `SKILL.md` 正文，
不增加下载计数。版本变化返回 `409 version_changed`，哈希不一致则失败关闭。
公开网站不得调用该预览接口。

可选 bridge 能力 `skill.openInstalled` 只接受 `slug`。Core 用本机所有权数据解析
已安装或内置 Skill，导航到现有 Skills 页的对应资源及其启用控件，不自动启用，
也不接受 iframe 传入的 URL、path 或 skill id。冲突或未安装会失败；旧宿主不声明
该能力时，嵌入页不显示打开按钮。

## 登录

在桌面客户端顶部登录 DeterminFlow 账号。Core 将唯一会话保存在
`data/account/session.json`，资源广场和官方公益模型 Plugin 直接复用，不再各自保存
访问令牌或续期令牌。旧版资源广场状态中的会话会在启动时清除。

本地会话文件权限为 `0600`，接口只允许桌面模式下的 loopback（本机回环）请求。
账号会话仅注入官方来源的内置能力；第三方 Plugin 无法通过 runtime service 读取。


登录后可在官网嵌入页查看发现目录与作者投稿。新宿主通过可选 bridge 能力
`author.resources.page`、`author.versions.page` 代理按资源分页的作者工作台，以及
`feedback.page` / `feedback.read` 代理当前账号的审核与举报回执；旧宿主仍可使用
`submissions.list`。退出或切换账号会清除内存中的私有列表，但本机投稿草稿按账号分区保留。

本机投稿草稿只存在于 `data/resource-marketplace/drafts`，按不可逆的账号与广场来源分区，
文件权限 `0600`，通过 CAS 保存；不上传官网，也不经 bridge 暴露 token 或 subject。
保存草稿和本地预览只允许用户自有单文件 `SKILL.md`。`GET /api/resource-marketplace/local-skills/:skill_id/preview`
返回预览正文和精确字节 SHA-256。可选查询 `target_slug` 与 `publication_version` 会生成一份不改写本地文件的投稿副本，
其 `name` 与版本分别对齐线上目标和发布版本；预览正文就是将要上传的字节。来源摘要继续用于发现本地文件变化，
准备后的摘要必须与上传和安装一致。新宿主在声明 `resource.publishPrepared` 后才能把任意本地 Skill 更新到已有线上资源；
缺少该能力时不得把本地 `skill.id` 当作远程 slug。`resource.publishPinned` 仍用于未锁定目标的投稿。
本机 `POST /publish` 仍兼容省略 `expected_sha256` 的旧客户端，一旦提供则在上传前核对准备后的同一批字节。
草稿按账号与线上目标分区；可记住该目标上次选择的本地来源，来源缺失时允许另选，不能改写已上传的不可变版本。

## 投稿和版本

资源契约预留 Skill、Prompt、Agent、Workflow 和 Rule；首期只接收一个 UTF-8 `SKILL.md`，
不接受附件。其他类型在各自包格式、审核和运行权限边界确定前不开放投稿或安装。
已提交版本不可覆盖；修改内容或许可时须递增版本。
新版本待审或被拒绝不会影响当前已上架版本。审核通过会切换公开版本，旧投稿不能覆盖更新的上架版本。
下架后目录与下载停止公开，审核员可恢复上架并保留处理记录。首次安装默认启用并开启自动注入，用户可在 Skills 页关闭；更新保留本地启用及自动注入设置。
安装内容写入 `data/skills/marketplace/`，与 `data/skills/local/` 中的用户作品隔离；
同 ID 跨来源冲突时安装失败，不会覆盖本地或内置内容。

投稿前由 Core 批量调用官网名称检查；这只提供即时反馈，最终重名约束仍由官网提交事务保证。
发布页可编辑显示名称、作者笔名、简介、功能分类、主要语言、标签、更新记录、详细使用说明和使用授权。
简介最多 50 字、更新记录最多 150 字、详细使用说明最多 1000 字；投稿草稿可保留待修正的旧超长内容，提交前必须满足限制。
默认社区使用授权，标准开放许可证按需选择；包内已有许可声明时须保持一致。
这些展示字段不改写本地 `SKILL.md`，随投稿冻结；新版本审核通过前不改变公开页面。
目录支持名称/简介/标签搜索、分类筛选和最近更新/最多下载排序；卡片只展示文字评论数量，评分在详情中查看。

桥接 v1 的可选 `host:init.payload.request_lifecycle=true` 声明请求进度能力。
宿主每 5 秒发送带原 requestId 的 `progress`（preparing / confirming / executing）；新页面据此续接 30 秒连接等待，
不把用户阅读确认框的时间当作操作失败。没有进度能力的旧宿主，写入请求等待其真实响应，不能提前丢弃确认结果。
页面销毁或连接超时时发送仅含 requestId 的 `cancel`；宿主关闭尚未执行的确认，执行中的写入不会伪装为已撤销。
开始写入后保留实际结果；断联或无法确认写入结果时提示刷新核对，不自动重试。

## Skill 元数据边界

本地 Skill 只强制 `name`、`description` 和正文可用。版本、作者、分类、语言、许可证、
兼容范围、标签和依赖均可缺省；未知分类及其他扩展元数据会保留并给出警告，不会被静默改成
`general`。内容元数据放在 `SKILL.md`，本地运行设置和社区来源事实分别存放：

| 层级 | 字段 | 约束 |
|---|---|---|
| `SKILL.md` 标准字段 | `name`、`description`、`license`、`compatibility`、`allowed-tools` | 本地只强制前两项 |
| `metadata` 内容字段 | `display_name`、`version`、`author`、`category`、`language`、`tags`、`determinflow.scope`、`determinflow.requires_*` | 可随 Skill 复制和分发 |
| 本地运行设置 | `enabled`、`auto_inject`、`priority`、`scope_override`、`group_ids` | 只写 `skills_config.json`，不回写 Skill |
| 社区安装溯源 | registry、资源/版本/发布者标识、安装版本、SHA-256、许可证、安装时间 | Core 安装成功后写入 `resource-provenance.json` |

社区投稿比本地加载严格：必须使用 SemVer（语义化版本），填写作者笔名、受支持分类、明确语言
和受支持使用授权；第二个及后续版本必须填写更新记录。官网返回稳定但不暴露账号 ID 的发布者
标识，Core 会连同资源 ID、版本 ID 和包哈希记录。若安装后的 `SKILL.md` 与记录哈希不同，
本地界面会标记为已修改；来源记录不参与 Skill 指令解析。
资源广场安装物由 Core 按只读受管资源加载，不能直接修改或作为作者原稿重新投稿；需要二次创作时
应复制为新的本地 Skill ID，并自行确认许可证与分发权利。

首次打开资源广场会出现版本化的第三方资源风险提示。作者发布时必须接受官网
`/marketplace/terms` 的当前发布协议，协议接受版本与时间随投稿保留；其中包括第三方责任边界、
审核与下架规则，以及 DeterminFlow 与笔枢相关资源市场之间的同步、镜像和溯源授权。

详情中评分至少有 5 份后才公开展示均分，样本不足时只展示评分人数；资源卡始终只展示文字评论数量。收藏和评分按统一账号去重；公开身份使用稳定的匿名社区标签。下载同时记录总量与每日聚合，统计写入失败不会阻止已校验资源包下载。举报进入私有审核队列，不在公开目录暴露。

## 运行前提

官网需先应用版本与审核记录迁移，并正确配置统一账号的 issuer、audience 和 JWKS。
`MARKETPLACE_REVIEWER_ACCOUNT_IDS` 仅填写明确指定的统一账号 ID；未配置时所有审核请求均被拒绝。
笔枢管理员身份不会自动获得审核权限。本地联调使用隔离测试身份，不代表生产账号已启用；
账号服务激活、审核员指定和桌面安装包发布分别验收。
