# 前端扩展使用指南

这份指南面向后续要继续维护 `drone-security-next` 的开发者，目标是两件事：

1. 让你知道这套前端现在的“真相源”分别放在哪里。
2. 让你在新增攻击、接入后端、修改拓扑或调整页面时，不会再回到旧版那种四处写死的状态。

---

## 1. 项目定位

当前新前端不是简单复刻旧页面，而是把旧版里分散的攻击配置、拓扑路径、评估指标和运行态调度，重新收拢成了几层：

- `domain/`：业务配置与规则
- `composables/`：运行态调度、接口桥接、场景切换
- `components/panels/`：三栏页面展示
- `components/layout/`：页头等布局组件
- `vite.config.js`：开发态桥接后端 TCP 服务

现在最重要的设计原则只有一句话：

> 新增一个攻击时，优先改配置和规则，不要先改组件。

---

## 2. 目录职责

### 2.1 核心文件

- `src/domain/attacks.js`
  - 攻击定义主表。
  - 管理攻击顺序、名称、图标、目标列表、后端命令、时长、结果文案、评估指标、证据内容。

- `src/domain/attackProfiles.js`
  - 攻击扩展语义层。
  - 管理“影响焦点”“传播焦点”“是否真实桥接”“后端能力说明”等 UI 层语义。
  - 如果后端还没实现完整攻击，这里就是你告诉前端“这是推演，不是真实注入”的地方。

- `src/domain/topology.js`
  - 拓扑节点、边、图标、攻击传播时间线。
  - 新增目标、调整传播路径、修复节点联动时，优先改这里。

- `src/domain/runtime.js`
  - 遥测格式化和线路状态判断。
  - 负责把 telemetry 转成页面可直接展示的运行时信息。

- `src/domain/phases.js`
  - 页面阶段常量。
  - 当前是 `idle / attacking / defended`。

- `src/composables/useControlTower.js`
  - 前端运行态中枢。
  - 负责：
    - 当前攻击/目标选择
    - 自动防御与手动防御
    - `/api/telemetry` 拉取
    - `/api/telemetry/stream` 订阅
    - `/api/attack` 命令发送
    - 攻击触发、收敛、复位

- `src/components/panels/AttackPanel.vue`
  - 左侧攻击编排栏。
  - 只负责展示和事件抛出，不应该再承担业务真相。

- `src/components/panels/TopologyPanel.vue`
  - 中间拓扑传播面板。
  - 根据 `attackEvent / defendEvent / resetEvent / telemetry` 演示传播过程。

- `src/components/panels/EvaluationPanel.vue`
  - 右侧评估面板。
  - 根据攻击配置和遥测结果生成指标趋势与成功率展示。

- `src/components/layout/AppHeader.vue`
  - 顶栏。

- `vite.config.js`
  - 本地开发时把 Vite 变成“前端 + 后端桥接器”。
  - 当前桥接：
    - `9998`：遥测 TCP
    - `9999`：攻击命令 TCP

---

## 3. 当前扩展模型

当前攻击分两类：

### 3.1 已接真实后端桥接

- `sensor`
- `control`

这两类会真正走 `/api/attack`，再由 `vite.config.js` 转发到后端命令口。

### 3.2 当前仍是前端推演

- `alarm`
- `timing`
- `swarm`

这三类现在的目标是：

- 页面可演示
- 拓扑会传播
- 右侧评估会变化
- 但不会真的向后端注入对应攻击

这不是问题，反而是当前合理设计。  
因为你的后端本来就没有完整实现五种攻击，所以前端必须明确区分：

- 哪些是“真实桥接”
- 哪些是“演示推演”

这层区分现在主要由 `src/domain/attackProfiles.js` 管理。

---

## 4. 运行方式

### 4.1 启动后端

在项目根目录运行：

```powershell
python demo/run_scenario.py
```

### 4.2 启动新前端

进入：

```powershell
cd web/drone-security-next
npm run dev
```

### 4.3 构建验证

```powershell
npm run build
```

当前这套新前端已经可以通过构建。

---

## 5. 最常见扩展场景

## 5.1 新增一个“前端推演型攻击”

如果后端还没实现，但你想先把页面演示做出来，这是最简单的扩展方式。

### 步骤 1：在 `src/domain/attacks.js` 里增加攻击定义

你至少要补这些字段：

```js
newAttack: {
  id: 'newAttack',
  label: '新攻击',
  icon: 'N',
  description: '攻击说明',
  targetMode: 'manual', // 或 auto
  targets: [
    { id: 'targetA', label: '目标A', focusNodeId: 'line_monitor' },
  ],
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
      title: '防御后结果',
      impacts: ['影响 1', '影响 2'],
    },
    danger: {
      title: '未防御结果',
      impacts: ['风险 1', '风险 2'],
    },
  },
  metrics: {
    attack: { availability: 60, integrity: 70, syncError: 1.2, attack: 82, detect: 65, defense: 0 },
    defend: { availability: 94, integrity: 95, syncError: 0.2, detect: 86, defense: 90 },
  },
  evidence: {
    standby: { title: '待命证据', items: ['证据 1'] },
    attacking: { title: '攻击中证据', items: ['证据 2'] },
    defended: { title: '防御后证据', items: ['证据 3'] },
  },
}
```

