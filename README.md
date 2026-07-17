# zhihu-salt-novel-downloader

知乎盐选小说下载器 - 异步并发下载 + 多格式导出 + 断点续传 + 桌面端

> 完整覆盖 **Web 前端 + FastAPI 后端 + Tauri 桌面端** 的全栈实现。
> 遵循 **开闭原则 / 依赖倒置 / 单一职责** 等企业级工程规范。

## 功能特性

### 核心能力
- **异步下载**: `asyncio + aiohttp` 实现高效并发下载
- **速率控制**: 令牌桶算法，避免触发反爬
- **断点续传**: 记录下载进度，支持中断后继续
- **多格式导出**: 支持 `.txt`、`.md`、`.epub`、`.mobi` 四种格式
- **智能分类**: 自动识别正文、番外、作者说
- **内容清洗**: 自动移除广告、水印、推广语
- **认证支持**: 支持 Cookie/z_c0 token 认证
- **User-Agent 轮换**: 模拟移动端请求
- **批量下载**: 支持从文件读取多个URL批量下载
- **更新检测**: 自动检测章节更新，增量下载
- **书架管理**: 本地书架，管理已下载书籍
- **Cookie自动读取**: 自动从浏览器获取Cookie，免手动导出
- **插件化架构**: 通过 pluggy 实现数据源/导出器/钩子的 SPI 扩展

### 端到端形态
- **CLI**: `zhihu-downloader download/shelf/serve` 命令行
- **HTTP API**: FastAPI + OpenAPI 3.1 + RFC 7807 错误模型
- **Web 前端**: React 18 + TypeScript + Tailwind + Radix UI（现代化 SPA）
- **桌面端**: Tauri 2.x + Rust 后端（跨平台：Windows / macOS / Linux）

## 技术栈

### 后端 (Python 3.10+)
- **Web 框架**: FastAPI + Uvicorn（ASGI）
- **数据校验**: Pydantic v2（严格模式）
- **ORM**: SQLAlchemy 2.x（async）
- **任务队列**: NATS JetStream
- **插件系统**: pluggy
- **可观测性**: OpenTelemetry
- **认证**: JWT + API Key + 限流（令牌桶）
- **CLI**: Click
- **打包**: PyInstaller
- **包管理**: uv

### 前端 (React 18)
- **状态管理**: Zustand（客户端状态）+ TanStack Query（服务端状态）
- **UI 库**: Radix UI（无样式可访问组件）+ Lucide Icons
- **样式**: Tailwind CSS 3.4 + CSS 变量主题（亮/暗）
- **国际化**: i18next + react-i18next（中/英）
- **构建**: Vite 6（路径别名、代码分割、代理）
- **通知**: Sonner

### 桌面端 (Tauri 2.x)
- **Rust 后端**: 进程管理、托盘菜单、插件系统
- **Webview**: 嵌入前端 Web 资源
- **Tauri 插件**: dialog / fs / shell / notification / store / os / log
- **跨平台打包**: NSIS / MSI / DEB / AppImage / DMG

## 快速开始

### 环境要求

- **Python** 3.10+
- **Node.js** 18+
- **Rust** 1.77+（仅桌面端）
- **uv** 包管理器

### 一键脚本

```bash
# 1. 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 同时启动后端和前端（推荐）
./scripts/dev.sh

# 或分别启动
./scripts/dev.sh --backend
./scripts/dev.sh --frontend
```

启动后访问：
- 前端: <http://localhost:5173>
- 后端 API: <http://localhost:3000/docs>
- 健康检查: <http://localhost:3000/api/health>

### 手动启动

#### 后端

```bash
# 安装依赖
uv sync

# 启动 API 服务
uv run zhihu-downloader serve --host 0.0.0.0 --port 3000

# 或开发模式（热重载）
uv run zhihu-downloader serve --reload
```

#### 前端

```bash
cd web
npm install          # 安装依赖
npm run dev          # 开发模式（http://localhost:5173）
npm run build        # 生产构建（输出到 dist/）
npm run type-check   # TypeScript 类型检查
```

