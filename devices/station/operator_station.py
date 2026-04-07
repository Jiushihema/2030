from base.base_station_device import BaseStationDevice
from common.message import Message, MsgType, AppProtocol, TransportMedium


class OperatorStationDevice(BaseStationDevice):
	"""
	操作员站 (站控层)
	对应拓扑节点: operator_station
	职责: 发起人工操作指令
	"""

	def send_manual_command(self, target_bay_device: str, action: str) -> None:
		"""
		供外部/UI调用的方法：发送手动控制指令

		:param target_bay_device: 目标间隔层设备ID (如 "line_monitor")
		:param action: 操作动作 (如 "close" 合闸, "open" 分闸)
		"""
		self.logger.info(f"操作员发起手动指令: 对 [{target_bay_device}] 执行 [{action}] 操作")

		# 将指令发送给同层的监控主机 (IEC 61850 MMS / WiFi6)
		# 监控主机收到后会透传给对应的间隔层设备
		self.send_to_peer(
			receiver_id="monitor_host",
			payload={
				"target_device": target_bay_device,
				"action": action,
				"source": "operator_manual"
			},
			msg_type=MsgType.CMD,
			app_protocol=AppProtocol.MMS,
			transport_medium=TransportMedium.WIFI6
		)