### 步骤 2：把攻击加入顺序

更新：

```js
export const ATTACK_ORDER = [...]
```

### 步骤 3：在 `src/domain/attackProfiles.js` 里补充语义

告诉前端这类攻击是桥接还是真实推演：

```js
newAttack: {
  selectionLabel: '传播焦点',
  targetHint: '当前版本暂无后端注入命令，选择项用于编排前端传播路径。',
  backendMode: 'simulation',
  backendBadge: '前端推演',
  backendTone: 'simulation',
  backendLabel: '后端能力：未接入该攻击，当前为前端推演。',
  executionLabel: '执行方式：三段式传播演示',
}
```

### 步骤 4：在 `src/domain/topology.js` 里补攻击时间线

补到 `ATTACK_TIMELINES`：

```js
newAttack: {
  targetA: [
    { nodes: ['line_monitor'], edges: [], summary: '第一阶段', consequences: ['影响描述'] },
    { nodes: ['line_monitor', 'breaker_it'], edges: ['e_lm_bit'], summary: '第二阶段', consequences: ['进一步影响'] },
  ],
}
```

### 步骤 5：验证

你要确认：

- 左侧能显示新攻击
- 目标切换正常
- 中间拓扑会按时间线传播
- 右侧指标和成功率会变化
- 手动防御和恢复正常都能收敛

---

## 5.2 把一个“前端推演型攻击”升级为“真实后端桥接攻击”

这是后面最重要的一类扩展。

### 步骤 1：先确认后端命令

你需要明确：

- 攻击开启命令是什么
- 攻击关闭命令是什么
- 后端是否支持目标级别区分

比如：

```js
commands: {
  attack: '7-on',
  defend: '7-off',
}
```

### 步骤 2：修改 `src/domain/attacks.js`

把 `commands.attack / commands.defend` 从 `null` 改成真实命令。

### 步骤 3：修改 `src/domain/attackProfiles.js`

把：

```js
backendMode: 'simulation'
```

改成：

```js
backendMode: 'bridge'
```

或如果仍是通道级、不是真正按目标细分：

```js
backendMode: 'coarse-bridge'
```

这一步很重要，因为它决定左侧和状态文案会不会误导用户。

### 步骤 4：如果后端支持目标级命令，再扩展 `useControlTower.js`

当前 `useControlTower.js` 发送的是攻击类型级命令。  
如果以后后端真的支持不同目标不同命令，建议不要在组件里写 `if/else`，而是把命令也配置化，比如：

```js
commands: {
  attackByTarget: {
    targetA: '7-1-on',
    targetB: '7-2-on',
  },
  defendByTarget: {
    targetA: '7-1-off',
    targetB: '7-2-off',
  },
}
```

然后在 `useControlTower.js` 里统一解析：

```js
function resolveAttackCommand(attack, targetId) { ... }
function resolveDefendCommand(attack, targetId) { ... }
```

这样比继续堆 `if (attack.id === ...)` 更可维护。

---

## 5.3 新增攻击目标

如果只是给已有攻击加一个新目标，比如 `control` 增加一个设备：

### 改 1：`src/domain/attacks.js`

在该攻击的 `targets` 里新增：

```js
{ id: 'deviceC1', label: '新设备', focusNodeId: 'monitor_host' }
```

### 改 2：`src/domain/topology.js`

在 `ATTACK_TIMELINES.control.deviceC1` 里补它的传播时间线。

如果不补这里，左侧虽然能选，但中间拓扑不会有合理传播。

---

## 5.4 新增一个拓扑节点

### 步骤 1：在 `TOPOLOGY_NODES` 增加节点

```js
{ id: 'new_node', label: '新节点', type: 'device', x: 40, y: 66 }
```

### 步骤 2：如果需要，新增图标类型

更新：

- `NODE_ICON_MAP`
- `NODE_SIZE_MAP`

### 步骤 3：增加边

在 `TOPOLOGY_EDGES` 里增加新边：

```js
{ id: 'e_new_old', source: 'new_node', target: 'line_monitor', label: '状态回传', lineType: 'solid', curve: 0.1, flow: true }
```

### 步骤 4：把新节点接入某个攻击时间线

否则只是静态展示，不能参与传播。

### 步骤 5：执行拓扑校验

`TopologyPanel.vue` 挂载时会调用 `validateTopology()`。  
只要你的时间线里引用了不存在的节点或边，控制台会直接报警。

这就是新前端相对旧版更安全的地方。

---

## 5.5 修改右侧评估逻辑

右侧评估现在主要依赖三部分：

