import time
from base.base_station_device import BaseStationDevice
from common.message import MsgType, AppProtocol, TransportMedium


class TimeSyncDevice(BaseStationDevice):
    """
    无线授时系统 (站控层)
    对应拓扑节点: time_sync_system
    职责: 向全站设备（过程层合并单元、同层监控主机等）发送高精度时间同步信号
    """

    def broadcast_time_sync(self, current_time: float = None) -> None:
        """
        供外部/定时任务调用的方法：触发全站时间同步广播

        :param current_time: 当前时间戳，如果不传则取系统当前时间
        """
        if current_time is None:
            current_time = time.time()

        # 构造授时 Payload
        payload = {
            "timestamp": current_time,
            "source": "time_sync"
        }

        self.logger.info(f"【无线授时系统】发起全站时间同步，时间戳: {current_time}")

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

        for peer_id in self.peer_ids:
            self.send_to_peer(
                receiver_id=peer_id,
                payload=payload,
                msg_type=MsgType.SYNC,
                app_protocol=AppProtocol.PTP,
                transport_medium=TransportMedium.RF_STANDARD
            )