"""
demo/run_scenario.py

电站全链路仿真演示 —— 并行运行 + 独立控制台攻击注入

使用:
  python demo/run_scenario.py
"""

import sys
import os
import time
import socket
import json
import logging
import argparse
import threading
from dataclasses import dataclass

os.system("")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from common.bus import MessageBus
from common.message import Message, MsgType, AppProtocol, TransportMedium
from common.topology import TopologyRegistry
from config.topology_config import SUBSTATION_TOPOLOGY
from devices.sensors.mechanical_sensor import MechanicalSensor
from devices.process.breaker_it import BreakerIntelligentTerminal
from devices.process.line_mu import LineMergingUnit
from devices.bay.line_monitor import LineMonitorDevice
from devices.station.monitor_host import MonitorHostDevice
from devices.station.data_server import DataServerDevice
from devices.station.operator_station import OperatorStationDevice
from devices.station.time_sync import TimeSyncDevice

CONSOLE_HOST = "localhost"
CONSOLE_PORT = 9999
TELEMETRY_HOST = "localhost"
TELEMETRY_PORT = 9998

bus = MessageBus()
topo = TopologyRegistry.get_instance()
topo.reset()
topo.load_config(SUBSTATION_TOPOLOGY)

# ── 日志初始化 ──
# ── 日志初始化 ──
os.makedirs("logs", exist_ok=True)

# 1. 定义通用的日志格式
COMMON_FORMATTER = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# 2. 设置 Root Logger (全局汇总 devices.log + 控制台告警)
_file_handler = logging.FileHandler("logs/devices.log", encoding="utf-8")
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(COMMON_FORMATTER)

_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.WARNING)
_console_handler.setFormatter(COMMON_FORMATTER)

_root = logging.getLogger()
_root.setLevel(logging.INFO)
_root.addHandler(_file_handler)
_root.addHandler(_console_handler)

# 3. 设置 Scenario Logger (带颜色的控制台输出，用于演示脚本自身的提示)
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


class ScenarioFormatter(logging.Formatter):
    LEVEL_COLORS = {logging.WARNING: RED, logging.ERROR: RED}

    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelno, GREEN)
        return color + super().format(record) + RESET


logger = logging.getLogger("scenario")
logger.setLevel(logging.INFO)
logger.propagate = False  # 阻止 scenario 日志流向 root(避免重复或写进 devices.log)
_s_handler = logging.StreamHandler()
_s_handler.setLevel(logging.INFO)
_s_handler.setFormatter(ScenarioFormatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
))
logger.addHandler(_s_handler)