### 指标来源

在 `src/domain/attacks.js`：

```js
metrics: {
  attack: {...},
  defend: {...},
}
```

### 阶段切换

在 `src/composables/useControlTower.js`：

- `phase`
- `attackEvent`
- `defendEvent`
- `resetEvent`

### 面板渲染

在 `src/components/panels/EvaluationPanel.vue`

如果你只是想改分数、证据、标题，优先改 `attacks.js`。  
只有当你想改“图表计算方式”或“显示结构”时，才改 `EvaluationPanel.vue`。

---

## 5.6 修改左侧面板布局

左侧已经被压缩过一轮，现在扩展建议是：

- 攻击项尽量保持“短信息卡片”
- 不要再把大段业务说明塞回攻击列表
- 说明类内容尽量放到“场景说明”
- 交互按钮尽量保持单行短按钮

如果你要继续压缩左栏，优先改：

- `AttackPanel.vue` 的模板层级
- `AttackPanel.vue` 的 `.attack-card`、`.description-card`、`.toggle-row`、`.action-row`

不要去改业务逻辑。

---

## 5.7 修改中间拓扑面板

中间拓扑的改法建议分成两类：

### 只改视觉

改：

- `TopologyPanel.vue` 的样式
- ECharts option 中的颜色、线宽、symbolSize

### 改传播逻辑

优先改：

- `src/domain/topology.js`

不要在 `TopologyPanel.vue` 里继续塞攻击分支逻辑。  
旧版最大的问题之一就是这里写死太多。

---

## 5.8 修改顶部栏

顶栏现在已经尽量压成工具条式结构了。

如果还要继续缩：

- 改 `AppHeader.vue`
- 尽量只保留：
  - 平台标题
  - 线路状态徽标

不要再把电压、电流、传感器等重复信息放回去，因为这些内容已经在中栏或右栏出现过。

---

## 6. 推荐扩展顺序

如果你后面继续开发，我建议按这个顺序推进：

### 第一阶段：补真实后端攻击

优先把后端真正能支持的攻击补齐，例如：

1. `sensor`
2. `control`
3. 未来如果有 `alarm` 命令，再升级 `alarm`

### 第二阶段：把命令解析彻底配置化

也就是把：

- 固定 `attack.commands.attack`
- 固定 `attack.commands.defend`

升级成：

- 按目标分发命令
- 按攻击类型映射命令

### 第三阶段：把 telemetry 和评估再耦合得更紧

例如：

- 某些指标直接由遥测推导
- 某些证据根据 telemetry 动态切换

这会让右栏比现在更可信。

---

## 7. 当前已知限制

这部分很重要，扩展前最好先知道。

### 7.1 不是五种攻击都已真实桥接

当前真实桥接主要还是：

- `sensor`
- `control`

其余攻击属于前端推演。

### 7.2 当前“目标选择”对真实后端仍不一定是目标级别

即使是桥接攻击，后端也可能仍是通道级命令，而不是设备级命令。  
所以你要区分：

- 页面聚焦目标
- 后端真实执行目标

这也是为什么新增了 `attackProfiles.js`。

### 7.3 旧版逻辑问题不要再搬回来

重点避免：

- 在组件里硬编码攻击分支
- 一个攻击在 3 个组件里维护 3 份规则
- 恢复正常时伪造错误的 defendEvent
- 目标可选但逻辑不生效

---

## 8. 扩展时的检查清单

每次改完，至少检查这 8 项：

1. 左侧是否能正确显示新攻击或新目标。
2. 目标切换后，中间拓扑是否真的变化。
3. 右侧评估是否跟着当前攻击变化。
4. 自动防御和立即防御是否都能收敛。
5. 恢复正常后，三个栏的状态是否一起复位。
6. `validateTopology()` 是否无错误。
7. `npm run build` 是否通过。
8. 如果是桥接攻击，后端是否真的收到了命令。

---

## 9. 一条最实用的维护规则

以后你看到一个需求，先判断它属于哪一层：

- 攻击定义变了：改 `attacks.js`
- 攻击语义变了：改 `attackProfiles.js`
- 拓扑传播变了：改 `topology.js`
- 运行调度变了：改 `useControlTower.js`
- 只是显示变了：改 `*.vue`

只要你能守住这条规则，这个新前端就不会再退化回旧版那种“代码能跑，但扩展一次就要全局找字符串”的状态。

---

## 10. 推荐的下一步

如果你后面继续做，我最推荐的三个方向是：

1. 把真实后端命令继续补齐到更多攻击类型。
2. 把桥接攻击的命令解析改成按目标配置，而不是固定命令。
3. 为 `attacks.js` 和 `topology.js` 各补一份简单 schema 校验，进一步防止配置写错。

如果你愿意，下一轮我可以继续直接帮你做这份指南对应的第一步落地：

- 把攻击命令解析抽成配置化函数
- 或者继续补一类真实桥接攻击的接入结构
