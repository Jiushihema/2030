"""
devices/process/line_mu.py

线路合并单元 ── 过程层汇聚节点

拓扑位置:
    自身直接采集线路电流电压 (无下属传感器)
    上层: → 10kV 线路测控 (line_monitor)
          → 10kV 线路保护 (line_protect)
    跨层: 无线授时系统 (time_sync) → 线路合并单元 (PTP/IEEE 1588)

通信协议:
    上行: 线路电参数 SV 协议 (IEC 61850-9-2) + 无线 Mesh

核心职责:
    1. 自身模拟采集 10kV 出线的电流电压（额定值附近随机抖动）
    2. 按 SV 协议打包上报给线路测控和线路保护
    3. 接收 PTP 时间同步
    4. 支持攻击注入（inject_frame 单帧覆盖；set_continuous_inject 持续覆盖）
"""
import logging
import random
import time
import threading
from typing import Any, Dict, Optional

from base.base_process import BaseProcessAggregator
from common.bus import MessageBus
from common.message import Message, MsgType, AppProtocol, TransportMedium
from common.topology import TopologyRegistry


class LineMergingUnit(BaseProcessAggregator):
    """
    线路合并单元

    上报协议: SV (IEC 61850-9-2) + 无线 Mesh
    上报类型: MsgType.DATA
    上报周期: 0.00025s (4kHz)

    数据来源: 自身模拟生成，在额定值附近随机抖动。
    攻击注入: inject_frame() 单帧；set_continuous_inject() 每帧异常直至 clear。

    Parameters
    ----------
    device_id       : str    默认 "line_mu"
    report_interval : float  SV 帧周期（秒），默认 0.00025
    sv_id           : str    SV 流标识，默认同 device_id
    nominal_voltage : float  额定线路电压（kV），默认 10.0
    nominal_current : float  额定线路电流（A），默认 50.0
    bus             : MessageBus
    device_name     : str
    topo            : TopologyRegistry
    """

    def __init__(
        self,
        device_id:       str   = "line_mu",
        report_interval: float = 0.00025,
        sv_id:           str   = "",
        nominal_voltage: float = 10.0,
        nominal_current: float = 50.0,
        bus:             MessageBus = None,
        device_name:     str   = "线路合并单元",
        topo:            TopologyRegistry = None,
        breaker_ref = None,
    ):
        super().__init__(
            device_id=device_id,
            app_protocol=AppProtocol.SV,
            transport_medium=TransportMedium.MESH,
            report_interval=report_interval,
            report_msg_type=MsgType.DATA,
            bus=bus,
            device_name=device_name,
            topo=topo,
        )
        self._breaker_ref = breaker_ref
        self._sv_id:           str   = sv_id or device_id
        self._nominal_voltage: float = nominal_voltage
        self._nominal_current: float = nominal_current
        self._total_sv_frames: int   = 0

        # ── 攻击注入 ──
        self._injected_frame: Optional[dict] = None
        # 持续注入：合闸时每帧覆盖采样；分闸后断路器状态优先，始终报失电
        self._continuous_inject: Optional[dict] = None
        self._continuous_override: Optional[dict] = None

        # ── 自驱动线程 ──
        self._running:    bool = False
        self._thread:     Optional[threading.Thread] = None
        self._stop_event: Optional[threading.Event] = None

        # ── 供主循环摘要读取的最近一帧缓存 ──
        self.last_sample: Optional[Dict[str, float]] = None

        self.audit_log("SYSTEM", "STARTUP", details={
            "sv_id": self._sv_id,
            "sample_rate_hz": int(1.0 / self.report_interval) if self.report_interval > 0 else 0,
            "nominal_voltage": self._nominal_voltage,
            "nominal_current": self._nominal_current
        }, level=logging.INFO)

    # ════════════════════════════════════════════
    #  只读属性
    # ════════════════════════════════════════════

    @property
    def sv_id(self) -> str:
        return self._sv_id

    @property
    def total_sv_frames(self) -> int:
        return self._total_sv_frames

    # ════════════════════════════════════════════
    #  自驱动线程
    # ════════════════════════════════════════════

    def start(self, stop_event: threading.Event = None) -> None:
        """
        启动自驱动采样线程，按 report_interval 周期自动采样上报。

        Parameters
        ----------
        stop_event : threading.Event  可选，留作扩展用（line_mu 持续运行不会自动退出）
        """
        if self._running:
            self.audit_log("SYSTEM", "THREAD_START_IGNORED", details={"reason": "Already running"}, level=logging.WARNING)
            return
        self._stop_event = stop_event
        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            name=f"{self.device_id}_loop",
            daemon=True,
        )
        self._thread.start()
        self.audit_log("SYSTEM", "SAMPLING_THREAD_STARTED", details={"interval": self.report_interval}, level=logging.INFO)

    def stop(self) -> None:
        """停止自驱动采样线程。"""
        if not self._running:
            return
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.audit_log("SYSTEM", "SAMPLING_THREAD_STOPPED", level=logging.INFO)

    def _loop(self) -> None:
        """线程主体：持续按 report_interval 周期采样上报。"""
        while self._running:
            sample = self.sample_and_report()
            if sample is not None:
                self.last_sample = sample
            time.sleep(self.report_interval)

    # ════════════════════════════════════════════
    #  攻击注入
    # ════════════════════════════════════════════

    def inject_frame(self, override: dict) -> None:
        """
        注入一帧异常采样数据。
        下次采样时优先消费一次，消费后自动清空，不影响后续正常数据。

        Parameters
        ----------
        override : dict  如 {"voltage": 25.0, "current": 200.0}
        """
        self._injected_frame = override
        self.audit_log("ATTACK", "FDI_SINGLE_FRAME_INJECTED", details={
            "override_data": override,
            "impact": "Data will be manipulated in the next sampling cycle"
        }, level=logging.DEBUG)

    def set_continuous_inject(self, override: dict) -> None:
        """持续按 override 上报 SV（带微小抖动，模拟异常波形）。"""
        self._continuous_inject = dict(override)
        self.audit_log("ATTACK", "FDI_CONTINUOUS_INJECT_STARTED", details={
            "override_data": self._continuous_inject
        }, level=logging.DEBUG)

    def clear_continuous_inject(self) -> None:
        """关闭持续注入，恢复常规额定值附近波动。"""
        if self._continuous_inject is not None:
            self._continuous_inject = None
            self.audit_log("ATTACK", "FDI_CONTINUOUS_INJECT_STOPPED", details={
                "action": "Restoring normal grid sampling"
            }, level=logging.DEBUG)

    def set_continuous_override(self, override: dict) -> None:
        """持续 override 上报 SV（带微小抖动，模拟异常波形）。"""
        self._continuous_override = dict(override)
        self.audit_log("ATTACK", "GRID_FAULT_SIMULATION_STARTED", details={
            "fault_data": self._continuous_override
        }, level=logging.DEBUG)

    def clear_continuous_override(self) -> None:
        """关闭持续注入，恢复常规额定值附近波动。"""
        if self._continuous_override is not None:
            self._continuous_override = None
        self.audit_log("ATTACK", "GRID_FAULT_SIMULATION_STOPPED", details={
            "fault_data": self._continuous_override
        }, level=logging.DEBUG)

    # ════════════════════════════════════════════
    #  自采集
    # ════════════════════════════════════════════

    def self_sample(self):
        # 断路器分闸优先：线路已隔离，合并单元只应反映失电，注入不覆盖
        if self._breaker_ref is not None and self._breaker_ref.breaker_state == "open":
            # if self._injected_frame is not None:
            #     discarded = self._injected_frame
            #     self._injected_frame = None
            #     self.logger.warning(f"线路失电，丢弃未消费的注入帧: {discarded}")
            self.clear_continuous_override()
            return {
                "voltage": round(abs(random.gauss(0, 0.05)), 4),
                "current": round(abs(random.gauss(0, 0.01)), 4),
            }

        # 单次注入帧（仅合闸时生效）
        # if self._injected_frame is not None:
        #     frame = self._injected_frame
        #     self._injected_frame = None
        #     self.logger.warning(f"消费注入帧: {frame}")
        #     return {
        #         "voltage": float(frame.get("voltage", self._nominal_voltage)),
        #         "current": float(frame.get("current", self._nominal_current)),
        #     }

        # 持续过压/过流注入（仅合闸时生效）
        if self._continuous_inject is not None:
            base = self._continuous_inject
            v0 = float(base.get("voltage", self._nominal_voltage))
            c0 = float(base.get("current", self._nominal_current))
            voltage = v0 + random.gauss(0, max(v0 * 0.002, 0.02))
            current = c0 + random.gauss(0, max(c0 * 0.005, 0.1))
            return {
                "voltage": round(voltage, 4),
                "current": round(current, 4),
            }

        # 持续过压/过流异常（仅合闸时生效）
        if self._continuous_override is not None:
            base = self._continuous_override
            v0 = float(base.get("voltage", self._nominal_voltage))
            c0 = float(base.get("current", self._nominal_current))
            voltage = v0 + random.gauss(0, max(v0 * 0.002, 0.02))
            current = c0 + random.gauss(0, max(c0 * 0.005, 0.1))
            return {
                "voltage": round(voltage, 4),
                "current": round(current, 4),
            }

        # 正常运行：额定值附近随机抖动（常规电网波动）
        voltage = self._nominal_voltage + random.gauss(0, self._nominal_voltage * 0.02)
        current = self._nominal_current + random.gauss(0, self._nominal_current * 0.03)
        return {
            "voltage": round(voltage, 4),
            "current": round(current, 4),
        }


    # ════════════════════════════════════════════
    #  采集并上报
    # ════════════════════════════════════════════

    def sample_and_report(self) -> Optional[Dict[str, float]]:
        """采集一次线路数据并上报 SV 帧。"""
        sample = self.self_sample()
        self.update_cache(self.device_id, {"value": sample})
        aggregated = self.aggregate(self.get_latest_cache())
        if aggregated is not None:
            self.report_to_upstream(aggregated)
        return sample

    # ════════════════════════════════════════════
    #  BaseProcessAggregator 必须实现的方法
    # ════════════════════════════════════════════

    def handle_sensor_data(self, msg: Message) -> None:
        """线路合并单元没有下属传感器，收到意外数据仅缓存。"""
        self.audit_log("SECURITY", "UNEXPECTED_SENSOR_DATA", msg=msg, details={
            "reason": "Line MU has no downstream sensors, possible topology spoofing"
        }, level=logging.WARNING)
        if isinstance(msg.payload, dict):
            self.update_cache(msg.sender_id, msg.payload)

    def aggregate(
        self, latest_data: Dict[str, Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """汇聚线路电流电压数据。"""
        self_data = latest_data.get(self.device_id, {})
        value = self_data.get("value", {})
        if not isinstance(value, dict) or not value:
            return None
        return {
            "voltage": value.get("voltage", 0.0),
            "current": value.get("current", 0.0),
        }

    def wrap_payload(self, aggregated: Dict[str, Any]) -> Dict[str, Any]:
        """包裹 SV 帧头。"""
        self._sample_counter += 1
        samples_per_second = int(1.0 / self.report_interval)
        smp_cnt = self._sample_counter % samples_per_second
        self._total_sv_frames += 1
        return {
            "svID":        self._sv_id,
            "smpCnt":      smp_cnt,
            "smpSynch":    self.current_time is not None,
            "confRev":     1,
            "sample_time": self.current_time or time.time(),
            "voltage":     aggregated.get("voltage", 0.0),
            "current":     aggregated.get("current", 0.0),
        }

    def execute_command(self, cmd_payload: Dict[str, Any]) -> Dict[str, Any]:
        """线路合并单元不支持控制指令。"""
        self.audit_log("SECURITY", "UNAUTHORIZED_COMMAND_TO_MU", details={
            "payload": cmd_payload,
            "reason": "Merging Unit does not support control commands"
        }, level=logging.WARNING)

        return {
            "success":   False,
            "error":     "线路合并单元不支持控制指令",
            "device_id": self.device_id,
        }