#### 桌面端

```bash
cd web
npm install

# 首次需要先生成图标
python3 ../scripts/generate_tauri_icons.py

# 开发模式（自动启动 Vite + Rust）
npm run tauri:dev

# 构建当前平台发布包
./scripts/build-desktop.sh

# 指定平台
./scripts/build-desktop.sh --linux
./scripts/build-desktop.sh --windows
./scripts/build-desktop.sh --macos
```

## 项目结构

```
zhihu-salt-novel-downloader/
├── src/zhihu_downloader/        # Python 后端
│   ├── api/                     # FastAPI 应用层
│   │   ├── app.py               # 应用工厂（中间件、路由、异常处理）
│   │   ├── dependencies.py      # 依赖注入
│   │   ├── errors.py            # RFC 7807 Problem 异常
│   │   ├── schemas.py           # Pydantic 契约（前后端对齐）
│   │   ├── tasks.py             # 任务管理与 SSE 事件流
│   │   └── routers/             # 路由模块（auth/books/download/...）
│   ├── auth/                    # 认证模块
│   │   ├── jwt_auth.py          # JWT 签发与校验
│   │   ├── api_key_manager.py   # API Key 管理
│   │   ├── cookie_manager.py    # Cookie 装载
│   │   ├── browser_cookie.py    # 浏览器自动读取
│   │   ├── rate_limiter.py      # 令牌桶限流
│   │   └── user_agent.py        # UA 轮换
│   ├── core/                    # 核心下载器
│   │   ├── downloader.py        # 异步下载主循环
│   │   ├── rate_limiter.py      # 限流
│   │   ├── circuit_breaker.py   # 熔断
│   │   ├── cache.py             # 响应缓存
│   │   ├── proxy_pool.py        # 代理池
│   │   └── ua_rotator.py        # UA 轮换
│   ├── parsers/                 # 内容解析
│   │   ├── article_parser.py
│   │   └── chapter_classifier.py
│   ├── exporters/               # 多格式导出
│   │   ├── base_exporter.py     # 抽象基类
│   │   ├── txt_exporter.py
│   │   ├── md_exporter.py
│   │   ├── epub_exporter.py
│   │   └── mobi_exporter.py
│   ├── plugins/                 # 插件系统（pluggy SPI）
│   │   ├── protocol.py          # 插件协议
│   │   ├── manager.py           # 插件管理器
│   │   ├── specs.py             # 插件规范
│   │   ├── sources/             # 数据源插件
│   │   └── exporters/           # 导出器插件
│   ├── services/                # 业务编排层
│   │   ├── download_service.py  # 下载编排
│   │   ├── shelf_service.py     # 书架业务
│   │   └── events.py            # 进度事件模型
│   ├── shelf/                   # 书架存储
│   │   └── shelf_manager.py
│   ├── infra/                   # 基础设施
│   │   ├── database.py          # 异步 SQLAlchemy
│   │   ├── models.py            # ORM 模型
│   │   └── repository.py        # 仓储模式
│   ├── observability/           # 可观测性
│   │   ├── otel_config.py       # OTel 配置
│   │   ├── tracing.py           # 链路追踪
│   │   └── metrics.py           # 指标
│   ├── tasks/                   # 任务编排
│   │   ├── nats_queue.py        # NATS JetStream
│   │   ├── state_machine.py     # 状态机
│   │   └── task_manager.py      # 任务管理
│   ├── utils/                   # 工具
│   │   ├── config.py            # 配置
│   │   ├── logging_setup.py     # 日志
│   │   ├── retry.py             # 重试
│   │   ├── security.py          # 安全工具
│   │   ├── content_cleaner.py   # 内容清洗
│   │   ├── checkpoint.py        # 断点
│   │   └── trace_context.py     # TraceId
│   └── cli.py                   # CLI 入口（含 serve 子命令）
│
├── web/                         # 前端 + 桌面端
│   ├── src/
│   │   ├── api/                 # REST 客户端
│   │   │   ├── client.ts        # axios 封装（TraceId/Token 注入）
│   │   │   ├── auth.ts          # 认证 API
│   │   │   ├── shelf.ts         # 书架 API
│   │   │   ├── download.ts      # 下载 API（含 SSE）
│   │   │   └── plugins.ts       # 插件 API
│   │   ├── components/          # 组件
│   │   │   ├── ui/              # 基础 UI（Button/Card/Dialog/...）
│   │   │   ├── Layout.tsx       # 主布局（侧边栏）
│   │   │   └── ErrorBoundary.tsx
│   │   ├── hooks/               # 自定义 Hook
│   │   │   ├── queries.ts       # TanStack Query
│   │   │   ├── useDownloadProgress.ts  # SSE 进度
│   │   │   ├── useTheme.ts      # 主题切换
│   │   │   └── useTauri.ts      # Tauri 环境检测
│   │   ├── store/               # Zustand
│   │   │   ├── authStore.ts     # 认证
│   │   │   └── appStore.ts      # 应用设置
│   │   ├── pages/               # 页面
│   │   │   ├── HomePage.tsx
│   │   │   ├── DownloadPage.tsx
│   │   │   ├── LibraryPage.tsx
│   │   │   ├── TasksPage.tsx
│   │   │   └── SettingsPage.tsx
│   │   ├── lib/                 # 工具
│   │   │   ├── utils.ts         # 通用工具
│   │   │   ├── queryClient.ts   # TanStack Query 配置
│   │   │   └── tauri.ts         # Tauri API 封装
│   │   ├── i18n/                # 国际化
│   │   ├── types/               # TypeScript 类型
│   │   ├── App.tsx              # 应用入口
│   │   └── main.tsx             # 渲染入口
│   ├── src-tauri/               # Tauri 桌面端 Rust 后端
│   │   ├── src/
│   │   │   ├── main.rs          # 入口
│   │   │   ├── lib.rs           # 应用主体
│   │   │   ├── commands.rs      # Tauri 命令
│   │   │   ├── backend.rs       # 后端进程管理
│   │   │   └── error.rs         # 错误处理
│   │   ├── capabilities/        # Tauri 权限
│   │   ├── icons/               # 应用图标
│   │   ├── tauri.conf.json      # Tauri 配置
│   │   └── Cargo.toml
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   └── package.json
│
├── scripts/                     # 辅助脚本
│   ├── dev.sh                   # 启动开发环境
│   ├── build-desktop.sh         # 打包桌面端
│   └── generate_tauri_icons.py  # 生成图标
│
├── docs/                        # 设计文档
├── pyproject.toml
├── uv.lock
└── README.md
```

