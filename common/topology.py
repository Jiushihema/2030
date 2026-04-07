"""
拓扑注册表 —— 全站设备连接关系数据源

职责:
  - 记录每台设备的所属层级
  - 记录设备间的通信连接 (无向链路)
  - 为设备初始化提供邻居自动发现能力
  - 支持运行时动态增删连接 (可用于攻击仿真)

使用顺序:
  1. 先调用 register_device() / add_link() 完成拓扑定义
     (或调用 load_config() 一次性加载)
  2. 再实例化设备 —— 设备 __init__ 自动查询本表
"""

import logging
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Optional

logger = logging.getLogger("TopologyRegistry")


class DeviceLayer:
    """设备所属层级常量"""
    PROCESS = 0   # 过程层
    BAY     = 1   # 间隔层
    STATION = 2   # 站控层

    _NAMES = {0: "过程层", 1: "间隔层", 2: "站控层"}

    @classmethod
    def name(cls, layer: int) -> str:
        return cls._NAMES.get(layer, f"未知层({layer})")


class TopologyRegistry:
    """
    全站拓扑注册表 (单例)

    数据结构:
      _devices:    { device_id: layer }          — 设备层级映射
      _adjacency:  { device_id: {neighbor_ids} } — 无向邻接表
    """

    _instance: Optional["TopologyRegistry"] = None

    @classmethod
    def get_instance(cls) -> "TopologyRegistry":
        """获取全局单例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """
        销毁单例 (测试隔离专用)
        下次 get_instance() 会创建新实例
        """
        cls._instance = None

    def __init__(self):
        self._devices:   Dict[str, int]      = {}
        self._adjacency: Dict[str, Set[str]]  = defaultdict(set)

    # ════════════════════════════════════════════
    #  拓扑构建
    # ════════════════════════════════════════════

    def register_device(self, device_id: str, layer: int) -> None:
        """
        注册设备及其所属层级

        Parameters
        ----------
        device_id : str   设备唯一 ID
        layer     : int   DeviceLayer.PROCESS / BAY / STATION
        """
        if device_id in self._devices:
            logger.warning(f"设备 [{device_id}] 重复注册，层级将被覆盖")
        self._devices[device_id] = layer
        logger.debug(
            f"注册设备: {device_id} → {DeviceLayer.name(layer)}"
        )

    def add_link(self, id_a: str, id_b: str) -> None:
        """
        添加双向通信链路

        Parameters
        ----------
        id_a, id_b : str  两端设备 ID
        """
        # 校验设备是否已注册
        for did in (id_a, id_b):
            if did not in self._devices:
                logger.warning(
                    f"设备 [{did}] 尚未注册，链路 ({id_a}↔{id_b}) "
                    f"仍会添加，但查询时可能出现层级未知的情况"
                )

        self._adjacency[id_a].add(id_b)
        self._adjacency[id_b].add(id_a)
        logger.debug(f"添加链路: {id_a} ↔ {id_b}")

    def remove_link(self, id_a: str, id_b: str) -> None:
        """
        移除通信链路 (可用于攻击仿真: 模拟网络中断)
        """
        self._adjacency[id_a].discard(id_b)
        self._adjacency[id_b].discard(id_a)
        logger.info(f"移除链路: {id_a} ↔ {id_b}")

    def load_config(self, config: dict) -> None:
        """
        从配置字典一次性加载完整拓扑

        Parameters
        ----------
        config : dict
            {
                "devices": { device_id: layer, ... },
                "links":   [ (id_a, id_b), ... ]
            }
        """
        # 注册所有设备
        for device_id, layer in config.get("devices", {}).items():
            self.register_device(device_id, layer)

        # 添加所有链路
        for id_a, id_b in config.get("links", []):
            self.add_link(id_a, id_b)

        logger.info(
            f"拓扑加载完成: {len(self._devices)} 台设备, "
            f"{sum(len(v) for v in self._adjacency.values()) // 2} 条链路"
        )

    # ════════════════════════════════════════════
    #  邻居查询 —— 设备初始化时调用
    # ════════════════════════════════════════════

    def get_neighbors_by_layer(
        self, device_id: str, target_layer: int
    ) -> List[str]:
        """
        获取指定设备在目标层级的所有邻居

        Parameters
        ----------
        device_id    : str  查询设备 ID
        target_layer : int  目标层级 (DeviceLayer.xxx)

        Returns
        -------
        list[str]  邻居设备 ID 列表 (排序, 保证确定性)
        """
        neighbors = self._adjacency.get(device_id, set())
        result = sorted(
            nid for nid in neighbors
            if self._devices.get(nid) == target_layer
        )
        return result

    def get_upstream_ids(self, device_id: str) -> List[str]:
        """获取上层邻居 (layer + 1)"""
        my_layer = self._devices.get(device_id)
        if my_layer is None:
            logger.warning(f"设备 [{device_id}] 未注册，无法查询上层邻居")
            return []
        return self.get_neighbors_by_layer(device_id, my_layer + 1)

    def get_downstream_ids(self, device_id: str) -> List[str]:
        """获取下层邻居 (layer - 1)"""
        my_layer = self._devices.get(device_id)
        if my_layer is None:
            logger.warning(f"设备 [{device_id}] 未注册，无法查询下层邻居")
            return []
        return self.get_neighbors_by_layer(device_id, my_layer - 1)

    def get_peer_ids(self, device_id: str) -> List[str]:
        """获取同层邻居 (same layer, 排除自身)"""
        my_layer = self._devices.get(device_id)
        if my_layer is None:
            logger.warning(f"设备 [{device_id}] 未注册，无法查询同层邻居")
            return []
        return [
            nid for nid in self.get_neighbors_by_layer(device_id, my_layer)
            if nid != device_id
        ]

    def get_device_layer(self, device_id: str) -> Optional[int]:
        """查询设备层级，未注册返回 None"""
        return self._devices.get(device_id)

    # ════════════════════════════════════════════
    #  全站查询 (调试 / 可视化)
    # ════════════════════════════════════════════

    def get_all_devices(self, layer: int = None) -> List[str]:
        """获取所有设备 ID，可按层级过滤"""
        if layer is not None:
            return sorted(
                did for did, lyr in self._devices.items() if lyr == layer
            )
        return sorted(self._devices.keys())

    def get_all_links(self) -> List[Tuple[str, str]]:
        """获取所有链路 (去重, 每条链路只返回一次)"""
        seen = set()
        links = []
        for src, neighbors in self._adjacency.items():
            for dst in neighbors:
                pair = tuple(sorted((src, dst)))
                if pair not in seen:
                    seen.add(pair)
                    links.append(pair)
        return sorted(links)

    def print_summary(self) -> None:
        """打印拓扑摘要 (调试用)"""
        print("=" * 60)
        print("  电站拓扑摘要")
        print("=" * 60)
        for layer in (DeviceLayer.STATION, DeviceLayer.BAY, DeviceLayer.PROCESS):
            devices = self.get_all_devices(layer)
            print(f"\n  [{DeviceLayer.name(layer)}] ({len(devices)} 台)")
            for did in devices:
                up   = self.get_upstream_ids(did)
                down = self.get_downstream_ids(did)
                peer = self.get_peer_ids(did)
                parts = []
                if up:   parts.append(f"↑{up}")
                if down: parts.append(f"↓{down}")
                if peer: parts.append(f"↔{peer}")
                conn_str = "  ".join(parts) if parts else "(无连接)"
                print(f"    {did:30s} {conn_str}")
        print("=" * 60)

    def reset(self) -> None:
        """清空所有拓扑数据"""
        self._devices.clear()
        self._adjacency.clear()
        logger.info("拓扑注册表已重置")


# ── 全局便捷访问 ──
global_topo = TopologyRegistry.get_instance()