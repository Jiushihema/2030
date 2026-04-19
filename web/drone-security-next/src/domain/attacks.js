export const ATTACK_STEP_INTERVAL_MS = 1800

export const ATTACKS = {
  sensor: {
    id: 'sensor',
    label: '传感器欺骗',
    icon: 'S',
    description: '伪造一次设备侧的传感器状态上报，让监测链路误判开关位姿并触发错误联动。',
    targetMode: 'manual',
    targets: [
      { id: 'sensorA', label: '机械传感器 mechanical_sensor', focusNodeId: 'mechanical_sensor' },
      { id: 'sensorB', label: '线路测量单元 line_mu', focusNodeId: 'line_mu' },
    ],
    commands: {
      attack: '1-2-on',
      defend: '1-2-off',
    },
    durations: {
      steps: 1,
      totalMs: ATTACK_STEP_INTERVAL_MS * 2 + 500,
    },
    resultCopy: {
      defended: {
        title: '防御联动生效',
        impacts: ['伪造状态被隔离，异常未进一步传导。', '控制链路恢复正常状态，同步保留审计痕迹。', '设备维持在安全工况。'],
      },
      danger: {
        title: '攻击持续造成误判',
        impacts: ['错误状态继续向上送达，运行人员得到失真反馈。', '控制侧可能触发不必要联动，造成误操作风险。', '后续过载场景会更难被正确识别。'],
      },
    },
    metrics: {
      attack: { availability: 75, integrity: 12, syncError: 0.15, attack: 78, detect: 65, defense: 0 },
      defend: { availability: 96, integrity: 97, syncError: 0.13, detect: 88, defense: 92 },
    },
    evidence: {
      standby: {
        title: '传感器欺骗攻击链路',
        items: [
          '目标点位为设备侧传感器上报链路，影响 breaker_it 与 line_monitor 的状态判断。',
          '前端将根据遥测和攻击阶段展示状态异常、告警与恢复过程。',
        ],
      },
      attacking: {
        title: '传感器欺骗进行中',
        items: [
          '伪造的开关位姿开始替代真实状态上报。',
          '拓扑图将突出状态上传路径，并标记传感器节点异常。',
          '若当前线路已过载，右侧评估会显示更高威胁等级。',
        ],
      },
      defended: {
        title: '传感器欺骗已被处置',
        items: [
          '防守动作撤销伪造命令，状态上传恢复真实值。',
          '系统保持记录该次异常，为后续审计留存证据。',
        ],
      },
    },
  },
  control: {
    id: 'control',
    label: '恶意控制',
    icon: 'C',
    description: '伪造控制报文影响 breaker_it 与 line_monitor 的动作逻辑，制造异常跳闸或控制偏转。',
    targetMode: 'manual',
    targets: [
      { id: 'deviceA1', label: '断路器间隔 breaker_it', focusNodeId: 'breaker_it' },
      { id: 'deviceA2', label: '线路测量单元 line_mu', focusNodeId: 'line_mu' },
      { id: 'deviceB1', label: '线路监测主机 line_monitor', focusNodeId: 'line_monitor' },
      { id: 'deviceB2', label: '监控主站 monitor_host', focusNodeId: 'monitor_host' },
    ],
    commands: {
      attack: '5-on',
      defend: '5-off',
    },
    durations: {
      steps: 3,
      totalMs: ATTACK_STEP_INTERVAL_MS * 3 + 500,
    },
    resultCopy: {
      defended: {
        title: '控制链路已回收',
        impacts: ['控制命令被阻断，关键设备恢复人工确认流程。', '联动风险降低，数据面和控制面重新分离。', '后续只保留状态观测与安全审计。'],
      },
      danger: {
        title: '恶意控制持续存在',
        impacts: ['断路器与线路设备可能收到错误动作指令。', '异常联动会扰动正常运行工况。', '中控与现场设备的信任边界被进一步削弱。'],
      },
    },
    metrics: {
      attack: { availability: 45, integrity: 60, syncError: 0.18, attack: 85, detect: 70, defense: 0 },
      defend: { availability: 94, integrity: 95, syncError: 0.16, detect: 85, defense: 88 },
    },
    evidence: {
      standby: {
        title: '恶意控制攻击链路',
        items: [
          '攻击目标覆盖断路器间隔、线路测量单元、监测主机等控制路径关键点。',
          '页面会按阶段展示控制侵入、动作扩散与恢复过程。',
        ],
      },
      attacking: {
        title: '恶意控制进行中',
        items: [
          '攻击者通过伪造控制命令影响下行链路。',
          '拓扑图将突出控制传播路径和被影响设备。',
          '评估面板会同步刷新攻击成功率和防守缺口。',
        ],
      },
      defended: {
        title: '恶意控制已被阻断',
        items: [
          '控制平面恢复受控状态，关键节点重新进入可信模式。',
          '系统保留事件痕迹，为追踪来源与复盘提供依据。',
        ],
      },
    },
  },
  alarm: {
    id: 'alarm',
    label: '告警压制',
    icon: 'A',
    description: '通过压制关键链路上的告警或异常提示，让运行人员丧失对故障演化的感知。',
    targetMode: 'manual',
    targets: [
      { id: 'gatewayA', label: '线路监测主机 line_monitor', focusNodeId: 'line_monitor' },
      { id: 'gatewayB', label: '监控主站 monitor_host', focusNodeId: 'monitor_host' },
    ],
    commands: {
      attack: '3-1-on',
      defend: '3-1-off',
    },
    durations: {
      steps: 4,
      totalMs: ATTACK_STEP_INTERVAL_MS * 4 + 500,
    },
    resultCopy: {
      defended: {
        title: '告警链路恢复',
        impacts: ['异常事件重新可见，运行视野恢复完整。', '主站与站端之间的告警上传重新贯通。', '后续处置可以基于真实证据开展。'],
      },
      danger: {
        title: '告警仍被压制',
        impacts: ['异常未及时暴露，处置窗口被延误。', '运行人员只能看到表面正常的状态。', '系统对复合攻击的识别能力进一步下降。'],
      },
    },
    metrics: {
      attack: { availability: 60, integrity: 55, syncError: 0.14, attack: 72, detect: 58, defense: 0 },
      defend: { availability: 95, integrity: 94, syncError: 0.13, detect: 82, defense: 85 },
    },
    evidence: {
      standby: {
        title: '告警压制攻击链路',
        items: [
          '重点影响告警上传和主站侧感知能力。',
          '视觉上表现为链路通行但风险提示不足。',
        ],
      },
      attacking: {
        title: '告警压制进行中',
        items: [
          '异常信号被吞没或降级，主站难以及时感知风险。',
          '部分上行链路仍可见，但告警语义已经失真。',
        ],
      },
      defended: {
        title: '告警压制已解除',
        items: [
          '告警恢复显示，运行员可重新获得完整态势。',
          '异常点位继续保留高亮，便于后续处理。',
        ],
      },
    },
  },
  timing: {
    id: 'timing',
    label: '时钟扰动',
    icon: 'T',
    description: '扰动时间同步系统，让关键节点收到偏移时标，从而影响顺序事件判断与联动时序。',
    targetMode: 'auto',
    autoTargetLabel: '时间同步系统及关联节点',
    commands: {
      attack: '4-on',
      defend: '4-off',
    },
    durations: {
      steps: 4,
      totalMs: ATTACK_STEP_INTERVAL_MS * 4 + 500,
    },
    resultCopy: {
      defended: {
        title: '时钟同步已修复',
        impacts: ['关键节点重新对齐时标。', '事件顺序与联动判断恢复可信。', '同步误差回落到安全区间。'],
      },
      danger: {
        title: '时钟仍受扰动',
        impacts: ['多节点事件顺序可能被误判。', '时序相关联动的可信度降低。', '攻击链溯源会受到额外干扰。'],
      },
    },
    metrics: {
      attack: { availability: 30, integrity: 70, syncError: 8.5, attack: 90, detect: 75, defense: 0 },
      defend: { availability: 92, integrity: 96, syncError: 0.2, detect: 90, defense: 94 },
    },
    evidence: {
      standby: {
        title: '时钟扰动攻击链路',
        items: [
          '影响对象是 time_sync 以及依赖它的核心节点。',
          '评估中同步误差将是最关键指标。',
        ],
      },
      attacking: {
        title: '时钟扰动进行中',
        items: [
          '同步报文向多个节点扩散，时标偏移逐步累积。',
          '页面会展示时钟链路传播和同步异常上升。',
        ],
      },
      defended: {
        title: '时钟扰动已被恢复',
        items: [
          '时间同步源重新可信，链路回到正常偏差范围。',
          '运行评估中的同步误差已回归低值。',
        ],
      },
    },
  },
  swarm: {
    id: 'swarm',
    label: '多点协同攻击',
    icon: 'W',
    description: '对多条关键链路进行并发干扰，形成更强的覆盖面与联动压制效果。',
    targetMode: 'auto',
    autoTargetLabel: '站端控制链路与设备汇聚区',
    commands: {
      attack: null,
      defend: null,
    },
    durations: {
      steps: 3,
      totalMs: ATTACK_STEP_INTERVAL_MS * 3 + 500,
    },
    resultCopy: {
      defended: {
        title: '协同攻击被拆解',
        impacts: ['关键路径逐步恢复，系统重新获得可控性。', '多源干扰被压缩在局部区域内。', '剩余风险主要停留在观测和清理阶段。'],
      },
      danger: {
        title: '协同攻击保持压力',
        impacts: ['多点位同时受扰，运行员视角快速收缩。', '局部恢复无法覆盖全部链路。', '系统承受更大的连续异常压力。'],
      },
    },
    metrics: {
      attack: { availability: 15, integrity: 40, syncError: 0.2, attack: 95, detect: 80, defense: 0 },
      defend: { availability: 90, integrity: 93, syncError: 0.18, detect: 88, defense: 91 },
    },
    evidence: {
      standby: {
        title: '多点协同攻击链路',
        items: [
          '多条链路将被同时施压，展示效果会覆盖控制、状态和上行通道。',
          '该模式更适合用于展示系统在复合攻击下的整体脆弱面。',
        ],
      },
      attacking: {
        title: '多点协同攻击进行中',
        items: [
          '多个设备与链路同时进入异常传播态。',
          '拓扑会显示多条高亮边，右侧指标快速下探。',
        ],
      },
      defended: {
        title: '多点协同攻击已收敛',
        items: [
          '关键链路被逐步清理，系统恢复观察和控制能力。',
          '剩余工作聚焦于状态核验和事件复盘。',
        ],
      },
    },
  },
}

export const ATTACK_ORDER = ['sensor', 'control', 'alarm', 'timing', 'swarm']

export function getAttackDefinition(attackId) {
  return ATTACKS[attackId] || ATTACKS.sensor
}
