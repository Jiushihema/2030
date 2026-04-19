import { getAttackDefinition } from './attacks'

const DEFAULT_ATTACK_PROFILE = {
  selectionLabel: '攻击对象',
  targetHint: '',
  backendMode: 'bridge',
  backendBadge: '后端桥接',
  backendTone: 'bridge',
  backendLabel: '后端能力：已接入攻击桥',
  executionLabel: '执行方式：阶段式传播',
  autoDefenseLabel: '自动防御',
  autoDefenseHint: '开启后会在攻击链路稳定后自动触发防御收敛。',
  manualDefenseHint: '关闭后会保留攻击结果，直到你手动防御或切回正常。',
}

const ATTACK_PROFILES = {
  sensor: {
    selectionLabel: '影响焦点',
    targetHint: '后端当前使用固定传感器欺骗通道，选择项用于切换前端演示焦点、传播路径和评估证据。',
    backendMode: 'coarse-bridge',
    backendBadge: '粗粒度桥接',
    backendTone: 'bridge',
    backendLabel: '后端能力：传感器欺骗桥已接入，但目标粒度仍是通道级。',
    executionLabel: '执行方式：持续注入，可自动收敛也可手动结束',
    autoDefenseHint: '开启后会在欺骗链路稳定后自动触发防御收敛，你也可以随时点击“立即防御”。',
    manualDefenseHint: '关闭后会保留持续欺骗态，直到点击“立即防御”或切回正常。',
  },
  control: {
    selectionLabel: '影响焦点',
    targetHint: '后端当前使用统一控制注入通道，选择项决定前端聚焦的设备与传播路径。',
    backendMode: 'coarse-bridge',
    backendBadge: '粗粒度桥接',
    backendTone: 'bridge',
    backendLabel: '后端能力：控制注入桥已接入，但目标粒度仍是通道级。',
    executionLabel: '执行方式：三段式控制传播演示',
  },
  alarm: {
    selectionLabel: '传播焦点',
    targetHint: '后端当前使用通信拓扑切断方法，选择项用于编排前端传播路径与评估结果。',
    backendMode: 'coarse-bridge',
    backendBadge: '粗粒度桥接',
    backendTone: 'bridge',
    backendLabel: '后端能力：通信拓扑切断已接入。',
    executionLabel: '执行方式：四段式告警扩散演示',
  },
  timing: {
    selectionLabel: '影响范围',
    targetHint: '时序攻击当前按全网时钟失步建模，不区分单个设备对象。',
    backendMode: 'coarse-bridge',
    backendBadge: '粗粒度桥接',
    backendTone: 'bridge',
    backendLabel: '后端能力：已接入时序攻击，断路器授时被欺骗。',
    executionLabel: '执行方式：全局时序偏移演示',
  },
  swarm: {
    selectionLabel: '影响范围',
    targetHint: '群体协同异常当前按整体行为失稳建模，不区分单个设备对象。',
    backendMode: 'simulation',
    backendBadge: '前端推演',
    backendTone: 'simulation',
    backendLabel: '后端能力：未接入群体攻击，当前为前端推演。',
    executionLabel: '执行方式：群体级异常传播演示',
  },
}

export function getAttackProfile(attackId) {
  const attack = getAttackDefinition(attackId)
  return {
    ...DEFAULT_ATTACK_PROFILE,
    ...attack,
    ...(ATTACK_PROFILES[attackId] || {}),
  }
}

export function getAttackTargetMeta(attackId, targetId) {
  const attack = getAttackProfile(attackId)

  if (attack.targetMode !== 'manual') {
    return {
      id: 'auto',
      label: attack.autoTargetLabel || '自动推演',
      focusNodeId: null,
    }
  }

  return attack.targets?.find((target) => target.id === targetId) || attack.targets?.[0] || {
    id: 'auto',
    label: attack.label,
    focusNodeId: null,
  }
}

export function usesBackendBridge(attackId) {
  const attack = getAttackProfile(attackId)
  return attack.backendMode === 'bridge' || attack.backendMode === 'coarse-bridge'
}
