const assetBase = typeof window === 'undefined' ? '' : window.location.origin

export const TOPOLOGY_NODES = [
  { id: 'time_sync', label: '时间同步系统', type: 'satellite', x: 50, y: 7 },
  { id: 'monitor_host', label: '监控主站', type: 'master', x: 50, y: 27 },
  { id: 'operator_station', label: '操作员站', type: 'gateway', x: 20, y: 42 },
  { id: 'data_server', label: '数据服务器', type: 'gateway', x: 80, y: 42 },
  { id: 'line_monitor', label: '线路监测主机', type: 'device', x: 50, y: 59 },
  { id: 'line_mu', label: '线路测量单元', type: 'device', x: 28, y: 81 },
  { id: 'breaker_it', label: '断路器间隔', type: 'device', x: 72, y: 81 },
  { id: 'mechanical_sensor', label: '机械传感器', type: 'sensor', x: 72, y: 95 },
]

export const TOPOLOGY_EDGES = [
  { id: 'e_ts_mh', source: 'time_sync', target: 'monitor_host', label: '时钟同步', lineType: 'dashed', curve: 0.0, flow: true },
  { id: 'e_ts_lmu', source: 'time_sync', target: 'line_mu', label: '时钟同步', lineType: 'dashed', curve: 0.1, flow: true },
  { id: 'e_ts_bit', source: 'time_sync', target: 'breaker_it', label: '时钟同步', lineType: 'dashed', curve: -0.1, flow: true },
  { id: 'e_os_mh', source: 'operator_station', target: 'monitor_host', label: '控制', lineType: 'solid', curve: 0.0, flow: true },
  { id: 'e_mh_ds', source: 'monitor_host', target: 'data_server', label: '数据', lineType: 'solid', curve: 0.0, flow: true },
  { id: 'e_mh_lm', source: 'monitor_host', target: 'line_monitor', label: '控制', lineType: 'solid', curve: 0.2, flow: true },
  { id: 'e_lm_mh', source: 'line_monitor', target: 'monitor_host', label: '数据', lineType: 'solid', curve: 0.2, flow: true },
  { id: 'e_lmu_lm', source: 'line_mu', target: 'line_monitor', label: '状态', lineType: 'solid', curve: 0.2, flow: true },
  { id: 'e_lm_bit', source: 'line_monitor', target: 'breaker_it', label: '控制', lineType: 'solid', curve: -0.2, flow: true },
  { id: 'e_bit_lm', source: 'breaker_it', target: 'line_monitor', label: '状态', lineType: 'solid', curve: -0.2, flow: true },
  { id: 'e_sensor_bit', source: 'mechanical_sensor', target: 'breaker_it', label: '位姿', lineType: 'solid', curve: -0.1, flow: true },
]

export const NODE_ICON_MAP = {
  satellite: `${assetBase}/icons/satellite.svg`,
  master: `${assetBase}/icons/master.svg`,
  gateway: `${assetBase}/icons/gateway.svg`,
  device: `${assetBase}/icons/device.svg`,
  sensor: `${assetBase}/icons/sensor.svg`,
}

export const NODE_SIZE_MAP = {
  satellite: 56,
  master: 60,
  gateway: 48,
  device: 44,
  sensor: 38,
}

export const TOPOLOGY_LEGEND = [
  '卫星: 时间同步系统',
  '主站: 监控中心节点',
  '网关: 站端接入节点',
  '设备: 一次/二次装置',
  '传感器: 现场状态源',
]

