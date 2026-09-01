# 路线图

## v5.0（本次重构交付）
- 单文件应用：CLI 内核 + 本地 Web UI（SSE 章节级进度）
- 断点续传 + 指数退避重试 + 限速内并发
- 扫码登录 / Cookie 导入（JSON/Netscape/原始串）/ 浏览器 Cookie（可选 extra）
- doctor：d_c0 感知 + 签名自检（区分"Cookie 失效"与"签名轮换"）+ 新版本提示
- 结构化解析（标题层级/列表/引用/图片）+ 广告清洗 + 番外/作者说分类
- 导出：txt / md（保留结构）/ epub（封面+两级 TOC+稳定 identifier+内嵌 CSS）
- 书架 + 追更（增量下载新章节，重导出整本）
- 安全：默认 127.0.0.1、URL 白名单（SSRF）、任务 LRU、cookies 0600、文件名防穿越
- 发布：单 tag → 测试门禁 → Win/Linux/macOS 三平台包 + SHA256SUMS

## v5.1
- **签名常量热补丁通道**：远程 JSON 覆盖 signature 硬编码常量（模式校验+本地兜底+审计日志），把"失效窗口"从数天压到分钟级
- **字体加密解码**：盐选部分页面用自定义字体映射（竞品最高频差评"乱码"），解析 TTF cmap 还原字符
- 签名失效自动上报通道（匿名、可选）：doctor 检测到签名层失败时提示一键反馈
- **书架文件下载端点**（/api/shelf/{id}/files/{name}）：需先设计防穿越方案（shelf.json 用户可编辑，不能直接按其路径发文件；候选=登记时哈希/复用任务白名单），v5.0 书架文件为只读展示
- **章节图片下载与本地回填**（v5.0 评审已知缺口：EPUB 内嵌因无下载层恒走 alt 降级；设计 = fetcher 图片缓存 + Block.src 回填，失败维持降级现状）
- mobi 导出（走本机 Calibre ebook-convert，不内置转换链）
- 定时追更（gui 模式内置调度器）
- **断点目录统一推导**（主审 round56 分流）：CLI prune 走 `<output>/.zhihu_state`、server DELETE 走 `<output>/.zhihu_tasks/<hash>/.zhihu_state`，跨路径移除各留残留（纯磁盘垃圾，不影响正确性与自愈）；engine 导出 `state_dir_for_book(output_dir, url)` 公共推导，两侧 prune 遍历候选目录
- **doctor 磁盘统计盲区**（D1 发现）：现只统计默认输出目录，CLI `-o` 别处的缓存不可见；补 `--output-dir` 或遍历 shelf 登记分目录汇总
- **resolve_book prefetched 出参**（I3 发现，v5.0 已裁接受双抓现状并有用例钉成本）：单篇链接走标准通路正文页被抓 2 次，根治 = 页面缓存随 meta 传出

## v5.2+
- 设备送达向导文档化：Kindle（USB/Send-to-Kindle 海外邮箱）、Kobo、Boox、微信读书导入指引
- Markdown 导出对 AI/拆文工作流优化（front-matter、章节锚点）；MCP Server 评估
- 多书批量下载队列 UI
- i18n（en）

## 永不做（合规红线，源自判例研究）
- 绕过付费墙 / 未购内容下载
- 逆向 APP 端 mst/xsec 设备签名抓"仅 APP 内阅读"内容
- 代理池 / 多账号轮换 / 对抗风控
- 内置资源库、搜索盗版源、任何分发/营利功能
- 去除版权声明/水印用于传播