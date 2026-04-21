const assetBase = typeof window === 'undefined' ? '' : window.location.origin

export const TOPOLOGY_NODES = [
  { id: 'time_sync', label: '时间同步系统', type: 'satellite', x: 50, y: 7 },
  { id: 'monitor_host', label: '监控主站', type: 'master', x: 50, y: 27 },
  { id: 'operator_station', label: '操作员站', type: 'gateway', x: 20, y: 42 },
  { id: 'data_server', label: '数据服务器', type: 'gateway', x: 80, y: 42 },
  { id: 'line_monitor', label: '线路测控', type: 'device', x: 50, y: 59 },
  { id: 'line_mu', label: '线路合并单元', type: 'device', x: 28, y: 81 },
  { id: 'breaker_it', label: '断路器智能终端', type: 'device', x: 72, y: 81 },
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

export const ATTACK_TIMELINES = {
  sensor: {
    sensorA: [
      { nodes: ['mechanical_sensor'], edges: [], summary: '机械传感器进入伪造上报状态。', consequences: ['机械传感器状态被伪造成 open。'] },
    ],
    sensorB: [
      { nodes: ['line_mu'], edges: [], summary: '线路合并单元被注入异常状态。', consequences: ['line_mu 开始上传失真测量值。'] },
    ],
  },
  control: {
    deviceB1: [
      { nodes: ['line_monitor'], edges: [], summary: '攻击者夺取 line_monitor 控制权，开始伪造下行控制。', consequences: ['line_monitor 的控制平面进入失控状态。'] },
      { nodes: ['line_monitor', 'breaker_it'], edges: ['e_lm_bit'], summary: '伪造合闸指令从 line_monitor 直达 breaker_it。', consequences: ['breaker_it 接收到异常合闸命令，现场执行风险迅速上升。'] },
      { nodes: ['line_monitor', 'breaker_it'], edges: ['e_lm_bit', 'e_bit_lm'], summary: '过压跳闸与自动重合闸保护被闭锁，异常状态持续。', consequences: ['breaker_it 状态回传继续误导上层控制视图，异常更难被自动收敛。'] },
    ],
  },
  alarm: {
    gatewayA: [
      { nodes: ['mechanical_sensor'], edges: ['e_sensor_bit'], summary: '异常先从现场状态上传链路出现。', consequences: ['现场状态虽然变化，但上层难以形成有效告警。'] },
      { nodes: ['mechanical_sensor', 'breaker_it'], edges: ['e_sensor_bit', 'e_bit_lm'], summary: '告警语义在设备侧被弱化。', consequences: ['断路器状态异常没有形成足够强的提醒。'] },
      { nodes: ['mechanical_sensor', 'breaker_it', 'line_monitor'], edges: ['e_sensor_bit', 'e_bit_lm', 'e_lm_mh'], summary: '线路测控接收到被压制的告警。', consequences: ['运行侧看到的风险等级被人为降低。'] },
      { nodes: ['mechanical_sensor', 'breaker_it', 'line_monitor'], edges: ['e_sensor_bit', 'e_bit_lm', 'e_lm_mh'], summary: '上行告警被持续压制。', consequences: ['主站获取不到完整的异常证据。'] },
    ],
    gatewayB: [
      { nodes: ['line_mu'], edges: ['e_lmu_lm'], summary: '线路合并单元异常开始上送。', consequences: ['异常存在，但还未形成有效告警。'] },
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
