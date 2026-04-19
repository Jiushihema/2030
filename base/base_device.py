"""
所有设备的顶层基类 —— 提供公共能力

统一管理：设备 ID / 名称、日志、总线注册、消息收发、时间同步

所有具体基类（BaseSensor、BaseIntelligentTerminal 等）都继承自此类
"""
import json
import logging
from abc import ABC
from typing import Any

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
        self.logger.debug(f"设备初始化: {self.device_name}")

    # ──────────────────────────────────────────
    # 日志记录
    # ──────────────────────────────────────────

    def audit_log(
            self,
            category: str,
            action: str,
            msg: Message = None,
            details: dict = None,
            level: int = logging.INFO
    ) -> None:
        """
        结构化安全审计日志输出
        :param category: 事件大类 (NETWORK, CONTROL, DATA, TIME, SECURITY, SYSTEM, ATTACK)
        :param action: 具体动作 (SEND, RECV, ALERT, EXEC, SYNC 等)
        :param msg: 关联的 Message 对象
        :param details: 补充的业务/异常上下文细节
        :param level: 日志级别 (logging.INFO/WARNING/CRITICAL)
        """
        log_record = {
            "timestamp": self.current_time,
            "device_id": self.device_id,
            "layer": self.__class__.__bases__[0].__name__,  # 提取直接基类名
            "category": category,
            "action": action,
        }
        if msg:
            log_record.update({
                "msg_id": getattr(msg, "msg_id", "unknown"),
                "sender": msg.sender_id,
                "receiver": getattr(msg, "receiver_id", "broadcast"),
                "msg_type": msg.msg_type,
                # "protocol": getattr(msg, "app_protocol", "unknown"),
                # "medium": getattr(msg, "transport_medium", "unknown"),
            })
        if details:
            # if "payload" in details:
            #     # 将原始 payload 替换为摘要
            #     details["payload_summary"] = self._extract_payload_summary(details.pop("payload"))

            log_record["details"] = details
        # 确保中文和格式正确输出
        self.logger.log(level, json.dumps(log_record, ensure_ascii=False))

    CRITICAL_PAYLOAD_KEYS = {
        "action", "position", "target", "reason", "state",
        "result", "error", "source", "cmd_time"
    }

    def _extract_payload_summary(self, payload: Any) -> Any:
        """智能提取 payload 中的关键控制参数，抛弃冗余数据"""
        if not payload:
            return None

        if isinstance(payload, dict):
            # 提取交集字段
            summary = {k: v for k, v in payload.items() if k in self.CRITICAL_PAYLOAD_KEYS}

            # 如果 payload 很大，但没有命中关键字，给出一个类型和大小摘要
            if not summary and len(payload) > 3:
                return f"<Dict with {len(payload)} keys, e.g., {list(payload.keys())[:2]}>"

            # 如果存在未提取的字段，加一个标记，提示分析人员原包更大
            if len(summary) < len(payload):
                summary["_truncated"] = True

            return summary if summary else payload

        elif isinstance(payload, list):
            return f"<List with {len(payload)} items>"

        elif isinstance(payload, (str, bytes)):
            # 字符串截断，防止缓冲区溢出攻击载荷打崩日志系统
            return payload[:100] + "..." if len(payload) > 100 else payload

        return payload

    # ──────────────────────────────────────────
    # 消息收发（走总线）
    # ──────────────────────────────────────────

    def send(self, msg: Message) -> bool:
        """
        通过总线单播发送消息
        返回 True/False 表示投递是否成功
        """
        self.audit_log("NETWORK", "SEND", msg=msg, details={"payload": msg.payload})
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
        self.audit_log("CONTROL", "FORWARD_MANUAL_CMD", msg=msg, details={
            "target": "breaker_it",
            "payload": msg.payload
        }, level=logging.INFO)

    # ──────────────────────────────────────────
    # 时间同步
    # ──────────────────────────────────────────

    def sync_time(self, timestamp: float) -> None:
        """接收时间同步信号，更新本地时间"""
        self.current_time = timestamp
        self.audit_log("TIME", "TIME_SYNC", details={"new_time": timestamp})

    # ──────────────────────────────────────────
    # 生命周期
    # ──────────────────────────────────────────

    def shutdown(self) -> None:
        """
        设备下线，从总线注销
        仿真结束或设备故障时调用
        """
        self.bus.unregister(self.device_id)
        self.audit_log("SYSTEM", "SHUTDOWN", level=logging.WARNING)

    # ──────────────────────────────────────────
    # 设备信息
    # ──────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"id={self.device_id} name={self.device_name}>"
        )