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

## 安装

### 方式一：pip install

```bash
pip install -e .
```

### 方式二：Docker

```bash
docker build -t zhihu-downloader .
docker run -v ./output:/app/output zhihu-downloader --url <URL>
```

## 快速开始

### 1. 获取认证 Cookie

使用 Chrome 插件（如 EditThisCookie）导出 Cookie 为 JSON 文件：

```json
[
  {"name": "z_c0", "value": "your_token_here"},
  {"name": "q_c1", "value": "..."}
]
```

### 2. 基本用法

```bash
# 查看帮助
python cli.py --help

# 列出章节（不下载）
python cli.py --url https://www.zhihu.com/market/xxx --list-only

# 下载为 Markdown
python cli.py --url https://www.zhihu.com/market/xxx \
  --cookie-file=cookies.json \
  --format=md

# 下载为 EPUB
python cli.py --url https://www.zhihu.com/market/xxx \
  --cookie-file=cookies.json \
  --format=epub

# 断点续传
python cli.py --url https://www.zhihu.com/market/xxx \
  --cookie-file=cookies.json \
  --resume

# 自定义并发数
python cli.py --url https://www.zhihu.com/market/xxx \
  --max-concurrent=5 \
  --rate-limit=3
```

### 3. 配置文件

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
python cli.py --url <URL> --config config.yaml
```

## 项目结构

```
zhihu-salt-novel-downloader/
├── core/              # 核心下载引擎
│   ├── downloader.py  # 异步并发下载器
│   ├── cache.py       # 响应缓存
│   └── rate_limiter.py # 速率限制器
├── parsers/           # 内容解析
│   ├── article_parser.py
│   └── chapter_classifier.py
├── exporters/        # 多格式导出
│   ├── txt_exporter.py
│   ├── md_exporter.py
│   └── epub_exporter.py
├── auth/             # 认证模块
│   ├── cookie_manager.py
│   └── user_agent.py
├── utils/            # 工具类
│   ├── config.py
│   ├── content_cleaner.py
│   ├── checkpoint.py
│   └── retry.py
├── cli.py            # 命令行入口
├── config.yaml       # 配置文件
└── requirements.txt  # 依赖清单
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

## 技术栈

- Python 3.9+
- asyncio + aiohttp
- BeautifulSoup4
- Click (CLI)
- ebooklib (EPUB)
- PyYAML

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest tests/ -v

# 代码格式化
black .
isort .
```

## License

MIT License
