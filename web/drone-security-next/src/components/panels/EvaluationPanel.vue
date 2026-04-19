<template>
  <section class="evaluation-shell">
    <div class="panel-head">
      <p class="panel-kicker">evaluation</p>
      <h2>效果评估</h2>
    </div>

    <div class="phase-box">
      <span class="phase-label">当前阶段</span>
      <span class="phase-value" :class="phaseClass">{{ phase }}</span>
    </div>

    <div class="runtime-box">
      <span>电压 {{ runtime.voltage }}</span>
      <span>电流 {{ runtime.current }}</span>
      <span>断路器 {{ runtime.breaker }}</span>
      <span>传感器 {{ runtime.sensor }}</span>
      <span>存储状态 {{ runtime.stored }}</span>
    </div>

    <div class="context-box">
      <span>{{ currentAttack.backendLabel }}</span>
      <span>{{ currentAttack.selectionLabel }}：{{ currentTarget.label }}</span>
    </div>

    <div class="metrics-grid">
      <article class="metric-card">
        <header>
          <span>可用性</span>
          <strong :class="metrics.availability.trend">{{ trendGlyph(metrics.availability.trend) }}</strong>
        </header>
        <div class="metric-value" :class="metrics.availability.trend">{{ metrics.availability.value }}%</div>
        <p>反映当前链路在攻击或防御过程中仍可提供稳定服务的程度。</p>
      </article>

      <article class="metric-card">
        <header>
          <span>完整性</span>
          <strong :class="metrics.integrity.trend">{{ trendGlyph(metrics.integrity.trend) }}</strong>
        </header>
        <div class="metric-value" :class="metrics.integrity.trend">{{ metrics.integrity.value }}%</div>
        <p>反映控制量、状态量和遥测值是否仍与真实设备状态保持一致。</p>
      </article>

      <article class="metric-card">
        <header>
          <span>同步误差</span>
          <strong :class="metrics.syncError.trend">{{ trendGlyph(metrics.syncError.trend) }}</strong>
        </header>
        <div class="metric-value" :class="metrics.syncError.trend">{{ metrics.syncError.value }}ms</div>
        <p>重点衡量时间链路、状态回传与执行动作之间的偏移程度。</p>
      </article>
    </div>

    <div class="chart-title">系统健康与威胁趋势</div>
    <div ref="lineChartRef" class="line-chart"></div>

    <div class="chart-title">攻击 / 检测 / 防御成功率</div>
    <div ref="barChartRef" class="bar-chart"></div>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { getAttackProfile, getAttackTargetMeta } from '../../domain/attackProfiles'
import { ATTACK_PHASES } from '../../domain/phases'
import { formatRuntime } from '../../domain/runtime'
import { echarts } from '../../lib/echarts'
import { formatClock } from '../../lib/time'

const props = defineProps({
  phase: {
    type: String,
    required: true,
  },
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
  currentAttackId: {
    type: String,
    default: '',
  },
  selectedAttackId: {
    type: String,
    default: 'sensor',
  },
  selectedTargetId: {
    type: String,
    default: 'auto',
  },
})

const runtime = computed(() => formatRuntime(props.telemetry))
const currentAttackId = computed(() => props.currentAttackId || props.attackEvent?.type || props.selectedAttackId || 'sensor')
const currentTargetId = computed(() => props.attackEvent?.target || props.selectedTargetId || 'auto')
const currentAttack = computed(() => getAttackProfile(currentAttackId.value))
const currentTarget = computed(() => getAttackTargetMeta(currentAttackId.value, currentTargetId.value))

const metrics = reactive({
  availability: { value: 98.5, trend: 'up' },
  integrity: { value: 99.2, trend: 'up' },
  syncError: { value: 0.12, trend: 'neutral' },
})

const successRates = reactive({
  attack: 0,
  detect: 0,
  defense: 0,
})

const phaseClass = computed(() => ({
  standby: props.phase === ATTACK_PHASES.idle,
  attacking: props.phase === ATTACK_PHASES.attacking,
  defended: props.phase === ATTACK_PHASES.defended,
}))

const lineChartRef = ref(null)
const barChartRef = ref(null)
const lineLabels = ref([])
const healthData = ref([])
const threatData = ref([])

