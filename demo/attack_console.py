"""
demo/attack_console.py

攻击注入控制台 —— 独立窗口运行

使用:
  python demo/attack_console.py
"""

import socket
import argparse
import os

os.system("")  # 激活 Windows ANSI 支持

YELLOW = "\033[33m"
GREEN  = "\033[32m"
RED    = "\033[31m"
RESET  = "\033[0m"

MENU = f"""
{YELLOW}========== 攻击注入控制台 =========={RESET}
  {RED}[1]{RESET} 持续过压帧（仅合闸时生效；分闸后为失电）
  {RED}[2]{RESET} 篡改传感器位置为 open   (trip 指令被拒 → 线路持续带故障)
  {RED}[3-1]{RESET} 通信干扰（间隔-站控）
  {RED}[3-2]{RESET} 通信干扰（过程-间隔）
  {GREEN}[4]{RESET} 人工合闸
  {GREEN}[5]{RESET} 人工分闸
  {RED}[6]{RESET} 授时欺骗（断路器）
  {RED}[7]{RESET} 伪造间隔层 GOOSE 合闸 + 闭锁自动分闸/重合闸
  {GREEN}[r]{RESET} 重置所有状态
  {GREEN}[s]{RESET} 查看当前状态
  {YELLOW}[q]{RESET} 退出仿真
{YELLOW}====================================={RESET}
"""

CMD_HINTS = {
    "1": "持续过压帧",
    "2": "篡改传感器位置为 open",
    "3-1": "通信干扰（间隔-站控）",
    "3-2": "通信干扰（过程-间隔）",
    "4": "人工合闸",
    "5": "人工分闸",
    "6": "授时欺骗（断路器）",
    "7": "伪造合闸并闭锁自动分合闸",
    "r": "重置所有状态",
    "s": "查看当前状态",
    "q": "退出仿真",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="攻击注入控制台")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=9999)
    args = parser.parse_args()

    print(f"连接仿真主进程 {args.host}:{args.port} ...")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.connect((args.host, args.port))
        except ConnectionRefusedError:
            print(f"{RED}连接失败，请先启动仿真主进程{RESET}")
            return

        print(f"{GREEN}连接成功！{RESET}")
        print(MENU)

        while True:
            try:
                cmd = input(">>> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n已退出控制台")
                break

            if not cmd:
                continue

            if cmd not in CMD_HINTS:
                print(f"{RED}未知指令: {cmd}{RESET}  可用: {list(CMD_HINTS.keys())}")
                continue

            print(f"  → {CMD_HINTS[cmd]}")

            try:
                s.sendall(cmd.encode())
            except (BrokenPipeError, OSError):
                print(f"{RED}仿真主进程已断开{RESET}")
                break

            if cmd == "q":
                print("已发送退出指令")
                break


if __name__ == "__main__":
    main()
