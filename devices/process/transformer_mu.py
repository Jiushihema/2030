"""
devices/process/transformer_mu.py

主变合并单元 —— 过程层汇聚节点

拓扑位置:
    下层: 电流传感器 (current_sensor) + 电压传感器 (voltage_sensor) → 主变合并单元
    上层: 主变合并单元 → 主变测控装置 (transformer_monitor)
                       → 主变保护装置 (transformer_protect)
    跨层: 无线授时系统 (time_sync) → 主变合并单元 (PTP/IEEE 1588)

通信协议:
    上行: 电参数采样数据 SV 协议 (IEC 61850-9-2) + 无线 Mesh
    下行 (采集): 电流数据 SA + 无线 Sub-G / 电压数据 100V + 无线 Sub-G
    授时: 时间同步 PTP/IEEE 1588 + 无线射频

核心职责:
    1. 接收电流和电压传感器高速采样数据, 缓存最新值
    2. 按 4kHz 采样率周期性汇聚三相电流电压为 SV 帧
    3. 包裹 SV 协议帧头 (svID, smpCnt, smpSynch 等)
    4. 将 SV 帧发送至主变测控和主变保护装置
    5. 接收 PTP 时间同步并级联转发给下属传感器
"""
import logging
import math
import threading
import time
from typing import Any, Dict, Optional

from base.base_process import BaseProcessAggregator
from common.bus import MessageBus
from common.message import Message, MsgType, AppProtocol, TransportMedium
from common.topology import TopologyRegistry


