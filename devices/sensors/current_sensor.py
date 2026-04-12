"""
devices/sensors/current_sensor.py

三相电流互感器 —— 过程层传感器 → 主变合并单元

采样模型与线路合并单元 self_sample() 一致：额定电流 + 比例高斯抖动（3% σ）。
"""

import random
import threading
import time
from typing import Any, Dict, Optional

from base.base_sensor import BaseSensor
from common.bus import MessageBus
from common.message import Message, MsgType, AppProtocol, TransportMedium
from common.topology import TopologyRegistry


class CurrentSensor(BaseSensor):
    """
    Parameters
    ----------
    device_id         : str    默认 "current_sensor"
    nominal_current   : float  额定电流 (A)，与主变合并单元 rated_current 对齐
    sample_interval   : float  采样周期 (s)，默认 0.00025 (4kHz，与 SV 帧率一致)
    bus, device_name, topo  同 BaseSensor
    """

    def __init__(
        self,
        device_id:       str   = "current_sensor",
        nominal_current: float = 600.0,
        sample_interval: float = 0.00025,
        bus:             MessageBus = None,
        device_name:     str   = "电流传感器",
        topo:            TopologyRegistry = None,
    ):
        super().__init__(
            device_id=device_id,
            app_protocol=AppProtocol.RAW_ANALOG,
            transport_medium=TransportMedium.SUB_G,
            sample_interval=sample_interval,
            report_mode="periodic",
            unit="A",
            msg_type=MsgType.DATA,
            change_threshold=None,
            bus=bus,
            device_name=device_name,
            topo=topo,
        )
        self._nominal_current = float(nominal_current)
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            self.logger.warning("周期采样线程已在运行，忽略重复启动")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            name=f"{self.device_id}_loop",
            daemon=True,
        )
        self._thread.start()
        self.logger.info(f"电流传感器周期采样启动，间隔={self.sample_interval}s")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=max(0.5, self.sample_interval * 4))
        self.logger.info("电流传感器周期采样已停止")

    def _loop(self) -> None:
        while self._running:
            self.collect_and_report()
            time.sleep(self.sample_interval)

    def _jitter_current(self) -> float:
        n = self._nominal_current
        return round(n + random.gauss(0, n * 0.03), 4)

    def load_data(self, filepath: str, mode: str = "once") -> int:
        self.logger.warning("电流传感器不支持外部 CSV，始终使用额定值仿真采样")
        return 0

    def sample(self) -> Dict[str, Any]:
        return {
            "ia": self._jitter_current(),
            "ib": self._jitter_current(),
            "ic": self._jitter_current(),
        }

    def on_message(self, msg: Message) -> None:
        if msg.msg_type == MsgType.SYNC:
            self._handle_time_sync(msg)
        else:
            self.logger.debug(
                f"收到非关注消息: type={msg.msg_type} from={msg.sender_id}"
            )
