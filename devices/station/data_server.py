import logging

from base.base_station_device import BaseStationDevice
from common.message import Message, MsgType, AppProtocol


class DataServerDevice(BaseStationDevice):
	"""
	数据服务器 (站控层)
	对应拓扑节点: data_server
	职责: 接收监控主机同步的全站数据并持久化
	"""

	def on_peer_data(self, msg: Message) -> None:
		"""
		处理同层设备（监控主机）发来的同步数据
		"""
		# 接收监控主机的数据同步 (IEC 61850 MMS / WiFi6)
		if msg.sender_id == "monitor_host" and msg.msg_type == MsgType.DATA:
			# 基类 BaseStationDevice 已经自动将 payload 存入了 _latest_data 和 _data_store
			# 这里只需补充持久化/落盘的业务逻辑（模拟）

			original_source = msg.payload.get("source", "unknown")
			data_type = msg.payload.get("data_type", "unknown")
			content = msg.payload.get("content", {})

			self.audit_log("DATA", "SAVE_TO_DB", msg=msg, details={
				"original_source": original_source,
				"data_type": data_type,
				"content": content
			})

			# 模拟写入数据库耗时或逻辑
			self._save_to_database(original_source, data_type, content)

	def _save_to_database(self, source: str, data_type: str, content: dict) -> None:
		"""
		模拟数据落盘
		"""
		# 实际开发中这里会是 SQL 插入或时序数据库写入操作
		self.audit_log("DATA", "DB_PERSISTED", details={
			"table": f"{source}_{data_type}"
		}, level=logging.DEBUG)