export const ATTACK_TIMELINES = {
  sensor: {
    sensorA: [
      { nodes: ['mechanical_sensor'], edges: [], summary: '机械传感器进入伪造上报状态。', consequences: ['机械传感器状态被伪造成 open。'] },
    ],
    sensorB: [
      { nodes: ['line_mu'], edges: [], summary: '线路测量单元被注入异常状态。', consequences: ['line_mu 开始上传失真测量值。'] },
    ],
  },
  control: {
    deviceA1: [
      { nodes: ['line_monitor'], edges: [], summary: '控制链路从线路监测主机开始被劫持。', consequences: ['控制视图开始偏离真实设备状态。'] },
      { nodes: ['line_monitor', 'breaker_it', 'line_mu'], edges: ['e_lm_bit', 'e_lmu_lm'], summary: '恶意控制下发到关键设备。', consequences: ['断路器与线路测量单元进入异常联动风险。'] },
      { nodes: ['line_monitor', 'breaker_it', 'line_mu'], edges: ['e_lm_bit', 'e_lmu_lm', 'e_bit_lm'], summary: '状态回传被污染，形成闭环误导。', consequences: ['主站对现场状态的判断进一步失真。'] },
    ],
    deviceA2: [
      { nodes: ['line_monitor'], edges: [], summary: '线路测量单元关联链路被锁定。', consequences: ['测量与控制之间的边界开始模糊。'] },
      { nodes: ['line_monitor', 'line_mu', 'breaker_it'], edges: ['e_lmu_lm', 'e_lm_bit'], summary: 'line_mu 与 breaker_it 同时被波及。', consequences: ['控制误导扩散到关键设备。'] },
      { nodes: ['line_monitor', 'line_mu', 'breaker_it'], edges: ['e_lmu_lm', 'e_lm_bit', 'e_bit_lm'], summary: '控制回路形成异常闭环。', consequences: ['现场动作与上位监控都受到影响。'] },
    ],
    deviceB1: [
      { nodes: ['monitor_host'], edges: [], summary: '主站控制意图被恶意劫持。', consequences: ['站端控制开始偏离真实操作意图。'] },
      { nodes: ['monitor_host', 'line_monitor', 'data_server'], edges: ['e_mh_lm', 'e_mh_ds'], summary: '主站到站端链路同时受扰。', consequences: ['数据和控制通道一起受到牵连。'] },
      { nodes: ['monitor_host', 'line_monitor', 'data_server'], edges: ['e_mh_lm', 'e_mh_ds', 'e_lm_mh'], summary: '上行回传被污染。', consequences: ['主站看到的是被回写过的状态。'] },
    ],
    deviceB2: [
      { nodes: ['operator_station'], edges: [], summary: '操作员侧入口被劫持。', consequences: ['人工操作指令的可信度下降。'] },
      { nodes: ['operator_station', 'monitor_host', 'data_server'], edges: ['e_os_mh', 'e_mh_ds'], summary: '站控路径向主站扩散。', consequences: ['主站与数据服务器同时进入风险域。'] },
      { nodes: ['operator_station', 'monitor_host', 'data_server'], edges: ['e_os_mh', 'e_mh_ds', 'e_lm_mh'], summary: '异常影响回流到监测平面。', consequences: ['控制面与观测面同步失真。'] },
    ],
  },
  alarm: {
    gatewayA: [
      { nodes: ['mechanical_sensor'], edges: ['e_sensor_bit'], summary: '异常先从现场状态上传链路出现。', consequences: ['现场状态虽然变化，但上层难以形成有效告警。'] },
      { nodes: ['mechanical_sensor', 'breaker_it'], edges: ['e_sensor_bit', 'e_bit_lm'], summary: '告警语义在设备侧被弱化。', consequences: ['断路器状态异常没有形成足够强的提醒。'] },
      { nodes: ['mechanical_sensor', 'breaker_it', 'line_monitor'], edges: ['e_sensor_bit', 'e_bit_lm', 'e_lm_mh'], summary: '线路监测主机接收到被压制的告警。', consequences: ['运行侧看到的风险等级被人为降低。'] },
      { nodes: ['mechanical_sensor', 'breaker_it', 'line_monitor'], edges: ['e_sensor_bit', 'e_bit_lm', 'e_lm_mh'], summary: '上行告警被持续压制。', consequences: ['主站获取不到完整的异常证据。'] },
    ],
    gatewayB: [
      { nodes: ['line_mu'], edges: ['e_lmu_lm'], summary: '线路测量异常开始上送。', consequences: ['异常存在，但还未形成有效告警。'] },
      { nodes: ['line_mu', 'line_monitor'], edges: ['e_lmu_lm', 'e_lm_mh'], summary: '告警在站端主机被压制。', consequences: ['上位系统只能看到被削弱的风险信息。'] },
      { nodes: ['line_mu', 'line_monitor', 'monitor_host'], edges: ['e_lmu_lm', 'e_lm_mh'], summary: '监控主站收到失真告警。', consequences: ['主站态势图对异常严重度判断不足。'] },
      { nodes: ['line_mu', 'line_monitor', 'monitor_host'], edges: ['e_lmu_lm', 'e_lm_mh', 'e_mh_ds'], summary: '告警压制影响数据留痕。', consequences: ['后续追溯时证据完整性下降。'] },
    ],
  },
  timing: {
    auto: [
      { nodes: ['time_sync'], edges: [], summary: '时间同步源开始出现偏移。', consequences: ['核心时钟源可信度下降。'] },
      { nodes: ['time_sync'], edges: ['e_ts_mh', 'e_ts_lmu', 'e_ts_bit'], summary: '偏移时标向关键节点扩散。', consequences: ['多个节点开始收到异常时间戳。'] },
      { nodes: ['time_sync', 'monitor_host', 'line_mu', 'breaker_it'], edges: ['e_ts_mh', 'e_ts_lmu', 'e_ts_bit'], summary: '关键控制与测量节点同时受扰。', consequences: ['联动顺序与事件先后关系变得不可靠。'] },
      { nodes: ['time_sync', 'monitor_host', 'operator_station', 'data_server', 'line_monitor', 'line_mu', 'breaker_it', 'mechanical_sensor'], edges: ['e_ts_mh', 'e_ts_lmu', 'e_ts_bit', 'e_os_mh', 'e_mh_ds', 'e_mh_lm', 'e_lmu_lm', 'e_lm_bit', 'e_sensor_bit'], summary: '全局态势受到时标偏移波及。', consequences: ['运行全景对事件因果的判断被严重干扰。'] },
    ],
  },
  swarm: {
    auto: [
      { nodes: [], edges: ['e_lm_bit', 'e_lmu_lm', 'e_mh_lm'], summary: '多点协同攻击开始同时施压。', consequences: ['多条关键边进入并发异常状态。'] },
      { nodes: ['breaker_it', 'line_mu', 'line_monitor'], edges: ['e_lm_bit', 'e_lmu_lm', 'e_mh_lm'], summary: '站端设备汇聚区出现联动异常。', consequences: ['控制、状态和上行通道同步受扰。'] },
      { nodes: ['breaker_it', 'line_mu', 'line_monitor', 'monitor_host'], edges: ['e_lm_bit', 'e_lmu_lm', 'e_mh_lm', 'e_bit_lm', 'e_lm_mh'], summary: '主站与站端之间形成复合压力。', consequences: ['系统可观察性和可控性同时下降。'] },
    ],
  },
}

export function getTimeline(attackId, targetId) {
  const scoped = ATTACK_TIMELINES[attackId]
  if (!scoped) return []
  return scoped[targetId] || scoped.auto || []
}

export function validateTopology() {
  const nodeIds = new Set(TOPOLOGY_NODES.map((node) => node.id))
  const edgeIds = new Set(TOPOLOGY_EDGES.map((edge) => edge.id))
  const errors = []

  for (const [attackId, variants] of Object.entries(ATTACK_TIMELINES)) {
    for (const [variantId, steps] of Object.entries(variants)) {
      steps.forEach((step, stepIndex) => {
        step.nodes.forEach((nodeId) => {
          if (!nodeIds.has(nodeId)) {
            errors.push(`Unknown node "${nodeId}" in ${attackId}/${variantId}/step-${stepIndex + 1}`)
          }
        })
        step.edges.forEach((edgeId) => {
          if (!edgeIds.has(edgeId)) {
            errors.push(`Unknown edge "${edgeId}" in ${attackId}/${variantId}/step-${stepIndex + 1}`)
          }
        })
      })
    }
  }

  return errors
}
