import type { InvestmentDirection } from '@/types/api'
import { DEFAULT_SYMBOLS } from '@/types/desk'

/** 仅使用已验证可取实时快照的 A 股标的（PandaData 当前仅支持 A 股实时行情）。 */
const DIRECTION_META: Record<
  InvestmentDirection,
  { name: string; kind: string; symbols: readonly string[] }
> = {
  equities: {
    name: '青松录',
    kind: '权益股票',
    symbols: ['000001.SZ', '600519.SH', '000002.SZ', '601318.SH', '600036.SH'],
  },
  public_funds: {
    name: '百川谱',
    kind: '公募基金',
    // 基金无实时快照；展示大盘蓝筹 A 股作为可观察代理。
    symbols: ['600519.SH', '600036.SH', '000858.SZ', '300750.SZ'],
  },
  cash_fixed_income: {
    name: '守元诀',
    kind: '现金固收',
    // 固收无实时快照；展示稳健的银行/保险 A 股作为可观察代理。
    symbols: ['601318.SH', '600036.SH', '000001.SZ'],
  },
  alternatives: {
    name: '观星篇',
    kind: '另类配置',
    symbols: ['002594.SZ', '300750.SZ', '000858.SZ'],
  },
  long_term_insurance: {
    name: '长宁策',
    kind: '长期储蓄保险',
    // 保险本身不可在仿真台交易；展示相近的稳健观察标的。
    symbols: ['601318.SH', '600036.SH', '600519.SH'],
  },
}

const DIRECTION_VALUES = Object.keys(DIRECTION_META) as InvestmentDirection[]

export function isInvestmentDirection(value: unknown): value is InvestmentDirection {
  return typeof value === 'string' && (DIRECTION_VALUES as string[]).includes(value)
}

export function parseInvestmentDirection(value: unknown): InvestmentDirection | null {
  if (Array.isArray(value)) return parseInvestmentDirection(value[0])
  return isInvestmentDirection(value) ? value : null
}

export function directionDisplayName(direction: InvestmentDirection): string {
  return DIRECTION_META[direction].name
}

export function directionKindLabel(direction: InvestmentDirection): string {
  return DIRECTION_META[direction].kind
}

/** 返回该方向的可观察标的池；未知方向回退默认列表。 */
export function symbolsForDirection(direction: InvestmentDirection | null | undefined): string[] {
  if (!direction || !DIRECTION_META[direction]) return [...DEFAULT_SYMBOLS]
  return [...DIRECTION_META[direction].symbols]
}

export function defaultSymbolForDirection(direction: InvestmentDirection | null | undefined): string {
  return symbolsForDirection(direction)[0] ?? DEFAULT_SYMBOLS[0]
}
