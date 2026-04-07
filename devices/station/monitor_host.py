from base.base_station_device import BaseStationDevice
from common.message import Message, MsgType, AppProtocol, TransportMedium


class MonitorHostDevice(BaseStationDevice):
	"""
	监控主机 (站控层)
	"""

	def on_bay_data(self, msg: Message) -> None:
		"""
		仅做数据展示与存储同步，不干预业务逻辑
		"""
		if msg.msg_type == MsgType.PROTECTION:
			self.logger.error(f"【展示】收到间隔层保护动作事件: {msg.payload}")
		elif msg.msg_type == MsgType.ALARM:
			self.logger.warning(f"【展示】收到间隔层告警事件: {msg.payload}")

		# 将收到的数据同步至数据服务器 (IEC 61850 MMS / WiFi6)
		self.send_to_peer(
			receiver_id="data_server",
			payload={"source": msg.sender_id, "data_type": msg.msg_type, "content": msg.payload},
			msg_type=MsgType.DATA,
			app_protocol=AppProtocol.MMS,
			transport_medium=TransportMedium.WIFI6
		)

	def on_peer_data(self, msg: Message) -> None:
		"""
		处理同层设备数据（重点：接收操作员站的手动指令）
		"""
		# 接收操作员站发来的手动操作指令 (IEC 61850 MMS / WiFi6)
		if msg.sender_id == "operator_station" and msg.msg_type == MsgType.CMD:
			# target_bay_device = msg.payload.get("target_bay_device", "line_monitor")
			target_bay_device = msg.payload.get("target_bay_device")
			self.logger.info(f"收到操作员站手动指令，准备转发给间隔层设备 [{target_bay_device}]")
			payload={
				"action": msg.payload.get("action"),
				"reason": msg.payload.get("source")
			}

			# 将操作员的手动指令下发给对应的间隔层设备 (IEC 61850 MMS / 有线)
			self.command_to_bay(
				receiver_id=target_bay_device,
				payload=payload,
				msg_type=MsgType.CMD,
				app_protocol=AppProtocol.MMS,
				transport_medium=TransportMedium.WIRED_ETH
			)