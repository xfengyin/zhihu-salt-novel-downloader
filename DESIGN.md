# 知乎盐选小说下载器 - 设计规范文档

## 1. 项目概述

### 1.1 项目定位
知乎盐选小说下载器是一款面向个人用户的内容获取工具，支持异步并发下载、多格式导出和断点续传功能。

### 1.2 设计理念
- **极简高效**: 三个步骤完成小说下载
- **清晰直观**: 状态实时可见，操作反馈明确
- **专业可靠**: 企业级架构，稳定性和可扩展性并重

---

## 2. 设计语言

### 2.1 美学方向
采用 **Modern Productivity** 风格 - 融合极简主义与功能性设计，强调内容层次和操作效率。

### 2.2 色彩系统

#### 主色调 (Primary)
```css
--primary: hsl(221.2 83.2% 53.3%);  /* #4F6BED - 信任蓝 */
--primary-light: hsl(217.2 91.2% 59.8%);  /* 暗色模式 */
```

#### 功能色
```css
--success: hsl(142 76% 36%);      /* #16A34A - 完成状态 */
--warning: hsl(38 92% 50%);       /* #F59E0B - 警告提示 */
--destructive: hsl(0 84.2% 60.2%); /* #EF4444 - 错误状态 */
--info: hsl(199 89% 48%);         /* #0EA5E9 - 信息提示 */
```

#### 中性色
```css
--background: hsl(0 0% 100%);      /* 背景色 - 亮色 */
--foreground: hsl(222.2 84% 4.9%); /* 前景色 - 深灰 */
--muted: hsl(210 40% 96.1%);      /* 辅助背景 */
--muted-foreground: hsl(215.4 16.3% 46.9%); /* 次要文字 */
--border: hsl(214.3 31.8% 91.4%); /* 边框色 */
```

#### 暗色模式
```css
--background: hsl(222.2 84% 4.9%);  /* #0F172A */
--foreground: hsl(210 40% 98%);    /* #F8FAFC */
--primary: hsl(217.2 91.2% 59.8%); /* #3B82F6 */
```

### 2.3 字体系统

#### 字体栈
```css
--font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
--font-mono: 'JetBrains Mono', 'Fira Code', monospace;
```

#### 字号规范
| 用途 | 字号 | 行高 | 字重 |
|------|------|------|------|
| 标题 H1 | 32px | 1.2 | 700 |
| 标题 H2 | 24px | 1.3 | 600 |
| 标题 H3 | 20px | 1.4 | 600 |
| 正文 | 16px | 1.5 | 400 |
| 辅助文字 | 14px | 1.5 | 400 |
| 标签/小字 | 12px | 1.4 | 500 |

### 2.4 间距系统
基于 4px 网格系统：
- `xs`: 4px
- `sm`: 8px
- `md`: 16px
- `lg`: 24px
- `xl`: 32px
- `2xl`: 48px

### 2.5 圆角与阴影
```css
--radius-sm: 6px;    /* 小按钮、输入框 */
--radius-md: 8px;    /* 卡片、面板 */
--radius-lg: 12px;   /* 模态框、大卡片 */
--radius-xl: 16px;   /* 特殊容器 */

--shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
--shadow-md: 0 4px 6px -1px rgba(0,0,0,0.1);
--shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.1);
```

---

## 3. 组件规范

### 3.1 按钮 (Button)

#### 变体 (Variant)
| 变体 | 用途 | 样式描述 |
|------|------|----------|
| `default` | 主要操作 | 蓝色实心，轻微阴影，hover加深10% |
| `destructive` | 危险操作 | 红色实心 |
| `outline` | 次要操作 | 透明背景，2px边框 |
| `ghost` | 辅助操作 | 透明背景，hover显示背景色 |
| `link` | 文字链接 | 下划线 |

#### 尺寸 (Size)
| 尺寸 | 高度 | 内边距 | 字号 |
|------|------|--------|------|
| `sm` | 36px | 8px 12px | 14px |
| `md` | 40px | 10px 16px | 14px |
| `lg` | 44px | 12px 24px | 16px |
| `icon` | 40px | 0 | 14px |

#### 状态
- **Default**: 正常状态
- **Hover**: 背景加深，cursor: pointer
- **Active**: scale(0.98)，轻微下沉
- **Disabled**: opacity: 0.5，cursor: not-allowed
- **Loading**: 显示旋转图标

### 3.2 输入框 (Input)

#### 样式
- 高度: 40px
- 边框: 1px solid var(--border)
- 圆角: var(--radius-sm)
- 过渡: 所有属性 200ms ease

#### 状态
- **Default**: 灰色边框
- **Focus**: 蓝色边框，ring阴影
- **Error**: 红色边框，红色ring
- **Disabled**: 降低透明度，灰色背景

### 3.3 卡片 (Card)

#### 结构
```html
<Card>
  <CardHeader>
    <CardTitle>标题</CardTitle>
    <CardDescription>描述文字</CardDescription>
  </CardHeader>
  <CardContent>内容区域</CardContent>
  <CardFooter>底部操作</CardFooter>
</Card>
```

#### 样式
- 背景: var(--card)
- 边框: 1px solid var(--border)
- 圆角: var(--radius-lg)
- 阴影: var(--shadow-sm)
- Hover: 阴影加深

### 3.4 开关 (Switch)

