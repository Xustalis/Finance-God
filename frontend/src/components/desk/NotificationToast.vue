<script setup lang="ts">
/**
 * 行情异动提醒弹窗（toast 堆叠）。
 * - 非模态、不遮挡：渲染在应用壳右下角，不抢占焦点。
 * - 可关闭：手动关闭即标记已读；定时自动关闭则保留为未读（提醒中心可翻看）。
 * - 可访问：警告/异常用 role=alert（assertive），普通用 role=status（polite）；
 *   关闭按钮有可读标签、可键盘操作；悬停/聚焦暂停自动关闭计时。
 * - prefers-reduced-motion 下禁用进出场动画。
 */
import { onBeforeUnmount, watch } from 'vue'
import { X } from 'lucide-vue-next'
import { useNotificationsStore } from '@/stores/notifications'
import { formatPercent, type MarketAlertSeverity } from '@/types/desk'
import type { MarketAlertView } from '@/types/desk'

/** 自动关闭时长（毫秒）：异常更久，普通较短。 */
const AUTO_DISMISS_MS: Record<MarketAlertSeverity, number> = {
  info: 7_000,
  warning: 9_000,
  error: 14_000,
}

const notifications = useNotificationsStore()

/** 每条 toast 的自动关闭计时器句柄。 */
const timers = new Map<string, ReturnType<typeof setTimeout>>()

function severityRole(severity: MarketAlertSeverity): 'alert' | 'status' {
  return severity === 'info' ? 'status' : 'alert'
}

function severityLive(severity: MarketAlertSeverity): 'assertive' | 'polite' {
  return severity === 'info' ? 'polite' : 'assertive'
}

function startTimer(alert: MarketAlertView): void {
  if (timers.has(alert.alert_id)) return
  const handle = setTimeout(() => {
    timers.delete(alert.alert_id)
    // 超时自动关闭：仅隐藏，保留为未读，供提醒中心翻看。
    notifications.dismissToast(alert.alert_id)
  }, AUTO_DISMISS_MS[alert.severity] ?? AUTO_DISMISS_MS.warning)
  timers.set(alert.alert_id, handle)
}

function clearTimer(alertId: string): void {
  const handle = timers.get(alertId)
  if (handle) {
    clearTimeout(handle)
    timers.delete(alertId)
  }
}

/** 悬停/聚焦时暂停自动关闭，避免用户阅读时被关掉。 */
function pause(alertId: string): void {
  clearTimer(alertId)
}

function resume(alert: MarketAlertView): void {
  startTimer(alert)
}

/** 手动关闭：标记已读（不再计入未读，也不会重复弹窗）。 */
function close(alertId: string): void {
  clearTimer(alertId)
  notifications.acknowledge(alertId)
}

// 为新出现的 toast 启动计时器，为已移除的清理计时器。
watch(
  () => notifications.toasts,
  (current) => {
    const currentIds = new Set(current.map((t) => t.alert_id))
    for (const alert of current) startTimer(alert)
    for (const id of [...timers.keys()]) {
      if (!currentIds.has(id)) clearTimer(id)
    }
  },
  { deep: true, immediate: true },
)

onBeforeUnmount(() => {
  for (const handle of timers.values()) clearTimeout(handle)
  timers.clear()
})
</script>

<template>
  <div
    v-if="notifications.hasToasts"
    class="toast-stack"
    aria-label="行情异动提醒"
  >
    <TransitionGroup name="toast">
      <article
        v-for="alert in notifications.toasts"
        :key="alert.alert_id"
        class="toast"
        :class="`toast--${alert.severity} toast--${alert.kind}`"
        :role="severityRole(alert.severity)"
        :aria-live="severityLive(alert.severity)"
        @mouseenter="pause(alert.alert_id)"
        @mouseleave="resume(alert)"
        @focusin="pause(alert.alert_id)"
        @focusout="resume(alert)"
      >
        <div class="toast-body">
          <p class="toast-head">
            <span class="toast-symbol">{{ alert.name }}</span>
            <span class="toast-code">{{ alert.symbol }}</span>
            <span class="toast-move" :class="alert.kind">
              {{ formatPercent(alert.change_percent) }}
            </span>
          </p>
          <p class="toast-message">{{ alert.message }}</p>
          <p class="toast-meta">数据时点 {{ alert.provider_time }}</p>
        </div>
        <button
          type="button"
          class="toast-close"
          :aria-label="`关闭 ${alert.name} 的异动提醒并标记已读`"
          @click="close(alert.alert_id)"
        >
          <X :size="16" aria-hidden="true" />
        </button>
      </article>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-stack {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 60;
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 340px;
  max-width: calc(100vw - 40px);
  pointer-events: none;
}
.toast {
  pointer-events: auto;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 12px 12px 12px 14px;
  border-radius: 10px;
  background: var(--paper, #fff);
  border: 1px solid var(--line, #e2e2e2);
  border-left-width: 3px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}
.toast--warning {
  border-left-color: #d98324;
}
.toast--error {
  border-left-color: #c0392b;
}
.toast--info {
  border-left-color: #2d7dd2;
}
.toast-body {
  flex: 1 1 auto;
  min-width: 0;
}
.toast-head {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin: 0 0 4px;
}
.toast-symbol {
  font-weight: 600;
  font-size: 13px;
}
.toast-code {
  font-size: 11px;
  color: var(--ink-soft, #888);
}
.toast-move {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  font-size: 13px;
}
.toast-move.surge {
  color: #c0392b;
}
.toast-move.plunge {
  color: #1f8a4c;
}
.toast-message {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink, #333);
}
.toast-meta {
  margin: 4px 0 0;
  font-size: 11px;
  color: var(--ink-soft, #999);
}
.toast-close {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--ink-soft, #888);
  cursor: pointer;
}
.toast-close:hover {
  background: var(--hover, rgba(0, 0, 0, 0.05));
  color: var(--ink, #333);
}
.toast-close:focus-visible {
  outline: 2px solid var(--accent, #2d7dd2);
  outline-offset: 1px;
}

.toast-enter-active,
.toast-leave-active {
  transition: transform 0.24s ease, opacity 0.24s ease;
}
.toast-enter-from {
  transform: translateX(16px);
  opacity: 0;
}
.toast-leave-to {
  transform: translateX(16px);
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .toast-enter-active,
  .toast-leave-active {
    transition: none;
  }
  .toast-enter-from,
  .toast-leave-to {
    transform: none;
  }
}
</style>
