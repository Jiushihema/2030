"""
base/base_sensor.py

改动说明：
  1. 新增 load_data() / clear_data() / _next_row() 方法
  2. 新增 _data_queue / _data_rows / _read_mode / _row_index 属性
  3. sample() 不改 —— 由子类自行在 sample() 开头调用 _next_row()
"""

import csv
import time
import logging
from abc import abstractmethod
from typing import Any, Dict, List, Optional

from base.base_device import BaseDevice
from common.bus import MessageBus
from common.message import Message, MsgType, AppProtocol, TransportMedium
from common.topology import TopologyRegistry, DeviceLayer, global_topo


class ReportTrigger:
    """上报触发类型常量"""
    PERIODIC = "periodic"
    EVENT    = "event"


class BaseSensor(BaseDevice):
    """
    过程层传感器基类

    --- 以下为新增的数据源相关文档 ---

    数据源机制:
      默认情况下 sample() 由子类自行生成数据 (simulate 模式)。
      调用 load_data(filepath, mode) 后切换为文件驱动模式,
      子类在 sample() 开头调用 self._next_row() 获取 CSV 行数据。

    load_data(filepath, mode) 参数:
      mode="once"  读完返回 None
      mode="loop"  循环回第一行
      mode="hold"  停在最后一行重复返回
    """

    VALID_READ_MODES = ("once", "loop", "hold")

    def __init__(
        self,
        device_id:        str,
        app_protocol:     str,
        transport_medium: str,
        sample_interval:  float,
        report_mode:      str,
        unit:             str = "",
        msg_type:         str = MsgType.DATA,
        change_threshold: Any = None,
        bus:              MessageBus = None,
        device_name:      str = "",
        topo:             TopologyRegistry = None,
    ):
        super().__init__(device_id=device_id, bus=bus, device_name=device_name)

        # ── 原有配置字段 (不变) ──
        self.app_protocol:     str   = app_protocol
        self.transport_medium: str   = transport_medium
        self.sample_interval:  float = sample_interval
        self.report_mode:      str   = report_mode
        self.unit:             str   = unit
        self.msg_type:         str   = msg_type
        self.change_threshold: Any   = change_threshold

        # ── 拓扑 (不变) ──
        self._topo = topo or global_topo
        self._upstream_ids: List[str] = self._discover_upstream()

        # ── 上一次采样值缓存 (不变) ──
        self._last_sample_value: Any = None

        # ── 新增: 文件数据源 ──
        self._data_rows:  List[Dict[str, str]] = []   # CSV 全部行 (原始字符串)
        self._row_index:  int  = 0                     # 当前读取位置
        self._read_mode:  str  = "once"                # 读取模式
        self._data_loaded: bool = False                # 是否已加载数据

        self.audit_log("SYSTEM", "STARTUP", details={
            "upstream": self._upstream_ids,
            "app_protocol": self.app_protocol,
            "transport_medium": self.transport_medium,
            "sample_interval": self.sample_interval,
            "report_mode": self.report_mode
        })

    # ════════════════════════════════════════════
    #  新增: 文件数据源管理
    # ════════════════════════════════════════════

    def load_data(self, filepath: str, mode: str = "once") -> int:
        """
        从 CSV 文件加载采样数据

        CSV 要求:
          - 第一行为表头 (列名对应 sample() 返回值的 key)
          - 后续每行为一次采样数据
          - 编码 UTF-8

        Parameters
        ----------
        filepath : str   CSV 文件路径
        mode     : str   读取模式
                         "once" — 读完返回 None
                         "loop" — 循环回第一行
                         "hold" — 停在最后一行重复返回

        Returns
        -------
        int  加载的数据行数

        Raises
        ------
        ValueError  mode 不合法
        FileNotFoundError  文件不存在
        """
        if mode not in self.VALID_READ_MODES:
            raise ValueError(
                f"无效的读取模式: {mode}, 合法值: {self.VALID_READ_MODES}"
            )

        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self._data_rows = list(reader)

        self._row_index  = 0
        self._read_mode  = mode
        self._data_loaded = True

        self.audit_log("DATA", "LOAD_DATA_SOURCE", details={
            "filepath": filepath,
            "rows": len(self._data_rows),
            "mode": mode
        }, level=logging.INFO)
        return len(self._data_rows)

    def clear_data(self) -> None:
        """清除已加载的文件数据, 恢复为 simulate 模式"""
        self._data_rows   = []
        self._row_index   = 0
        self._data_loaded = False
        self.audit_log("DATA", "CLEAR_DATA_SOURCE", details={"action": "revert_to_simulate"}, level=logging.INFO)

    def _next_row(self) -> Optional[Dict[str, str]]:
        """
        获取下一行 CSV 数据

        子类在 sample() 开头调用此方法:
          - 返回 dict  → 使用文件数据 (值均为字符串, 子类负责类型转换)
          - 返回 None  → 无文件数据, 子类走自生成逻辑

        Returns
        -------
        dict | None  CSV 行数据 (字符串字典) 或 None
        """
        if not self._data_loaded or not self._data_rows:
            return None

        # 已经读完所有行
        if self._row_index >= len(self._data_rows):
            if self._read_mode == "once":
                return None
            elif self._read_mode == "loop":
                self._row_index = 0
            elif self._read_mode == "hold":
                return dict(self._data_rows[-1])

        row = dict(self._data_rows[self._row_index])
        self._row_index += 1
        return row

    @property
    def data_loaded(self) -> bool:
        """是否已加载文件数据"""
        return self._data_loaded

    @property
    def data_remaining(self) -> int:
        """剩余未读取的行数 (once 模式下有意义)"""
        if not self._data_loaded:
            return 0
        return max(0, len(self._data_rows) - self._row_index)

    # ════════════════════════════════════════════
    #  拓扑邻居自动发现
    # ════════════════════════════════════════════

    def _discover_upstream(self) -> List[str]:
        """
        从拓扑注册表自动发现上层汇聚节点

        传感器在拓扑中注册为 PROCESS 层, 其上层邻居有两种:
          1. 同为 PROCESS 层的智能终端/合并单元 (过程层内部汇聚链路)
          2. BAY 层的间隔层设备 (跨层直连, 较少见)

        Returns
        -------
        list[str]  上层汇聚节点 ID 列表 (已去重排序)
        """
        same_layer  = self._topo.get_peer_ids(self.device_id)
        upper_layer = self._topo.get_upstream_ids(self.device_id)
        return sorted(set(same_layer + upper_layer))

    @property
    def upstream_ids(self) -> List[str]:
        """只读属性: 上层汇聚节点 ID 列表"""
        return list(self._upstream_ids)

    # ════════════════════════════════════════════
    #  采集 → 判定 → 打包 → 上报 (模板方法)
    # ════════════════════════════════════════════

    def collect_and_report(self) -> None:
        """
        流程:
        1. sample()              → 获取原始采样值
        2. _evaluate_trigger()   → 判定本次上报触发类型
        3. 更新 _last_sample_value → 无论是否上报都更新，确保下次变化检测准确
        4. trigger 为 None 则跳过上报，直接返回
        5. build_payload()       → 打包为标准载荷
        6. _send_to_upstream()   → 发送给所有上层汇聚节点
        """

        # 步骤 1: 采集
        raw_value = self.sample()
        if raw_value is None:
            self.audit_log("DATA", "SAMPLE_FAILED", details={
                "reason": "sample() returned None",
                "impact": "Data stream interrupted"
            }, level=logging.WARNING)
            return

        # 步骤 2: 判定触发类型
        trigger = self._evaluate_trigger(raw_value)

        # 步骤 3: 更新历史缓存 (无论是否上报都要更新)
        self._last_sample_value = raw_value

        # 步骤 4: 如果不需要上报则结束
        if trigger is None:
            return

        if trigger == ReportTrigger.EVENT:
            self.audit_log("DATA", "EVENT_TRIGGERED", details={
                "new_value": raw_value
            }, level=logging.DEBUG)

        # 步骤 5: 打包 + 上报
        payload = self.build_payload(raw_value, trigger)
        self._send_to_upstream(payload)

    # ════════════════════════════════════════════
    #  触发判定
    # ════════════════════════════════════════════

    def _evaluate_trigger(self, new_value: Any) -> Optional[str]:
        """
        判定本次采样的上报触发类型

        判定规则:
          - periodic 模式: 每次采样都上报, 触发类型为 PERIODIC
          - event 模式:    仅变化时上报, 触发类型为 EVENT; 无变化返回 None
          - mixed 模式:    每次都上报; 检测到变化标记 EVENT, 否则标记 PERIODIC

        Parameters
        ----------
        new_value : Any  本次采样的原始值

        Returns
        -------
        str | None  ReportTrigger 常量; None 表示本次不上报
        """
        changed = self._detect_change(new_value)

        if self.report_mode == "periodic":
            return ReportTrigger.PERIODIC

        elif self.report_mode == "event":
            return ReportTrigger.EVENT if changed else None

        elif self.report_mode == "mixed":
            return ReportTrigger.EVENT if changed else ReportTrigger.PERIODIC

        else:
            return ReportTrigger.PERIODIC

    def _detect_change(self, new_value: Any) -> bool:
        """
        检测新采样值相对于上一次是否发生了有意义的变化

        判定依据:
          - 首次采样 (_last_sample_value is None): 视为变化
          - change_threshold 为 None: 直接比较 !=
          - change_threshold 为数值: |new - old| > threshold
          - change_threshold 为 dict: 检查指定字段

        Parameters
        ----------
        new_value : Any  本次采样值

        Returns
        -------
        bool  True 表示检测到变化
        """
        if self._last_sample_value is None:
            return True

        threshold = self.change_threshold

        # 未配置阈值: 直接比较
        if threshold is None:
            return new_value != self._last_sample_value

        # 数值型阈值
        if isinstance(threshold, (int, float)):
            try:
                return abs(new_value - self._last_sample_value) > threshold
            except TypeError:
                return new_value != self._last_sample_value

        # 字段型阈值: {"field": "position"} 或 {"fields": ["position", "state"]}
        if isinstance(threshold, dict):
            return self._detect_field_change(new_value, threshold)

        return new_value != self._last_sample_value

    def _detect_field_change(self, new_value: Any, threshold: dict) -> bool:
        """
        基于字段名检测变化 (适用于字典型采样值, 如机械状态传感器)

        Parameters
        ----------
        new_value : Any   新采样值 (应为 dict)
        threshold : dict  {"field": "position"} 或 {"fields": ["position", "state"]}

        Returns
        -------
        bool  任一指定字段变化则返回 True
        """
        if not isinstance(new_value, dict) or not isinstance(self._last_sample_value, dict):
            return new_value != self._last_sample_value

        fields = list(threshold.get("fields", []))
        if "field" in threshold:
            fields.insert(0, threshold["field"])

        for f in fields:
            if self._last_sample_value.get(f) != new_value.get(f):
                return True
        return False

    # ════════════════════════════════════════════
    #  载荷打包
    # ════════════════════════════════════════════

    def build_payload(self, raw_value: Any, report_trigger: str) -> Dict[str, Any]:
        """
        将原始采样值打包为标准载荷字典

        子类可重写以添加额外字段, 建议调用 super().build_payload() 保留基础结构。

        Parameters
        ----------
        raw_value      : Any  sample() 返回的原始值
        report_trigger : str  ReportTrigger 常量

        Returns
        -------
        dict  标准载荷, 格式:
              {
                  "device_id":      "temperature_sensor",
                  "value":          75.3,
                  "unit":           "℃",
                  "timestamp":      1711699200.0,
                  "report_trigger": "periodic"
              }
        """
        return {
            "device_id":      self.device_id,
            "value":          raw_value,
            "unit":           self.unit,
            "sample_time":    self.current_time or time.time(),
            "report_trigger": report_trigger,
        }

    # ════════════════════════════════════════════
    #  消息发送
    # ════════════════════════════════════════════

    def _send_to_upstream(self, payload: Dict[str, Any]) -> None:
        """
        向所有上层汇聚节点发送数据消息

        Parameters
        ----------
        payload : dict  build_payload() 构造的标准载荷
        """
        if not self._upstream_ids:
            self.audit_log("NETWORK", "ISOLATED_SENSOR", details={
                "reason": "No upstream neighbors found"
            }, level=logging.WARNING)
            return

        for target_id in self._upstream_ids:
            msg = Message(
                sender_id=self.device_id,
                receiver_id=target_id,
                msg_type=self.msg_type,
                app_protocol=self.app_protocol,
                transport_medium=self.transport_medium,
                payload=payload,
                timestamp=self.current_time or time.time(),
            )
            success = self.send(msg)
            if not success:
                self.audit_log("NETWORK", "SEND_FAILED", details={"target": target_id}, level=logging.WARNING)


    # ════════════════════════════════════════════
    #  消息接收
    # ════════════════════════════════════════════

    def on_message(self, msg: Message) -> None:
        """
        总线回调入口

        传感器作为叶子节点, 仅关注:
          - SYNC : 来自上层设备级联转发的时间同步信号
        """
        if msg.msg_type == MsgType.SYNC:
            self._handle_time_sync(msg)
        else:
            self.audit_log("SECURITY", "ILLEGAL_SENSOR_ACCESS", msg=msg, details={
                "impact": "Direct probing or control packet sent to physical layer leaf node",
                "action": "Dropped"
            }, level=logging.CRITICAL)

    def _handle_time_sync(self, msg: Message) -> None:
        """
        处理时间同步消息

        传感器是叶子节点, 仅更新自身时钟, 不再向下级联转发。

        Parameters
        ----------
        msg : Message  payload 格式: {"sync_time": float}
        """
        ts = msg.payload.get("sync_time") if isinstance(msg.payload, dict) else None
        if ts is not None:
            self.sync_time(ts)
            self.audit_log("TIME", "TIME_SYNCED", msg=msg, details={"sync_timestamp": ts}, level=logging.DEBUG)
        else:
            self.audit_log("TIME", "INVALID_SYNC_PAYLOAD", msg=msg, level=logging.WARNING)

    # ════════════════════════════════════════════
    #  抽象方法 —— 子类必须实现
    # ════════════════════════════════════════════

    @abstractmethod
    def sample(self) -> Any:
        """
        执行一次数据采集, 返回原始采样值

        这是传感器子类唯一必须实现的方法。

        示例 (温度传感器):
            def sample(self) -> float:
                return random.uniform(35.0, 85.0)

        示例 (电流传感器):
            def sample(self) -> dict:
                return {"ia": 120.5, "ib": 119.8, "ic": 121.2}

        示例 (机械状态传感器):
            def sample(self) -> dict:
                return {"position": "closed", "op_count": 1523}

        Returns
        -------
        Any  采样值; 返回 None 表示采样失败, 本轮将跳过
        """
        ...