#### 样式
- 宽度: 44px
- 高度: 24px
- 圆角: 全圆角
- 轨道: 未选中灰色，选中蓝色
- 圆点: 20px，白色，阴影

#### 动画
- 状态切换: transform 200ms cubic-bezier

### 3.5 进度条 (Progress)

#### 样式
- 高度: 16px
- 背景: var(--muted)
- 进度条: var(--primary)，渐变动画
- 圆角: 全圆角

#### 动画
- 进度变化: width 300ms ease-out

### 3.6 下拉选择器 (Select)

#### 样式
- 触发器: 与Input样式一致
- 下拉面板: 白色背景，圆角，阴影
- 选项: hover高亮，圆角
- 选中: 左侧显示Check图标

---

## 4. 页面布局

### 4.1 整体结构
```
┌─────────────────────────────────────────────────┐
│  Header (固定顶部)                               │
│  Logo + 标题    |    下载  设置  按钮组           │
├─────────────────────────────────────────────────┤
│  Main Content                                   │
│  ┌───────────────────────┐ ┌─────────────────┐  │
│  │                       │ │  Quick Start    │  │
│  │   Active Panel        │ │  Card           │  │
│  │   (Download/Config)    │ │                 │  │
│  │                       │ ├─────────────────┤  │
│  │                       │ │  Format Cards   │  │
│  │                       │ │                 │  │
│  └───────────────────────┘ └─────────────────┘  │
├─────────────────────────────────────────────────┤
│  Status Bar (固定底部)                          │
│  连接状态 | 下载进度 | 版本号 | 时间              │
└─────────────────────────────────────────────────┘
```

### 4.2 响应式断点
| 断点 | 宽度 | 布局变化 |
|------|------|----------|
| Mobile | < 640px | 单列堆叠 |
| Tablet | 640px - 1024px | 双列侧边栏收缩 |
| Desktop | > 1024px | 完整三列布局 |

### 4.3 栅格系统
- 12列栅格
- 间距: 24px (lg), 16px (md), 8px (sm)
- 最大宽度: 1280px

---

## 5. 交互动效

### 5.1 过渡动画
| 元素 | 属性 | 时长 | 缓动函数 |
|------|------|------|----------|
| 按钮点击 | transform | 100ms | ease-out |
| 输入框聚焦 | border-color, ring | 200ms | ease |
| 卡片hover | shadow | 200ms | ease |
| 页面切换 | opacity, transform | 300ms | ease-out |
| 进度条 | width | 300ms | ease-out |

### 5.2 加载状态
- 按钮loading: 中心显示旋转图标
- 下载中: 进度条动态填充 + 脉冲动画
- 导出中: 按钮显示加载状态

### 5.3 反馈动画
- 操作成功: 绿色Toast提示
- 操作失败: 红色Toast + 错误信息
- 进度更新: 平滑过渡，无跳跃

---

## 6. 无障碍设计

### 6.1 ARIA规范
- 所有交互元素具有可访问标签
- 进度条使用 `role="progressbar"`
- 下拉框使用 `role="listbox"`
- 开关使用 `role="switch"`

### 6.2 键盘导航
- Tab: 焦点顺序导航
- Enter/Space: 激活按钮
- Esc: 关闭下拉菜单/弹窗

### 6.3 颜色对比度
- 正文: 至少 4.5:1
- 大文字: 至少 3:1
- UI组件: 至少 3:1

---

## 7. 技术实现

### 7.1 技术栈
- **框架**: React 18 + TypeScript
- **样式**: Tailwind CSS 3.4
- **组件库**: Radix UI (无障碍)
- **构建**: Vite 6
- **图标**: Lucide React

### 7.2 组件库 (shadcn/ui)
| 组件 | 用途 |
|------|------|
| Button | 操作按钮 |
| Card | 内容容器 |
| Input | 文本输入 |
| Label | 标签文字 |
| Switch | 开关控件 |
| Progress | 进度显示 |
| Select | 下拉选择 |

### 7.3 目录结构
```
web/
├── src/
│   ├── components/
│   │   ├── ui/           # shadcn/ui 组件
│   │   ├── DownloadPanel.tsx
│   │   ├── ConfigPanel.tsx
│   │   └── StatusBar.tsx
│   ├── lib/
│   │   └── utils.ts      # 工具函数
│   ├── types/
│   │   └── index.ts      # TypeScript 类型
│   ├── App.tsx
│   ├── main.tsx
│   └── index.css
├── index.html
├── package.json
├── vite.config.ts
├── tailwind.config.js
└── tsconfig.json
```

---

## 8. 附录

### 8.1 图标清单
| 用途 | 图标 | 颜色 |
|------|------|------|
| 下载 | Download | primary |
| 设置 | Settings | muted |
| 格式 | FileText | primary |
| 书籍 | BookOpen | primary |
| 链接 | Link | primary |
| 上传 | Upload | muted |
| 播放 | Play | white |
| 加载 | Loader2 | current (旋转) |
| 状态-连接 | Wifi | green |
| 状态-断开 | WifiOff | red |
| 存储 | HardDrive | muted |
| 时间 | Clock | muted |

### 8.2 状态映射
| 下载状态 | 显示文本 | 颜色 |
|----------|----------|------|
| idle | 就绪 | green |
| downloading | 下载中 | blue |
| exporting | 导出中 | purple |
| completed | 完成 | green |
| error | 错误 | red |
