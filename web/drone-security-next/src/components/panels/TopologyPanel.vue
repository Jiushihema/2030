<template>
  <section class="topology-shell">
    <div class="topology-head">
      <div>
        <p class="panel-kicker">topology</p>
        <h2>攻击传播拓扑</h2>
      </div>
      <div class="stat-row">
        <span class="stat normal">正常 {{ stats.normal }}</span>
        <span class="stat affected">受影响 {{ stats.affected }}</span>
        <span class="stat defended">已收敛 {{ stats.defended }}</span>
      </div>
    </div>

    <div ref="chartRef" class="topology-chart"></div>

    <div class="mini-panel">
      <div class="mini-title">线路母线实时趋势</div>
      <div ref="miniTrendRef" class="mini-chart"></div>
    </div>

    <div class="legend-row">
      <span v-for="item in TOPOLOGY_LEGEND" :key="item">{{ item }}</span>
    </div>

    <div v-if="activeConsequences.length" class="impact-strip">
      <span class="impact-title">当前影响</span>
      <span v-for="item in activeConsequences" :key="item" class="impact-item">{{ item }}</span>
    </div>

    <div v-if="isExploded" class="explosion-mask">
      <div class="explosion-emoji">!</div>
      <div class="explosion-title">线路已进入高风险状态</div>
      <div class="explosion-copy">
        当前场景已出现严重异常，请恢复正常场景以重新同步遥测、拓扑与评估状态。
      </div>
      <button type="button" class="restore-btn" @click="$emit('restore')">恢复系统</button>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ATTACK_STEP_INTERVAL_MS } from '../../domain/attacks'
import { getAttackTargetMeta } from '../../domain/attackProfiles'
import {
  getTimeline,
  NODE_ICON_MAP,
  NODE_SIZE_MAP,
  TOPOLOGY_EDGES,
  TOPOLOGY_LEGEND,
  TOPOLOGY_NODES,
  validateTopology,
} from '../../domain/topology'
import { echarts } from '../../lib/echarts'

const props = defineProps({
  attackEvent: {
    type: Object,
    default: null,
  },
  defendEvent: {
    type: Object,
    default: null,
  },
  resetEvent: {
    type: Object,
    default: null,
  },
  telemetry: {
    type: Object,
    default: null,
  },
  history: {
    type: Object,
    required: true,
  },
  lineState: {
    type: String,
    required: true,
  },
  currentAttackId: {
    type: String,
    default: '',
  },
})

defineEmits(['restore'])

const chartRef = ref(null)
const miniTrendRef = ref(null)
const isExploded = computed(() => props.telemetry?.plantState === 'exploded')

const activeConsequences = ref([])
const nodeTags = reactive({})
const nodeStatus = reactive(Object.fromEntries(TOPOLOGY_NODES.map((node) => [node.id, 'normal'])))
const stats = reactive({
  normal: TOPOLOGY_NODES.length,
  affected: 0,
  defended: 0,
})

let chart = null
let miniTrendChart = null
let resizeHandler = null
let stepTimer = null
let attackedNodes = []
let activeEdgeIds = []

function updateStats() {
  const values = Object.values(nodeStatus)
  stats.normal = values.filter((value) => value === 'normal').length
  stats.affected = values.filter((value) => value === 'affected').length
  stats.defended = values.filter((value) => value === 'defended').length
}

function clearNodeTags() {
  Object.keys(nodeTags).forEach((key) => {
    delete nodeTags[key]
  })
}

function resetView() {
  clearNodeTags()
  activeConsequences.value = []
  attackedNodes = []
  activeEdgeIds = []
  TOPOLOGY_NODES.forEach((node) => {
    nodeStatus[node.id] = 'normal'
  })
  updateStats()
}

