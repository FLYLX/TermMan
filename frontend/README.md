# TermPaws Frontend

TermPaws 的前端应用，基于 React + TypeScript + Vite 构建。

## 技术栈

- **React 18** - UI 框架
- **TypeScript** - 类型安全
- **Vite** - 构建工具
- **Tailwind CSS** - 样式框架
- **shadcn/ui** - UI 组件库
- **TanStack Query** - 数据请求
- **TanStack Router** - 路由管理
- **xterm.js** - 终端模拟

## 快速开始

### 环境要求

- Bun (推荐) 或 Node.js 18+

### 安装依赖

```bash
bun install
```

### 开发模式

```bash
bun run dev
```

访问 http://localhost:5173

### 构建生产版本

```bash
bun run build
```

## 目录结构

```
frontend/
├── src/
│   ├── components/       # UI 组件
│   │   ├── ui/           # shadcn/ui 基础组件
│   │   └── ...           # 业务组件
│   ├── routes/           # 路由页面
│   ├── hooks/            # 自定义 Hooks
│   ├── lib/              # 工具函数
│   ├── client/           # API 客户端 (自动生成)
│   └── main.tsx          # 入口文件
├── public/               # 静态资源
├── index.html            # HTML 模板
├── vite.config.ts        # Vite 配置
├── tailwind.config.js    # Tailwind 配置
└── package.json          # 项目配置
```

## 主要功能页面

| 路由 | 页面 | 说明 |
|------|------|------|
| `/` | Dashboard | 仪表盘 |
| `/login` | Login | 登录页 |
| `/items` | Items | 终端列表 |
| `/items/:id` | ItemDetail | 终端详情/终端界面 |
| `/handlers` | Handlers | Agent 配置列表 |
| `/handlers/:id` | HandlerDetail | Agent 配置详情 |
| `/knowledge` | Knowledge | 知识库管理 |
| `/settings` | Settings | 系统设置 |

## API 客户端

前端 API 客户端通过 OpenAPI 自动生成：

```bash
# 从后端 OpenAPI 规范生成客户端
bun run generate-client
```

生成的客户端代码位于 `src/client/` 目录。

## 终端组件

使用 xterm.js 实现终端模拟：

- 支持 WebSocket 实时连接
- 支持终端输入/输出
- 支持终端大小调整
- 支持复制/粘贴

## 样式规范

- 使用 Tailwind CSS 原子类
- 组件使用 shadcn/ui
- 支持深色模式

## 代码规范

- 使用 Biome 进行代码格式化
- 使用 TypeScript 严格模式
- 组件使用函数式写法