## API 概览

| 模块 | 端点 | 说明 |
|------|------|------|
| 健康 | `GET /api/health` | 健康检查 |
| 认证 | `POST /api/auth/login` | 登录 |
| 认证 | `POST /api/auth/register` | 注册 |
| 认证 | `POST /api/auth/refresh` | 刷新 token |
| 用户 | `GET /api/users/me` | 当前用户 |
| 下载 | `POST /api/downloads` | 启动下载 |
| 下载 | `GET /api/downloads` | 任务列表 |
| 下载 | `GET /api/downloads/{id}` | 任务状态 |
| 下载 | `GET /api/downloads/{id}/events` | SSE 进度流 |
| 下载 | `POST /api/downloads/{id}/cancel` | 取消 |
| 书架 | `GET /api/shelves` | 书籍列表 |
| 书架 | `POST /api/shelves` | 添加书籍 |
| 书架 | `DELETE /api/shelves/{url}` | 删除 |
| 书架 | `GET /api/shelves/stats` | 统计 |
| 插件 | `GET /api/plugins` | 插件列表 |
| 插件 | `POST /api/plugins` | 安装 |
| 插件 | `DELETE /api/plugins/{id}` | 卸载 |

完整 OpenAPI 文档: <http://localhost:3000/docs>

## 开发命令

