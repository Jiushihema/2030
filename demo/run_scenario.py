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

# ── 日志初始化 ──
os.makedirs("logs", exist_ok=True)

bus = MessageBus()
topo = TopologyRegistry.get_instance()
topo.reset()
topo.load_config(SUBSTATION_TOPOLOGY)

_file_handler = logging.FileHandler("logs/devices.log", encoding="utf-8")
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
))

_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.WARNING)
_console_handler.setFormatter(logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
))

_root = logging.getLogger()
_root.setLevel(logging.INFO)
_root.addHandler(_file_handler)
_root.addHandler(_console_handler)

GREEN = "\033[32m"
RED   = "\033[31m"
RESET = "\033[0m"

class ScenarioFormatter(logging.Formatter):
    LEVEL_COLORS = {logging.WARNING: RED, logging.ERROR: RED}
    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelno, GREEN)
        return color + super().format(record) + RESET

logger = logging.getLogger("scenario")
logger.setLevel(logging.INFO)
logger.propagate = False
_s_handler = logging.StreamHandler()
_s_handler.setLevel(logging.INFO)
_s_handler.setFormatter(ScenarioFormatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
))
logger.addHandler(_s_handler)

_stop_event = threading.Event()
_pause_event = threading.Event()


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


# ════════════════════════════════════════════
#  Socket 指令服务器
# ════════════════════════════════════════════

_OVERVOLTAGE_PAYLOAD = {"voltage": 25.0, "current": 200.0}


def _dispatch(cmd: str, ctx: SimContext) -> None:
    if cmd == "1-1":
        if not ctx.is_1_1:
            ctx.line_mu.set_continuous_inject(_OVERVOLTAGE_PAYLOAD)
            logger.warning(
                "合闸时持续过压帧；分闸后注入不生效，SV 为失电数据"
            )
            ctx.is_1_1 = True
        else:
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

    elif cmd == "1-2":
        # 篡改传感器：强制显示 open，让 breaker_it 误判已分闸，拒绝执行 trip
        if not ctx.is_1_2:
            ctx.mechanical_sensor._position = "open"
            ctx.mechanical_sensor._last_sample_value = None
            logger.warning("已篡改传感器位置为 open，trip 指令将被拒绝，线路持续带故障！")
            ctx.is_1_2 = True
        else:
            ctx.mechanical_sensor._spring_charged = True
            ctx.mechanical_sensor.set_position("closed")
            logger.warning("传感器位置篡改结束")
            ctx.is_1_2 = False
    
    elif cmd == "3-1":
        if not ctx.is_3_1:
            topo.remove_link("line_monitor", "monitor_host")
            logger.warning("通信干扰成功。【间隔层-站控层】通信链路已在物理层瘫痪")
            ctx.is_3_1 = True
        else:
            topo.add_link("line_monitor", "monitor_host")
            logger.warning("【间隔层-站控层】通信干扰成功结束")
            ctx.is_3_1 = False

    elif cmd == "3-2":
        if not ctx.is_3_2:
            topo.remove_link("line_monitor", "breaker_it")
            logger.warning("通信干扰成功。【断路器-间隔层】通信链路已在物理层瘫痪")
            ctx.is_3_2 = True
        else:
            topo.add_link("line_monitor", "breaker_it")
            logger.warning("【断路器-间隔层】通信干扰成功结束")
            ctx.is_3_2 = False

    elif cmd == "4":
        if not ctx.is_4:
            topo.remove_link("time_sync", "breaker_it")
            topo.add_link("fake_time_sync", "breaker_it")
            ctx.is_time_spoofing = True
            logger.warning("授时欺骗")
            ctx.is_4 = True
        else:
            topo.add_link("time_sync", "breaker_it")
            topo.remove_link("fake_time_sync", "breaker_it")
            ctx.is_time_spoofing = False
            logger.warning("授时欺骗结束")
            ctx.is_4 = False

    elif cmd == "5":
        # 攻击5：伪造间隔层 GOOSE 直投过程层合闸；闭锁过压跳闸与自动重合闸
        if not ctx.is_5:
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
        else:
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
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((CONSOLE_HOST, CONSOLE_PORT))
        srv.listen(1)
        srv.settimeout(1.0)
        logger.info("指令监听已启动: %s:%d  等待控制台连接...", CONSOLE_HOST, CONSOLE_PORT)

        while not _stop_event.is_set():
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            logger.info("控制台已连接: %s", addr)
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

            logger.info("控制台已断开")


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
            logger.info(
                "voltage=%5.1fkV  current=%5.1fA  "
                "断路器=%-12s  传感器=%-12s  入库=%d",
                v, c,
                breaker_it.breaker_state,
                mechanical_sensor.position,
                _get_total(data_server),
            )

            if abs(v - 25) < 5 and abs(c - 200) < 5:
                BOOM_COUNT += 1
            else:
                BOOM_COUNT = 0

        if BOOM_COUNT > 20:
            BOOM_COUNT = 0          # ← 重置计数，避免重复触发
            _pause_event.set()      # ← 设置暂停标志
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
