# DeterminFlow Desktop

本目录只服务于桌面发行构建。服务版仍从仓库根目录执行 `python run.py`，无需加载这里的 Tauri、PyInstaller 或安装包配置。

## 架构

| 部分 | 实现 | 运行职责 |
|---|---|---|
| 桌面壳 | Tauri 2 | 创建原生窗口、启动和关闭本地后端 |
| 后端 | PyInstaller `onedir` | 冻结现有 Python/FastAPI 服务，不要求用户安装 Python |
| 前端 | 现有 `web/dist` | 由本地 FastAPI 服务提供，入口和服务版一致 |
| 桌面适配 | `ui/desktop-adapter.js` | 仅由 Tauri 注入，提供错误弹窗和 Provider Key 保存前连通性检查；服务版不加载 |

桌面进程每次选择一个空闲的 `127.0.0.1` 端口。窗口在 `/api/system/status` 返回成功后才进入现有 Web UI；重复打开只会唤起已有窗口；窗口退出时会终止内置后端及其子进程。

## Windows 正式安装包

| 部分 | 实现 |
|---|---|
| 安装包 | NSIS `currentUser`，不申请管理员权限；向导使用正式品牌图 |
| 更新 | Tauri Updater + Cloudflare R2/GitHub/Gitee；R2 优先，按可用性回退 GitHub 或 Gitee |
| 构建 | GitHub Actions `windows-2025`，在真实 x64 Windows Runner 上完成安装与卸载验证 |
| 配置 | `desktop/src-tauri/tauri.conf.json` |
| 工作流 | `.github/workflows/desktop-windows.yml` |

同一版本生成两个安装包：

| 安装包 | 内容 | 后续更新 |
|---|---|---|
| Core | 纯净 DeterminFlow Core | 通过 `latest.json` 更新 Core |
| Full | 同一 Core，加构建时全部公开官方 Plugin 快照 | Core 仍走同一 `latest.json`；Plugin 由 Plugin 页面独立更新 |

Full 不是单独 Edition，也不使用第二套应用标识、数据目录或 Core 更新通道。Full 首次
启动会把快照中精确锁定的 Plugin 合并进用户数据并启用一次；已存在的 Plugin 记录不会
被覆盖。之后安装普通 Core 更新包不会删除 Plugin，用户手动停用的 Plugin 也不会在日常
启动时被重新启用。

Windows Release 使用 GUI Subsystem，只显示主界面，不额外打开 CMD 窗口；应用、安装器和卸载器统一使用 `web/public/brand/determinflow-mark.svg` 对应的正式图标。

GitHub 临时分支 `codex/desktop-tauri-poc` 会运行 `.github/workflows/desktop-windows.yml`，分别上传 14 天有效的 Core/Full 候选 Artifact，不创建 Tag 或 Release。`v*` Tag 则在两种安装包全部通过 Windows 安装、启动和卸载验证后，创建正式 GitHub Release。

## macOS Apple Silicon 候选包

macOS 打包与 Windows 正式发行链路独立，不改变 NSIS、Updater、Tag 或 GitHub Release 行为。当前只提供 **Apple Silicon（arm64）Core 候选**，不是已签名、已公证的正式桌面版。私有仓库不新增 `.github` 公开发行工作流。

| 部分 | 实现 |
|---|---|
| 产物 | `.app` + `.dmg` |
| 架构 | 仅 `arm64`、macOS 11.0+，不构建 universal 或 Intel |
| 配置 | `desktop/src-tauri/tauri.macos.conf.json` |
| 签名 | `tauri build --no-sign`，不注入更新私钥 |
| 更新包 | `createUpdaterArtifacts=false`，不生成 `.sig` / updater tar.gz |
| 范围 | 只构建 Core，不构建 Full |
| 发布 | 本地候选验证，不创建 Tag 或 Release |

