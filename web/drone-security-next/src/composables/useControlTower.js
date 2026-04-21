import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ATTACK_ORDER } from '../domain/attacks'
import { getAttackProfile, usesBackendBridge } from '../domain/attackProfiles'
import { ATTACK_PHASES } from '../domain/phases'
import { formatRuntime, getLineState } from '../domain/runtime'
import { formatClock } from '../lib/time'

function createInitialStatus(attack) {
  const modeLabel = usesBackendBridge(attack.id) ? '真实桥接' : '前端推演'
  return `已选择 ${attack.label}，当前为${modeLabel}模式，可以继续切换攻击焦点并发起演示。`
}

function createLaunchStatus(attack) {
  if (usesBackendBridge(attack.id)) {
    return `${attack.label} 已启动，前端会跟随后端桥接结果并聚焦当前攻击对象。`
  }
  return `${attack.label} 已启动，当前仅进行前端推演，不会向后端发送该类攻击命令。`
}

function createDefendStatus(attack) {
  if (usesBackendBridge(attack.id)) {
    return `${attack.label} 已进入防御收敛阶段，界面会同步标记被影响节点与恢复结果。`
  }
  return `${attack.label} 已进入前端收敛阶段，当前结果来自推演链路而非真实后端回执。`
}

function createDangerStatus(attack) {
  if (usesBackendBridge(attack.id)) {
    return `${attack.label} 已完成攻击链路推演，当前保持未防御状态。`
  }
  return `${attack.label} 已完成前端推演，当前保持未防御状态。`
}

