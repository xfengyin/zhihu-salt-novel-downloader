# zhihu-salt-novel-downloader

知乎盐选小说下载器 - 异步并发下载 + 多格式导出 + 断点续传

## 功能特性

- **异步下载**: `asyncio + aiohttp` 实现高效并发下载
- **速率控制**: 令牌桶算法，避免触发反爬
- **断点续传**: 记录下载进度，支持中断后继续
- **多格式导出**: 支持 `.txt`、`.md`、`.epub` 三种格式
- **智能分类**: 自动识别正文、番外、作者说
- **内容清洗**: 自动移除广告、水印、推广语
- **认证支持**: 支持 Cookie/z_c0 token 认证
- **User-Agent 轮换**: 模拟移动端请求
- **Web界面**: 提供现代化的 Web UI

## 技术栈

### 后端 (Python)
- Python 3.10+
- asyncio + aiohttp
- BeautifulSoup4
- Click (CLI)
- ebooklib (EPUB)
- PyYAML
- FastAPI (Web API)
- Pydantic

### 前端 (React)
- React 18 + TypeScript
- Tailwind CSS 3.4
- shadcn/ui + Radix UI
- Vite 6
- Lucide Icons

### 工具
- **uv**: 现代化 Python 包管理器
- **ruff**: 代码检查与格式化
- **pytest**: 单元测试

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- uv 包管理器

### 安装 uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 或者使用 pip
pip install uv
```

### 后端开发环境安装

```bash
# 克隆项目
git clone https://github.com/xfengyin/zhihu-salt-novel-downloader.git
cd zhihu-salt-novel-downloader

# 使用 uv 安装所有依赖（含开发依赖）
uv sync --all-extras

# 激活虚拟环境
source .venv/bin/activate  # Linux/macOS
# 或
.venv\Scripts\activate    # Windows

# 安装预提交钩子（可选）
uv run pre-commit install
```

### 前端开发环境安装

```bash
cd web

# 使用 npm 安装依赖
npm install

# 或使用 pnpm
pnpm install

# 或使用 yarn
yarn install
```

## 开发命令

### 后端

```bash
# 运行 CLI
uv run zhihu-download --help
uv run zhihu-download --url <URL> --format md

# 运行测试
uv run pytest tests/ -v

# 代码格式化
uv run ruff check --fix .
uv run black .

# 类型检查
uv run mypy src/

# 运行 FastAPI 服务（Web 模式）
uv run uvicorn src.zhihu_downloader.api:app --reload --port 8000
```

### 前端

```bash
cd web

# 开发模式
npm run dev
# 访问 http://localhost:3000

# 构建生产版本
npm run build

# 预览生产版本
npm run preview

# 代码检查
npm run lint
```

## 项目结构

```
zhihu-salt-novel-downloader/
├── src/zhihu_downloader/     # Python 源代码
│   ├── core/                 # 核心模块
│   │   ├── downloader.py     # 异步下载器
│   │   ├── cache.py          # 响应缓存
│   │   └── rate_limiter.py   # 速率限制器
│   ├── parsers/              # 内容解析
│   │   ├── article_parser.py
│   │   └── chapter_classifier.py
│   ├── exporters/            # 多格式导出
│   │   ├── base_exporter.py
│   │   ├── txt_exporter.py
│   │   ├── md_exporter.py
│   │   └── epub_exporter.py
│   ├── auth/                 # 认证模块
│   │   └── cookie_manager.py
│   ├── utils/                # 工具类
│   │   ├── config.py
│   │   ├── checkpoint.py
│   │   └── content_cleaner.py
│   └── cli.py                # CLI 入口
├── web/                      # 前端源码
│   ├── src/
│   │   ├── components/       # React 组件
│   │   │   └── ui/           # shadcn/ui 组件
│   │   ├── lib/              # 工具函数
│   │   └── types/            # TypeScript 类型
│   └── ...
├── tests/                    # 测试用例
├── pyproject.toml            # Python 项目配置
├── uv.lock                   # 依赖锁定文件
└── DESIGN.md                 # 设计规范文档
```

## 使用方法

### 1. 获取认证 Cookie

使用 Chrome 插件（如 EditThisCookie）导出 Cookie 为 JSON 文件：

```json
[
  {"name": "z_c0", "value": "your_token_here"},
  {"name": "q_c1", "value": "..."}
]
```

### 2. CLI 使用

```bash
# 查看帮助
uv run zhihu-download --help

# 列出章节（不下载）
uv run zhihu-download --url https://www.zhihu.com/market/xxx --list-only

# 下载为 Markdown
uv run zhihu-download --url https://www.zhihu.com/market/xxx \
  --cookie-file=cookies.json \
  --format=md

# 下载为 EPUB
uv run zhihu-download --url https://www.zhihu.com/market/xxx \
  --cookie-file=cookies.json \
  --format=epub

# 断点续传
uv run zhihu-download --url https://www.zhihu.com/market/xxx \
  --cookie-file=cookies.json \
  --resume

# 自定义并发数
uv run zhihu-download --url https://www.zhihu.com/market/xxx \
  --max-concurrent=5 \
  --rate-limit=3
```

### 3. Web 界面使用

```bash
# 启动后端 API 服务
cd zhihu-salt-novel-downloader
uv run uvicorn src.zhihu_downloader.api:app --reload --port 8000

# 启动前端开发服务器
cd web
npm run dev
```

然后访问 http://localhost:3000

### 4. 配置文件

创建 `config.yaml`:

```yaml
download:
  max_concurrent: 3
  rate_limit: 2.0
  max_retries: 3

output:
  output_dir: "./output"
  default_format: "md"

auth:
  cookie_file: "./cookies.json"
```

然后运行:

```bash
uv run zhihu-download --url <URL> --config config.yaml
```

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

## 开发指南

### 代码规范

项目使用以下工具确保代码质量：

```bash
# 代码格式化 (ruff + black)
uv run ruff check --fix .

# 导入排序
uv run isort .

# 类型检查
uv run mypy src/
```

### 测试

```bash
# 运行所有测试
uv run pytest

# 运行测试并生成覆盖率报告
uv run pytest --cov=src/zhihu_downloader --cov-report=html

# 查看覆盖率报告
open htmlcov/index.html
```

### 提交规范

本项目使用 Conventional Commits 规范：

```
feat: 添加新功能
fix: 修复 bug
docs: 文档更新
style: 代码格式调整
refactor: 代码重构
test: 测试相关
chore: 构建/工具相关
```

## License

MIT License
