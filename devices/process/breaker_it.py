"""
devices/process/breaker_it.py

断路器智能终端 —— 过程层汇聚节点
"""

import time
from typing import Any, Dict, Optional

from base.base_process import BaseProcessAggregator
from common.bus import MessageBus
from common.message import Message, MsgType, AppProtocol, TransportMedium
from common.topology import TopologyRegistry


class BreakerIntelligentTerminal(BaseProcessAggregator):

    CMD_COOLDOWN: float = 0.5  # 指令冷却期（秒）

    def __init__(
        self,
        device_id:       str   = "breaker_it",
        report_interval: float = 1.0,
        bus:             MessageBus = None,
        device_name:     str   = "断路器智能终端",
        topo:            TopologyRegistry = None,
    ):
        super().__init__(
            device_id=device_id,
            app_protocol=AppProtocol.GOOSE,
            transport_medium=TransportMedium.RF_LOW_LATENCY,
            report_interval=report_interval,
            report_msg_type=MsgType.STATUS,
            bus=bus,
            device_name=device_name,
            topo=topo,
        )

        self._breaker_state:      str   = "close"
        self._last_cmd_time:      Optional[float] = None
        self._last_cmd_action:    Optional[str]   = None
        # self._cmd_cooldown_until: float = 0.0

        self.logger.info("断路器智能终端初始化完成")

    # ════════════════════════════════════════════
    #  只读属性
    # ════════════════════════════════════════════

    @property
    def breaker_state(self) -> str:
        return self._breaker_state

    @property
    def last_cmd_action(self) -> Optional[str]:
        return self._last_cmd_action

    # ════════════════════════════════════════════
    #  传感器数据处理
    # ════════════════════════════════════════════

    def handle_sensor_data(self, msg: Message) -> None:
        if msg.sender_id not in self._downstream_ids:
            return

        # 只缓存传感器数据，不覆盖控制侧状态
        self.update_cache(msg.sender_id, msg.payload)

        # 事件触发立即透传
        trigger = (msg.payload.get("report_trigger", "periodic")
                if isinstance(msg.payload, dict) else "periodic")
        if trigger == "event":
            self.logger.info(
                f"检测到断路器变位事件: state={self._breaker_state}, 立即透传至间隔层"
            )
            self.forward_event(msg, MsgType.STATUS)


    # ════════════════════════════════════════════
    #  数据汇聚
    # ════════════════════════════════════════════

    def aggregate(self, latest_data: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        mech_data  = latest_data.get("mechanical_sensor", {})
        mech_value = mech_data.get("value", {})
        if not isinstance(mech_value, dict):
            mech_value = {}

        return {
            "device_id":       self.device_id,
            "breaker_state":   self._breaker_state,
            "position":        mech_value.get("position", "close"),
            "operation_count": mech_value.get("operation_count", 0),
            "travel_time_ms":  mech_value.get("travel_time_ms", 0.0),
            "spring_charged":  mech_value.get("spring_charged", None),
            "last_cmd_action": self._last_cmd_action,
            "last_cmd_time":   self._last_cmd_time,
            "report_time":     self.current_time or time.time(),
        }

    # ════════════════════════════════════════════
    #  控制指令执行
    # ════════════════════════════════════════════

    def execute_command(self, cmd_payload: Dict[str, Any]) -> Dict[str, Any]:
        action = cmd_payload.get("action", "").lower()
        now    = self.current_time or time.time()

        if action == "close":
            return self._execute_close(now)
        elif action in ("open", "trip"):
            return self._execute_open(now)
        else:
            self.logger.warning(f"未知指令: {action}")
            return {"success": False, "error": f"未知指令: {action}", "device_id": self.device_id}

    def _execute_close(self, timestamp: float) -> Dict[str, Any]:
        if self._breaker_state == "closed":
            return {
                "success": False, "error": "断路器已处于合闸状态",
                "device_id": self.device_id, "state": self._breaker_state,
            }

        self._breaker_state      = "closed"
        self._last_cmd_action    = "close"
        self._last_cmd_time      = timestamp
        self._cmd_cooldown_until = timestamp + self.CMD_COOLDOWN
        self._notify_sensor_position("closed", timestamp)
        self.logger.warning("执行合闸指令完成")
        return {
            "success": True, "action": "close", "state": "closed",
            "device_id": self.device_id, "exec_time": timestamp,
        }

    def _execute_open(self, timestamp: float) -> Dict[str, Any]:
        """
        执行分闸前先查传感器缓存的位置。
        若传感器被篡改显示 open，breaker_it 误判已分闸，拒绝执行，
        线路持续带故障运行。
        """
        if self._breaker_state == "open":
            return {
                "success": False, "error": "断路器已处于分闸状态",
                "device_id": self.device_id, "state": self._breaker_state,
            }

        # 查传感器缓存位置
        mech_data       = self._latest_cache.get("mechanical_sensor", {})
        sensor_position = mech_data.get("value", {}).get("position", "close")

        if sensor_position == "open":
            # 传感器显示已分闸（可能被篡改），拒绝执行，线路持续带故障
            self.logger.warning(
                f"传感器显示已处于分闸位置，拒绝执行分闸指令 "
                f"（传感器可能被篡改！线路持续带故障！）"
            )
            return {
                "success":   False,
                "error":     "传感器显示断路器已处于分闸状态，拒绝执行",
                "device_id": self.device_id,
                "state":     sensor_position,
            }

        self._breaker_state      = "open"
        self._last_cmd_action    = "open"
        self._last_cmd_time      = timestamp
        self._cmd_cooldown_until = timestamp + self.CMD_COOLDOWN
        self._notify_sensor_position("open", timestamp)
        self.logger.warning("执行分闸指令完成")
        return {
            "success": True, "action": "open", "state": "open",
            "device_id": self.device_id, "exec_time": timestamp,
        }

    def _notify_sensor_position(self, position: str, timestamp: float) -> None:
        for sensor_id in self._downstream_ids:
            cmd_msg = Message(
                sender_id=self.device_id,
                receiver_id=sensor_id,
                msg_type=MsgType.CMD,
                app_protocol=AppProtocol.GOOSE,
                transport_medium=self.transport_medium,
                payload={
                    "action":    "set_position",
                    "position":  position,
                    "source":    self.device_id,
                    "exec_time": timestamp,
                },
                timestamp=timestamp,
            )
            self.send(cmd_msg)
            self.logger.debug(f"位置变更通知已发送: [{sensor_id}] → {position}")

    # ════════════════════════════════════════════
    #  指令来源校验
    # ════════════════════════════════════════════

    def should_accept_command(self, msg: Message) -> bool:
        is_valid_source = (msg.sender_id in self._upstream_ids) or (msg.app_protocol == AppProtocol.GOOSE)
        if not is_valid_source:
            return False

        local_time = self.current_time
        cmd_time = msg.payload.get("cmd_time", msg.timestamp) if isinstance(msg.payload, dict) else msg.timestamp

        time_diff = local_time - cmd_time
        if abs(time_diff) > 1.5:
            self.logger.critical(
                f"【安全拦截】拒绝执行控制指令！报文时间与本地时钟偏差过大 ({time_diff:.2f}秒)。"
            )
            # 拒绝接收该指令，后续的 execute_command 将不会被调用
            return False

        return True
