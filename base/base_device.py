"""
所有设备的顶层基类 —— 提供公共能力

统一管理：设备 ID / 名称、日志、总线注册、消息收发、时间同步

所有具体基类（BaseSensor、BaseIntelligentTerminal 等）都继承自此类
"""

import logging
from abc import ABC
from common.message import Message, MsgType
from common.bus import MessageBus, global_bus


class BaseDevice(ABC):

    def __init__(
        self,
        device_id:   str,
        bus:         MessageBus = None,
        device_name: str = ""
    ):
        """
        :param device_id:    设备唯一 ID
        :param bus:          消息总线实例
                             - 生产代码：默认使用 global_bus
                             - 测试代码：显式传入独立的 MessageBus() 实例
                               以避免测试间状态污染
        :param device_name:  设备可读名称（可选，默认同 device_id）
        """
        self.device_id   = device_id
        self.device_name = device_name or device_id
        self.bus         = bus or global_bus
        self.current_time: float = None   # 最近一次同步的时间戳

        self.logger = logging.getLogger(
            f"{self.__class__.__name__}({device_id})"
        )

        # 自动注册到总线，绑定 on_message 为消息处理入口
        self.bus.register(self.device_id, self.on_message)
        self.logger.info(f"设备初始化: {self.device_name}")

    # ──────────────────────────────────────────
    # 消息收发（走总线）
    # ──────────────────────────────────────────

    def send(self, msg: Message) -> bool:
        """
        通过总线单播发送消息
        返回 True/False 表示投递是否成功
        """
        self.logger.info(
            f"发送 -> {msg.receiver_id} | 协议={msg.app_protocol} "
            f"| 介质={msg.transport_medium} | 类型={msg.msg_type}"
        )
        return self.bus.send(msg)

    def broadcast(self, msg: Message) -> None:
        """通过总线全量广播（发送给所有已注册设备）"""
        self.bus.broadcast(msg)

    def broadcast_by_type(self, msg: Message) -> None:
        """通过总线订阅广播（发送给订阅了该 msg_type 的设备）"""
        self.bus.broadcast_by_type(msg)

    def subscribe(self, msg_type: str) -> None:
        """订阅某类消息，收到时由 on_message 处理"""
        self.bus.subscribe(msg_type, self.on_message)
        self.logger.info(f"订阅消息类型: {msg_type}")

    def unsubscribe(self, msg_type: str) -> None:
        """取消订阅某类消息"""
        self.bus.unsubscribe(msg_type, self.on_message)
        self.logger.info(f"取消订阅消息类型: {msg_type}")

    def on_message(self, msg: Message) -> None:
        """
        总线回调入口 —— 收到发给本设备的消息时被调用
        子类应重写此方法以实现业务逻辑
        默认实现仅记录一条 debug 日志，不强制重写
        """
        self.logger.debug(
            f"收到消息: {msg.msg_type} from {msg.sender_id}"
        )

    # ──────────────────────────────────────────
    # 时间同步
    # ──────────────────────────────────────────

    def sync_time(self, timestamp: float) -> None:
        """接收时间同步信号，更新本地时间"""
        self.current_time = timestamp
        self.logger.info(f"时间同步: {timestamp}")

    # ──────────────────────────────────────────
    # 生命周期
    # ──────────────────────────────────────────

    def shutdown(self) -> None:
        """
        设备下线，从总线注销
        仿真结束或设备故障时调用
        """
        self.bus.unregister(self.device_id)
        self.logger.info(f"设备下线: {self.device_name}")

    # ──────────────────────────────────────────
    # 设备信息
    # ──────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"id={self.device_id} name={self.device_name}>"
        )