### 后端

```bash
# CLI 子命令
uv run zhihu-downloader download --url <URL> --format md
uv run zhihu-downloader download --batch-file urls.txt
uv run zhihu-downloader download --url <URL> --auto-cookie
uv run zhihu-downloader shelf --list
uv run zhihu-downloader shelf --add <URL>
uv run zhihu-downloader serve --port 3000 --reload

# 测试与质量
uv run pytest                       # 单元测试
uv run ruff check .                 # Lint
uv run mypy src/                    # 类型检查
```

### 前端

```bash
cd web

npm run dev          # 开发服务器
npm run build        # 生产构建
npm run preview      # 预览生产构建
npm run type-check   # TypeScript 类型检查
npm run lint         # ESLint
npm run format       # Prettier 格式化
```

### 桌面端

```bash
cd web

# 开发模式
npm run tauri:dev

# 构建当前平台
./scripts/build-desktop.sh

# 构建特定平台
./scripts/build-desktop.sh --linux
./scripts/build-desktop.sh --macos
./scripts/build-desktop.sh --windows
```

## 使用示例

### 1. CLI 下载

```bash
# 单本下载
uv run zhihu-downloader download \
  --url "https://www.zhihu.com/market/book/12345" \
  --format epub \
  --output-dir ./books

# 批量下载（文件每行一个 URL）
echo "https://www.zhihu.com/market/book/12345" > urls.txt
echo "https://www.zhihu.com/market/book/67890" >> urls.txt
uv run zhihu-downloader download --batch-file urls.txt

# 自动从浏览器读取 Cookie
uv run zhihu-downloader download --url <URL> --auto-cookie

# 断点续传
uv run zhihu-downloader download --url <URL> --resume
```

### 2. Web 界面

1. 启动后端：`./scripts/dev.sh --backend`
2. 启动前端：`./scripts/dev.sh --frontend`
3. 访问 <http://localhost:5173>
4. 在「下载」页粘贴小说 URL，选择格式后点击开始
5. 实时查看 SSE 推送的下载进度
6. 下载完成后在「书架」页管理书籍

### 3. 桌面端

1. 启动开发模式：`cd web && npm run tauri:dev`
2. 应用窗口自动打开，无需手动启动后端（Rust 端自动 spawn）
3. 生产构建：`./scripts/build-desktop.sh`
4. 产物路径：`web/src-tauri/target/release/bundle/`

## 架构亮点

### 后端
- **依赖倒置**: Service 层依赖 Protocol 接口，Downloader/Exporter/Sorter 通过 SPI 解耦
- **开闭原则**: 新增数据源/导出器只需注册插件，主流程不变
- **可观测性**: TraceId 全链路透传 + OpenTelemetry 指标
- **高可用**: 熔断器 + 限流 + 重试 + 多实例一致状态
- **可扩展**: NATS JetStream 任务队列，水平扩展 Worker

### 前端
- **关注点分离**: API 层（client.ts）+ 状态层（store）+ 视图层（pages）
- **错误边界**: ErrorBoundary 捕获组件错误
- **类型契约**: TypeScript 接口与后端 Pydantic 严格对齐
- **i18n**: 中英文 200+ 翻译键，自动检测浏览器语言
- **主题系统**: 亮色/暗色/跟随系统，CSS 变量驱动
- **响应式**: Tailwind 断点适配桌面/平板/手机

### 桌面端
- **进程管理**: Rust 端 spawn / kill 后端子进程
- **优雅退出**: 关闭主窗口仅隐藏到托盘
- **能力隔离**: Tauri capabilities 细粒度权限控制
- **存储抽象**: Tauri Store + localStorage 双重 fallback

## 合规声明

> ⚠️ **重要提示**：
>
> 本工具仅限用于已购买内容的**个人离线阅读**。
>
> 请勿使用本工具进行任何形式的：
> - 内容分发
> - 商业使用
> - 侵权传播
>
> 使用本工具即表示您同意承担相关法律责任。

## License

MIT License