export function useControlTower() {
  const selectedAttackId = ref(ATTACK_ORDER[0])
  const selectedTargetId = ref(getAttackProfile(ATTACK_ORDER[0]).targets?.[0]?.id || 'auto')
  const defenseEnabled = ref(true)
  const isBusy = ref(false)
  const phase = ref(ATTACK_PHASES.idle)
  const statusMessage = ref(createInitialStatus(getAttackProfile(ATTACK_ORDER[0])))
  const attackResult = ref(null)
  const telemetry = ref(null)
  const attackEvent = ref(null)
  const defendEvent = ref(null)
  const resetEvent = ref(null)
  const currentAttackId = ref('')
  const currentTargetId = ref('')
  const history = reactive({
    labels: [],
    voltage: [],
    current: [],
  })

  const backendAttackState = reactive({
    overloadInjected: false,
    sensorSpoofed: false,
    maliciousControl: false,
  })

  const selectedAttack = computed(() => getAttackProfile(selectedAttackId.value))
  const attackOptions = computed(() => ATTACK_ORDER.map((attackId) => getAttackProfile(attackId)))
  const runtime = computed(() => formatRuntime(telemetry.value))
  const lineState = computed(() => getLineState(telemetry.value))

  let telemetryStream = null
  let reconnectTimer = null
  let telemetryPollTimer = null
  let attackTimer = null

  watch(selectedAttackId, (attackId) => {
    const attack = getAttackProfile(attackId)
    selectedTargetId.value = attack.targets?.[0]?.id || 'auto'
    attackResult.value = null
    statusMessage.value = createInitialStatus(attack)
  })

  function clearAttackTimer() {
    if (attackTimer) {
      clearTimeout(attackTimer)
      attackTimer = null
    }
  }

  function initHistory() {
    const now = Date.now()
    history.labels.splice(0, history.labels.length)
    history.voltage.splice(0, history.voltage.length)
    history.current.splice(0, history.current.length)

    for (let index = 7; index >= 0; index -= 1) {
      history.labels.push(formatClock(new Date(now - index * 1000)))
      history.voltage.push(0)
      history.current.push(0)
    }
  }

  function pushHistoryPoint(payload) {
    history.labels.push(formatClock(new Date()))
    history.voltage.push(Number(payload?.voltage || 0))
    history.current.push(Number(payload?.current || 0))

    if (history.labels.length > 8) history.labels.shift()
    if (history.voltage.length > 8) history.voltage.shift()
    if (history.current.length > 8) history.current.shift()
  }

  function applyTelemetry(payload) {
    telemetry.value = payload
    backendAttackState.overloadInjected = Number(payload?.voltage || 0) >= 20
    pushHistoryPoint(payload)
  }

  async function sendAttackCommand(cmd) {
    const response = await fetch('/api/attack', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cmd }),
    })

    if (!response.ok) {
      const text = await response.text()
      throw new Error(text || `HTTP ${response.status}`)
    }
  }

  async function sendCommandSafe(cmd) {
    try {
      await sendAttackCommand(cmd)
      return true
    } catch (error) {
      console.warn('[control-tower] command failed', cmd, error)
      return false
    }
  }

  async function pullTelemetryOnce() {
    try {
      const response = await fetch('/api/telemetry')
      if (!response.ok) return
      const payload = await response.json()
      if (payload?.data) {
        applyTelemetry(payload.data)
      }
    } catch {
      // ignore pull errors, stream may still be active
    }
  }

  function connectTelemetryStream() {
    telemetryStream = new EventSource('/api/telemetry/stream')
    telemetryStream.onmessage = (event) => {
      try {
        applyTelemetry(JSON.parse(event.data))
      } catch {
        // ignore invalid telemetry frames
      }
    }

    telemetryStream.onerror = () => {
      telemetryStream?.close()
      reconnectTimer = setTimeout(connectTelemetryStream, 1500)
    }
  }

  async function triggerAttackCommand(attack) {
    if (!attack.commands.attack) return true

    if (attack.id === 'sensor') {
      if (backendAttackState.sensorSpoofed) return true
      const ok = await sendCommandSafe(attack.commands.attack)
      if (ok) backendAttackState.sensorSpoofed = true
      return ok
    }

    if (attack.id === 'control') {
      const ok = await sendCommandSafe(attack.commands.attack)
      if (ok) backendAttackState.maliciousControl = true
      return ok
    }

    if (attack.id === 'alarm') {
      const targetId = currentTargetId.value || selectedTargetId.value
      const cmd = attack.commands.attack[targetId]
      return sendCommandSafe(cmd)
    }

    return sendCommandSafe(attack.commands.attack)
  }

  async function triggerDefendCommand(attack) {
    if (!attack.commands.defend) return true

    if (attack.id === 'sensor') {
      if (!backendAttackState.sensorSpoofed) return true
      const ok = await sendCommandSafe(attack.commands.defend)
      if (ok) backendAttackState.sensorSpoofed = false
      return ok
    }

    if (attack.id === 'control') {
      if (!backendAttackState.maliciousControl) return true
      const ok = await sendCommandSafe(attack.commands.defend)
      if (ok) backendAttackState.maliciousControl = false
      return ok
    }

    if (attack.id === 'alarm') {
      const targetId = currentTargetId.value || selectedTargetId.value
      const cmd = attack.commands.defend[targetId]
      return sendCommandSafe(cmd)
    }

    return sendCommandSafe(attack.commands.defend)
  }

  async function settleAttackAsDefended(attackId = currentAttackId.value || selectedAttackId.value) {
    clearAttackTimer()

    const attack = getAttackProfile(attackId)
    await triggerDefendCommand(attack)

    phase.value = ATTACK_PHASES.defended
    defendEvent.value = {
      type: attack.id,
      target: currentTargetId.value,
      _t: Date.now(),
    }
    statusMessage.value = createDefendStatus(attack)
    attackResult.value = attack.resultCopy.defended
    isBusy.value = false
  }

  async function launchAttack() {
    clearAttackTimer()

    const attack = selectedAttack.value
    const targetId = attack.targetMode === 'manual' ? selectedTargetId.value : 'auto'

    isBusy.value = true
    phase.value = ATTACK_PHASES.attacking
    currentAttackId.value = attack.id
    currentTargetId.value = targetId
    attackResult.value = null
    statusMessage.value = createLaunchStatus(attack)

    const commandOk = await triggerAttackCommand(attack)
    if (!commandOk && attack.commands.attack) {
      statusMessage.value = `${attack.label} 的后端指令发送失败，前端仍会保留传播演示用于核对界面逻辑。`
    }

    attackEvent.value = {
      type: attack.id,
      target: targetId,
      defense: defenseEnabled.value,
      _t: Date.now(),
    }

    if (attack.durations.totalMs > 0) {
      attackTimer = setTimeout(async () => {
        if (defenseEnabled.value) {
          await settleAttackAsDefended(attack.id)
          return
        }

        statusMessage.value = createDangerStatus(attack)
        attackResult.value = attack.resultCopy.danger
        isBusy.value = false
      }, attack.durations.totalMs)
      return
    }

    statusMessage.value = usesBackendBridge(attack.id)
      ? `${attack.label} 已进入持续态，等待自动或手动防御。`
      : `${attack.label} 已进入持续推演态，等待自动或手动收敛。`
    isBusy.value = false
  }

  async function activateScenario(mode) {
    clearAttackTimer()

    if (mode === 'continuous-overvoltage') {
      const breakerState = String(telemetry.value?.breakerState || '').toLowerCase()
      if (breakerState !== 'closed') {
        await sendCommandSafe('m-1')
      }
      const ok = await sendCommandSafe('1-1-on')
      if (ok) {
        backendAttackState.overloadInjected = true
        statusMessage.value = '持续注入过压帧已开启，仅在合闸状态下持续生效。'
      } else {
        statusMessage.value = '持续注入过压帧下发失败，请检查后端仿真状态。'
      }
      return
    }

    if (mode === 'overload') {
      const breakerState = String(telemetry.value?.breakerState || '').toLowerCase()
      if (breakerState === 'open') {
        await sendCommandSafe('m-1')
      }
      const ok = await sendCommandSafe('o')
      if (ok) backendAttackState.overloadInjected = true
      statusMessage.value = '负荷冲击已触发，实时遥测与拓扑会继续反映线路变化。'
      return
    }

    const ok = await sendCommandSafe('r')
    if (ok) {
      backendAttackState.overloadInjected = false
      backendAttackState.sensorSpoofed = false
      backendAttackState.maliciousControl = false
    }

    phase.value = ATTACK_PHASES.idle
    currentAttackId.value = ''
    currentTargetId.value = ''
    attackResult.value = null
    isBusy.value = false
    statusMessage.value = '系统已恢复到正常场景，等待下一次攻击编排。'
    resetEvent.value = { mode: 'normal', _t: Date.now() }
    await pullTelemetryOnce()
  }

  async function restoreFromExplosion() {
    await activateScenario('normal')
  }

  async function defendNow() {
    if (!currentAttackId.value) {
      statusMessage.value = '当前没有处于活动态的攻击，无法执行立即防御。'
      return
    }

    await settleAttackAsDefended(currentAttackId.value)
  }

  onMounted(() => {
    initHistory()
    connectTelemetryStream()
    pullTelemetryOnce()
    telemetryPollTimer = setInterval(pullTelemetryOnce, 1000)
  })

  onUnmounted(() => {
    clearAttackTimer()

    if (reconnectTimer) clearTimeout(reconnectTimer)
    if (telemetryPollTimer) clearInterval(telemetryPollTimer)
    telemetryStream?.close()
  })

  return {
    attackOptions,
    selectedAttack,
    selectedAttackId,
    selectedTargetId,
    defenseEnabled,
    isBusy,
    phase,
    statusMessage,
    attackResult,
    telemetry,
    runtime,
    lineState,
    history,
    currentAttackId,
    currentTargetId,
    attackEvent,
    defendEvent,
    resetEvent,
    setSelectedAttack(attackId) {
      selectedAttackId.value = attackId
    },
    setSelectedTarget(targetId) {
      selectedTargetId.value = targetId
    },
    setDefenseEnabled(value) {
      defenseEnabled.value = value
    },
    launchAttack,
    defendNow,
    activateScenario,
    restoreFromExplosion,
  }
}
