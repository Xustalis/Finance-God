/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** /api/v1 包络域客户端基址（api/client.ts、useRealtimeVoice）。 */
  readonly VITE_API_BASE_URL?: string
  /** 交易台裸 JSON 域客户端基址（services/tradingDesk.ts），默认 /api。 */
  readonly VITE_FINANCE_API_BASE_URL?: string
  readonly VITE_WORKBENCH_ORIGIN?: string
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}
