import logging

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
		local_time = self.current_time
		event_time = msg.timestamp

		# 如果时间差大于 2 秒，说明全站时钟可能遭到了欺骗或漂移
		if abs(local_time - event_time) > 2.0:
			self.audit_log("SECURITY", "TIME_DESYNC_DETECTED", msg=msg, details={
				"local_time": local_time,
				"event_time": event_time,
				"diff": local_time - event_time
			}, level=logging.CRITICAL)

		if msg.msg_type == MsgType.PROTECTION:
			self.audit_log("CONTROL", "PROTECTION_DISPLAY", msg=msg, level=logging.WARNING)
		elif msg.msg_type == MsgType.ALARM:
			self.audit_log("DATA", "ALARM_DISPLAY", msg=msg, level=logging.WARNING)

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
			target_bay_device = msg.payload.get("target_bay_device")
			action = msg.payload.get("action")

			# 记录关键的控制指令下发链路
			self.audit_log("CONTROL", "FORWARD_COMMAND", msg=msg, details={
				"target_bay": target_bay_device,
				"action": action
			}, level=logging.INFO)
			payload = {
				"action": action,
				"reason": msg.payload.get("source"),
				"cmd_time": self.current_time
			}
			self.command_to_bay(
				receiver_id=target_bay_device,
				payload=payload,
				msg_type=MsgType.CMD,
				app_protocol=AppProtocol.MMS,
				transport_medium=TransportMedium.WIRED_ETH
			)