function buildMiniTrendOption() {
  return {
    animation: false,
    backgroundColor: 'transparent',
    grid: { top: 12, left: 26, right: 10, bottom: 18 },
    xAxis: {
      type: 'category',
      data: props.history.labels,
      axisLabel: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: [
      {
        type: 'value',
        min: 0,
        max: 30,
        axisLabel: { color: '#8eb3d1', fontSize: 9, formatter: '{value}kV' },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.1)', type: 'dashed' } },
      },
      {
        type: 'value',
        min: 0,
        max: 220,
        axisLabel: { show: false },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '电压',
        type: 'line',
        yAxisIndex: 0,
        data: props.history.voltage,
        smooth: true,
        symbol: 'none',
        lineStyle: { color: '#ff737d', width: 2 },
      },
      {
        name: '电流',
        type: 'line',
        yAxisIndex: 1,
        data: props.history.current,
        smooth: true,
        symbol: 'none',
        lineStyle: { color: '#4bc8ff', width: 2 },
      },
    ],
  }
}

function resolveRuntimeEdgeKind(edgeId) {
  if (props.lineState === 'overload' && edgeId === 'e_lmu_lm') return 'alarm'
  if (props.lineState === 'overload' && edgeId === 'e_lm_bit') return 'trip'
  if ((props.currentAttackId === 'sensor' || props.currentAttackId === 'control') && (edgeId === 'e_sensor_bit' || edgeId === 'e_bit_lm')) {
    return 'status'
  }
  return 'normal'
}

function buildTopologyOption() {
  const statusColorMap = {
    normal: '#5dffb2',
    affected: '#ff646e',
    defended: '#4bc8ff',
  }

  const runtimeColorMap = {
    normal: '#5dffb2',
    alarm: '#ff646e',
    trip: '#5dffb2',
    status: '#4bc8ff',
  }

  const runtimeLabelMap = {
    alarm: '过载告警',
    trip: '保护动作',
    status: '状态回传',
  }

  const nodes = TOPOLOGY_NODES.map((node) => {
    const status = nodeStatus[node.id]
    let color = statusColorMap[status]
    let labelColor = status === 'normal' ? '#d4e6f8' : color
    let borderWidth = status === 'normal' ? 0 : 3
    let shadowBlur = status === 'normal' ? 8 : 18
    let size = NODE_SIZE_MAP[node.type]

    if (node.id === 'line_mu' && status === 'normal') {
      if (props.lineState === 'overload') {
        color = '#ff646e'
        labelColor = '#ff646e'
        borderWidth = 3
        shadowBlur = 24
        nodeTags.line_mu = '过载'
      } else if (props.lineState === 'no-current') {
        color = '#ffffff'
        labelColor = '#ffffff'
        borderWidth = 4
        shadowBlur = 26
        size += 4
        nodeTags.line_mu = '断流'
      } else if (nodeTags.line_mu === '过载' || nodeTags.line_mu === '断流') {
        delete nodeTags.line_mu
      }
    }

    return {
      id: node.id,
      name: node.label,
      x: node.x,
      y: node.y,
      symbol: `image://${NODE_ICON_MAP[node.type]}`,
      symbolSize: size,
      label: {
        show: true,
        position: 'bottom',
        color: labelColor,
        fontSize: 11,
        formatter: nodeTags[node.id] ? `${node.label}\n${nodeTags[node.id]}` : node.label,
      },
      itemStyle: {
        borderColor: color,
        borderWidth,
        shadowColor: color,
        shadowBlur,
      },
    }
  })

  const edges = TOPOLOGY_EDGES.map((edge) => {
    const isAttackEdge = activeEdgeIds.includes(edge.id)
    const runtimeKind = resolveRuntimeEdgeKind(edge.id)
    const runtimeActive = runtimeKind !== 'normal'
    const color = isAttackEdge ? '#ff646e' : runtimeColorMap[runtimeKind]

    return {
      source: edge.source,
      target: edge.target,
      label: {
        show: runtimeActive || Boolean(edge.label),
        formatter: runtimeActive ? runtimeLabelMap[runtimeKind] : edge.label,
        color: isAttackEdge ? '#ff8890' : runtimeActive ? runtimeColorMap[runtimeKind] : '#89a2ba',
        fontSize: runtimeActive ? 10 : 9,
        fontWeight: runtimeActive ? 'bold' : 'normal',
        backgroundColor: runtimeActive ? 'rgba(5, 14, 28, 0.86)' : 'transparent',
        padding: runtimeActive ? [2, 6] : 0,
        borderRadius: runtimeActive ? 999 : 0,
      },
      lineStyle: {
        color,
        width: isAttackEdge ? 2.6 : runtimeActive ? 2.2 : 1.2,
        type: edge.lineType,
        opacity: isAttackEdge || runtimeActive ? 1 : 0.58,
        curveness: edge.curve,
      },
      effect: {
        show: runtimeActive || edge.flow,
        period: isAttackEdge ? 1.5 : runtimeKind === 'trip' ? 1.4 : runtimeKind === 'alarm' ? 1.7 : 2.3,
        trailLength: isAttackEdge ? 0.45 : runtimeKind === 'normal' ? 0.22 : 0.36,
        color,
        symbolSize: isAttackEdge ? 8 : runtimeKind === 'normal' ? 4 : 6,
      },
    }
  })

  return {
    animation: true,
    backgroundColor: 'transparent',
    series: [
      {
        type: 'graph',
        layout: 'none',
        roam: true,
        zoom: 0.88,
        center: ['50%', '48%'],
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: 8,
        data: nodes,
        links: edges,
        emphasis: { disabled: true },
      },
    ],
  }
}