let lineChart = null
let barChart = null
let resizeHandler = null
let metricTimer = null

function trendGlyph(trend) {
  if (trend === 'up') return '↑'
  if (trend === 'down') return '↓'
  return '→'
}

function initSeries() {
  const now = Date.now()
  lineLabels.value = []
  healthData.value = []
  threatData.value = []

  for (let index = 9; index >= 0; index -= 1) {
    lineLabels.value.push(formatClock(new Date(now - index * 2000)))
    healthData.value.push(98)
    threatData.value.push(2)
  }
}

function animateMetrics(target) {
  if (metricTimer) {
    clearInterval(metricTimer)
  }

  const start = {
    availability: metrics.availability.value,
    integrity: metrics.integrity.value,
    syncError: metrics.syncError.value,
  }

  let step = 0
  metricTimer = setInterval(() => {
    step += 1
    const progress = step / 24
    metrics.availability.value = +(start.availability + (target.availability - start.availability) * progress).toFixed(1)
    metrics.integrity.value = +(start.integrity + (target.integrity - start.integrity) * progress).toFixed(1)
    metrics.syncError.value = +(start.syncError + (target.syncError - start.syncError) * progress).toFixed(2)

    if (step >= 24) {
      clearInterval(metricTimer)
      metricTimer = null
    }
  }, 50)
}

function buildLineOption() {
  return {
    animation: false,
    backgroundColor: 'transparent',
    grid: { top: 20, right: 14, bottom: 24, left: 34 },
    xAxis: {
      type: 'category',
      data: lineLabels.value,
      axisLabel: { color: '#89a2ba', fontSize: 9, interval: 4 },
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.12)' } },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { color: '#89a2ba', fontSize: 9 },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.12)', type: 'dashed' } },
    },
    legend: {
      top: 0,
      right: 0,
      textStyle: { color: '#89a2ba', fontSize: 9 },
      data: ['健康度', '威胁度'],
    },
    series: [
      {
        name: '健康度',
        type: 'line',
        data: healthData.value,
        smooth: true,
        symbol: 'circle',
        symbolSize: 4,
        lineStyle: { color: '#5dffb2', width: 2 },
        itemStyle: { color: '#5dffb2' },
        areaStyle: { color: 'rgba(93,255,178,0.06)' },
      },
      {
        name: '威胁度',
        type: 'line',
        data: threatData.value,
        smooth: true,
        symbol: 'circle',
        symbolSize: 4,
        lineStyle: { color: '#ff646e', width: 2 },
        itemStyle: { color: '#ff646e' },
        areaStyle: { color: 'rgba(255,100,110,0.06)' },
      },
    ],
  }
}

function buildBarOption() {
  return {
    animation: false,
    backgroundColor: 'transparent',
    grid: { top: 16, right: 14, bottom: 24, left: 34 },
    xAxis: {
      type: 'category',
      data: ['攻击成功率', '检测成功率', '防御成功率'],
      axisLabel: { color: '#89a2ba', fontSize: 10 },
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.12)' } },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { color: '#89a2ba', fontSize: 9, formatter: '{value}%' },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.12)', type: 'dashed' } },
    },
    series: [
      {
        type: 'bar',
        barWidth: '40%',
        data: [
          { value: successRates.attack, itemStyle: { color: '#4bc8ff' } },
          { value: successRates.detect, itemStyle: { color: '#ffbe5c' } },
          { value: successRates.defense, itemStyle: { color: '#5dffb2' } },
        ],
        label: {
          show: true,
          position: 'inside',
          formatter: '{c}%',
          color: '#ffffff',
          fontSize: 11,
          fontWeight: 'bold',
        },
      },
    ],
  }
}

function refreshCharts() {
  lineChart?.setOption(buildLineOption(), true)
  barChart?.setOption(buildBarOption(), true)
}

