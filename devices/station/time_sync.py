import logging
import time
from base.base_station_device import BaseStationDevice
from common.message import MsgType, AppProtocol, TransportMedium


class TimeSyncDevice(BaseStationDevice):
    """
    无线授时系统 (站控层)
    对应拓扑节点: time_sync_system
    职责: 向全站设备（过程层合并单元、同层监控主机等）发送高精度时间同步信号
    """

    def __init__(self, device_id: str = "time_sync_system", bus=None, initial_time: float = None, **kwargs):
        """
        :param initial_time: 初始时间戳。如果传 None，则默认使用宿主机的当前真实时间。
        """
        # 1. 先调用父类初始化拓扑和基础组件
        super().__init__(device_id=device_id, bus=bus, **kwargs)
        # 2. 赋予初始时间
        start_time = initial_time if initial_time is not None else time.time()
        self.sync_time(start_time)
        # 3. 记录日志 (作为授时源，自己的时钟初始化是一个重要事件)
        self.audit_log("TIME", "CLOCK_INITIALIZED", details={
            "initial_time": start_time,
            "is_simulated_time": initial_time is not None
        }, level=logging.INFO)

    def broadcast_time_sync(self, current_time: float = None) -> None:
        """
        供外部/定时任务调用的方法：触发全站时间同步广播

        :param current_time: 当前时间戳，如果不传则取系统当前时间
        """
        if current_time is None:
            current_time = time.time()

        self.sync_time(current_time)
        # 构造授时 Payload
        payload = {
            "timestamp": current_time,
            "source": "time_sync"
        }

        self.audit_log("TIME", "BROADCAST_SYNC", details={"sync_timestamp": current_time})

        # 1. 向过程层设备（主变合并单元、线路合并单元）跨层广播授时信号
        # 对应架构图: 时间同步 PTP/IEEE 1588 -> 无线射频
        self.broadcast_to_process_layer(
            payload=payload,
            msg_type=MsgType.SYNC,
            app_protocol=AppProtocol.PTP,
            transport_medium=TransportMedium.RF_STANDARD
        )

        # 2. 向同层设备（监控主机等）发送授时信号
        # 对应架构图: 时间同步（误差≤1ms）PTP/IEEE 1588 -> 无线射频
        for peer_id in self.peer_ids:
            self.send_to_peer(
                receiver_id=peer_id,
                payload=payload,
                msg_type=MsgType.SYNC,
                app_protocol=AppProtocol.PTP,
                transport_medium=TransportMedium.RF_STANDARD
            )

    def time_sync_to_process(self, receiver_id: str, current_time: float = None) -> None:
        if current_time is None:
            current_time = time.time()

        # 构造授时 Payload
        payload = {
            "timestamp": current_time,
            "source": "time_sync"
        }

        self.audit_log("TIME", "SEND_SYNC_PROCESS", details={"target": receiver_id, "sync_timestamp": current_time})

        self.send_to_process_layer(
            receiver_id=receiver_id,
            payload=payload,
            msg_type=MsgType.SYNC,
            app_protocol=AppProtocol.PTP,
            transport_medium=TransportMedium.RF_STANDARD
        )

    def time_sync_to_station(self, current_time: float = None) -> None:
        if current_time is None:
            current_time = time.time()

        # 构造授时 Payload
        payload = {
            "timestamp": current_time,
            "source": "time_sync"
        }

        self.audit_log("TIME", "SEND_SYNC_STATION", details={"sync_timestamp": current_time})

        for peer_id in self.peer_ids:
            self.send_to_peer(
                receiver_id=peer_id,
                payload=payload,
                msg_type=MsgType.SYNC,
                app_protocol=AppProtocol.PTP,
                transport_medium=TransportMedium.RF_STANDARD
            )