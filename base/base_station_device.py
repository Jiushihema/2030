"""
站控层 (Station Control Layer) 设备基类

站控层是智能电网三层架构的最高层，负责全站监控、
人机交互、数据存储、时间同步及控制决策。

通信模式:
  ┌─────────────────────────────────────────────────┐
  │ 【站控层】    ←→ 同层 MMS/WiFi6 · PTP/无线射频   │
  ├─────────────────────────────────────────────────┤
  │  间隔层  ↑ MMS/有线            ↓ MMS/有线        │
  ├─────────────────────────────────────────────────┤
  │  过程层  ↓ PTP/无线射频 (跨层授时)                │
  └─────────────────────────────────────────────────┘

可派生的具体设备:
  - 监控主机
  - 操作员站
  - 无线授时系统
  - 数据服务器
"""
import logging
from collections import deque
from typing import Any, Deque, Dict, List

from base.base_device import BaseDevice
from common.message import Message, MsgType, AppProtocol, TransportMedium
from common.bus import MessageBus
from common.topology import TopologyRegistry, DeviceLayer


class BaseStationDevice(BaseDevice):
    """
    站控层设备基类

    提供:
      - 消息自动路由 (间隔层 / 同层 / 跨层过程层)
      - 接收钩子: on_bay_data / on_peer_data / on_process_data
      - 便捷发送: command_to_bay / send_to_peer / send_to_process_layer
      - 双层数据存储: 最新快照 (_latest_data) + 历史队列 (_data_store)
    """

    # 历史队列默认最大长度 (每个来源设备独立计数)
    DEFAULT_MAX_HISTORY = 1000

    def __init__(
        self,
        device_id:         str,
        bus:               MessageBus = None,
        device_name:       str = "",
        bay_layer_ids:     List[str] = None,
        peer_ids:          List[str] = None,
        process_layer_ids: List[str] = None,
        max_history:       int = DEFAULT_MAX_HISTORY,
    ):
        """
        Parameters
        ----------
        device_id : str
            设备唯一标识
        bus : MessageBus, optional
            消息总线实例
        device_name : str, optional
            设备可读名称
        bay_layer_ids : list[str]
            下层 (间隔层) 设备 ID 列表
            例: ["transformer_monitor", "transformer_protect",
                 "line_monitor", "line_protect"]
        peer_ids : list[str]
            同层 (站控层) 设备 ID 列表
            例: ["operator_station", "time_sync_system", "data_server"]
        process_layer_ids : list[str]
            过程层设备 ID 列表 (仅用于跨层通信, 如无线授时)
            例: ["transformer_mu", "line_mu"]
        max_history : int
            每个来源设备的历史记录最大条数 (默认 1000)
        """
        super().__init__(device_id, bus, device_name)

        topo = TopologyRegistry.get_instance()

        self.bay_layer_ids: List[str] = (
            bay_layer_ids
            if bay_layer_ids is not None
            else topo.get_downstream_ids(device_id)  # 间隔层 = layer - 1
        )
        self.peer_ids: List[str] = (
            peer_ids
            if peer_ids is not None
            else topo.get_peer_ids(device_id)
        )
        self.process_layer_ids: List[str] = (
            process_layer_ids
            if process_layer_ids is not None
            else topo.get_neighbors_by_layer(  # 过程层 = 跨层
                device_id, DeviceLayer.PROCESS
            )
        )

        self._max_history = max_history

        # ── 数据存储 ──
        # 最新快照: { sender_id: latest_payload }
        self._latest_data: Dict[str, Any] = {}
        # 历史队列: { sender_id: deque([payload, ...]) }
        self._data_store:  Dict[str, Deque[Any]] = {}

        self.audit_log("SYSTEM", "STARTUP", details={
            "bay_layer": self.bay_layer_ids,
            "peer": self.peer_ids,
            "process_layer_cross": self.process_layer_ids
        })

    # ════════════════════════════════════════════
    #  消息路由
    # ════════════════════════════════════════════

    def on_message(self, msg: Message) -> None:
        """
        总线回调入口 —— 按发送方所属层级自动分发

        路由规则:
          1. msg_type == SYNC         → 自动调用 sync_time()
          2. sender ∈ bay_layer_ids   → on_bay_data()
          3. sender ∈ peer_ids        → on_peer_data()
          4. 以上都不匹配             → 记录 warning 日志
        """
        # ── 时间同步: 自动更新本地时钟 ──
        if msg.msg_type == MsgType.SYNC:
            if msg.sender_id not in self.peer_ids and msg.sender_id not in self.process_layer_ids:
                self.audit_log("SECURITY", "SYNC_SPOOFING_DETECTED", msg=msg, details={
                    "reason": "SYNC message from unauthorized source"
                }, level=logging.CRITICAL)
            else:
                ts = msg.payload.get("timestamp", msg.timestamp) if isinstance(msg.payload, dict) else msg.timestamp
                self.sync_time(ts)
                self.audit_log("TIME", "TIME_SYNCED", msg=msg, level=logging.DEBUG)

        # ── 按来源分发 ──
        sender = msg.sender_id

        if sender in self.bay_layer_ids:
            self._on_bay_data(msg)

        elif sender in self.peer_ids:
            self._on_peer_data(msg)

        else:
            self.audit_log("SECURITY", "UNAUTHORIZED_SOURCE", msg=msg, details={
                "reason": "Sender not found in valid topology"
            }, level=logging.CRITICAL)

    # ══════════════════════════════════════════
    #  接收处理
    # ══════════════════════════════════════════

    def _on_bay_data(self, msg: Message) -> None:
        """
        处理间隔层上送的数据 (下行接收)

        典型数据:
          - 监测数据 (IEC 61850 MMS / 有线) — 来自测控装置
          - 保护数据 (IEC 61850 MMS / 有线) — 来自保护装置

        默认行为:
          记录日志 + 存入 _latest_data 和 _data_store
        """
        self.audit_log("NETWORK", "RECEIVE_BAY", msg=msg, details={"payload": msg.payload})
        self._store_data(msg.sender_id, msg.payload)
        self.on_bay_data(msg)

    def _on_peer_data(self, msg: Message) -> None:
        """
        处理同层设备发来的数据

        典型场景:
          - 监控主机 ← 操作员站   (操作指令, MMS / WiFi6)
          - 监控主机 ← 无线授时   (时间同步, PTP / 无线射频)
          - 数据服务器 ← 监控主机  (数据同步, MMS / WiFi6)

        默认行为:
          记录日志 + 存入数据存储
        """
        self.audit_log("NETWORK", "RECEIVE_PEER", msg=msg, details={"payload": msg.payload})
        self._store_data(msg.sender_id, msg.payload)
        self.on_peer_data(msg)

    # ════════════════════════════════════════════
    #  接收钩子 —— 子类按需重写
    # ════════════════════════════════════════════
    def on_bay_data(self, msg: Message) -> None:
        """
        子类钩子：处理过程层上送的数据 (下行接收)
        默认实现为空，子类按需重写
        子类应重写以实现: 数据展示、告警研判、存储入库等
        """
        pass

    def on_peer_data(self, msg: Message) -> None:
        """
        子类钩子：处理同层设备发来的数据
        默认实现为空，子类按需重写
        子类应重写以实现: 指令处理、数据持久化等
        """
        pass

    # ════════════════════════════════════════════
    #  下行发送 —— 向间隔层下发指令
    # ════════════════════════════════════════════

    def command_to_bay(
        self,
        receiver_id:      str,
        payload:          Any,
        msg_type:         str = MsgType.CMD,
        app_protocol:     str = AppProtocol.MMS,
        transport_medium: str = TransportMedium.WIRED_ETH,
    ) -> bool:
        """
        向间隔层设备下发控制指令

        典型场景:
          监控主机 → 10kV 线路测控 (合闸指令, MMS / 有线)

        默认参数:
          - 协议: IEC 61850 MMS
          - 介质: 有线传输
          - 类型: CMD
        """
        msg = Message(
            sender_id=self.device_id,
            receiver_id=receiver_id,
            msg_type=msg_type,
            app_protocol=app_protocol,
            transport_medium=transport_medium,
            payload=payload,
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
        app_protocol:     str = AppProtocol.MMS,
        transport_medium: str = TransportMedium.WIFI6,
    ) -> bool:
        """
        向同层设备发送数据

        典型场景:
          - 操作员站 → 监控主机   (操作指令, MMS / WiFi6)
          - 监控主机 → 数据服务器  (数据同步, MMS / WiFi6)

        默认参数:
          - 协议: IEC 61850 MMS
          - 介质: WiFi6

        注意: 无线授时系统发送时应将参数覆盖为
              app_protocol=PTP, transport_medium=RF_STANDARD
        """
        msg = Message(
            sender_id=self.device_id,
            receiver_id=receiver_id,
            msg_type=msg_type,
            app_protocol=app_protocol,
            transport_medium=transport_medium,
            payload=payload,
        )
        return self.send(msg)

    # ════════════════════════════════════════════
    #  跨层发送 —— 向过程层发送 (授时等)
    # ════════════════════════════════════════════

    def send_to_process_layer(
        self,
        receiver_id:      str,
        payload:          Any,
        msg_type:         str = MsgType.SYNC,
        app_protocol:     str = AppProtocol.PTP,
        transport_medium: str = TransportMedium.RF_STANDARD,
    ) -> bool:
        """
        跨层发送至过程层设备

        典型场景:
          无线授时系统 → 主变合并单元 / 线路合并单元
          (PTP 时间同步 / 无线射频)

        说明:
          仅特定设备 (如无线授时系统) 需要使用此方法,
          普通站控层设备不应直接与过程层通信。
        """
        msg = Message(
            sender_id=self.device_id,
            receiver_id=receiver_id,
            msg_type=msg_type,
            app_protocol=app_protocol,
            transport_medium=transport_medium,
            payload=payload,
        )
        return self.send(msg)

    def broadcast_to_process_layer(
        self,
        payload:          Any,
        msg_type:         str = MsgType.SYNC,
        app_protocol:     str = AppProtocol.PTP,
        transport_medium: str = TransportMedium.RF_STANDARD,
    ) -> None:
        """向所有已配置的过程层设备广播 (如全站授时)"""
        for pid in self.process_layer_ids:
            self.send_to_process_layer(
                pid, payload, msg_type, app_protocol, transport_medium
            )

    # ════════════════════════════════════════════
    #  数据存储
    # ════════════════════════════════════════════

    def _store_data(self, sender_id: str, payload: Any) -> None:
        """
        内部存储方法 —— 同时更新最新快照和历史队列

        历史队列使用 deque(maxlen) 自动淘汰最旧记录,
        防止长时间仿真导致内存溢出
        """
        # 最新快照
        self._latest_data[sender_id] = payload

        # 历史队列
        if sender_id not in self._data_store:
            self._data_store[sender_id] = deque(maxlen=self._max_history)
        self._data_store[sender_id].append(payload)

    def get_latest(self, sender_id: str = None) -> Any:
        """
        获取最新数据快照

        Parameters
        ----------
        sender_id : str, optional
            指定来源设备 ID; 为 None 时返回全量副本

        Returns
        -------
        dict | Any | None
        """
        if sender_id:
            return self._latest_data.get(sender_id)
        return dict(self._latest_data)

    def get_history(self, sender_id: str) -> List[Any]:
        """
        获取指定设备的历史数据

        Returns
        -------
        list  历史记录副本 (最旧在前)
        """
        return list(self._data_store.get(sender_id, []))

    def get_history_count(self, sender_id: str = None) -> int | Dict[str, int]:
        """
        查询历史记录条数

        Parameters
        ----------
        sender_id : str, optional
            指定设备; 为 None 时返回所有设备的条数字典
        """
        if sender_id:
            return len(self._data_store.get(sender_id, []))
        return {k: len(v) for k, v in self._data_store.items()}

    def clear_store(self) -> None:
        """清空所有数据存储 (快照 + 历史)"""
        self._data_store.clear()
        self._latest_data.clear()
        self.audit_log("DATA", "STORE_CLEARED", level=logging.DEBUG)