# 4. 设置各设备独立的日志文件 (工厂函数)
def setup_device_logger(class_name: str, device_id: str) -> None:
    """为指定设备精准匹配 logger 并创建独立的日志文件"""
    # BaseDevice 中生成的 logger name 格式为: 类名(device_id)
    logger_name = f"{class_name}({device_id})"
    dev_logger = logging.getLogger(logger_name)
    dev_logger.setLevel(logging.INFO)

    fh = logging.FileHandler(f"logs/{device_id}.log", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(COMMON_FORMATTER)
    dev_logger.addHandler(fh)

    # 如果不希望该设备的日志再输出到总文件(devices.log)，可解开下面这行注释
    # dev_logger.propagate = False


DEVICE_CONFIGS = [
    ("LineMonitorDevice", "line_monitor"),
    ("MonitorHostDevice", "monitor_host"),
    ("OperatorStationDevice", "operator_station"),
    ("DataServerDevice", "data_server"),
    ("TimeSyncDevice", "time_sync"),
    ("TimeSyncDevice", "fake_time_sync"),
    ("BreakerIntelligentTerminal", "breaker_it"),
    ("MechanicalSensor", "mechanical_sensor"),
    ("LineMergingUnit", "line_mu"),
]

for cls_name, dev_id in DEVICE_CONFIGS:
    setup_device_logger(cls_name, dev_id)

_stop_event = threading.Event()
_pause_event = threading.Event()
_plant_exploded = threading.Event()


# ════════════════════════════════════════════
#  仿真上下文
# ════════════════════════════════════════════

@dataclass
class SimContext:
    line_mu:           LineMergingUnit
    mechanical_sensor: MechanicalSensor
    breaker_it:        BreakerIntelligentTerminal
    data_server:       DataServerDevice
    line_monitor:      LineMonitorDevice
    bus:               MessageBus
    operator_station:  OperatorStationDevice
    is_time_spoofing: bool = False
    is_1_1: bool = False
    is_1_2: bool = False
    is_3_1: bool = False
    is_3_2: bool = False
    is_4: bool = False
    is_5: bool = False


def _get_total(data_server: DataServerDevice) -> int:
    count = data_server.get_history_count()
    return sum(count.values()) if isinstance(count, dict) else count


class TelemetryPushServer:
    """简易遥测推送服务: TCP 文本行(JSON)"""
    def __init__(self, host: str = TELEMETRY_HOST, port: int = TELEMETRY_PORT):
        self.host = host
        self.port = port
        self._srv = None
        self._clients = set()
        self._lock = threading.Lock()
        self._thread = None
        self._running = threading.Event()

    def start(self):
        self._running.set()
        self._thread = threading.Thread(target=self._accept_loop, name="telemetry_push_server", daemon=True)
        self._thread.start()
        logger.info("遥测推送已启动: %s:%d", self.host, self.port)

    def _accept_loop(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            self._srv = srv
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((self.host, self.port))
            srv.listen(5)
            srv.settimeout(1.0)
            while self._running.is_set() and not _stop_event.is_set():
                try:
                    conn, _ = srv.accept()
                    conn.setblocking(True)
                    with self._lock:
                        self._clients.add(conn)
                except socket.timeout:
                    continue
                except OSError:
                    break

    def broadcast(self, payload: dict):
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        dead = []
        with self._lock:
            clients = list(self._clients)
        for conn in clients:
            try:
                conn.sendall(data)
            except Exception:
                dead.append(conn)
        if dead:
            with self._lock:
                for conn in dead:
                    self._clients.discard(conn)
                    try:
                        conn.close()
                    except Exception:
                        pass

    def stop(self):
        self._running.clear()
        if self._srv is not None:
            try:
                self._srv.close()
            except Exception:
                pass
        with self._lock:
            clients = list(self._clients)
            self._clients.clear()
        for conn in clients:
            try:
                conn.close()
            except Exception:
                pass


# ════════════════════════════════════════════
#  Socket 指令服务器
# ════════════════════════════════════════════

_OVERVOLTAGE_PAYLOAD = {"voltage": 25.0, "current": 200.0}


def _dispatch(cmd: str, ctx: SimContext) -> None:
    if cmd in ("1-1", "1-1-on", "1-1-off"):
        turn_on = (cmd == "1-1-on") or (cmd == "1-1" and not ctx.is_1_1)
        turn_off = (cmd == "1-1-off") or (cmd == "1-1" and ctx.is_1_1)
        if turn_on:
            ctx.line_mu.set_continuous_inject(_OVERVOLTAGE_PAYLOAD)
            logger.warning(
                "合闸时持续过压帧；分闸后注入不生效，SV 为失电数据"
            )
            ctx.is_1_1 = True
        elif turn_off:
            ctx.line_mu.clear_continuous_inject()
            ctx.line_monitor._protection_locked = False
            ctx.line_monitor._auto_reclose_enabled = True
            ctx.line_monitor.suppress_overvoltage_protection = False
            ctx.line_monitor._overvoltage_trip_count = 0
            ctx.line_monitor._voltage_window.clear()
            ctx.line_monitor._overvoltage_persistent_ticks = 0
            ctx.line_monitor._last_window_stat = None
            if ctx.breaker_it.breaker_state != "closed":
                ctx.breaker_it.execute_command({"action": "close"})
            ctx.is_1_1 = False

    elif cmd in ("1-2", "1-2-on", "1-2-off"):
        # 篡改传感器：强制显示 open，让 breaker_it 误判已分闸，拒绝执行 trip
        turn_on = (cmd == "1-2-on") or (cmd == "1-2" and not ctx.is_1_2)
        turn_off = (cmd == "1-2-off") or (cmd == "1-2" and ctx.is_1_2)
        if turn_on:
            # 使用传感器标准状态接口，确保立即事件上报到 breaker_it 缓存
            ctx.mechanical_sensor.set_position("open")
            logger.warning("已篡改传感器位置为 open，trip 指令将被拒绝，线路持续带故障！")
            ctx.is_1_2 = True
        elif turn_off:
            ctx.mechanical_sensor.set_position("closed")
            logger.warning("传感器位置篡改结束")
            ctx.is_1_2 = False
    
    elif cmd in ("3-1", "3-1-on", "3-1-off"):
        turn_on = (cmd == "3-1-on") or (cmd == "3-1" and not ctx.is_3_1)
        turn_off = (cmd == "3-1-off") or (cmd == "3-1" and ctx.is_3_1)
        if turn_on:
            topo.remove_link("line_monitor", "monitor_host")
            logger.warning("通信干扰成功。【间隔层-站控层】通信链路已在物理层瘫痪")
            ctx.is_3_1 = True
        elif turn_off:
            topo.add_link("line_monitor", "monitor_host")
            logger.warning("【间隔层-站控层】通信干扰成功结束")
            ctx.is_3_1 = False

    elif cmd in ("3-2", "3-2-on", "3-2-off"):
        turn_on = (cmd == "3-2-on") or (cmd == "3-2" and not ctx.is_3_2)
        turn_off = (cmd == "3-2-off") or (cmd == "3-2" and ctx.is_3_2)
        if turn_on:
            topo.remove_link("line_monitor", "breaker_it")
            logger.warning("通信干扰成功。【断路器-间隔层】通信链路已在物理层瘫痪")
            ctx.is_3_2 = True
        elif turn_off:
            topo.add_link("line_monitor", "breaker_it")
            logger.warning("【断路器-间隔层】通信干扰成功结束")
            ctx.is_3_2 = False

    elif cmd in ("4", "4-on", "4-off"):
        turn_on = (cmd == "4-on") or (cmd == "4" and not ctx.is_4)
        turn_off = (cmd == "4-off") or (cmd == "4" and ctx.is_4)
        if turn_on:
            topo.remove_link("time_sync", "breaker_it")
            topo.add_link("fake_time_sync", "breaker_it")
            ctx.is_time_spoofing = True
            logger.warning("授时欺骗")
            ctx.is_4 = True
        elif turn_off:
            topo.add_link("time_sync", "breaker_it")
            topo.remove_link("fake_time_sync", "breaker_it")
            ctx.is_time_spoofing = False
            logger.warning("授时欺骗结束")
            ctx.is_4 = False

    elif cmd in ("5", "5-on", "5-off"):
        # 攻击5：伪造间隔层 GOOSE 直投过程层合闸；闭锁过压跳闸与自动重合闸
        turn_on = (cmd == "5-on") or (cmd == "5" and not ctx.is_5)
        turn_off = (cmd == "5-off") or (cmd == "5" and ctx.is_5)
        if turn_on:
            ctx.line_monitor.suppress_overvoltage_protection = True
            ctx.line_monitor._auto_reclose_enabled = False
            ctx.line_monitor._reclose_armed = False
            if ctx.line_monitor._reclose_timer is not None:
                ctx.line_monitor._reclose_timer.cancel()
                ctx.line_monitor._reclose_timer = None
            now = time.time()
            forged = Message(
                sender_id="line_monitor",
                receiver_id="breaker_it",
                msg_type=MsgType.CMD,
                app_protocol=AppProtocol.GOOSE,
                transport_medium=TransportMedium.RF_LOW_LATENCY,
                payload={
                    "action": "close",
                    "reason": "forged_bay_goose_injection",
                    "cmd_time": now,
                },
                timestamp=now,
            )
            ok = ctx.bus.send(forged)
            if ok:
                logger.warning(
                    "攻击5：已伪造间隔层报文直投断路器智能终端合闸；"
                    "过压本地切除与自动重合闸已闭锁（可再次输入 5 解除）"
                )
            else:
                logger.warning(
                    "攻击5：伪造合闸报文投递失败（检查拓扑链路 line_monitor↔breaker_it 是否被切断）"
                )
            ctx.is_5 = True
        elif turn_off:
            ctx.line_monitor.suppress_overvoltage_protection = False
            ctx.line_monitor._auto_reclose_enabled = True
            logger.warning("攻击5 结束：过压保护判据与自动重合闸策略已恢复为默认")
            ctx.is_5 = False

    elif cmd == "m-1":
        ctx.operator_station.send_manual_command("line_monitor", "breaker_it", "close")
        logger.warning("人工合闸")

    elif cmd == "m-2":
        ctx.operator_station.send_manual_command("line_monitor", "breaker_it", "trip")
        logger.warning("人工分闸")

    elif cmd == "o":
        ctx.line_mu.set_continuous_override(_OVERVOLTAGE_PAYLOAD)
        logger.warning("电网过载异常")

    elif cmd == "r":
        ctx.line_mu.clear_continuous_inject()
        ctx.line_mu.clear_continuous_override()
        ctx.mechanical_sensor._spring_charged = True
        ctx.mechanical_sensor.set_position("closed")
        ctx.line_monitor._reclose_armed = False
        if ctx.line_monitor._reclose_timer is not None:
            ctx.line_monitor._reclose_timer.cancel()
        topo.add_link("line_monitor", "monitor_host")
        topo.add_link("line_monitor", "breaker_it")
        ctx.is_time_spoofing = False
        topo.add_link("time_sync", "breaker_it")
        topo.remove_link("fake_time_sync", "breaker_it")
        ctx.line_monitor._protection_locked = False
        ctx.line_monitor._auto_reclose_enabled = True
        ctx.line_monitor.suppress_overvoltage_protection = False
        ctx.line_monitor._overvoltage_trip_count = 0
        ctx.line_monitor._voltage_window.clear()
        ctx.line_monitor._overvoltage_persistent_ticks = 0
        ctx.line_monitor._last_window_stat = None
        if ctx.breaker_it.breaker_state != "closed":
            ctx.breaker_it.execute_command({"action": "close"})
        ctx.is_1_1 = False
        ctx.is_1_2 = False
        ctx.is_3_1 = False
        ctx.is_3_2 = False
        ctx.is_4 = False
        ctx.is_5 = False
        _plant_exploded.clear()
        _pause_event.clear()  # ← 解除暂停，主循环恢复
        logger.warning("所有状态已重置")


    elif cmd == "s":
        last = ctx.line_mu.last_sample
        v = last.get("voltage", 0) if last else 0
        c = last.get("current", 0) if last else 0
        logger.info(
            "voltage=%.1fkV  current=%.1fA  断路器=%s | "
            "传感器位置=%s | 弹簧储能=%s | 总线消息=%d | 入库=%d",
            v, c,
            ctx.breaker_it.breaker_state,
            ctx.mechanical_sensor.position,
            ctx.mechanical_sensor.spring_charged,
            len(ctx.bus.get_history()),
            _get_total(ctx.data_server),
        )

    elif cmd == "q":
        logger.info("收到退出指令，正在停止仿真...")
        _stop_event.set()

    else:
        logger.warning("未知指令: %s", cmd)


def socket_server(ctx: SimContext) -> None:
    def _handle_client(conn: socket.socket, addr) -> None:
        logger.info("控制端已连接: %s", addr)
        with conn:
            conn.settimeout(1.0)
            while not _stop_event.is_set():
                try:
                    data = conn.recv(64).decode().strip().lower()
                except socket.timeout:
                    continue
                except Exception:
                    break
                if not data:
                    break
                _dispatch(data, ctx)
        logger.info("控制端已断开: %s", addr)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((CONSOLE_HOST, CONSOLE_PORT))
        srv.listen(8)
        srv.settimeout(1.0)
        logger.info("指令监听已启动: %s:%d  等待控制台连接...", CONSOLE_HOST, CONSOLE_PORT)

        while not _stop_event.is_set():
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=_handle_client,
                args=(conn, addr),
                name=f"cmd_client_{addr[0]}_{addr[1]}",
                daemon=True,
            ).start()


# ════════════════════════════════════════════
#  主仿真逻辑
# ════════════════════════════════════════════

def run() -> None:

    # ── 初始化 ──
    bus = MessageBus()
    topo = TopologyRegistry.get_instance()
    topo.reset()
    topo.load_config(SUBSTATION_TOPOLOGY)

    line_monitor      = LineMonitorDevice("line_monitor", bus=bus)
    monitor_host      = MonitorHostDevice("monitor_host", bus=bus)
    operator_station = OperatorStationDevice("operator_station", bus=bus)
    data_server       = DataServerDevice("data_server", bus=bus)
    time_sync = TimeSyncDevice("time_sync", bus=bus)

    topo.register_device("fake_time_sync", 2)
    fake_time_sync = TimeSyncDevice("fake_time_sync", bus=bus)

    # breaker_it 必须先于 line_mu 实例化
    breaker_it        = BreakerIntelligentTerminal(bus=bus, topo=topo, report_interval=1)
    mechanical_sensor = MechanicalSensor(bus=bus, topo=topo, initial_position="closed")
    line_mu           = LineMergingUnit(bus=bus, topo=topo, breaker_ref=breaker_it, report_interval=1)

    for dev_id in ("line_protect", "transformer_mu", "transformer_monitor",
                   "transformer_protect", "transformer_it", "transformer_status", "fake_time_sync"):
        bus.register(dev_id, lambda m: None)

    logger.info("初始化时间戳")
    time_sync.broadcast_time_sync()

    # ── 启动设备线程 ──
    mechanical_sensor.start()
    line_mu.start()

    ctx = SimContext(
        line_mu=line_mu,
        mechanical_sensor=mechanical_sensor,
        breaker_it=breaker_it,
        data_server=data_server,
        line_monitor=line_monitor,
        bus=bus,
        operator_station=operator_station,
    )

    logger.info("电站全链路仿真演示启动（并行运行模式）")
    logger.info("断路器初始状态: %s", breaker_it.breaker_state)
    telemetry_push = TelemetryPushServer()
    telemetry_push.start()

    # ── 启动 socket 服务器线程 ──
    server_thread = threading.Thread(
        target=socket_server, args=(ctx,),
        name="socket_server", daemon=True,
    )
    server_thread.start()

    # ── 主循环 ──
    prev_breaker_state = breaker_it.breaker_state
    tick = 0
    SUMMARY_TICKS = 1
    BOOM_COUNT = 0

    while not _stop_event.is_set():
        if _pause_event.is_set():
            time.sleep(0.5)
            continue

        time.sleep(1)
        tick += 1

        time_sync.broadcast_time_sync()

        if ctx.is_time_spoofing:
            fake_time_sync.time_sync_to_process("breaker_it", time.time() + 100)

        breaker_now = breaker_it.breaker_state
        if breaker_now != prev_breaker_state:
            logger.warning("断路器变位: %s → %s", prev_breaker_state, breaker_now)
            prev_breaker_state = breaker_now

        if tick % SUMMARY_TICKS == 0:
            last = line_mu.last_sample
            v = last.get("voltage", 0) if last else 0
            c = last.get("current", 0) if last else 0
            stored = _get_total(data_server)
            logger.info(
                "voltage=%5.1fkV  current=%5.1fA  "
                "断路器=%-12s  传感器=%-12s  入库=%d",
                v, c,
                breaker_it.breaker_state,
                mechanical_sensor.position,
                stored,
            )
            telemetry_push.broadcast({
                "voltage": v,
                "current": c,
                "breakerState": breaker_it.breaker_state,
                "sensorState": mechanical_sensor.position,
                "storedCount": stored,
                "plantState": "exploded" if _plant_exploded.is_set() else "normal",
                "updatedAt": time.time(),
            })

            if abs(v - 25) < 5 and abs(c - 200) < 5:
                BOOM_COUNT += 1
            else:
                BOOM_COUNT = 0

        if BOOM_COUNT > 20:
            BOOM_COUNT = 0          # ← 重置计数，避免重复触发
            _plant_exploded.set()
            _pause_event.set()      # ← 设置暂停标志
            telemetry_push.broadcast({
                "voltage": v,
                "current": c,
                "breakerState": breaker_it.breaker_state,
                "sensorState": mechanical_sensor.position,
                "storedCount": stored,
                "plantState": "exploded",
                "updatedAt": time.time(),
            })
            logger.info(r"""
                  _.-^^---....,,--       
              _--                  --_  
             <      电 厂 爆 炸 了      >)
             |                         | 
              \._                   _./  
                 ```--. . , ; .--'''       
                       | |   |             
                    .-=||  | |=-.   
                    `-=#$%&%$#=-'   
                       | ;  :|     
              _____.,-#%&$@%#&#~,._____
             """)
            logger.warning("仿真已暂停！请在控制台输入 [r] 重置并继续...")

    # ── 清理 ──
    line_mu.stop()
    mechanical_sensor.stop()
    server_thread.join(timeout=2)
    telemetry_push.stop()

    logger.info("演示完成")
    logger.info(
        "总线消息总数: %d  断路器最终状态: %s",
        len(bus.get_history()), breaker_it.breaker_state,
    )
    


def main() -> None:
    parser = argparse.ArgumentParser(description="电站全链路仿真演示")
    args = parser.parse_args()
    run()


if __name__ == "__main__":
    main()
