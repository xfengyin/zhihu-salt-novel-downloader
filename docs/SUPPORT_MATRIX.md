# 支持范围与限制（Support Matrix）

本文档列出 zhihu-salt-novel-downloader 对各类型知乎 URL 的支持状态、说明与替代方案，
用于解决 issue #2 中「仅 APP 内阅读」内容的文档与体验缺口。

URL 分类逻辑与运行时提示实现于 `src/zhihu_downloader/plugins/sources/zhihu_salt.py`，
运行时会在终端 / SSE 进度流中给出友好提示（见
`src/zhihu_downloader/services/download_service.py` 的 `_emit_url_hint`）。

## 状态图例

| 状态 | 含义 |
|------|------|
| ✅ 支持 | 网页端可直接解析并下载正文 |
| ⚠️ 有条件支持 | 需要有效 Cookie 或对应网页入口，否则可能为空或触发反爬 |
| ❌ 暂不支持 | 需要移动端签名（`mst`/`xsec`），网页端无合法入口 |

## URL 类型 × 支持状态

| URL 类型 | 示例 | 支持状态 | 说明 | 替代方案 |
|----------|------|----------|------|----------|
| 公开回答 | `https://www.zhihu.com/question/<id>/answer/<id>` | ✅ 支持 | 默认最佳支持，无需付费 Cookie，可直接解析 RichText 正文 | — |
| 专栏文章 | `https://zhuanlan.zhihu.com/p/<id>` | ✅ 支持 | 公开专栏文章，直接解析正文 | — |
| 盐选专栏（市场付费） | `https://www.zhihu.com/market/paid_column/<col_id>` | ⚠️ 有条件支持 | 下载整本书目录，需 Cookie 含有效 `z_c0` | 更新 Cookie（见下文） |
| 盐选单章节 | `https://www.zhihu.com/market/paid_column/<col_id>/section/<sec_id>` | ⚠️ 有条件支持 | 仅下载该章节，不获取全书目录；需有效 `z_c0` | 改用专栏整书 URL |
| 移动端付费专栏（非仅 APP 形式） | `https://story.zhihu.com/manuscript/paid_column/<col_id>` | ⚠️ 如可用 | 若同一内容在网页端有对应 market URL 且可读，则可用 | 优先替换为 `www.zhihu.com/market/paid_column/...` |
| 移动端单章节（非仅 APP 形式） | `https://story.zhihu.com/manuscript/paid_column/<col_id>/<sec_id>` | ⚠️ 如可用 | 路径不带 `/section/` 关键词；网页端可读则可用 | 优先替换为 market section URL |
| 移动端付费专栏（仅 APP 内阅读） | `https://story.zhihu.com/manuscript/paid_column/<col_id>` | ❌ 暂不支持 | 需 APP 级 `mst`/`xsec` 签名与设备信息，网页端无合法入口 | 见下方「替代方案」 |
| 移动端单章节（仅 APP 内阅读） | `https://story.zhihu.com/manuscript/paid_column/<col_id>/<sec_id>` | ❌ 暂不支持 | 同上 | 见下方「替代方案」 |
| 非知乎系 URL | `https://example.com/...` | ❌ 不支持 | 不属于知乎系域名，无法解析 | 检查 URL 是否正确 |

> **注意**：`story.zhihu.com/manuscript/paid_column/...` 链接本身并不直接等同于「仅 APP 内阅读」。
> 同一内容可能存在两种形态：
> 1. **非仅 APP 形式** —— 在网页端有对应的 market URL 且正文可读，本工具可用；
> 2. **仅 APP 内阅读形式** —— 只能在知乎 APP 内打开，依赖移动端 API 签名，本工具暂不支持。
>
> 当前版本对 `story.zhihu.com` 链接统一判定为「仅 APP 内阅读」并给出提示，
> 因此建议优先改用网页版 market URL 以获得最佳体验。

## 什么是「仅 APP 内阅读」

「仅 APP 内阅读」是指内容没有公开的网页端正文入口，只能通过知乎移动端 App 打开。
其接口请求需要 `mst` / `xsec` 等签名参数以及设备信息（如 `x-zse-96`、`x-zse-93` 等）。
这些签名由 App 内计算生成，网页端没有合法入口，因此当前版本无法直接下载正文。

## 替代方案

### ① 优先找同一内容的 web market URL

「仅 APP 内阅读」内容通常也有对应的网页版盐选入口：

- 在知乎网页版搜索书名 / 章节标题；
- 将 `story.zhihu.com/manuscript/paid_column/<col_id>` 替换为
  `https://www.zhihu.com/market/paid_column/<col_id>`；
- 章节同理：`.../manuscript/paid_column/<col_id>/<sec_id>` →
  `https://www.zhihu.com/market/paid_column/<col_id>/section/<sec_id>`；
- 若网页端能正常打开并看到正文，即可用本工具下载。

### ② 使用 APP 内的人工方式

若确实没有网页端入口，可退而求其次：

- 使用知乎 APP 的「缓存 / 离线」功能保存到本地；
- 截图保存章节；
- 手动复制正文到本地文档；
- 再配合本工具的导出 / 书架功能整理。

### ③ 网页可读但有 zse-ck 反爬

若网页端正文可读，但请求被知乎 `zse-ck`（配合 `x-zse-96`）反爬拦截：

1. 在浏览器中重新登录知乎，导出最新 Cookie（确保包含 `z_c0`，以及可用的 `zse_ck`）；
2. 使用 `--auto-cookie` 自动从浏览器读取，或手动更新 Cookie 文件；
3. 参考仓库中新增的 `x-zse-96` 签名模块（见 issue #4 对应实现）重新生成请求头。

## 快速判断流程

```text
拿到 URL
  ├─ 是知乎系域名？
  │    └─ 否 → ❌ 不支持，检查 URL 是否正确
  └─ 是
       ├─ www.zhihu.com/question/.../answer/...  → ✅ 直接下载
       ├─ zhuanlan.zhihu.com/p/...               → ✅ 直接下载
       ├─ www.zhihu.com/market/paid_column/...   → ⚠️ 需有效 z_c0，可直接下载
       ├─ story.zhihu.com/manuscript/...         → 先找网页 market URL
       │     ├─ 找到且网页可读      → ✅ 用 market URL 下载
       │     └─ 找不到（仅 APP 内阅读）→ ❌ 用替代方案 ①/②
       └─ 其他 → 参考上方支持矩阵
```

## 相关文件

- URL 分类与提示逻辑：`src/zhihu_downloader/plugins/sources/zhihu_salt.py`
- 提示文案：`src/zhihu_downloader/services/download_service.py`（`_emit_url_hint`）
- 章节 ID 解析：`src/zhihu_downloader/parsers/article_parser.py`
- 单元测试：`tests/test_sources.py`