class TransformerMergingUnit(BaseProcessAggregator):
    """
    主变合并单元

    上报协议: SV (IEC 61850-9-2) + 无线 Mesh
    上报消息类型: MsgType.DATA (电参数采样数据)
    上报周期: 0.00025s (4kHz, 每秒 4000 帧)

    Parameters
    ----------
    device_id        : str    设备 ID, 默认 "transformer_mu"
    report_interval  : float  SV 帧上报周期 (秒), 默认 0.00025 (4kHz)
    sv_id            : str    SV 流标识, 默认与 device_id 相同
    rated_current    : float  额定电流 (A), 用于品质因子计算
    rated_voltage    : float  额定电压 (V), 用于品质因子计算
    bus              : MessageBus  消息总线实例
    device_name      : str    可读名称
    topo             : TopologyRegistry  拓扑注册表实例
    """

    def __init__(
        self,
        device_id:       str   = "transformer_mu",
        report_interval: float = 0.00025,
        sv_id:           str   = "",
        rated_current:   float = 600.0,
        rated_voltage:   float = 57.74,
        bus:             MessageBus = None,
        device_name:     str   = "主变合并单元",
        topo:            TopologyRegistry = None,
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

        # ── SV 帧参数 ──
        self._sv_id: str = sv_id or device_id
        self._rated_current: float = rated_current
        self._rated_voltage: float = rated_voltage

        # ── 数据质量标志 ──
        self._quality_flags: Dict[str, str] = {
            "current": "good",
            "voltage": "good",
        }

        # ── 统计 ──
        self._total_sv_frames: int = 0

        # ── 自驱动 SV 线程 (与 line_mu 一致, 按 report_interval 周期上报) ──
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event: Optional[threading.Event] = None
        self._logged_empty_cache: bool = False

        # 最近一帧完整 SV 载荷 (wrap_payload 之后), 供调试 / 演示读取
        self.last_sample: Optional[Dict[str, Any]] = None

        self.audit_log("SYSTEM", "STARTUP", details={
            "sv_id": self._sv_id,
            "sample_rate_hz": int(1.0 / self.report_interval) if self.report_interval > 0 else 0,
            "rated_current": self._rated_current,
            "rated_voltage": self._rated_voltage
        }, level=logging.INFO)

    # ════════════════════════════════════════════
    #  状态属性 (只读)
    # ════════════════════════════════════════════

    @property
    def sv_id(self) -> str:
        """SV 流标识"""
        return self._sv_id

    @property
    def total_sv_frames(self) -> int:
        """已发送的 SV 帧总数"""
        return self._total_sv_frames

    @property
    def quality_flags(self) -> Dict[str, str]:
        """数据质量标志"""
        return dict(self._quality_flags)

    # ════════════════════════════════════════════
    #  自驱动 SV 上报线程
    # ════════════════════════════════════════════

    def start(self, stop_event: threading.Event = None) -> None:
        """启动周期性 SV 上报线程。"""
        if self._running:
            self.audit_log("SYSTEM", "THREAD_START_IGNORED", details={"reason": "Already running"}, level=logging.WARNING)
            return
        self._stop_event = stop_event
        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            name=f"{self.device_id}_sv_loop",
            daemon=True,
        )
        self._thread.start()
        self.audit_log("SYSTEM", "SAMPLING_THREAD_STARTED", details={
            "interval": self.report_interval,
            "hz": int(1.0 / self.report_interval) if self.report_interval > 0 else 0
        }, level=logging.INFO)

    def stop(self) -> None:
        """停止 SV 上报线程。"""
        if not self._running:
            return
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self.audit_log("SYSTEM", "SAMPLING_THREAD_STOPPED", level=logging.INFO)

    def _loop(self) -> None:
        while self._running:
            if self._stop_event is not None and self._stop_event.is_set():
                break
            self.periodic_report()
            time.sleep(self.report_interval)

    def report_to_upstream(self, payload: Dict[str, Any]) -> None:
        """上报并缓存最近一帧 SV (wrap_payload 仅调用一次, 避免采样计数重复递增)。"""
        wrapped = self.wrap_payload(payload)
        self.last_sample = wrapped

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

    # ════════════════════════════════════════════
    #  传感器数据处理 (BaseProcessAggregator 要求实现)
    # ════════════════════════════════════════════

    def handle_sensor_data(self, msg: Message) -> None:
        """
        处理来自电流/电压传感器的高速采样数据

        策略:
          纯缓存模式 —— 传感器数据到达后仅更新缓存,
          不触发立即上报。SV 帧的上报完全由 periodic_report() 驱动,
          保证严格的 4kHz 采样同步。

        Parameters
        ----------
        msg : Message  来自电流或电压传感器的数据消息
        """
        if msg.sender_id not in self._downstream_ids:
            self.audit_log("SECURITY", "UNEXPECTED_SENSOR_DATA", msg=msg, details={
                "reason": "Sender not in downstream topology"
            }, level=logging.WARNING)
            return

        # 更新缓存
        self.update_cache(msg.sender_id, msg.payload)

        # 更新质量标志
        self._update_quality(msg.sender_id)

        # self.logger.debug(
        #     f"采样数据缓存更新: [{msg.sender_id}]"
        # )

    def _update_quality(self, sensor_id: str) -> None:
        """
        根据传感器数据更新质量标志

        Parameters
        ----------
        sensor_id : str  传感器 ID
        """
        if "current" in sensor_id and self._quality_flags["current"] != "good":
            self._quality_flags["current"] = "good"
            self.audit_log("DATA", "SENSOR_QUALITY_RESTORED", details={"sensor": "current"}, level=logging.INFO)
        elif "voltage" in sensor_id and self._quality_flags["voltage"] != "good":
            self._quality_flags["voltage"] = "good"
            self.audit_log("DATA", "SENSOR_QUALITY_RESTORED", details={"sensor": "voltage"}, level=logging.INFO)

    # ════════════════════════════════════════════
    #  数据汇聚 (BaseProcessAggregator 要求实现)
    # ════════════════════════════════════════════

    def aggregate(
        self, latest_data: Dict[str, Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        将电流和电压传感器的最新采样值汇聚为 SV 数据帧载荷

        SV 帧数据段包含三相电流和三相电压的瞬时采样值。

        Parameters
        ----------
        latest_data : dict  缓存快照 { sensor_id: payload_dict }

        Returns
        -------
        dict  SV 帧数据载荷, 格式:
              {
                  "ia": float, "ib": float, "ic": float,  # 三相电流
                  "ua": float, "ub": float, "uc": float,  # 三相电压
                  "quality_current": "good"|"invalid",
                  "quality_voltage": "good"|"invalid",
              }
        None  缓存完全为空时返回 None
        """
        # 提取电流数据
        current_data = latest_data.get("current_sensor", {})
        current_value = current_data.get("value", {})
        if not isinstance(current_value, dict):
            current_value = {}

        # 提取电压数据
        voltage_data = latest_data.get("voltage_sensor", {})
        voltage_value = voltage_data.get("value", {})
        if not isinstance(voltage_value, dict):
            voltage_value = {}

        # 如果电流和电压数据都为空, 跳过
        if not current_value and not voltage_value:
            return None

        # 标记缺失数据的质量标志
        if not current_value and self._quality_flags["current"] != "invalid":
            self._quality_flags["current"] = "invalid"
            self.audit_log("SECURITY", "SENSOR_DATA_LOSS", details={
                "sensor": "current_sensor",
                "impact": "SV_quality_degraded_to_invalid"
            }, level=logging.CRITICAL)
        if not voltage_value and self._quality_flags["voltage"] != "invalid":
            self._quality_flags["voltage"] = "invalid"
            self.audit_log("SECURITY", "SENSOR_DATA_LOSS", details={
                "sensor": "voltage_sensor",
                "impact": "SV_quality_degraded_to_invalid"
            }, level=logging.CRITICAL)

        return {
            # 三相电流
            "ia": current_value.get("ia", 0.0),
            "ib": current_value.get("ib", 0.0),
            "ic": current_value.get("ic", 0.0),
            # 三相电压
            "ua": voltage_value.get("ua", 0.0),
            "ub": voltage_value.get("ub", 0.0),
            "uc": voltage_value.get("uc", 0.0),
            # 数据质量
            "quality_current": self._quality_flags["current"],
            "quality_voltage": self._quality_flags["voltage"],
        }

    # ════════════════════════════════════════════
    #  SV 协议载荷包装 (重写基类钩子)
    # ════════════════════════════════════════════

    def wrap_payload(
        self, aggregated: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        包裹 SV 协议帧头

        IEC 61850-9-2 SV 帧格式:
          - svID       : SV 流标识
          - smpCnt     : 采样计数器 (0~3999, 每秒复位)
          - smpSynch   : 是否已同步 (bool)
          - confRev    : 配置版本号
          - sample_time: 采样时间戳
          - data       : 实际采样数据 (aggregate() 输出)

        Parameters
        ----------
        aggregated : dict  aggregate() 返回的汇聚载荷

        Returns
        -------
        dict  完整 SV 帧
        """
        # 递增采样计数器
        self._sample_counter += 1
        # 每秒复位 (基于 4kHz 采样率)
        samples_per_second = int(1.0 / self.report_interval)
        smp_cnt = self._sample_counter % samples_per_second

        self._total_sv_frames += 1

        return {
            "svID":        self._sv_id,
            "smpCnt":      smp_cnt,
            "smpSynch":    self.current_time is not None,
            "confRev":     1,
            "sample_time": self.current_time or time.time(),
            "data":        aggregated,
        }

    # ════════════════════════════════════════════
    #  控制指令执行 (BaseProcessAggregator 要求实现)
    # ════════════════════════════════════════════

    def execute_command(self, cmd_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        主变合并单元不支持控制指令

        合并单元是纯采集设备, 不执行任何控制动作。

        Parameters
        ----------
        cmd_payload : dict  指令载荷

        Returns
        -------
        dict  固定返回不支持
        """
        self.audit_log("SECURITY", "UNAUTHORIZED_COMMAND_TO_MU", details={
            "payload": cmd_payload,
            "reason": "Transformer Merging Unit does not support control commands"
        }, level=logging.WARNING)
        return {
            "success":   False,
            "error":     "主变合并单元不支持控制指令, 请发送至断路器智能终端",
            "device_id": self.device_id,
        }

    # ════════════════════════════════════════════
    #  计算辅助方法 (供间隔层装置使用的有效值计算)
    # ════════════════════════════════════════════

    def compute_rms_from_cache(self) -> Optional[Dict[str, float]]:
        """
        基于当前缓存的瞬时值估算有效值 (RMS)

        注意: 单点瞬时值无法精确计算 RMS, 此方法仅用于粗略估算。
        精确 RMS 计算应在间隔层测控装置中基于连续采样序列完成。

        Returns
        -------
        dict  {"ia_rms", "ib_rms", "ic_rms", "ua_rms", "ub_rms", "uc_rms"}
        None  缓存为空时
        """
        aggregated = self.aggregate(dict(self._latest_cache))
        if aggregated is None:
            return None

        # 瞬时值转估算有效值: Vrms ≈ |v_inst| / √2 (假设纯正弦)
        sqrt2 = math.sqrt(2)
        return {
            "ia_rms": round(abs(aggregated.get("ia", 0.0)) / sqrt2, 4),
            "ib_rms": round(abs(aggregated.get("ib", 0.0)) / sqrt2, 4),
            "ic_rms": round(abs(aggregated.get("ic", 0.0)) / sqrt2, 4),
            "ua_rms": round(abs(aggregated.get("ua", 0.0)) / sqrt2, 4),
            "ub_rms": round(abs(aggregated.get("ub", 0.0)) / sqrt2, 4),
            "uc_rms": round(abs(aggregated.get("uc", 0.0)) / sqrt2, 4),
        }

    # ════════════════════════════════════════════
    #  周期性上报 (重写以添加统计日志)
    # ════════════════════════════════════════════

    def periodic_report(self) -> None:
        """
        周期性 SV 帧上报 (4kHz 下禁止每帧 INFO, 仅每秒汇总一次)

        逻辑与基类相同, 但不调用 super, 以免基类对每次上报打 INFO。
        """
        if not self._latest_cache:
            if not self._logged_empty_cache:
                self.audit_log("DATA", "CACHE_EMPTY", details={"reason": "Waiting for sensor data"}, level=logging.DEBUG)
                self._logged_empty_cache = True
            return

        self._logged_empty_cache = False

        # missing = [
        #     sid for sid in self._downstream_ids
        #     if sid not in self._latest_cache
        # ]
        # if missing and self._report_count < 5:
        #     self.logger.debug(f"以下传感器尚无缓存数据: {missing}")

        aggregated = self.aggregate(dict(self._latest_cache))
        if aggregated is None:
            # self.logger.debug("aggregate() 返回 None, 跳过本轮上报")
            return

        self.report_to_upstream(aggregated)
        self._report_count += 1

        samples_per_second = int(1.0 / self.report_interval)
        if self._total_sv_frames % samples_per_second == 0:
            self.audit_log("SYSTEM", "SV_STATS_SUMMARY", details={
                "total_frames": self._total_sv_frames,
                "smpCnt": self._sample_counter,
                "smpSynch": self.current_time is not None,
                "quality_current": self._quality_flags["current"],
                "quality_voltage": self._quality_flags["voltage"]
            }, level=logging.INFO)