function appendTelemetryPoint(payload) {
  if (!payload) return

  lineLabels.value.push(formatClock(new Date()))
  lineLabels.value.shift()

  const voltage = Number(payload.voltage || 0)
  const current = Number(payload.current || 0)
  const health = Math.max(0, Math.min(100, 100 - Math.max(0, voltage - 10) * 4 - Math.max(0, current - 80) * 0.15))
  const threat = Math.max(0, Math.min(100, Math.max(0, voltage - 10) * 6 + Math.max(0, current - 80) * 0.2))

  healthData.value.push(+health.toFixed(1))
  threatData.value.push(+threat.toFixed(1))
  healthData.value.shift()
  threatData.value.shift()
}

watch(
  () => props.attackEvent,
  (event) => {
    if (!event) return
    const config = getAttackProfile(event.type)
    metrics.availability.trend = 'down'
    metrics.integrity.trend = 'down'
    metrics.syncError.trend = event.type === 'timing' ? 'down' : 'neutral'
    animateMetrics(config.metrics.attack)
    successRates.attack = config.metrics.attack.attack
    successRates.detect = config.metrics.attack.detect
    successRates.defense = config.metrics.attack.defense
    refreshCharts()
  },
)

watch(
  () => props.defendEvent,
  (event) => {
    if (!event) return
    const config = getAttackProfile(event.type)
    metrics.availability.trend = 'up'
    metrics.integrity.trend = 'up'
    metrics.syncError.trend = 'up'
    animateMetrics(config.metrics.defend)
    successRates.detect = config.metrics.defend.detect
    successRates.defense = config.metrics.defend.defense
    refreshCharts()
  },
)

watch(
  () => props.resetEvent,
  (event) => {
    if (!event) return
    metrics.availability.trend = 'up'
    metrics.integrity.trend = 'up'
    metrics.syncError.trend = 'neutral'
    animateMetrics({ availability: 98.5, integrity: 99.2, syncError: 0.12 })
    successRates.attack = 0
    successRates.detect = 0
    successRates.defense = 0
    refreshCharts()
  },
)

watch(
  () => props.telemetry,
  (payload) => {
    if (!payload) return
    appendTelemetryPoint(payload)
    refreshCharts()
  },
  { deep: true },
)

onMounted(() => {
  initSeries()
  lineChart = echarts.init(lineChartRef.value)
  barChart = echarts.init(barChartRef.value)
  resizeHandler = () => {
    lineChart?.resize()
    barChart?.resize()
  }
  window.addEventListener('resize', resizeHandler)
  refreshCharts()
})

onUnmounted(() => {
  if (metricTimer) clearInterval(metricTimer)
  lineChart?.dispose()
  barChart?.dispose()
  if (resizeHandler) {
    window.removeEventListener('resize', resizeHandler)
  }
})
</script>

<style scoped>
.evaluation-shell {
  display: flex;
  flex-direction: column;
  gap: 9px;
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
  font-size: 18px;
}

.phase-box,
.runtime-box,
.context-box,
.metric-card {
  border: 1px solid var(--border-soft);
  border-radius: 14px;
  background: rgba(7, 17, 30, 0.72);
}

.phase-box,
.runtime-box,
.context-box {
  padding: 9px 11px;
}

.phase-box {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.phase-label,
.chart-title {
  color: var(--text-muted);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.phase-value {
  font-weight: 700;
}

.phase-value.standby {
  color: var(--text-secondary);
}

.phase-value.attacking {
  color: var(--brand-red);
}

.phase-value.defended {
  color: var(--brand-green);
}

.runtime-box,
.context-box {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  color: var(--text-secondary);
  font-size: 11px;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

.metric-card {
  padding: 9px 10px;
}

.metric-card header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: var(--text-muted);
  font-size: 11px;
}

.metric-value {
  margin-top: 6px;
  font-size: 20px;
  font-weight: 800;
}

.metric-value.up,
.metric-card strong.up {
  color: var(--brand-green);
}

.metric-value.down,
.metric-card strong.down {
  color: var(--brand-red);
}

.metric-value.neutral,
.metric-card strong.neutral {
  color: var(--brand-amber);
}

.metric-card p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 10px;
  line-height: 1.35;
}

.line-chart {
  height: 118px;
}

.bar-chart {
  height: 124px;
}

@media (max-width: 1280px) {
  .metrics-grid {
    grid-template-columns: 1fr;
  }
}
</style>
