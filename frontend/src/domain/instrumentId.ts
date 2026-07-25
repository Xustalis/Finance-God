const INSTRUMENT_PATTERNS: Readonly<Record<string, RegExp>> = {
  SH: /^\d{6}\.SH$/,
  SZ: /^\d{6}\.SZ$/,
  HK: /^\d{5}\.HK$/,
  OF: /^\d{6}\.OF$/,
  US: /^[A-Z][A-Z0-9.-]{0,9}\.US$/,
}

export function parseInstrumentId(value: string): string | null {
  const normalized = value.trim().toUpperCase()
  const suffix = normalized.split('.').at(-1)
  if (!suffix) return null
  return INSTRUMENT_PATTERNS[suffix]?.test(normalized) ? normalized : null
}

export function requireInstrumentId(value: string): string {
  const instrumentId = parseInstrumentId(value)
  if (!instrumentId) {
    throw new Error('证券代码格式无效；请使用带合法交易所后缀的代码')
  }
  return instrumentId
}
