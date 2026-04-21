"""
base/base_process.py

过程层基类 

继承关系:  BaseDevice → BaseProcessAggregator 

职责:
  - 从拓扑注册表自动发现上层邻居 (间隔层) 和下层邻居 (传感器)
  - 维护持久最新值缓存 (_latest_cache), 不因上报而清空
  - 提供工具方法: 更新缓存、向上层上报、事件透传
  - 接收并执行控制指令, 回复 ACK 应答
  - 接收时间同步信号并级联转发给下属传感器

"""
import logging
import time
from abc import abstractmethod
from typing import Any, Dict, List, Optional

from base.base_device import BaseDevice
from common.bus import MessageBus
from common.message import Message, MsgType, AppProtocol, TransportMedium
from common.topology import TopologyRegistry, DeviceLayer, global_topo


class BaseProcessAggregator(BaseDevice):
    """
    过程层汇聚节点基类 (智能终端 + 合并单元统一抽象)

    构造参数 (子类通过 __init__ 传入):
      - app_protocol       : str    上报协议 (GOOSE / SV)
      - transport_medium   : str    传输介质
      - report_interval    : float  周期性上报间隔 (秒)
      - report_msg_type    : str    周期性上报的消息类型
                                    智能终端: MsgType.STATUS
                                    合并单元: MsgType.DATA

    子类必须实现:
      - handle_sensor_data(msg)       : 收到传感器数据后的处理逻辑
      - aggregate(latest_data)        : 将缓存数据汇聚为上报载荷
      - execute_command(cmd_payload)  : 执行控制指令

    子类可选重写:
      - wrap_payload(aggregated)      : 上报前载荷包装 (默认直传)
      - should_accept_command(msg)    : 指令来源校验 (默认仅接受上层)
    """

    def __init__(
        self,
        device_id:        str,
        app_protocol:     str,
        transport_medium: str,
        report_interval:  float,
        report_msg_type:  str,
        bus:              MessageBus = None,
        device_name:      str = "",
        topo:             TopologyRegistry = None,
    ):
        """
        :param device_id:         设备唯一 ID (须与拓扑配置一致)
        :param app_protocol:      上报应用层协议
                                  智能终端: AppProtocol.GOOSE
                                  合并单元: AppProtocol.SV
        :param transport_medium:  传输介质
                                  如 TransportMedium.RF_LOW_LATENCY / MESH
        :param report_interval:   周期性上报间隔 (秒), 供外部调度器读取
                                  智能终端: 1.0 ~ 5.0
                                  合并单元: 0.00025 (4kHz)
        :param report_msg_type:   周期性上报的消息业务类型
                                  智能终端: MsgType.STATUS (设备状态)
                                  合并单元: MsgType.DATA   (电气量采样)
        :param bus:               消息总线实例
        :param device_name:       可读名称
        :param topo:              拓扑注册表实例
        """
        super().__init__(device_id=device_id, bus=bus, device_name=device_name)

        # ── 设备配置字段 (生命周期内不变) ──
        self.app_protocol:     str   = app_protocol
        self.transport_medium: str   = transport_medium
        self.report_interval:  float = report_interval
        self.report_msg_type:  str   = report_msg_type
        self._report_count: int = 0  # 上报计数器

        # ── 拓扑 ──
        self._topo = topo or global_topo

        # ── 从拓扑表自动发现邻居 ──
        # 上层: 间隔层 (BAY) 设备
        self._upstream_ids: List[str] = self._topo.get_upstream_ids(
            self.device_id
        )
        # 下层: 同层 (PROCESS) 直连的传感器
        self._downstream_ids: List[str] = self._topo.get_peer_ids(
            self.device_id
        )
        # 站控层直连邻居: 授时系统 (合并单元跨层 PTP)
        self._time_sync_sources: List[str] = self._topo.get_neighbors_by_layer(
            self.device_id, DeviceLayer.STATION
        )

        # ── 持久最新值缓存 ──
        # 始终保持每个下属传感器的最新数据, 不因上报而清空
        # 结构: { sensor_id: payload_dict }
        self._latest_cache: Dict[str, Dict[str, Any]] = {}

        # ── SV 采样序号计数器 (合并单元使用, 智能终端可忽略) ──
        self._sample_counter: int = 0

        self.audit_log("SYSTEM", "STARTUP", details={
            "app_protocol": self.app_protocol,
            "transport_medium": self.transport_medium,
            "report_interval": self.report_interval,
            "report_msg_type": self.report_msg_type,
            "upstream": self._upstream_ids,
            "downstream": self._downstream_ids,
            "time_sync_sources": self._time_sync_sources
        })

    # ════════════════════════════════════════════
    #  邻居访问属性
    # ════════════════════════════════════════════

    @property
    def upstream_ids(self) -> List[str]:
        """只读: 间隔层上层邻居 ID 列表"""
        return list(self._upstream_ids)

    @property
    def downstream_ids(self) -> List[str]:
        """只读: 下属传感器 ID 列表"""
        return list(self._downstream_ids)

    @property
    def time_sync_sources(self) -> List[str]:
        """只读: 站控层授时系统 ID 列表"""
        return list(self._time_sync_sources)

    @property
    def sample_counter(self) -> int:
        """只读: 当前 SV 采样序号"""
        return self._sample_counter

    # ════════════════════════════════════════════
    #  消息接收与分派 (基类管机制)
    # ════════════════════════════════════════════

    def on_message(self, msg: Message) -> None:
        """
        总线回调入口 —— 按消息类型分派

        分派规则:
          DATA / STATUS → handle_sensor_data()  (下层设备数据上报)
          CMD           → _dispatch_command()   (上层控制指令执行)
          SYNC          → _handle_time_sync()   (时间同步信号处理)
        """
        if msg.msg_type in (MsgType.DATA, MsgType.STATUS):
            self.handle_sensor_data(msg)
        elif msg.msg_type == MsgType.CMD:
            self._dispatch_command(msg)
        elif msg.msg_type == MsgType.SYNC:
            self._handle_time_sync(msg)
        else:
            self.audit_log("SECURITY", "UNHANDLED_MESSAGE", msg=msg, details={
                "reason": "Unsupported message type in Process layer"
            }, level=logging.WARNING)



    # ════════════════════════════════════════════
    #  缓存查询 (调试 / 测试)
    # ════════════════════════════════════════════

    def get_latest_cache(self) -> Dict[str, Dict[str, Any]]:
        """获取持久最新值缓存的快照"""
        return dict(self._latest_cache)

    # ════════════════════════════════════════════
    #  控制指令处理
    # ════════════════════════════════════════════

    def _dispatch_command(self, msg: Message) -> None:
        """
        控制指令分派骨架 (基类管理)

        流程:
          1. 调用 should_accept_command() 校验来源
          2. 调用子类的 execute_command() 执行
          3. 发送 ACK 应答

        Parameters
        ----------
        msg : Message  控制指令, payload 格式示例:
              {"action": "close", "target": "breaker_it", "params": {}}
        """
        if not self.should_accept_command(msg):
            self.audit_log("SECURITY", "UNAUTHORIZED_COMMAND_INJECTION", msg=msg, details={
                "reason": "Command source not verified by logic (bypass detected)",
                "action": "Command execution blocked"
            }, level=logging.CRITICAL)

            ack_msg = Message(
                sender_id=self.device_id,
                receiver_id=msg.sender_id,
                msg_type=MsgType.ACK,
                app_protocol=self.app_protocol,
                transport_medium=self.transport_medium,
                payload={
                    "ack_for": msg.msg_id,
                    "device_id": self.device_id,
                    "ack_time": self.current_time or time.time(),
                },
                timestamp=self.current_time or time.time(),
            )
            self.send(ack_msg)
            return

        self.audit_log("CONTROL", "COMMAND_RECEIVED", msg=msg, details={
            "payload": msg.payload
        }, level=logging.INFO)

        result = self.execute_command(msg.payload)

        self.audit_log("CONTROL", "COMMAND_EXECUTED", msg=msg, details={
            "result": result
        }, level=logging.INFO)

        ack_msg = Message(
            sender_id=self.device_id,
            receiver_id=msg.sender_id,
            msg_type=MsgType.ACK,
            app_protocol=self.app_protocol,
            transport_medium=self.transport_medium,
            payload={
                "ack_for":   msg.msg_id,
                "result":    result,
                "device_id": self.device_id,
                "ack_time": self.current_time or time.time(),
            },
            timestamp=self.current_time or time.time(),
        )
        self.send(ack_msg)

    # ════════════════════════════════════════════
    #  时间同步: 接收 + 级联转发 (基类全权管理)
    # ════════════════════════════════════════════

    def _handle_time_sync(self, msg: Message) -> None:
        """
        处理时间同步消息并级联转发给下属传感器

        时间同步来源由拓扑决定, 基类不区分:
          - 合并单元: 来自站控层授时系统 (跨层 PTP)
          - 智能终端: 来自间隔层级联转发

        流程:
          1. 提取时间戳, 更新自身时钟
          2. 向每个下属传感器转发同步信号

        Parameters
        ----------
        msg : Message  payload 格式: {"sync_time": float}
        """
        ts = (msg.payload.get("timestamp")
              if isinstance(msg.payload, dict) else None)
        if ts is None:
            self.audit_log("TIME", "INVALID_SYNC_PAYLOAD", msg=msg, level=logging.WARNING)
            return

        # 更新自身时钟
        self.sync_time(ts)
        self.audit_log("TIME", "TIME_SYNCED", msg=msg, details={"sync_timestamp": ts}, level=logging.INFO)

        # 级联转发给所有下属传感器
        success_count = 0
        for sensor_id in self._downstream_ids:
            sync_msg = Message(
                sender_id=self.device_id,
                receiver_id=sensor_id,
                msg_type=MsgType.SYNC,
                app_protocol=AppProtocol.PTP,
                transport_medium=self.transport_medium,
                payload={"sync_time": ts},
                timestamp=ts,
            )
            if self.send(sync_msg):
                success_count += 1
            else:
                self.audit_log("NETWORK", "TIME_SYNC_FORWARD_FAILED", details={
                    "target": sensor_id
                }, level=logging.WARNING)

        self.audit_log("TIME", "TIME_SYNC_CASCADED", details={
            "target_count": success_count,
            "total_downstream": len(self._downstream_ids)
        }, level=logging.DEBUG)

    # ════════════════════════════════════════════
    #  抽象方法 —— 子类必须实现
    # ════════════════════════════════════════════

    @abstractmethod
    def handle_sensor_data(self, msg: Message) -> None:
        """
        处理来自下属传感器的数据 —— 子类全权决定策略

        基类已完成消息类型分派, 子类拿到的 msg 一定是
        DATA 或 STATUS 类型。子类自行决定:
          - 是否调用 update_cache() 缓存
          - 是否调用 forward_event() 立即转发
          - 是否调用 report_to_upstream() 汇聚上报
          - 或者任何自定义逻辑

        基类提供的工具方法:
          - self.update_cache(sensor_id, payload)       更新缓存
          - self.forward_event(msg, msg_type)           事件即时透传
          - self.report_to_upstream(payload)             汇聚后上报
          - self._latest_cache                           当前缓存 (只读)
          - self._downstream_ids                         下属传感器列表

        示例 (主变智能终端 — 纯缓存, 等周期上报):
            def handle_sensor_data(self, msg):
                if msg.sender_id in self._downstream_ids:
                    self.update_cache(msg.sender_id, msg.payload)

        示例 (断路器智能终端 — 变位立即转发, 其余缓存):
            def handle_sensor_data(self, msg):
                if msg.sender_id not in self._downstream_ids:
                    return
                self.update_cache(msg.sender_id, msg.payload)
                trigger = msg.payload.get("report_trigger", "periodic")
                if trigger == "event":
                    self.forward_event(msg, MsgType.STATUS)

        示例 (合并单元 — 无脑缓存, 上报完全由 periodic_report 驱动):
            def handle_sensor_data(self, msg):
                if msg.sender_id in self._downstream_ids:
                    self.update_cache(msg.sender_id, msg.payload)

        Parameters
        ----------
        msg : Message  来自传感器的数据消息 (msg_type 为 DATA 或 STATUS)
        """
        ...

    @abstractmethod
    def aggregate(
        self, latest_data: Dict[str, Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        将缓存的传感器数据汇聚为一条上报载荷

        在 periodic_report() 或子类自行调用 report_to_upstream() 前调用。
        latest_data 是缓存快照, 子类不应修改它。

        示例 (主变智能终端):
            def aggregate(self, latest_data):
                return {
                    "device_id":   self.device_id,
                    "pressure":    latest_data.get("pressure_sensor", {}).get("value"),
                    "moisture":    latest_data.get("moisture_sensor", {}).get("value"),
                    "gas":         latest_data.get("gas_sensor", {}).get("value"),
                    "vibration":   latest_data.get("vibration_sensor", {}).get("value"),
                    "temperature": latest_data.get("temperature_sensor", {}).get("value"),
                    "sample_time": time.time(),
                }

        示例 (主变合并单元):
            def aggregate(self, latest_data):
                return {
                    "ia": latest_data.get("current_sensor", {}).get("value", {}).get("ia"),
                    "ib": ...,
                    "ua": latest_data.get("voltage_sensor", {}).get("value", {}).get("ua"),
                    "ub": ...,
                }

        Parameters
        ----------
        latest_data : dict  持久缓存快照 { sensor_id: payload_dict }

        Returns
        -------
        dict | None  汇聚载荷; None 表示汇聚失败
        """
        ...

    @abstractmethod
    def execute_command(self, cmd_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行控制指令并返回结果

        示例 (断路器智能终端):
            def execute_command(self, cmd_payload):
                action = cmd_payload.get("action")
                if action == "close":
                    self._state = "closed"
                    return {"success": True, "state": "closed"}
                elif action == "open":
                    self._state = "open"
                    return {"success": True, "state": "open"}
                return {"success": False, "error": f"未知指令: {action}"}

        示例 (不支持控制指令的设备):
            def execute_command(self, cmd_payload):
                return {"success": False, "error": "本设备不支持控制指令"}

        Parameters
        ----------
        cmd_payload : dict  指令载荷 {"action": ..., "target": ..., "params": ...}

        Returns
        -------
        dict  执行结果, 至少包含 "success": bool
        """
        ...

    # ════════════════════════════════════════════
    #  钩子方法 —— 有默认实现, 子类可选重写
    # ════════════════════════════════════════════

    def wrap_payload(
        self, aggregated: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        上报前的载荷包装，针对不同协议进行包装，如sv协议需要包裹sv协议帧头，
        goose协议直接传载荷

        默认实现: 直接透传 (适用于 GOOSE 智能终端)。

        合并单元子类应重写, 包裹 SV 协议帧头:
            def wrap_payload(self, aggregated):
                self._sample_counter += 1
                return {
                    "svID":        self.device_id,
                    "smpCnt":      self._sample_counter,
                    "smpSynch":    self.current_time is not None,
                    "sample_time": self.current_time or time.time(),
                    "data":        aggregated,
                }

        Parameters
        ----------
        aggregated : dict  aggregate() 返回的汇聚载荷

        Returns
        -------
        dict  最终上报载荷
        """
        return aggregated

    def should_accept_command(self, msg: Message) -> bool:
        """
        控制指令来源校验，可在后期实现防御开启关闭等策略

        默认实现: 仅接受来自已知上层邻居的指令。
        子类可重写以放宽或收紧校验规则。

        Parameters
        ----------
        msg : Message  控制指令消息

        Returns
        -------
        bool  True 表示接受并执行, False 表示拒绝
        """
        return msg.sender_id in self._upstream_ids
    # ════════════════════════════════════════════
    #  工具方法 —— 基类提供, 子类按需调用
    # ════════════════════════════════════════════

    def update_cache(self, sensor_id: str, payload: Dict[str, Any]) -> None:
        """
        更新持久最新值缓存

        子类在 handle_sensor_data() 中调用, 将传感器数据存入缓存。
        缓存不会因上报而清空, 始终保持每个传感器的最新值。

        Parameters
        ----------
        sensor_id : str   传感器设备 ID
        payload   : dict  传感器上报的载荷字典
        """
        self._latest_cache[sensor_id] = payload
        self.audit_log("DATA", "CACHE_UPDATE", details={"sensor": sensor_id}, level=logging.DEBUG)

    def report_to_upstream(self, payload: Dict[str, Any]) -> None:
        """
        数据发送逻辑

        使用 self.report_msg_type 作为消息类型:
          - 智能终端: MsgType.STATUS
          - 合并单元: MsgType.DATA

        流程:
          1. 调用 wrap_payload() 做协议包装
          2. 逐一单播发送给每个上层邻居

        Parameters
        ----------
        payload : dict  aggregate() 返回的汇聚载荷
        """
        wrapped = self.wrap_payload(payload)

        for target_id in self._upstream_ids:
            msg = Message(
                sender_id=self.device_id,
                receiver_id=target_id,
                msg_type=self.report_msg_type,
                app_protocol=self.app_protocol,
                transport_medium=self.transport_medium,
                payload=wrapped,
                timestamp=self.current_time or time.time(),
            )
            success = self.send(msg)
            if not success:
                self.audit_log("NETWORK", "REPORT_FAILED", details={"target": target_id}, level=logging.WARNING)

    def forward_event(self, msg: Message, msg_type: str) -> None:
        """
        将传感器数据立马上传

        不经过 aggregate(), 以最低延迟转发。
        适用于断路器变位、保护告警等毫秒级响应场景。
        子类在 handle_sensor_data() 中判断需要立即转发时调用。

        注意: 由于 payload 已被重新包装 (加了 aggregator_id、source_sensor 等),
        与原始传感器消息的语义已不同, 因此 msg_type 必须由调用方显式指定,
        避免语义混淆。

        Parameters
        ----------
        msg      : Message  来自传感器的原始事件消息
        msg_type : str      转发消息的业务类型, 由调用方指定
                            示例: MsgType.STATUS (断路器变位事件)

        子类调用示例:
            # 断路器智能终端: 变位事件
            self.forward_event(msg, MsgType.STATUS)
        """
        event_payload = {
            "aggregator_id": self.device_id,
            "source_sensor": msg.sender_id,
            "trigger":       msg.payload.get("report_trigger", "event")
                             if isinstance(msg.payload, dict) else "event",
            "data":          msg.payload,
        }

        self.audit_log("DATA", "EVENT_FORWARD_START", msg=msg, details={
            "target_layer": "upstream", "targets": self._upstream_ids
        }, level=logging.INFO)

        for target_id in self._upstream_ids:
            event_msg = Message(
                sender_id=self.device_id,
                receiver_id=target_id,
                msg_type=msg_type,
                app_protocol=self.app_protocol,
                transport_medium=self.transport_medium,
                payload=event_payload,
                timestamp=self.current_time or time.time(),
            )
            success = self.send(event_msg)
            if not success:
                self.audit_log("NETWORK", "EVENT_FORWARD_FAILED", details={"target": target_id}, level=logging.WARNING)

    def periodic_report(self) -> None:
        """
        周期性上报 (由外部仿真调度器按 self.report_interval 周期调用)

        流程:
          1. 检查缓存是否有数据
          2. 记录尚无缓存数据的传感器 (调试用)
          3. 调用 aggregate() 由子类汇聚
          4. 调用 report_to_upstream() 发送 (内部会调 wrap_payload())

        子类如果需要完全自定义周期上报逻辑, 可重写此方法。
        """
        if not self._latest_cache:
            return

        # 记录哪些下属传感器尚无缓存数据, 方便调试
        missing = [
            sid for sid in self._downstream_ids
            if sid not in self._latest_cache
        ]
        if missing and self._report_count < 5:
            self.audit_log("DATA", "MISSING_SENSOR_DATA", details={"missing_sensors": missing}, level=logging.DEBUG)

        aggregated = self.aggregate(dict(self._latest_cache))
        if aggregated is None:
            return

        self.report_to_upstream(aggregated)
        self._report_count += 1

        self.audit_log("DATA", "PERIODIC_REPORT_DONE", details={
            "report_count": self._report_count
        }, level=logging.DEBUG)