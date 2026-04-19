# 2030 电力攻防演示项目

这个仓库包含一个电力场景仿真后端，以及一套新的前端演示界面。

## 目录

- `demo/`
  - 场景启动与攻击控制入口。
- `devices/`
  - 设备侧仿真逻辑。
- `common/`
  - 总线、拓扑和通用消息定义。
- `config/`
  - 配置文件。
- `web/drone-security-next/`
  - 当前使用中的新前端。
- `docs/`
  - 项目文档与表格资料。

## 前端现状

旧前端已移除，当前前端为：

- [web/drone-security-next](C:/Users/hema/Desktop/2030/web/drone-security-next)

新前端的特点：

- 攻击定义集中在 `src/domain/attacks.js`
- 攻击语义集中在 `src/domain/attackProfiles.js`
- 拓扑传播集中在 `src/domain/topology.js`
- 运行态调度集中在 `src/composables/useControlTower.js`

## 启动方式

先启动后端：

```powershell
python demo/run_scenario.py
```

再启动前端：

```powershell
cd web/drone-security-next
npm run dev
```

## 构建验证

```powershell
cd web/drone-security-next
npm run build
```

## 扩展文档

详细前端扩展说明见：

- [FRONTEND_EXTENSION_GUIDE.md](C:/Users/hema/Desktop/2030/web/drone-security-next/FRONTEND_EXTENSION_GUIDE.md)
