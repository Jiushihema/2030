"""
消息总线 —— 所有设备间的通信都通过这里中转

支持：
  - 单播：点对点发送给指定设备
  - 广播（全量）：发送给所有已注册设备（除发送者）
  - 广播（订阅）：发送给所有订阅了某消息类型的设备

攻击仿真时可在此处注入拦截、篡改、重放等攻击逻辑
"""

import json
import logging
import threading
from typing import Dict, List, Callable

from common.message import Message
from common.topology import TopologyRegistry

logger = logging.getLogger("MessageBus")

# 消息处理器类型
MessageHandler = Callable[[Message], None]


class MessageBus:

    def __init__(self):
        # 按 device_id 注册的单播处理器
        self._unicast_handlers: Dict[str, MessageHandler] = {}

        # 按 msg_type 注册的广播订阅处理器
        self._broadcast_handlers: Dict[str, List[MessageHandler]] = {}

        # 全局消息历史（供攻击五 / 日志对比使用）
        self._message_history: List[dict] = []

        # 线程锁 —— 保护并发读写安全
        self._lock = threading.Lock()

    # ──────────────────────────────────────────
    # 注册 / 注销
    # ──────────────────────────────────────────

    def register(self, device_id: str, handler: MessageHandler) -> None:
        """注册设备到总线（单播路由）"""
        with self._lock:
            self._unicast_handlers[device_id] = handler
        logger.info(f"设备 [{device_id}] 已注册到消息总线")

    def unregister(self, device_id: str) -> None:
        """从总线注销设备"""
        with self._lock:
            removed = self._unicast_handlers.pop(device_id, None)
        if removed is not None:
            logger.info(f"设备 [{device_id}] 已从消息总线注销")

    def subscribe(self, msg_type: str, handler: MessageHandler) -> None:
        """
        订阅某类消息的广播
        msg_type: 使用 MsgType 常量
        handler:  收到该类消息时的处理方法
        """
        with self._lock:
            self._broadcast_handlers.setdefault(msg_type, []).append(handler)
        logger.info(f"新增广播订阅: msg_type={msg_type}")

    def unsubscribe(self, msg_type: str, handler: MessageHandler) -> None:
        """取消订阅某类消息的广播"""
        with self._lock:
            handlers = self._broadcast_handlers.get(msg_type, [])
            if handler in handlers:
                handlers.remove(handler)
        logger.info(f"取消广播订阅: msg_type={msg_type}")

    # ──────────────────────────────────────────
    # 发送
    # ──────────────────────────────────────────

    def send(self, msg: Message) -> bool:
        """
        单播：将消息发送给 msg.receiver_id 对应的设备
        返回 True 表示投递成功，False 表示目标设备未注册
        """
        self._record(msg)

        with self._lock:
            handler = self._unicast_handlers.get(msg.receiver_id)

        if handler is None:
            logger.warning(
                f"[BUS] 单播失败：目标设备 [{msg.receiver_id}] 未注册，"
                f"消息丢弃 (msg_id={msg.msg_id})"
            )
            return False

        topo = TopologyRegistry.get_instance()
        if msg.sender_id != msg.receiver_id:
            # 查询拓扑邻接表，看是否存在连通链路
            neighbors = topo._adjacency.get(msg.sender_id, set())
            if msg.receiver_id not in neighbors:
                # logger.critical(
                #     f"[BUS] 🚫 物理链路断开/信号丢失：无法跨越断开的信道 "
                #     f"从 [{msg.sender_id}] 传送到 [{msg.receiver_id}]！"
                #     f"(类型={msg.msg_type})"
                # )
                # 链路不存在，模拟空中信号掩盖或网线被剪断，投递失败
                return False

        logger.debug(
            f"[BUS] {msg.sender_id} -> {msg.receiver_id} "
            f"| 协议={msg.app_protocol} | 介质={msg.transport_medium} | 类型={msg.msg_type} "
        )

        # TODO: 攻击注入点 —— 可在此处插入消息篡改/丢弃/重放逻辑
        handler(msg)
        return True

    def broadcast(self, msg: Message) -> None:
        """
        全量广播：将消息发送给所有已注册设备（除发送者自身）
        使用 list() 快照迭代，避免广播过程中注册/注销导致字典变动报错
        """
        self._record(msg)

        with self._lock:
            # 取快照，避免迭代中字典被修改
            handlers_snapshot = list(self._unicast_handlers.items())

        logger.debug(
            f"[BUS] 广播(全量) from {msg.sender_id} | 类型={msg.msg_type}"
        )

        for dev_id, handler in handlers_snapshot:
            if dev_id != msg.sender_id:
                # TODO: 攻击注入点
                handler(msg)

    def broadcast_by_type(self, msg: Message) -> None:
        """
        订阅广播：将消息发送给所有通过 subscribe() 订阅了
        该 msg_type 的处理器
        使用 list() 快照迭代，避免回调中取消订阅导致列表变动报错
        """
        self._record(msg)

        with self._lock:
            # 取快照
            handlers_snapshot = list(
                self._broadcast_handlers.get(msg.msg_type, [])
            )

        if not handlers_snapshot:
            logger.warning(f"[BUS] 广播无订阅者: msg_type={msg.msg_type}")
            return

        logger.debug(
            f"[BUS] 广播(订阅) from {msg.sender_id} | 类型={msg.msg_type} "
            f"| 订阅者数={len(handlers_snapshot)}"
        )

        for handler in handlers_snapshot:
            # TODO: 攻击注入点
            handler(msg)

    # ──────────────────────────────────────────
    # 消息历史（攻击五 / 离线分析）
    # ──────────────────────────────────────────

    def _record(self, msg: Message) -> None:
        """记录所有经过总线的消息（线程安全）"""
        with self._lock:
            self._message_history.append(msg.serialize())

    def get_history(
        self,
        sender_id: str = None,
        msg_type:  str = None
    ) -> list:
        """
        查询消息历史，可按 sender_id / msg_type 过滤
        返回副本，避免外部修改影响内部状态
        """
        with self._lock:
            result = list(self._message_history)

        if sender_id:
            result = [m for m in result if m["sender_id"] == sender_id]
        if msg_type:
            result = [m for m in result if m["msg_type"] == msg_type]
        return result

    def export_history(self, filepath: str) -> None:
        """将消息历史导出为 JSON 文件，供离线分析"""
        with self._lock:
            history_snapshot = list(self._message_history)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(history_snapshot, f, ensure_ascii=False, indent=2)
        logger.info(f"消息历史已导出: {filepath}")

    def clear_history(self) -> None:
        """清空消息历史（测试用例间隔离时使用）"""
        with self._lock:
            self._message_history.clear()
        logger.info("[BUS] 消息历史已清空")

    def reset(self) -> None:
        """
        完全重置总线状态（测试隔离专用）
        清空所有注册、订阅和历史记录
        """
        with self._lock:
            self._unicast_handlers.clear()
            self._broadcast_handlers.clear()
            self._message_history.clear()
        logger.info("[BUS] 总线已完全重置")


# ── 全局单例 ──────────────────────────────────
# 生产代码默认使用；测试时请显式传入新的 MessageBus() 实例
global_bus = MessageBus()
