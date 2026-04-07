"""
devices/sensors/voltage_sensor.py

电压传感器 —— 过程层传感器

拓扑位置:  电压传感器 → 主变合并单元 (transformer_mu)
通信协议:  电压数据 100V + 无线 Sub-G
上报模式:  periodic (每次采样都上报, 供合并单元做 4kHz 同步采样)

采样值格式 (三相电压):
    {
        "ua": float,   # A相电压 (V)
        "ub": float,   # B相电压 (V)
        "uc": float,   # C相电压 (V)
    }
"""

import random
import math
import time
from typing import Any, Dict

from base.base_sensor import BaseSensor, ReportTrigger
from common.bus import MessageBus
from common.message import MsgType, AppProtocol, TransportMedium
from common.topology import TopologyRegistry, global_topo


class VoltageSensor(BaseSensor):
    """
    电压传感器

    模拟三相交流电压采样, 输出瞬时电压值。
    采样率与主变合并单元的 SV 帧率对齐 (默认 4kHz, 即 0.00025s)。

    Parameters
    ----------
    device_id        : str    设备 ID, 默认 "voltage_sensor"
    nominal_voltage  : float  额定相电压有效值 (V), 默认 57.74V (100V线电压 / √3)
    frequency        : float  电网频率 (Hz), 默认 50.0
    noise_ratio      : float  噪声幅度占额定值的比例, 默认 0.005 (0.5%)
    sample_interval  : float  采样周期 (秒), 默认 0.00025 (4kHz)
    bus              : MessageBus  消息总线实例
    device_name      : str    可读名称
    topo             : TopologyRegistry  拓扑注册表实例
    """

    def __init__(
        self,
        device_id:       str   = "voltage_sensor",
        nominal_voltage: float = 57.74,
        frequency:       float = 50.0,
        noise_ratio:     float = 0.005,
        sample_interval: float = 0.00025,
        bus:             MessageBus = None,
        device_name:     str   = "电压传感器",
        topo:            TopologyRegistry = None,
    ):
        super().__init__(
            device_id=device_id,
            app_protocol=AppProtocol.RAW_ANALOG,
            transport_medium=TransportMedium.SUB_G,
            sample_interval=sample_interval,
            report_mode="periodic",
            unit="V",
            msg_type=MsgType.DATA,
            change_threshold=None,      # 周期性全量上报, 无需变化检测
            bus=bus,
            device_name=device_name,
            topo=topo,
        )

        # ── 电气参数 ──
        self.nominal_voltage: float = nominal_voltage
        self.frequency:       float = frequency
        self.noise_ratio:     float = noise_ratio

        # ── 峰值 = 有效值 × √2 ──
        self._peak_voltage: float = nominal_voltage * math.sqrt(2)

        # ── 三相相位偏移 (弧度): A=0°, B=-120°, C=-240° ──
        self._phase_offsets: Dict[str, float] = {
            "ua": 0.0,
            "ub": -2.0 * math.pi / 3.0,
            "uc": -4.0 * math.pi / 3.0,
        }

        # ── 内部采样计数器 (用于计算相位角) ──
        self._sample_count: int = 0

        self.logger.info(
            f"电压传感器参数: 额定电压={self.nominal_voltage}V(有效值), "
            f"峰值={self._peak_voltage:.2f}V, "
            f"频率={self.frequency}Hz, "
            f"噪声比={self.noise_ratio}"
        )

    # ════════════════════════════════════════════
    #  核心采样方法 (BaseSensor 要求实现)
    # ════════════════════════════════════════════

    def sample(self) -> Dict[str, float]:
        """
        三相电压瞬时值采样

        优先从 CSV 数据源读取, 无数据则自行生成正弦波。
        """
        # ── 文件数据源优先 ──
        row = self._next_row()
        if row is not None:
            return self._parse_voltage_row(row)

        # ── 原有自生成逻辑 (不变) ──
        t = self._sample_count * self.sample_interval
        self._sample_count += 1
        omega = 2.0 * math.pi * self.frequency

        result = {}
        for phase, offset in self._phase_offsets.items():
            ideal = self._peak_voltage * math.sin(omega * t + offset)
            noise = random.gauss(0, self._peak_voltage * self.noise_ratio)
            result[phase] = round(ideal + noise, 4)
        return result

    def _parse_voltage_row(self, row: Dict[str, str]) -> Dict[str, float]:
        """
        将 CSV 行数据转换为电压采样值

        CSV 列名: ua, ub, uc (浮点数)

        Parameters
        ----------
        row : dict  CSV 行 (值为字符串)

        Returns
        -------
        dict  {"ua": float, "ub": float, "uc": float}
        """
        try:
            return {
                "ua": float(row["ua"]),
                "ub": float(row["ub"]),
                "uc": float(row["uc"]),
            }
        except (KeyError, ValueError) as e:
            self.logger.warning(f"CSV 行解析失败: {row}, 错误: {e}")
            # 解析失败回退到自生成
            return self.sample()


    # ════════════════════════════════════════════
    #  载荷打包 (可选重写, 添加电压专有字段)
    # ════════════════════════════════════════════

    def build_payload(self, raw_value: Any, report_trigger: str) -> Dict[str, Any]:
        """
        在基类标准载荷基础上, 添加电压传感器专有字段

        额外字段:
          - sample_count : 采样序号 (供合并单元对齐)
          - nominal_voltage : 额定电压 (V)
        """
        payload = super().build_payload(raw_value, report_trigger)
        payload["sample_count"]    = self._sample_count
        payload["nominal_voltage"] = self.nominal_voltage
        return payload

    # ════════════════════════════════════════════
    #  仿真辅助方法
    # ════════════════════════════════════════════

    def set_voltage(self, nominal_voltage: float) -> None:
        """
        运行时调整额定电压 (仿真场景: 模拟过压/欠压)

        Parameters
        ----------
        nominal_voltage : float  新的额定相电压有效值 (V)
        """
        self.nominal_voltage = nominal_voltage
        self._peak_voltage = nominal_voltage * math.sqrt(2)
        self.logger.info(
            f"额定电压已调整: {nominal_voltage}V (峰值={self._peak_voltage:.2f}V)"
        )

    def reset_sample_counter(self) -> None:
        """重置采样计数器 (通常在时间同步后调用)"""
        self._sample_count = 0
        self.logger.debug("采样计数器已重置")