function refreshCharts() {
  chart?.setOption(buildTopologyOption(), true)
  miniTrendChart?.setOption(buildMiniTrendOption(), true)
}

function applyAttackStep(step) {
  const targetMeta = props.attackEvent ? getAttackTargetMeta(props.attackEvent.type, props.attackEvent.target) : null
  activeConsequences.value = step.consequences || []
  attackedNodes = [...step.nodes]
  activeEdgeIds = [...step.edges]

  TOPOLOGY_NODES.forEach((node) => {
    nodeStatus[node.id] = 'normal'
  })
  attackedNodes.forEach((nodeId) => {
    nodeStatus[nodeId] = 'affected'
  })

  clearNodeTags()
  if (step.summary && attackedNodes.length) {
    const anchorNodeId = targetMeta?.focusNodeId && attackedNodes.includes(targetMeta.focusNodeId)
      ? targetMeta.focusNodeId
      : attackedNodes[0]
    nodeTags[anchorNodeId] = step.summary
  } else if (targetMeta?.focusNodeId) {
    nodeTags[targetMeta.focusNodeId] = '演示焦点'
  }

  updateStats()
  refreshCharts()
}

function stopStepTimer() {
  if (stepTimer) {
    clearInterval(stepTimer)
    stepTimer = null
  }
}

watch(
  () => props.attackEvent,
  (event) => {
    if (!event) return

    stopStepTimer()
    clearNodeTags()

    const steps = getTimeline(event.type, event.target)
    if (!steps.length) {
      resetView()
      refreshCharts()
      return
    }

    let index = 0
    const playStep = () => {
      if (index >= steps.length) {
        stopStepTimer()
        return
      }
      applyAttackStep(steps[index])
      index += 1
    }

    playStep()
    if (steps.length > 1) {
      stepTimer = setInterval(playStep, ATTACK_STEP_INTERVAL_MS)
    }
  },
)

watch(
  () => props.defendEvent,
  (event) => {
    if (!event) return
    stopStepTimer()
    attackedNodes.forEach((nodeId) => {
      nodeStatus[nodeId] = 'defended'
    })
    activeEdgeIds = []
    activeConsequences.value = ['防御策略已执行，传播链路正在收敛。']
    clearNodeTags()
    updateStats()
    refreshCharts()
  },
)

watch(
  () => props.resetEvent,
  (event) => {
    if (!event) return
    stopStepTimer()
    resetView()
    refreshCharts()
  },
)

watch(
  () => [props.telemetry, props.history.labels.length, props.lineState, props.currentAttackId],
  () => {
    refreshCharts()
  },
  { deep: true },
)

