# drone-security-next

这是当前使用中的新前端工程，用来替代旧版演示脚本式前端。

## 目标

- 保持三栏演示效果
- 收拢攻击、拓扑、评估的真相源
- 让后续新增攻击、目标和传播路径时优先改配置而不是改组件

## 关键目录

- `src/domain/attacks.js`
  - 攻击定义、目标、命令、结果文案、指标、证据
- `src/domain/attackProfiles.js`
  - 攻击语义层，区分真实桥接和前端推演
- `src/domain/topology.js`
  - 拓扑节点、边和攻击传播时间线
- `src/composables/useControlTower.js`
  - 运行态调度中心
- `src/components/panels/`
  - 左中右三栏面板

## 运行

先在仓库根目录启动后端：

```powershell
python demo/run_scenario.py
```

再在当前目录启动前端：

```powershell
npm run dev
```

## 构建

```powershell
npm run build
```

## 说明

当前真实后端桥接主要覆盖：

- `sensor`
- `control`

其余攻击目前以前端推演为主，但拓扑、评估和阶段切换都已接入统一配置层。

更详细的扩展规则见：

- [FRONTEND_EXTENSION_GUIDE.md](C:/Users/hema/Desktop/2030/web/drone-security-next/FRONTEND_EXTENSION_GUIDE.md)
