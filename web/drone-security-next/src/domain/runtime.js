export const DEFAULT_RUNTIME = {
  mode: '等待遥测',
  voltage: '--',
  current: '--',
  breaker: '--',
  sensor: '--',
  stored: '--',
}

export function getLineState(telemetry) {
  const current = Number(telemetry?.current || 0)
  const voltage = Number(telemetry?.voltage || 0)

  if (current <= 1) return 'no-current'
  if (voltage >= 20 || current >= 160) return 'overload'
  return 'normal'
}

export function formatRuntime(telemetry) {
  if (!telemetry) return DEFAULT_RUNTIME

  const lineState = getLineState(telemetry)
  const modeText = lineState === 'no-current'
    ? '无流工况'
    : lineState === 'overload'
      ? '过载工况'
      : '正常工况'

  return {
    mode: modeText,
    voltage: `${Number(telemetry.voltage || 0).toFixed(1)}kV`,
    current: `${Number(telemetry.current || 0).toFixed(1)}A`,
    breaker: telemetry.breakerState || '--',
    sensor: telemetry.sensorState || '--',
    stored: `${telemetry.storedCount ?? '--'}`,
  }
}
