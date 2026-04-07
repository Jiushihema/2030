"""
电站拓扑配置 —— 全站设备与连接关系的声明式定义

与拓扑文档 (202603281529.md) 一一对应
修改拓扑时只需修改此文件, 无需改动任何设备代码
"""

from common.topology import DeviceLayer

SUBSTATION_TOPOLOGY = {

    # ── 设备注册: { device_id: layer } ──
    "devices": {
        # 过程层
        "pressure_sensor":       DeviceLayer.PROCESS,
        "moisture_sensor":       DeviceLayer.PROCESS,
        "gas_sensor":            DeviceLayer.PROCESS,
        "vibration_sensor":      DeviceLayer.PROCESS,
        "temperature_sensor":    DeviceLayer.PROCESS,
        "transformer_it":        DeviceLayer.PROCESS,   # 主变智能终端
        "current_sensor":        DeviceLayer.PROCESS,
        "voltage_sensor":        DeviceLayer.PROCESS,
        "transformer_mu":        DeviceLayer.PROCESS,   # 主变合并单元
        "mechanical_sensor":     DeviceLayer.PROCESS,   # 机械状态传感器
        "breaker_it":            DeviceLayer.PROCESS,   # 断路器智能终端
        "line_mu":               DeviceLayer.PROCESS,   # 线路合并单元

        # 间隔层
        "transformer_status":    DeviceLayer.BAY,       # 主变状态检测终端
        "transformer_monitor":   DeviceLayer.BAY,       # 主变测控装置
        "transformer_protect":   DeviceLayer.BAY,       # 主变保护装置
        "line_monitor":          DeviceLayer.BAY,       # 10kV 线路测控
        "line_protect":          DeviceLayer.BAY,       # 10kV 线路保护

        # 站控层
        "operator_station":      DeviceLayer.STATION,   # 操作员站
        "time_sync":             DeviceLayer.STATION,   # 无线授时系统
        "monitor_host":          DeviceLayer.STATION,   # 监控主机
        "data_server":           DeviceLayer.STATION,   # 数据服务器
    },

    # ── 通信链路: [ (id_a, id_b), ... ] ──
    # 每条链路对应拓扑文档中的一条箭头 (双向注册, 设备双方均可感知)
    "links": [
        # === 过程层内部 ===
        # 各传感器 → 主变智能终端
        ("pressure_sensor",    "transformer_it"),
        ("moisture_sensor",    "transformer_it"),
        ("gas_sensor",         "transformer_it"),
        ("vibration_sensor",   "transformer_it"),
        ("temperature_sensor", "transformer_it"),

        # 电流/电压传感器 → 主变合并单元
        ("current_sensor",     "transformer_mu"),
        ("voltage_sensor",     "transformer_mu"),

        # 机械状态传感器 → 断路器智能终端
        ("mechanical_sensor",  "breaker_it"),

        # === 过程层 → 间隔层 ===
        # 主变智能终端 → 主变状态检测终端
        ("transformer_it",     "transformer_status"),

        # 主变合并单元 → 主变测控 / 主变保护
        ("transformer_mu",     "transformer_monitor"),
        ("transformer_mu",     "transformer_protect"),

        # 断路器智能终端 ↔ 10kV 线路测控
        ("breaker_it",         "line_monitor"),

        # 线路合并单元 → 10kV 线路测控 / 线路保护
        ("line_mu",            "line_monitor"),
        ("line_mu",            "line_protect"),

        # === 间隔层内部 ===
        # 主变状态检测终端 → 主变测控装置
        ("transformer_status", "transformer_monitor"),

        # === 间隔层 → 站控层 ===
        ("transformer_monitor", "monitor_host"),
        ("transformer_protect", "monitor_host"),
        ("line_monitor",        "monitor_host"),
        ("line_protect",        "monitor_host"),

        # === 站控层内部 ===
        ("operator_station",   "monitor_host"),
        ("time_sync",          "monitor_host"),
        ("monitor_host",       "data_server"),

        # === 站控层 → 过程层 (跨层授时) ===
        ("time_sync",          "transformer_mu"),
        ("time_sync",          "line_mu"),
    ],
}