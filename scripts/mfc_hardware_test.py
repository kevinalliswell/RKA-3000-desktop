#!/usr/bin/env python3
"""MQV 质量流量控制器真机测试 CLI。

用于现场联调，无需启动 GUI，直接与设备通信并打印收发帧及解析结果。

用法示例：
  # 读取通道01的 SP+PV
  python scripts/mfc_hardware_test.py --port /dev/ttyUSB0 --addr 01 --action read

  # 写入 SP-0 = 2.0 L/min（满量程 10.0 L/min）
  python scripts/mfc_hardware_test.py --port /dev/ttyUSB0 --addr 01 --action write --sp 2.0 --full-scale 10.0

  # 扫描地址 01–06，报告哪些设备在线
  python scripts/mfc_hardware_test.py --port /dev/ttyUSB0 --action scan

  # 读取时打印原始帧（十六进制）
  python scripts/mfc_hardware_test.py --port /dev/ttyUSB0 --addr 01 --action read --verbose
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 将 src 加入路径，支持直接运行
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rka_desktop.core.mfc_protocol import (
    DeviceError,
    ProtocolError,
    build_read_frame,
    build_write_frame,
    parse_read_response,
    parse_write_response,
)
from rka_desktop.core.mfc_registers import EepromAddr, RamAddr, FULL_SCALE_COUNT, sp_eeprom_addr

_RAM_SP_ADDR = int(RamAddr.SP_CURRENT)


def _hex_str(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def _open_serial(port: str, baudrate: int):
    try:
        import serial
    except ImportError:
        print("错误：pyserial 未安装，请运行 pip install pyserial", file=sys.stderr)
        sys.exit(1)
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=1.0,
        )
        return ser
    except Exception as exc:
        print(f"错误：串口 {port} 打开失败 — {exc}", file=sys.stderr)
        sys.exit(1)


def _transact(ser, frame: bytes, verbose: bool) -> bytes:
    if verbose:
        print(f"  → 发送: {_hex_str(frame)}")
    ser.reset_input_buffer()
    ser.write(frame)
    buf = bytearray()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        byte = ser.read(1)
        if not byte:
            break
        buf.extend(byte)
        if byte[0] == 0x0A:
            break
    raw = bytes(buf)
    if verbose and raw:
        print(f"  ← 接收: {_hex_str(raw)}")
    return raw


def cmd_read(ser, addr: str, full_scale: float, verbose: bool) -> None:
    frame = build_read_frame(addr, _RAM_SP_ADDR, count=2)
    raw = _transact(ser, frame, verbose)
    if not raw:
        print(f"[{addr}] 超时：未收到应答")
        return
    try:
        words = parse_read_response(raw, expected_count=2)
    except (ProtocolError, DeviceError) as exc:
        print(f"[{addr}] 错误：{exc}")
        return
    sp_raw, pv_raw = words[0], words[1]
    scale = full_scale / FULL_SCALE_COUNT
    sp_lpm = sp_raw * scale
    pv_lpm = pv_raw * scale
    print(f"[{addr}] SP = {sp_lpm:.4f} L/min (raw={sp_raw})"
          f"  |  PV = {pv_lpm:.4f} L/min (raw={pv_raw})")


def cmd_write(ser, addr: str, sp_lpm: float, full_scale: float, sp_index: int, verbose: bool) -> None:
    if sp_lpm < 0 or sp_lpm > full_scale:
        print(f"错误：设定值 {sp_lpm} 超出量程 [0, {full_scale}]", file=sys.stderr)
        return
    raw_value = round(sp_lpm / full_scale * FULL_SCALE_COUNT)
    eeprom_addr = sp_eeprom_addr(sp_index)
    frame = build_write_frame(addr, eeprom_addr, raw_value)
    raw_resp = _transact(ser, frame, verbose)
    if not raw_resp:
        print(f"[{addr}] 超时：未收到写入应答")
        return
    try:
        end_code = parse_write_response(raw_resp)
        print(f"[{addr}] 写入 SP-{sp_index} = {sp_lpm:.4f} L/min (raw={raw_value})"
              f"  →  结束代码: {end_code}")
    except (ProtocolError, DeviceError) as exc:
        print(f"[{addr}] 写入错误：{exc}")


def cmd_scan(ser, baudrate: int, verbose: bool) -> None:
    print(f"扫描地址 01–06（波特率={baudrate}）...")
    online: list[str] = []
    for i in range(1, 7):
        addr = f"{i:02d}"
        frame = build_read_frame(addr, _RAM_SP_ADDR, count=1)
        raw = _transact(ser, frame, verbose)
        if not raw:
            print(f"  [{addr}] 离线（超时）")
            continue
        try:
            parse_read_response(raw, expected_count=1)
            print(f"  [{addr}] 在线 ✓")
            online.append(addr)
        except (ProtocolError, DeviceError) as exc:
            print(f"  [{addr}] 响应异常：{exc}")
        time.sleep(0.05)
    print(f"\n在线设备：{online if online else '无'}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MQV 质量流量控制器真机测试工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--port", required=True, help="串口设备路径，如 /dev/ttyUSB0 或 COM3")
    parser.add_argument("--baudrate", type=int, default=9600, help="波特率，默认 9600")
    parser.add_argument("--addr", default="01", help="机器地址（2位十六进制），默认 01")
    parser.add_argument(
        "--action", choices=["read", "write", "scan"], required=True,
        help="操作类型：read=读SP/PV，write=写SP，scan=扫描在线设备",
    )
    parser.add_argument("--sp", type=float, default=0.0, help="[write] 设定流量（L/min）")
    parser.add_argument("--full-scale", type=float, default=10.0,
                        help="满量程（L/min），默认 10.0")
    parser.add_argument("--sp-index", type=int, default=0,
                        help="[write] SP 段索引 0–7，默认 0（SP-0）")
    parser.add_argument("--verbose", action="store_true", help="打印原始收发帧（十六进制）")
    args = parser.parse_args()

    ser = _open_serial(args.port, args.baudrate)
    print(f"串口 {args.port} 已打开（{args.baudrate} baud）\n")

    try:
        if args.action == "read":
            cmd_read(ser, args.addr, args.full_scale, args.verbose)
        elif args.action == "write":
            cmd_write(ser, args.addr, args.sp, args.full_scale, args.sp_index, args.verbose)
        elif args.action == "scan":
            cmd_scan(ser, args.baudrate, args.verbose)
    finally:
        ser.close()


if __name__ == "__main__":
    main()
