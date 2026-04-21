"""
device_bay/line_monitor.py

10kV 线路测控 (间隔层)

过压判据：对最近 SV_VOLTAGE_WINDOW_SIZE 帧电压做滑动均值（可选 RMS），
仅当窗口已满且窗口统计量连续 OVERVOLTAGE_PERSIST_COUNT 次高于阈值时才跳闸，
避免单点尖峰误动；与演示侧持续过压注入等 SV 流共用同一判据。
"""
import logging
import math
import time
import threading
from collections import deque
from typing import Deque, Optional, Dict, Any

from base.base_bay_device import BaseBayDevice
from common.message import Message, MsgType, AppProtocol, TransportMedium


class LineMonitorDevice(BaseBayDevice):

    OVERVOLTAGE_THRESHOLD = 12.0  # kV
    RECLOSE_DELAY         = 3.0   # 秒，方便手动演示
    COMMAND_TIMEOUT = 2.0  # 指令等待 ACK 的超时时间（秒）

    # 累计过压跳闸达到此次数时起闭锁自动重合闸（前几次仍可重合）
    RECLOSE_LOCK_AT_OVERVOLTAGE_TRIP = 5

    SV_VOLTAGE_WINDOW_SIZE = 5
    # 窗口已满后，连续若干次「窗口统计量 > 阈值」才出口跳闸
    OVERVOLTAGE_PERSIST_COUNT = 3
    # True：窗口内电压 RMS；False：算术均值
    USE_RMS_VOLTAGE_WINDOW = False

    def __init__(self, device_id="line_monitor", bus=None):
        super().__init__(device_id=device_id, bus=bus)

        self._reclose_timer:         threading.Timer = None
        self._last_voltage:          float = 0.0
        self._last_window_stat:      Optional[float] = None
        self._voltage_window:        Deque[float] = deque(maxlen=self.SV_VOLTAGE_WINDOW_SIZE)
        self._overvoltage_persistent_ticks: int = 0
        self._last_breaker_position: str   = "close"
        self._reclose_armed:         bool  = False
        self._protection_locked:       bool  = False
        self._auto_reclose_enabled:    bool  = True
        self._overvoltage_trip_count:  int   = 0
        # 演示用：闭锁过压判据触发的本地跳闸（不阻止 SV 上送与窗口统计）
        self.suppress_overvoltage_protection: bool = False

        self._pending_commands: Dict[str, Dict[str, Any]] = {}

    # ════════════════════════════════════════════
    #  闭环控制：指令超时处理
    # ════════════════════════════════════════════

    def _on_command_timeout(self, msg_id: str, action: str) -> None:
        """定时器触发：指令超时未收到下游 ACK"""
        cmd_info = self._pending_commands.pop(msg_id, None)
        if not cmd_info:
            return  # 已经被正常 ACK 处理并移除了
        # 记录本地严重安全日志
        self.audit_log("SECURITY", "COMMAND_TIMEOUT", details={
            "action": action,
            "msg_id": msg_id,
            "reason": "No ACK received from breaker_it, communication may be down or device is dead!"
        }, level=logging.CRITICAL)
        # 向上级主站紧急告警：通信瘫痪
        self.report_to_station(
            receiver_id="monitor_host",
            payload={
                "event": "communication_lost",
                "target": "breaker_it",
                "action": action,
                "impact": f"Protection {action} command failed to confirm. Grid is in DANGER!"
            },
            msg_type=MsgType.ALARM,
            app_protocol=AppProtocol.MMS,
        )

    # ════════════════════════════════════════════
    #  过程层数据处理
    # ════════════════════════════════════════════

    def on_process_data(self, msg: Message) -> None:
        if msg.sender_id == "line_mu" and msg.app_protocol == AppProtocol.SV:
            self._handle_sv_data(msg)
        elif msg.sender_id == "breaker_it" and msg.app_protocol == AppProtocol.GOOSE:
            self._handle_breaker_msg(msg)

    def _window_voltage_stat(self) -> Optional[float]:
        """窗口未满返回 None；已满返回均值或 RMS。"""
        w = self._voltage_window
        if len(w) < self.SV_VOLTAGE_WINDOW_SIZE:
            return None
        if self.USE_RMS_VOLTAGE_WINDOW:
            return math.sqrt(sum(v * v for v in w) / len(w))
        return sum(w) / len(w)

    def _handle_sv_data(self, msg: Message) -> None:
        voltage = float(msg.payload.get("voltage", 0.0))
        current = float(msg.payload.get("current", 0.0))
        self._last_voltage = voltage
        self._voltage_window.append(voltage)

        window_stat = self._window_voltage_stat()
        self._last_window_stat = window_stat

        window_ready = window_stat is not None
        if window_ready:
            over = window_stat > self.OVERVOLTAGE_THRESHOLD
            if over:
                if not self._protection_locked:
                    self._overvoltage_persistent_ticks += 1
            else:
                self._overvoltage_persistent_ticks = 0
        else:
            self._overvoltage_persistent_ticks = 0

        persist_ok = (
            window_ready
            and self._overvoltage_persistent_ticks >= self.OVERVOLTAGE_PERSIST_COUNT
        )

        if (
            persist_ok
            and window_stat > self.OVERVOLTAGE_THRESHOLD
            and not self.suppress_overvoltage_protection
        ):
            if self._protection_locked:
                return
            self._protection_locked = True
            self._overvoltage_trip_count += 1
            if self._overvoltage_trip_count >= self.RECLOSE_LOCK_AT_OVERVOLTAGE_TRIP:
                self._auto_reclose_enabled = False
                self._reclose_armed = False
                if self._reclose_timer is not None:
                    self._reclose_timer.cancel()
                    self._reclose_timer = None
                self.audit_log("CONTROL", "PROTECTION_LOCKOUT", details={
                    "trip_count": self._overvoltage_trip_count,
                    "reason": "max_overvoltage_trips_reached"
                }, level=logging.WARNING)

            stat_label = "RMS" if self.USE_RMS_VOLTAGE_WINDOW else "MEAN"
            self.audit_log("CONTROL", "PROTECTION_TRIP", details={
                "reason": "line_overvoltage",
                "stat_type": stat_label,
                "window_stat": window_stat,
                "raw_voltage": voltage,
                "window_size": self.SV_VOLTAGE_WINDOW_SIZE,
                "persist_ticks": self._overvoltage_persistent_ticks
            }, level=logging.WARNING)

            trip_msg = Message(
                sender_id=self.device_id,
                receiver_id="breaker_it",
                msg_type=MsgType.CMD,
                app_protocol=AppProtocol.GOOSE,
                transport_medium=TransportMedium.RF_LOW_LATENCY,
                payload={"action": "trip", "reason": "line_overvoltage"},
                timestamp=self.current_time,
            )
            # 启动定时器
            timer = threading.Timer(self.COMMAND_TIMEOUT, self._on_command_timeout, args=[trip_msg.msg_id, "trip"])
            timer.daemon = True
            timer.start()

            # 将上下文存入 pending_commands，等待 ACK 时使用
            self._pending_commands[trip_msg.msg_id] = {
                "timer": timer,
                "action": "trip",
                "voltage": voltage,
                "window_stat": window_stat
            }

            self.send(trip_msg)

            # self.command_to_process(
            #     receiver_id="breaker_it",
            #     payload={"action": "trip", "reason": "line_overvoltage"},
            #     msg_type=MsgType.CMD,
            #     app_protocol=AppProtocol.GOOSE,
            #     transport_medium=TransportMedium.RF_LOW_LATENCY,
            # )
            # self.report_to_station(
            #     receiver_id="monitor_host",
            #     payload={
            #         "event": "line_trip_executed",
            #         "voltage": voltage,
            #         "window_voltage_stat": window_stat,
            #         "window_size": self.SV_VOLTAGE_WINDOW_SIZE,
            #     },
            #     msg_type=MsgType.ALARM,
            #     app_protocol=AppProtocol.MMS,
            # )
        else:
            normal = (
                (window_stat is not None and window_stat <= self.OVERVOLTAGE_THRESHOLD)
                or (window_stat is None and voltage <= self.OVERVOLTAGE_THRESHOLD)
            )
            if normal:
                if self._protection_locked:
                    self._protection_locked = False
                    self.audit_log("CONTROL", "PROTECTION_UNLOCKED", level=logging.INFO)
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
            ack_for = payload.get("ack_for")

            # 收到 ACK，取消对应的超时定时器
            cmd_info = self._pending_commands.pop(ack_for, None)
            if cmd_info and "timer" in cmd_info:
                cmd_info["timer"].cancel()

            # result = payload.get("result", {})
            # if result.get("success") and result.get("action") == "open":
            #     # 分闸后线路进入失电态，清空过压滑窗，避免历史高压残留导致重合闸误判失败
            #     self._voltage_window.clear()
            #     self._overvoltage_persistent_ticks = 0
            #     self._last_window_stat = None
            #     if not self._auto_reclose_enabled:
            #         self.audit_log("CONTROL", "RECLOSE_DISABLED", details={
            #             "reason": "lockout_threshold_reached"
            #         }, level=logging.WARNING)
            #     else:
            #         self.audit_log("CONTROL", "BREAKER_TRIP_SUCCESS", msg=msg, details={
            #             "action": "open",
            #             "next_step": "schedule_reclose"
            #         }, level=logging.INFO)
            #         self._reclose_armed = True
            #         self._schedule_reclose()
            # elif not result.get("success"):
            #     # 分闸失败（可能传感器被篡改导致拒绝执行）
            #     self.audit_log("SECURITY", "BREAKER_TRIP_REJECTED", msg=msg, details={
            #         "error": result.get("error"),
            #         "breaker_state": result.get("state"),
            #         "impact": "line_remains_faulty"
            #     }, level=logging.CRITICAL)
            #
            #     self.report_to_station(
            #         receiver_id="monitor_host",
            #         payload={
            #             "event":  "trip_rejected",
            #             "reason": result.get("error"),
            #             "state":  result.get("state"),
            #         },
            #         msg_type=MsgType.ALARM,
            #         app_protocol=AppProtocol.MMS,
            #     )
            result = payload.get("result", {})
            action = result.get("action") or (cmd_info.get("action") if cmd_info else "unknown")

            if result.get("success"):
                if action in ("open", "trip"):
                    self.audit_log("CONTROL", "BREAKER_TRIP_SUCCESS", msg=msg, details={
                        "action": "open",
                        "next_step": "schedule_reclose"
                    }, level=logging.INFO)

                    # 确认跳闸成功后，才向站控层上报！
                    v_report = cmd_info.get("voltage", self._last_voltage) if cmd_info else self._last_voltage
                    w_report = cmd_info.get("window_stat",
                                            self._last_window_stat) if cmd_info else self._last_window_stat

                    self.report_to_station(
                        receiver_id="monitor_host",
                        payload={
                            "event": "line_trip_executed",
                            "voltage": v_report,
                            "window_voltage_stat": w_report,
                            "window_size": self.SV_VOLTAGE_WINDOW_SIZE,
                        },
                        msg_type=MsgType.ALARM,
                        app_protocol=AppProtocol.MMS,
                    )
                    # 启动重合闸
                    self._voltage_window.clear()
                    self._overvoltage_persistent_ticks = 0
                    self._last_window_stat = None
                    if not self._auto_reclose_enabled:
                        self.audit_log("CONTROL", "RECLOSE_DISABLED", details={"reason": "lockout"},
                                       level=logging.WARNING)
                    else:
                        self._reclose_armed = True
                        self._schedule_reclose()
                elif action == "close":
                    self.audit_log("CONTROL", "BREAKER_CLOSE_SUCCESS", msg=msg, level=logging.INFO)
            elif not result.get("success"):
                # 分闸/合闸失败（如传感器被篡改导致拒绝执行）
                self.audit_log("SECURITY", f"BREAKER_CMD_REJECTED", msg=msg, details={
                    "action": action,
                    "error": result.get("error"),
                    "breaker_state": result.get("state"),
                    "impact": "line_remains_faulty" if action in ("open", "trip") else "reclose_failed"
                }, level=logging.CRITICAL)
                self.report_to_station(
                    receiver_id="monitor_host",
                    payload={
                        "event": f"{action}_rejected",
                        "reason": result.get("error"),
                        "state": result.get("state"),
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

        self.audit_log("CONTROL", "RECLOSE_SCHEDULED", details={
            "delay_seconds": self.RECLOSE_DELAY
        }, level=logging.INFO)

    def _attempt_reclose(self) -> None:
        if not self._reclose_armed:
            return
        self._reclose_armed = False

        v_chk = (
            self._last_window_stat
            if self._last_window_stat is not None
            else self._last_voltage
        )
        if v_chk > self.OVERVOLTAGE_THRESHOLD:
            self.audit_log("CONTROL", "RECLOSE_ABORTED", details={
                "reason": "permanent_fault",
                "voltage_check": v_chk,
                "threshold": self.OVERVOLTAGE_THRESHOLD
            }, level=logging.WARNING)

            self.report_to_station(
                receiver_id="monitor_host",
                payload={
                    "event":   "reclose_failed",
                    "reason":  "permanent_fault",
                    "voltage": self._last_voltage,
                    "window_voltage_stat": self._last_window_stat,
                },
                msg_type=MsgType.ALARM,
                app_protocol=AppProtocol.MMS,
            )
            return

        self.audit_log("CONTROL", "RECLOSE_CONDITION_MET", level=logging.INFO)
        self._send_close_command()

    def _send_close_command(self) -> None:
        for target_id in self.downstream_ids:
            if "breaker" in target_id:
                close_msg = Message(
                    sender_id=self.device_id,
                    receiver_id=target_id,
                    msg_type=MsgType.CMD,
                    app_protocol=AppProtocol.GOOSE,
                    transport_medium=TransportMedium.RF_LOW_LATENCY,
                    payload={"action": "close", "reason": "auto_reclose"},
                    timestamp=self.current_time or time.time(),
                )
                timer = threading.Timer(self.COMMAND_TIMEOUT, self._on_command_timeout,
                                        args=[close_msg.msg_id, "close"])
                timer.daemon = True
                timer.start()

                self._pending_commands[close_msg.msg_id] = {
                    "timer": timer,
                    "action": "close"
                }

                self.send(close_msg)
                self.audit_log("CONTROL", "RECLOSE_EXECUTE_SENT", details={
                    "target": target_id,
                    "msg_id": close_msg.msg_id
                }, level=logging.INFO)

    # ════════════════════════════════════════════
    #  站控层指令处理
    # ════════════════════════════════════════════

    def on_station_command(self, msg: Message) -> None:
        if msg.sender_id == "monitor_host" and msg.msg_type == MsgType.CMD:
            action = msg.payload.get("action", "unknown")
            self.audit_log("CONTROL", "FORWARD_MANUAL_CMD", msg=msg, details={
                "target": "breaker_it",
                "payload": msg.payload
            }, level=logging.INFO)

            fwd_msg = Message(
                sender_id=self.device_id,
                receiver_id="breaker_it",
                msg_type=MsgType.CMD,
                app_protocol=AppProtocol.GOOSE,
                transport_medium=TransportMedium.RF_LOW_LATENCY,
                payload=msg.payload,
                timestamp=self.current_time or time.time(),
            )
            timer = threading.Timer(self.COMMAND_TIMEOUT, self._on_command_timeout, args=[fwd_msg.msg_id, action])
            timer.daemon = True
            timer.start()

            self._pending_commands[fwd_msg.msg_id] = {
                "timer": timer,
                "action": action
            }

            self.send(fwd_msg)