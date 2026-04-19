"""
devices/sensors/mechanical_sensor.py

机械状态传感器 —— 过程层传感器

拓扑位置:  机械状态传感器 → 断路器智能终端 (breaker_it)
通信协议:  分合位置 (合闸) / 开关量 + 无线 Sub-G
上报模式:  mixed
  - 周期上报: 后台线程按 sample_interval 自动触发 collect_and_report()
  - 事件上报: position 变化时立即额外触发一次，不等下一个采样周期

采样值格式 (断路器机械状态):
    {
        "position":        str,    # 分合位置: "open" / "closed" / "intermediate"
        "operation_count": int,    # 累计操作次数
        "travel_time_ms":  float,  # 最近一次动作行程时间 (ms)
        "spring_charged":  bool,   # 弹簧是否已储能
    }
"""
import logging
import random
import threading
import time
from typing import Any, Dict

from base.base_sensor import BaseSensor, ReportTrigger
from common.bus import MessageBus
from common.message import Message, MsgType, AppProtocol, TransportMedium
from common.topology import TopologyRegistry


class MechanicalSensor(BaseSensor):
    """
    机械状态传感器

    纯状态驱动，不依赖 CSV。内部维护断路器当前机械状态，
    后台线程按 sample_interval 周期上报；position 发生变化时
    立即额外触发一次事件上报，不等下一个采样周期。

    breaker_it 执行分合闸后会通过总线发送 CMD(set_position) 消息，
    on_message 收到后调用 set_position() 完成状态闭环回写。

    Parameters
    ----------
    device_id        : str    设备 ID，默认 "mechanical_sensor"
    initial_position : str    初始分合位置，默认 "open"
    sample_interval  : float  采样周期（秒），默认 1s
    bus              : MessageBus  消息总线实例
    device_name      : str    可读名称
    topo             : TopologyRegistry  拓扑注册表实例
    """

    VALID_POSITIONS = ("open", "closed", "intermediate")

    def __init__(
        self,
        device_id:        str   = "mechanical_sensor",
        initial_position: str   = "open",
        sample_interval:  float = 1,
        bus:              MessageBus = None,
        device_name:      str   = "机械状态传感器",
        topo:             TopologyRegistry = None,
    ):
        super().__init__(
            device_id=device_id,
            app_protocol=AppProtocol.RAW_DIGITAL,
            transport_medium=TransportMedium.SUB_G,
            sample_interval=sample_interval,
            report_mode="mixed",
            unit="",
            msg_type=MsgType.STATUS,
            change_threshold={"field": "position"},
            bus=bus,
            device_name=device_name,
            topo=topo,
        )

        self._position:        str   = initial_position
        self._operation_count: int   = 0
        self._travel_time_ms:  float = 0.0
        self._spring_charged:  bool  = True

        self._running: bool = False
        self._thread:  threading.Thread = None

        self.audit_log("SYSTEM", "STARTUP", details={
            "initial_position": self._position,
            "sample_interval": self.sample_interval
        }, level=logging.INFO)

    # ════════════════════════════════════════════
    #  状态属性 (只读)
    # ════════════════════════════════════════════

    @property
    def position(self) -> str:
        return self._position

    @property
    def operation_count(self) -> int:
        return self._operation_count

    @property
    def spring_charged(self) -> bool:
        return self._spring_charged

    # ════════════════════════════════════════════
    #  周期采样线程
    # ════════════════════════════════════════════

    def start(self) -> None:
        """启动后台周期采样线程。"""
        if self._running:
            # self.logger.warning("周期采样线程已在运行，忽略重复启动")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            name=f"{self.device_id}_loop",
            daemon=True,
        )
        self._thread.start()
        self.audit_log("SYSTEM", "SAMPLING_THREAD_START", details={"interval": self.sample_interval})

    def stop(self) -> None:
        """停止后台周期采样线程，等待线程退出。"""
        if not self._running:
            return
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=self.sample_interval * 3)
        self.audit_log("SYSTEM", "SAMPLING_THREAD_STOP")

    def _loop(self) -> None:
        """后台线程主体：周期性调用标准采集上报流程。"""
        while self._running:
            self.collect_and_report()
            time.sleep(self.sample_interval)

    # ════════════════════════════════════════════
    #  核心采样方法 (BaseSensor 要求实现)
    # ════════════════════════════════════════════

    def sample(self) -> Dict[str, Any]:
        """返回当前内部机械状态快照，所有字段由状态机自动维护。"""
        return {
            "position":        self._position,
            "operation_count": self._operation_count,
            "travel_time_ms":  self._travel_time_ms,
            "spring_charged":  self._spring_charged,
        }

    # ════════════════════════════════════════════
    #  消息接收
    # ════════════════════════════════════════════

    def on_message(self, msg: Message) -> None:
        """
        总线回调入口。

        处理以下消息类型:
          - SYNC : 来自上层设备的时间同步信号
          - CMD  : 来自 breaker_it 的位置变更指令（闭环回写）
        """
        if msg.msg_type == MsgType.SYNC:
            self._handle_time_sync(msg)
        elif msg.msg_type == MsgType.CMD:
            if msg.sender_id not in self.upstream_ids:
                self.audit_log("SECURITY", "ILLEGAL_SENSOR_TAMPERING", msg=msg, details={
                    "impact": "Unauthorized attempt to tamper with physical sensor state via bypass command",
                    "action": "Command Dropped"
                }, level=logging.CRITICAL)
                return
            self._handle_command(msg)
        else:
            self.audit_log("SECURITY", "ILLEGAL_SENSOR_ACCESS", msg=msg, details={
                "action": "Message Dropped"
            }, level=logging.CRITICAL)

    def _handle_command(self, msg: Message) -> None:
        """
        处理来自 breaker_it 的位置变更指令。

        breaker_it 执行分合闸后通过总线发送:
            payload = {"action": "set_position", "position": "open"/"closed"}

        收到后调用 set_position() 完成状态同步，同时触发事件上报，
        确保 breaker_it 下一次收到的周期状态与实际执行结果一致。
        """
        if not isinstance(msg.payload, dict):
            self.audit_log("CONTROL", "INVALID_COMMAND_FORMAT", msg=msg, level=logging.WARNING)
            return

        action = msg.payload.get("action")

        if action == "set_position":
            new_position = msg.payload.get("position")
            if not new_position:
                # self.logger.warning("set_position 指令缺少 position 字段")
                return
            try:
                self.set_position(new_position)
            except ValueError as e:
                self.audit_log("CONTROL", "SET_POSITION_FAILED", details={"error": str(e)}, level=logging.WARNING)
        else:
            self.audit_log("CONTROL", "UNKNOWN_COMMAND", details={"action": action}, level=logging.DEBUG)

    def _handle_time_sync(self, msg: Message) -> None:
        """
        处理时间同步消息，更新自身时钟，不向下级联转发。
        """
        ts = msg.payload.get("sync_time") if isinstance(msg.payload, dict) else None
        if ts is not None:
            self.sync_time(ts)
            self.audit_log("TIME", "TIME_SYNCED", details={"sync_timestamp": ts}, level=logging.DEBUG)
        # else:
        #     self.logger.warning(f"时间同步载荷格式异常: {msg.payload}")

    # ════════════════════════════════════════════
    #  状态控制接口
    # ════════════════════════════════════════════

    def set_position(self, new_position: str) -> None:
        """
        设置断路器位置，自动更新关联字段并立即触发一次事件上报。

        位置变化时：
          - operation_count  到达终态（open/closed）时自增
          - travel_time_ms   随机生成正常范围值（40~80ms），中间态清零
          - spring_charged   合闸后置 False（弹簧释放），分闸后置 True
        """
        if new_position not in self.VALID_POSITIONS:
            raise ValueError(
                f"非法位置值: {new_position}, 合法值: {self.VALID_POSITIONS}"
            )

        old_position = self._position
        if old_position == new_position:
            # self.logger.debug(f"位置未变化，仍为 {new_position}")
            return

        self._position = new_position

        if new_position in ("open", "closed"):
            self._operation_count += 1
            self._travel_time_ms = round(random.uniform(40.0, 80.0), 2)
            self._spring_charged = new_position != "closed"
        else:
            self._travel_time_ms = 0.0

        self.audit_log("CONTROL", "PHYSICAL_STATE_CHANGED", details={
            "old_position": old_position,
            "new_position": new_position,
            "operation_count": self._operation_count,
            "travel_time_ms": self._travel_time_ms,
            "spring_charged": self._spring_charged
        }, level=logging.INFO)

        # 立即触发事件上报，绕过 _evaluate_trigger 直接指定 EVENT
        current_sample = self.sample()
        payload = self.build_payload(current_sample, ReportTrigger.EVENT)
        self._send_to_upstream(payload)
        # 同步更新缓存，避免后台周期线程下一拍重复判定为变化
        self._last_sample_value = current_sample

    def charge_spring(self) -> None:
        """模拟弹簧储能完成（合闸后由外部在适当延时后调用）。"""
        self._spring_charged = True
        self.audit_log("CONTROL", "SPRING_CHARGED", level=logging.DEBUG)

    # ════════════════════════════════════════════
    #  便捷仿真接口
    # ════════════════════════════════════════════

    def simulate_close(self) -> None:
        """模拟完整合闸过程: open → intermediate → closed"""
        if self._position != "open":
            self.audit_log("CONTROL", "INVALID_SIMULATION_STATE", details={"expected": "open", "current": self._position}, level=logging.WARNING)
        self.set_position("intermediate")
        self.set_position("closed")

    def simulate_open(self) -> None:
        """模拟完整分闸过程: closed → intermediate → open"""
        if self._position != "closed":
            self.audit_log("CONTROL", "INVALID_SIMULATION_STATE", details={"expected": "closed", "current": self._position}, level=logging.WARNING)
        self.set_position("intermediate")
        self.set_position("open")