onMounted(() => {
  const errors = validateTopology()
  if (errors.length) {
    console.warn('[topology] validation errors', errors)
  }

  chart = echarts.init(chartRef.value)
  miniTrendChart = echarts.init(miniTrendRef.value)

  resizeHandler = () => {
    chart?.resize()
    miniTrendChart?.resize()
  }

  window.addEventListener('resize', resizeHandler)
  updateStats()
  refreshCharts()
})

onUnmounted(() => {
  stopStepTimer()
  chart?.dispose()
  miniTrendChart?.dispose()
  if (resizeHandler) {
    window.removeEventListener('resize', resizeHandler)
  }
})
</script>

<style scoped>
.topology-shell {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 0;
  width: 100%;
  border-radius: 22px;
  overflow: hidden;
  background:
    linear-gradient(180deg, rgba(3, 10, 18, 0.18) 0%, rgba(3, 10, 18, 0.55) 100%),
    url('../../assets/image.png') center / cover no-repeat;
}

.topology-head,
.legend-row,
.impact-strip,
.topology-chart,
.mini-panel {
  position: relative;
  z-index: 1;
}

.topology-shell::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(0, 0, 0, 0.52) 0%, rgba(0, 0, 0, 0.42) 45%, rgba(0, 0, 0, 0.74) 100%);
}

.topology-head {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: center;
  padding: 18px 18px 10px;
}

.panel-kicker {
  margin: 0 0 8px;
  color: var(--brand-cyan);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.2em;
}

h2 {
  margin: 0;
  font-size: 24px;
}

.stat-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.stat {
  padding: 8px 12px;
  border-radius: 999px;
  background: rgba(7, 17, 30, 0.72);
  font-size: 12px;
  font-weight: 700;
}

.stat.normal {
  color: var(--brand-green);
}

.stat.affected {
  color: var(--brand-red);
}

.stat.defended {
  color: var(--brand-cyan);
}

.topology-chart {
  flex: 1;
  min-height: 0;
}

.mini-panel {
  position: absolute;
  left: 26px;
  top: 54%;
  width: 220px;
  height: 150px;
  padding: 8px 10px 6px;
  border: 1px solid rgba(255, 255, 255, 0.24);
  border-radius: 18px;
  background: rgba(2, 10, 18, 0.62);
  backdrop-filter: blur(2px);
}

.mini-title {
  color: #d4e6f8;
  font-size: 11px;
}

.mini-chart {
  width: 100%;
  height: calc(100% - 20px);
}

.legend-row,
.impact-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 0 18px 12px;
  padding: 10px 12px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 16px;
  background: rgba(2, 10, 18, 0.56);
  color: var(--text-secondary);
  font-size: 12px;
}

.legend-row {
  justify-content: center;
}

.impact-title {
  color: var(--brand-red);
  font-weight: 700;
}

.impact-item {
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(255, 100, 110, 0.12);
  border: 1px solid rgba(255, 100, 110, 0.24);
  color: #ffd0d4;
}

.explosion-mask {
  position: absolute;
  inset: 0;
  z-index: 5;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background:
    radial-gradient(circle at center, rgba(255, 120, 0, 0.38) 0%, rgba(180, 20, 0, 0.56) 36%, rgba(0, 0, 0, 0.84) 76%),
    rgba(0, 0, 0, 0.72);
  text-align: center;
}

.explosion-emoji {
  font-size: 64px;
  font-weight: 800;
}

.explosion-title {
  font-size: 30px;
  font-weight: 800;
  color: #ffd9b0;
}

.explosion-copy {
  max-width: 520px;
  color: #ffc5b0;
}

.restore-btn {
  min-height: 44px;
  padding: 0 20px;
  border-radius: 16px;
  background: rgba(0, 0, 0, 0.55);
  border: 1px solid rgba(255, 209, 128, 0.48);
  color: #ffe4b2;
  cursor: pointer;
}

@media (max-width: 1220px) {
  .topology-shell {
    min-height: 720px;
  }
}
</style>