图标由 `desktop/scripts/generate_macos_icon.py` 从 `web/public/brand/determinflow-mark.svg` 生成 `desktop/src-tauri/icons/icon.icns`。Tauri 会自动合并 `tauri.macos.conf.json`；macOS 必须使用 `npm run build:macos`，不要直接运行 Windows 使用的 `npm run build`。

未签名候选包在本机打开时，可能需要在 Finder 中右键打开，或先清除隔离属性。这不表示已经完成 Apple 代码签名或公证。

## 数据边界

Windows 运行数据位于 `%LOCALAPPDATA%\\io.determinflow.desktop`；macOS 位于 `~/Library/Application Support/io.determinflow.desktop`：

```text
io.determinflow.desktop/
├── config/  # 用户配置；升级时不覆盖
├── data/    # 会话、工作流、Workspace、Skills、Rules、Plugins
└── logs/    # 服务日志与 backend-console.log
```

构建只读取 Git `HEAD` 中的白名单配置。模型配置由 `models_config.example.json` 生成；MCP Server 和 Extension 默认关闭；Plugin Source 固定为公开仓库。忽略的 `config/models_config.json`、工作区数据、本地 Plugin 状态和凭据不会进入安装包。

升级不会覆盖模型、会话、Workflow、Workspace、Plugin 锁或用户自定义 Plugin 仓库；
Core 拥有且 UI 中不可编辑的官方 Plugin Source 会随桌面 Runtime 刷新，因此 Plugin
Catalog 可以在不发布新 Core 的情况下继续跟踪官方仓库 `main`。

## 本地验证

平台无关测试可在 macOS 或 Linux 运行。Windows NSIS 安装、WebView2 和卸载行为必须由 Windows CI 验证。Apple Silicon `.app` / `.dmg` 在本机用 `npm run build:macos` 验证。

```bash
python -m pytest tests/test_desktop_packaging.py -q
python desktop/scripts/stage_defaults.py
(cd web && npm ci && npm run build)
python -m pip install pyinstaller==6.21.0
python desktop/scripts/build_backend.py
python desktop/scripts/smoke_backend.py
python desktop/scripts/verify_bundle.py
(cd desktop && npm ci)
(cd desktop && npm test)
(cd desktop/src-tauri && cargo test)
```

macOS 额外验证：

```bash
python -m venv desktop/.build/macos-venv
desktop/.build/macos-venv/bin/python desktop/scripts/install_macos_build_dependencies.py
MACOSX_DEPLOYMENT_TARGET=11.0 desktop/.build/macos-venv/bin/python \
  desktop/scripts/build_backend.py --flavor core
desktop/.build/macos-venv/bin/python desktop/scripts/smoke_backend.py
python desktop/scripts/generate_macos_icon.py
(cd desktop && MACOSX_DEPLOYMENT_TARGET=11.0 npm run build:macos)
desktop/.build/macos-venv/bin/python desktop/scripts/verify_bundle.py \
  --expected-flavor core \
  --app-bundle desktop/src-tauri/target/release/bundle/macos/DeterminFlow.app \
  --dmg desktop/src-tauri/target/release/bundle/dmg/DeterminFlow_1.0.2_aarch64.dmg \
  --verify-macos-load-commands \
  --verify-dmg-container \
  --forbid-updater-artifacts desktop/src-tauri/target/release/bundle
```

## 桌面更新发布

每次社区版正式发版都必须完成以下两项加速分发收尾，候选构建不执行：

1. **同步最新桌面安装包**：GitHub 正式 Release 验证通过后，Windows 发布流水线把该版本的 Core/Full 安装包、签名及校验文件同步到 R2，公网内容校验通过后才更新稳定 `latest.json`。发行完成前必须确认稳定清单的版本与签名对应本次 GitHub Release；同步失败不得把发行标记为完成。
2. **同步最新官方插件**：在 `DeterminFlow-Plugins` 仓库手动运行 `CI`，使用当前公开 `main`，将 `core_ref` 设置为本次 Core Tag 或精确 Commit，并明确勾选 `publish_registry`。插件测试通过后同步不可变包和签名目录，最后更新稳定 Manifest。核对公网目录的 Commit 与本次选定的官方插件提交一致，并通过签名、归档摘要及内容摘要验证；不能只检查 URL 返回 200。Full 的内置快照仍以本次构建锁为准，不改写旧安装包。

