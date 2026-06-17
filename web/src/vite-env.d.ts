/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端 API 基础地址，未配置时回退到本地开发默认值 */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
