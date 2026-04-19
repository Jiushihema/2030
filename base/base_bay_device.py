"""
间隔层 (Bay Layer) 设备基类

间隔层是智能电网三层架构的中间层，承担数据汇聚、测量监控、
保护判断、指令转发等核心功能。

通信模式:
  ┌─────────────────────────────────────────────────┐
  │  站控层  ↑ MMS/有线            ↓ MMS/有线        │
  ├─────────────────────────────────────────────────┤
  │ 【间隔层】     ←→ 同层 Modbus-TCP / 无线Mesh     │
  ├─────────────────────────────────────────────────┤
  │  过程层  ↑ SV·GOOSE/Mesh·射频   ↓ GOOSE/有线     │
  └─────────────────────────────────────────────────┘

可派生的具体设备:
  - 主变状态检测终端
  - 主变测控装置
  - 主变保护装置
  - 10kV 线路测控
  - 10kV 线路保护
"""
import logging
import time
from typing import Any, Dict, List

from base.base_device import BaseDevice
from common.message import Message, MsgType, AppProtocol, TransportMedium
from common.bus import MessageBus
from common.topology import TopologyRegistry


class BaseBayDevice(BaseDevice):
    """
    间隔层设备基类

    提供:
      - 消息自动路由 (按发送方所属层级分发)
      - 过程层数据接收 / 站控层指令接收 / 同层数据接收 的默认钩子
      - 上行报告 / 下行指令 / 同层通信 的便捷发送方法
      - 多源数据缓冲区, 供子类做数据汇聚或保护判断
    """

    def __init__(
        self,
        device_id:      str,
        bus:            MessageBus = None,
        device_name:    str = "",
        upstream_ids:   List[str] = None,
        downstream_ids: List[str] = None,
        peer_ids:       List[str] = None,
    ):
        """
        Parameters
        ----------
        device_id : str
            设备唯一标识
        bus : MessageBus, optional
            消息总线实例 (测试时传入独立实例, 生产默认 global_bus)
        device_name : str, optional
            设备可读名称 (默认同 device_id)
        upstream_ids : list[str]
            上层 (站控层) 设备 ID 列表
            例: ["monitor_host"]
        downstream_ids : list[str]
            下层 (过程层) 设备 ID 列表
            例: ["transformer_mu", "transformer_it"]
        peer_ids : list[str]
            同层设备 ID 列表
            例: ["transformer_status_terminal"]
        """
        super().__init__(device_id, bus, device_name)

        topo = TopologyRegistry.get_instance()

        self.upstream_ids: List[str] = (
            upstream_ids
            if upstream_ids is not None
            else topo.get_upstream_ids(device_id)
        )
        self.downstream_ids: List[str] = (
            downstream_ids
            if downstream_ids is not None
            else topo.get_downstream_ids(device_id)
        )
        self.peer_ids: List[str] = (
            peer_ids
            if peer_ids is not None
            else topo.get_peer_ids(device_id)
        )

        # ── 数据缓冲区 ──
        # 按来源设备 ID 暂存最新一帧数据, 供子类汇聚 / 判断使用
        # { sender_id: latest_payload }
        self._data_buffer: Dict[str, Any] = {}
        self._process_msg_counters: Dict[str, int] = {}
        self._last_process_log_time: Dict[str, float] = {}

        self.audit_log("SYSTEM", "STARTUP", details={
            "upstream": self.upstream_ids,
            "downstream": self.downstream_ids,
            "peer": self.peer_ids
        })

    # ════════════════════════════════════════════
    #  消息路由
    # ════════════════════════════════════════════

    def on_message(self, msg: Message) -> None:
        """
        总线回调入口 —— 按发送方所属层级自动分发

        路由规则:
          1. sender ∈ downstream_ids → on_process_data()
          2. sender ∈ upstream_ids   → on_station_command()
          3. sender ∈ peer_ids       → on_peer_data()
          4. 以上都不匹配            → 记录 warning 日志
        """

        extracted_time = msg.timestamp

        if self.current_time is not None and extracted_time != self.current_time:
            time_diff = extracted_time - self.current_time
            # 如果一次时钟同步导致本地时间跳变超过 50ms，记录安全告警 (可能是延迟攻击或授时欺骗)
            if abs(time_diff) > 5.00:
                self.audit_log("SECURITY", "TIME_JUMP_DETECTED", msg=msg, details={
                    "old_time": self.current_time,
                    "new_time": extracted_time,
                    "jump_delta": time_diff
                }, level=logging.WARNING)

        # 更新本地时间
        if self.current_time != extracted_time:
            self.current_time = extracted_time

        # ── 按来源分发 ──
        sender = msg.sender_id

        if sender in self.downstream_ids:
            self._on_process_data(msg)

        elif sender in self.upstream_ids:
            self._on_station_command(msg)

        elif sender in self.peer_ids:
            self._on_peer_data(msg)

        else:
            self.audit_log("SECURITY", "UNAUTHORIZED_SOURCE", msg=msg, details={
                "reason": "Sender not found in valid topology (upstream/downstream/peer)"
            }, level=logging.CRITICAL)

    # ══════════════════════════════════════════
    #  接收处理
    # ══════════════════════════════════════════

    def _on_process_data(self, msg: Message) -> None:
        """
        处理过程层上送的数据 (下行接收)
        新增特性: 自我限流打桩机制，防止 4kHz 高频 SV 数据产生日志风暴。
        每秒钟仅输出一次汇总日志，包含收包统计和最新载荷切片。
        """
        import time

        sender = msg.sender_id
        # 使用仿真时间，若仿真时间未初始化则回退至系统真实时间
        now = self.current_time
        # 1. 限流器初始化
        if sender not in self._last_process_log_time:
            self._last_process_log_time[sender] = now
            self._process_msg_counters[sender] = 0
        # 2. 计数器累加
        self._process_msg_counters[sender] += 1
        # 3. 检查是否达到 1 秒的打桩周期
        time_diff = now - self._last_process_log_time[sender]
        if time_diff >= 1.0:
            # 达到 1 秒，打印汇总日志
            self.audit_log("NETWORK", "RECEIVE_PROCESS_SUMMARY", details={
                "sender": sender,
                "msg_type": msg.msg_type,
                "app_protocol": getattr(msg, "app_protocol", "unknown"),
                "packets_per_sec": self._process_msg_counters[sender],
                "latest_payload_sample": str(msg.payload)[:200]  # 截断以防超大恶意报文
            }, level=logging.DEBUG)  # 保持 DEBUG 级别，避免干扰上层重要告警
            # 重置限流器状态
            self._last_process_log_time[sender] = now
            self._process_msg_counters[sender] = 0
        # 4. 正常更新业务数据缓冲并触发子类回调 (不受限流影响，保护逻辑 4000 帧全量执行)
        self._data_buffer[sender] = msg.payload
        self.on_process_data(msg)

    def _on_station_command(self, msg: Message) -> None:
        """
        处理站控层下发的控制指令 (上行接收)

        典型指令:
          - 合闸 / 分闸指令 (IEC 61850 MMS / 有线)

        默认行为:
          仅记录日志
        """
        self.audit_log("NETWORK", "RECEIVE_STATION", msg=msg, details={"payload": msg.payload})
        self.on_station_command(msg)

    def _on_peer_data(self, msg: Message) -> None:
        """
        处理同层设备发来的数据

        典型场景:
          - 主变测控装置 ← 主变状态检测终端 (Modbus-TCP / 无线 Mesh)

        默认行为:
          记录日志 + 缓存到 _data_buffer[sender_id]
        """
        self.audit_log("NETWORK", "RECEIVE_PEER", msg=msg, details={"payload": msg.payload})
        self._data_buffer[msg.sender_id] = msg.payload
        self.on_peer_data(msg)


    # ════════════════════════════════════════════
    #  接收钩子 —— 子类按需重写
    # ════════════════════════════════════════════

    def on_process_data(self, msg: Message) -> None:
        """
        子类钩子：处理过程层上送的数据 (下行接收)
        默认实现为空，子类按需重写
        子类应重写以实现: 数据解析、阈值判断、保护逻辑等
        """
        pass

    def on_station_command(self, msg: Message) -> None:
        """
        子类钩子：处理站控层下发的控制指令 (上行接收)
        默认实现为空，子类按需重写
        子类应重写以实现: 指令校验、转发至过程层等
        """
        pass

    def on_peer_data(self, msg: Message) -> None:
        """
        子类钩子：处理同层设备发来的数据
        默认实现为空，子类按需重写
        子类应重写以实现: 数据融合、状态综合判断等
        """
        pass

    # ════════════════════════════════════════════
    #  上行发送 —— 向站控层报告
    # ════════════════════════════════════════════

    def report_to_station(
        self,
        receiver_id:      str,
        payload:          Any,
        msg_type:         str = MsgType.MONITOR,
        app_protocol:     str = AppProtocol.MMS,
        transport_medium: str = TransportMedium.WIRED_ETH,
    ) -> bool:
        """
        向站控层设备上报数据

        默认参数 (覆盖间隔层 → 站控层的主流通信规范):
          - 协议:  IEC 61850 MMS
          - 介质:  有线传输
          - 类型:  MONITOR (监测数据)

        保护装置应将 msg_type 指定为 MsgType.PROTECTION

        Parameters
        ----------
        receiver_id : str      目标站控层设备 ID (如 "monitor_host")
        payload     : Any      数据内容
        msg_type    : str      消息类型 (MONITOR / PROTECTION / ALARM)

        Returns
        -------
        bool  投递是否成功
        """
        current_ts = self.current_time

        msg = Message(
            sender_id=self.device_id,
            receiver_id=receiver_id,
            msg_type=msg_type,
            app_protocol=app_protocol,
            transport_medium=transport_medium,
            payload=payload,
            timestamp=current_ts,
        )
        return self.send(msg)

    def report_to_all_stations(
        self,
        payload:          Any,
        msg_type:         str = MsgType.MONITOR,
        app_protocol:     str = AppProtocol.MMS,
        transport_medium: str = TransportMedium.WIRED_ETH,
    ) -> None:
        """将数据上报给所有已配置的站控层设备"""
        for sid in self.upstream_ids:
            self.report_to_station(
                sid, payload, msg_type, app_protocol, transport_medium
            )

    # ════════════════════════════════════════════
    #  下行发送 —— 向过程层下发指令
    # ════════════════════════════════════════════

    def command_to_process(
        self,
        receiver_id:      str,
        payload:          Any,
        msg_type:         str = MsgType.CMD,
        app_protocol:     str = AppProtocol.GOOSE,
        transport_medium: str = TransportMedium.WIRED_ETH,
    ) -> bool:
        """
        向过程层设备下发控制指令

        典型场景:
          10kV 线路测控 → 断路器智能终端 (GOOSE / 有线)

        默认参数:
          - 协议: GOOSE
          - 介质: 有线传输
          - 类型: CMD
        """
        current_ts = self.current_time

        msg = Message(
            sender_id=self.device_id,
            receiver_id=receiver_id,
            msg_type=msg_type,
            app_protocol=app_protocol,
            transport_medium=transport_medium,
            payload=payload,
            timestamp=current_ts,
        )
        return self.send(msg)

    # ════════════════════════════════════════════
    #  同层发送
    # ════════════════════════════════════════════

    def send_to_peer(
        self,
        receiver_id:      str,
        payload:          Any,
        msg_type:         str = MsgType.DATA,
        app_protocol:     str = AppProtocol.MODBUS_TCP,
        transport_medium: str = TransportMedium.MESH,
    ) -> bool:
        """
        向同层设备发送数据

        典型场景:
          主变状态检测终端 → 主变测控装置 (Modbus-TCP / 无线 Mesh)

        默认参数:
          - 协议: Modbus-TCP
          - 介质: 无线 Mesh
        """
        current_ts = self.current_time

        msg = Message(
            sender_id=self.device_id,
            receiver_id=receiver_id,
            msg_type=msg_type,
            app_protocol=app_protocol,
            transport_medium=transport_medium,
            payload=payload,
            timestamp=current_ts,
        )
        return self.send(msg)

    # ════════════════════════════════════════════
    #  数据缓冲区操作
    # ════════════════════════════════════════════

    def get_buffered_data(self, sender_id: str = None) -> Any:
        """
        查询缓冲区

        Parameters
        ----------
        sender_id : str, optional
            指定来源设备 ID; 为 None 时返回全量副本

        Returns
        -------
        dict | Any | None
        """
        if sender_id:
            return self._data_buffer.get(sender_id)
        return dict(self._data_buffer)

    def clear_buffer(self) -> None:
        """清空数据缓冲区"""
        self._data_buffer.clear()
        self.audit_log("DATA", "BUFFER_CLEARED", level=logging.DEBUG)