两个仓库必须保持 `R2_DISTRIBUTION_ENABLED=true`。任何一个同步步骤失败，都作为本次正式发版的未完成项处理。普通 PR 和 macOS 候选构建只上传 Actions 产物，不更新 R2 稳定入口。

macOS 候选由 `Desktop macOS candidate` 工作流生成，分别生成 Apple Silicon Core 与 Full；Full 捆绑锁定的公开官方插件快照。两种候选均包含 DMG、SHA-256、冻结后端、包内及 DMG 安装副本后端验证。候选未经 Developer ID 签名、公证和用户侧安装验收，不进入官网正式下载或自动更新清单。

桌面端并行检查 R2、GitHub 与 Gitee 的最新发布。相同版本与签名下优先使用 R2；R2 不可用或签名与 GitHub/Gitee 权威发布不一致时，回退原有 GitHub/Gitee 选择规则。所有来源最终都必须通过同一 Tauri 公钥验签，R2 只承载分发流量，不改变 GitHub Tag 和 Release 的版本权威。

正式发布仍先创建 GitHub Release，并同时上传 Core/Full NSIS 安装包、各自同名 `.sig`、SHA-256 文件和 `latest.json`。当仓库变量 `R2_DISTRIBUTION_ENABLED=true` 时，发布任务再调用 `desktop/scripts/publish_r2_release.py`：先上传并公开校验 `desktop/releases/vX/` 下的不可变资产，最后更新 `desktop/stable/latest.json`。同名不可变对象内容不一致时任务会失败，不会覆盖历史版本。R2 凭据只通过 `R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY` Secret 和 `R2_BUCKET`、`R2_ENDPOINT_URL` Variable 注入。更新签名私钥不得进入 Git，只通过 `TAURI_SIGNING_PRIVATE_KEY` Secret 注入构建。macOS 候选包不进入该更新通道。

Full 构建从官方 Plugin 仓库的 `main` Catalog 解析当时全部公开 Plugin，执行声明式资源
预检后锁定精确 Commit 与内容摘要，再写入安装包。Core 自动更新不重置 Plugin 状态。
官方 Plugin 在线安装和后续更新优先使用独立签名的 R2 Registry，不要求系统安装 Git；
R2 不可用、签名或内容校验失败时回退 GitHub/Gitee Git 源。自定义第三方 Plugin 来源
仍使用系统 Git。Full 的内置快照和 Core 自动更新都不会重置用户的 Plugin 状态。

服务版仍按原入口运行，不初始化 Tauri 更新插件，也不显示更新 UI。若 R2、GitHub 与 Gitee 都没有可用 `latest.json`，桌面端会保留当前版本并提示更新服务尚未发布，不影响应用本身使用。

## 首版限制

- Windows 安装包尚未做 Authenticode（Windows 代码签名），因此不同 Windows 设备上的 SmartScreen 表现可能不同。
- 正式 Windows 发布前必须在 Windows Runner 验证正常关窗、重复启动、Updater 安装、覆盖安装与卸载
  都不会遗留 `determinflow-backend.exe`，并完成一次真实跨版本升级验收。
- macOS 候选包未做 Apple 代码签名和公证，不进入 GitHub Release，也不提供自动更新。
- 不内置 Node.js、npm、Git 或 Git Bash。Windows 上 `execute_command` 使用 `cmd.exe`；Python Workflow 由冻结后端兼容执行；Shell Workflow 需要用户另行安装 Git Bash。
- Windows `downloadBootstrapper` 保持安装包较小。Windows 10/11 通常已有 WebView2；缺失时安装器需要联网下载。
