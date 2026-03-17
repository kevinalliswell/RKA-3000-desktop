"""MQV 系列质量流量控制器通信协议 — 帧构建与解析。

协议帧格式：
  STX | 机器地址(2) | 子地址(2) | X(1) | 命令/应答(可变) | ETX | 校验和(2) | CR | LF

校验和算法：
  sum(STX..ETX) & 0xFF 的二进制补码，用 2 位大写 ASCII 十六进制表示。

参考：references/MQV质量流量控制器通信协议.md
"""
from __future__ import annotations

STX = 0x02
ETX = 0x03
CR = 0x0D
LF = 0x0A
SUB_ADDR = b"00"  # 子地址固定为 "00"
ADDR_TYPE = b"X"  # 标准地址范围 58H


# ---------------------------------------------------------------------------
# 校验和
# ---------------------------------------------------------------------------

def _checksum(frame_bytes: bytes) -> bytes:
    """计算从 STX 到 ETX（含两端）的校验和，返回 2 字节大写 ASCII。"""
    total = sum(frame_bytes) & 0xFF
    cs = (0x100 - total) & 0xFF
    return f"{cs:02X}".encode("ascii")


# ---------------------------------------------------------------------------
# 帧构建
# ---------------------------------------------------------------------------

def build_read_frame(machine_addr: str, reg_addr: int, count: int) -> bytes:
    """构建读数据命令帧（RD）。

    Args:
        machine_addr: 2 位十六进制字符串，如 "01"。
        reg_addr:     寄存器地址（整数），地址首位决定存储区：
                      0x0000–0x0FFF → RAM，0x1000–0x1FFF → EEPROM。
        count:        读取字数（16-bit 字）。

    Returns:
        完整帧字节串，含 STX … LF。
    """
    addr_str = f"{reg_addr:04X}".encode("ascii")
    count_str = f"{count:04X}".encode("ascii")
    payload = b"RD" + addr_str + count_str
    return _wrap_frame(machine_addr, payload)


def build_write_frame(machine_addr: str, reg_addr: int, value: int) -> bytes:
    """构建写数据命令帧（WD，单字写入）。

    Args:
        machine_addr: 2 位十六进制字符串，如 "01"。
        reg_addr:     目标地址（整数）。
        value:        写入值（0–65535）。

    Returns:
        完整帧字节串，含 STX … LF。
    """
    addr_str = f"{reg_addr:04X}".encode("ascii")
    data_str = f"{value:04X}".encode("ascii")
    payload = b"WD" + addr_str + data_str
    return _wrap_frame(machine_addr, payload)


def _wrap_frame(machine_addr: str, payload: bytes) -> bytes:
    """将应用层 payload 封装为完整帧。"""
    body = (
        machine_addr.upper().encode("ascii")
        + SUB_ADDR
        + ADDR_TYPE
        + payload
    )
    inner = bytes([STX]) + body + bytes([ETX])
    cs = _checksum(inner)
    return inner + cs + bytes([CR, LF])


# ---------------------------------------------------------------------------
# 帧解析
# ---------------------------------------------------------------------------

class ProtocolError(Exception):
    """协议帧格式错误或校验失败。"""


class DeviceError(Exception):
    """设备返回异常结束代码。"""

    # 结束代码描述映射
    _END_CODE_DESC: dict[str, str] = {
        "00": "正常结束",
        "21": "警告：通讯不能设定的地址写入，写入未执行",
        "23": "警告：地址超范围，终止读写，此前写入有效",
        "40": "异常：地址未设定 W，废弃全部电文",
        "41": "异常：WS 或 RS 未设定，废弃全部电文",
        "43": "异常：ETX 位置不正确或地址末尾缺少逗号，废弃全部电文",
        "46": "异常：地址异常，废弃全部电文",
        "47": "异常：读出数据数异常，废弃全部电文",
        "48": "异常：写入数值异常，除异常地址外写入",
        "99": "异常：未定义命令或其它电文异常，废弃全部电文",
    }

    def __init__(self, end_code: str) -> None:
        self.end_code = end_code
        desc = self._END_CODE_DESC.get(end_code, f"未知结束代码 {end_code}")
        super().__init__(f"[{end_code}] {desc}")


def parse_read_response(raw: bytes, expected_count: int) -> list[int]:
    """解析读数据应答帧，返回整数列表（每个元素对应一个 16-bit 字）。

    Args:
        raw:            完整应答字节串（含 STX … LF）。
        expected_count: 预期读取字数，用于校验数据长度。

    Returns:
        长度为 expected_count 的整数列表。

    Raises:
        ProtocolError: 帧格式错误或校验和不匹配。
        DeviceError:   设备返回非 "00"/"21"/"23" 结束代码。
    """
    _validate_frame(raw)
    # 去掉 STX、机器地址(2)、子地址(2)、X(1) = 6 字节前缀，以及 ETX+CS+CR+LF = 5 字节后缀
    app_layer = raw[6:-5]  # end_code(2) + data(N*4)
    end_code = app_layer[:2].decode("ascii")
    if end_code not in ("00", "21", "23"):
        raise DeviceError(end_code)
    data_hex = app_layer[2:]
    if len(data_hex) != expected_count * 4:
        raise ProtocolError(
            f"数据长度不符：期望 {expected_count * 4} 字节，实际 {len(data_hex)} 字节"
        )
    return [int(data_hex[i * 4: i * 4 + 4], 16) for i in range(expected_count)]


def parse_write_response(raw: bytes) -> str:
    """解析写数据应答帧，返回结束代码字符串。

    Raises:
        ProtocolError: 帧格式错误或校验和不匹配。
        DeviceError:   设备返回异常结束代码（40/41/43/46/47/48/99）。
    """
    _validate_frame(raw)
    app_layer = raw[6:-5]
    end_code = app_layer[:2].decode("ascii")
    if end_code not in ("00", "21", "23"):
        raise DeviceError(end_code)
    return end_code


def _validate_frame(raw: bytes) -> None:
    """校验帧完整性：最小长度、STX/ETX 标志、校验和。"""
    # 最小帧：STX(1)+addr(2)+sub(2)+X(1)+end(2)+ETX(1)+cs(2)+CR(1)+LF(1) = 13
    if len(raw) < 13:
        raise ProtocolError(f"帧长度过短：{len(raw)} 字节")
    if raw[0] != STX:
        raise ProtocolError("帧起始符不是 STX(02H)")
    etx_pos = raw.find(ETX, 6)
    if etx_pos < 0:
        raise ProtocolError("未找到 ETX(03H)")
    inner = raw[: etx_pos + 1]
    expected_cs = _checksum(inner)
    actual_cs = raw[etx_pos + 1: etx_pos + 3]
    if actual_cs != expected_cs:
        raise ProtocolError(
            f"校验和不匹配：期望 {expected_cs.decode()}, 实际 {actual_cs.decode(errors='replace')}"
        )
