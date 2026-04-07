"""
device_bay/line_monitor.py

10kV 线路测控 (间隔层)
"""

import time
import threading

from base.base_bay_device import BaseBayDevice
from common.message import Message, MsgType, AppProtocol, TransportMedium


class LineMonitorDevice(BaseBayDevice):

    OVERVOLTAGE_THRESHOLD = 12.0  # kV
    RECLOSE_DELAY         = 3.0   # 秒，方便手动演示

    def __init__(self, device_id="line_monitor", bus=None):
        super().__init__(device_id=device_id, bus=bus)

        self._reclose_timer:         threading.Timer = None
        self._last_voltage:          float = 0.0
        self._last_breaker_position: str   = "close"
        self._reclose_armed:         bool  = False

    # ════════════════════════════════════════════
    #  过程层数据处理
    # ════════════════════════════════════════════

    def on_process_data(self, msg: Message) -> None:
        if msg.sender_id == "line_mu" and msg.app_protocol == AppProtocol.SV:
            self._handle_sv_data(msg)
        elif msg.sender_id == "breaker_it" and msg.app_protocol == AppProtocol.GOOSE:
            self._handle_breaker_msg(msg)

    def _handle_sv_data(self, msg: Message) -> None:
        voltage = msg.payload.get("voltage", 0.0)
        current = msg.payload.get("current", 0.0)
        self._last_voltage = voltage

        if voltage > self.OVERVOLTAGE_THRESHOLD:
            self.logger.warning(f"线路过压，执行本地紧急切除！voltage={voltage}kV")
            self.command_to_process(
                receiver_id="breaker_it",
                payload={"action": "trip", "reason": "line_overvoltage"},
                msg_type=MsgType.CMD,
                app_protocol=AppProtocol.GOOSE,
                transport_medium=TransportMedium.RF_LOW_LATENCY,
            )
            self.report_to_station(
                receiver_id="monitor_host",
                payload={"event": "line_trip_executed", "voltage": voltage},
                msg_type=MsgType.ALARM,
                app_protocol=AppProtocol.MMS,
            )
        else:
            self.report_to_station(
                receiver_id="monitor_host",
                payload={"line_voltage": voltage, "line_current": current},
                msg_type=MsgType.MONITOR,
                app_protocol=AppProtocol.MMS,
            )

    def _handle_breaker_msg(self, msg: Message) -> None:
        payload = msg.payload

        # ACK：判断分闸是否成功，成功则启动重合闸
        if msg.msg_type == MsgType.ACK:
            result = payload.get("result", {})
            if result.get("success") and result.get("action") == "open":
                self.logger.info("分闸成功，启动重合闸计时器")
                self._reclose_armed = True
                self._schedule_reclose()
            elif not result.get("success"):
                # 分闸失败（可能传感器被篡改导致拒绝执行）
                self.logger.warning(
                    f"分闸指令被拒绝：{result.get('error')}  "
                    f"【警告】线路持续带故障运行！"
                )
                self.report_to_station(
                    receiver_id="monitor_host",
                    payload={
                        "event":  "trip_rejected",
                        "reason": result.get("error"),
                        "state":  result.get("state"),
                    },
                    msg_type=MsgType.ALARM,
                    app_protocol=AppProtocol.MMS,
                )

        # STATUS：更新传感器上报的断路器位置缓存，只做同步不触发控制
        elif msg.msg_type == MsgType.STATUS:
            data  = payload.get("data", {})
            value = data.get("value", {}) if isinstance(data, dict) else {}
            if isinstance(value, dict) and "position" in value:
                self._last_breaker_position = value["position"]

            self.report_to_station(
                receiver_id="monitor_host",
                payload={"breaker_status": payload.get("breaker_state")},
                msg_type=MsgType.STATUS,
                app_protocol=AppProtocol.MMS,
            )

    # ════════════════════════════════════════════
    #  重合闸
    # ════════════════════════════════════════════

    def _schedule_reclose(self) -> None:
        if self._reclose_timer is not None:
            self._reclose_timer.cancel()
        self._reclose_timer = threading.Timer(self.RECLOSE_DELAY, self._attempt_reclose)
        self._reclose_timer.daemon = True
        self._reclose_timer.start()
        self.logger.info(f"重合闸计时器已启动，{self.RECLOSE_DELAY}s 后尝试合闸")

    def _attempt_reclose(self) -> None:
        if not self._reclose_armed:
            return
        self._reclose_armed = False

        if self._last_voltage > self.OVERVOLTAGE_THRESHOLD:
            self.logger.warning(
                f"重合闸放弃：线路仍然异常 voltage={self._last_voltage}kV"
            )
            self.report_to_station(
                receiver_id="monitor_host",
                payload={
                    "event":   "reclose_failed",
                    "reason":  "permanent_fault",
                    "voltage": self._last_voltage,
                },
                msg_type=MsgType.ALARM,
                app_protocol=AppProtocol.MMS,
            )
            return

        self.logger.info("重合闸条件满足，发送合闸指令")
        self._send_close_command()

    def _send_close_command(self) -> None:
        for target_id in self.downstream_ids:
            if "breaker" in target_id:
                msg = Message(
                    sender_id=self.device_id,
                    receiver_id=target_id,
                    msg_type=MsgType.CMD,
                    app_protocol=AppProtocol.GOOSE,
                    transport_medium=TransportMedium.RF_LOW_LATENCY,
                    payload={"action": "close", "reason": "auto_reclose"},
                    timestamp=self.current_time or time.time(),
                )
                self.send(msg)
                self.logger.info(f"重合闸指令已发送 → [{target_id}]")

    # ════════════════════════════════════════════
    #  站控层指令处理
    # ════════════════════════════════════════════

    def on_station_command(self, msg: Message) -> None:
        if msg.sender_id == "monitor_host" and msg.msg_type == MsgType.CMD:
            self.logger.info(f"收到监控主机下发的手动指令: {msg.payload}，转发至断路器")
            self.command_to_process(
                receiver_id="breaker_it",
                payload=msg.payload,
                msg_type=MsgType.CMD,
                app_protocol=AppProtocol.GOOSE,
                transport_medium=TransportMedium.RF_LOW_LATENCY,
            )
