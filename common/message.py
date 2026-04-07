"""
统一报文结构 —— 全系统所有设备通信的基础数据单元
"""
from dataclasses import dataclass, field
from typing import Any
import time
import uuid
import json


class AppProtocol:
    """
    应用层协议常量 (决定数据段怎么打包、怎么理解)
    对应拓扑图箭头前面的部分
    """
    MODBUS_RTU = "Modbus-RTU"
    MODBUS_TCP = "Modbus-TCP"
    GOOSE      = "GOOSE"
    SV         = "SV(IEC61850-9-2)"
    MMS        = "IEC61850-MMS"
    PTP        = "PTP/IEEE1588"
    RAW_DIGITAL= "RAW_Digital"   # 例如压力数据的数字量
    RAW_ANALOG = "RAW_Analog"    # 例如微水/温度的4-20mA模拟量

class TransportMedium:
    """
    物理传输/网络介质常量 (决定信号怎么发出去)
    对应拓扑图箭头后面的部分 (-> xxx)
    """
    LORA       = "LoRa"
    NB_IOT     = "NB-IoT"
    SUB_G      = "Sub-G"
    RF_LOW_LATENCY = "超低时延射频"
    MESH       = "无线Mesh"
    WIFI6      = "WiFi6"
    RF_STANDARD= "无线射频"
    WIRED_ETH  = "Wired_Ethernet" # 用于处理拓扑图中没有标明"->B"的默认有线连接



class MsgType:
    """消息类型常量"""
    DATA       = "data"          # 普通数据上报 (如温度、压力)
    STATUS     = "status"        # 状态数据 (如断路器分合位置、设备状态)
    ALARM      = "alarm"         # 告警
    PROTECTION = "protection"    # 保护数据
    MONITOR    = "monitor"       # 监测数据
    CMD        = "cmd"           # 控制指令 (如合闸指令、执行指令)
    SYNC       = "time_sync"     # 时间同步
    ACK        = "ack"           # 确认应答


@dataclass
class Message:
    """
    统一报文
    - sender_id        : 发送方设备 ID
    - receiver_id      : 接收方设备 ID
    - msg_type         : 业务消息类型 (MsgType)
    - app_protocol     : 应用层协议 (AppProtocol)
    - transport_medium : 传输介质 (TransportMedium)
    - payload          : 具体数据内容（字典或对象）
    - msg_id           : 报文唯一标识
    - timestamp        : 报文创建时间戳
    """
    sender_id:        str
    receiver_id:      str
    msg_type:         str
    app_protocol:     str
    payload:          Any
    transport_medium: str = TransportMedium.WIRED_ETH
    msg_id:           str = field(default="")
    timestamp:        float = field(default_factory=time.time)
    def __post_init__(self):
        if not self.msg_id:
            self.msg_id = str(uuid.uuid4())
    # ── 序列化 / 反序列化 ──────────────────────
    def serialize(self) -> dict:
        return {
            "msg_id":           self.msg_id,
            "sender_id":        self.sender_id,
            "receiver_id":      self.receiver_id,
            "msg_type":         self.msg_type,
            "app_protocol":     self.app_protocol,
            "transport_medium": self.transport_medium,
            "payload":          self.payload,
            "timestamp":        self.timestamp,
        }
    def to_json(self) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(self.serialize(), ensure_ascii=False, indent=2)
    @staticmethod
    def deserialize(data: dict) -> "Message":
        return Message(
            sender_id        = data["sender_id"],
            receiver_id      = data.get("receiver_id", ""),
            msg_type         = data["msg_type"],
            app_protocol     = data["app_protocol"],
            transport_medium = data.get("transport_medium", TransportMedium.WIRED_ETH),
            payload          = data["payload"],
            msg_id           = data.get("msg_id", ""),
            timestamp        = data.get("timestamp", time.time()),
        )