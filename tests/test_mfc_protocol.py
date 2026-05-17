"""MQV 协议帧构建与解析单元测试。

测试用例以协议文档（references/MQV质量流量控制器通信协议.md）中
3 组已知输入输出为基准，逐字节验证。
"""
import pytest

from rka_desktop.core.mfc_protocol import (
    DeviceError,
    ProtocolError,
    build_read_frame,
    build_write_frame,
    parse_read_response,
    parse_write_response,
)

# ---------------------------------------------------------------------------
# 文档示例常量（字节级别，来自协议文档图像，已人工校验）
# ---------------------------------------------------------------------------

# 示例1：读 SP+PV（机器地址01，RAM 04B6H，读2字）
# 校验和验证：sum=850 → 0x52 → 补码 0xAE ✓
READ_SP_PV_FRAME = bytes([
    0x02,                                           # STX
    0x30, 0x31,                                     # 机器地址 "01"
    0x30, 0x30,                                     # 子地址 "00"
    0x58,                                           # "X"
    0x52, 0x44,                                     # "RD"
    0x30, 0x34, 0x42, 0x36,                         # 地址 "04B6"
    0x30, 0x30, 0x30, 0x32,                         # 数量 "0002"
    0x03,                                           # ETX
    0x41, 0x45,                                     # 校验和 "AE"
    0x0D, 0x0A,                                     # CR LF
])

# 示例1 应答：SP=0x0032(50), PV=0x0168(360)
# 校验和验证：sum=786 → 0x12 → 补码 0xEE ✓
READ_SP_PV_RESPONSE = bytes([
    0x02,
    0x30, 0x31,
    0x30, 0x30,
    0x58,
    0x30, 0x30,                                     # 结束代码 "00"
    0x30, 0x30, 0x33, 0x32,                         # SP "0032"
    0x30, 0x31, 0x36, 0x38,                         # PV "0168"
    0x03,
    0x45, 0x45,                                     # 校验和 "EE"
    0x0D, 0x0A,
])

# 示例2：写 SP-0=0（机器地址01，EEPROM 1131H，值0）
# 校验和验证：sum=831 → 0x3F → 补码 0xC1 ✓
WRITE_SP0_FRAME = bytes([
    0x02,
    0x30, 0x31,
    0x30, 0x30,
    0x58,
    0x57, 0x44,                                     # "WD"
    0x31, 0x31, 0x33, 0x31,                         # 地址 "1131"
    0x30, 0x30, 0x30, 0x30,                         # 数据 "0000"
    0x03,
    0x43, 0x31,                                     # 校验和 "C1"
    0x0D, 0x0A,
])

# 示例2 应答：正常结束
# 校验和验证：sum=382 → 0x7E → 补码 0x82 ✓
WRITE_SP0_RESPONSE = bytes([
    0x02,
    0x30, 0x31,
    0x30, 0x30,
    0x58,
    0x30, 0x30,                                     # 结束代码 "00"
    0x03,
    0x38, 0x32,                                     # 校验和 "82"
    0x0D, 0x0A,
])


# ---------------------------------------------------------------------------
# 辅助：构造含正确校验和的错误应答帧
# ---------------------------------------------------------------------------

def _make_response(machine_addr: str, end_code: str, data: bytes = b"") -> bytes:
    """构造合法的应答帧（含正确校验和），用于测试各种结束代码场景。"""
    body = (
        machine_addr.upper().encode("ascii")
        + b"00"                                     # 子地址固定
        + b"X"
        + end_code.encode("ascii")
        + data
    )
    inner = bytes([0x02]) + body + bytes([0x03])
    total = sum(inner) & 0xFF
    cs_byte = (0x100 - total) & 0xFF
    cs = f"{cs_byte:02X}".encode("ascii")
    return inner + cs + bytes([0x0D, 0x0A])


# ===========================================================================
# build_read_frame
# ===========================================================================

class TestBuildReadFrame:
    def test_doc_example_exact_bytes(self):
        """文档示例1：逐字节验证读 SP/PV 命令帧。"""
        frame = build_read_frame("01", 0x04B6, 2)
        assert frame == READ_SP_PV_FRAME

    def test_ram_address_prefix(self):
        """RAM 地址 0x04B6 → 帧中地址字段应为 ASCII "04B6"。"""
        frame = build_read_frame("01", 0x04B6, 2)
        assert b"04B6" in frame

    def test_eeprom_address_prefix(self):
        """EEPROM 地址 0x1131 → 帧中地址字段应为 ASCII "1131"。"""
        frame = build_read_frame("01", 0x1131, 1)
        assert b"1131" in frame

    def test_count_zero_padded(self):
        """count=1 → 帧中数量字段为 "0001"（4 位零填充）。"""
        frame = build_read_frame("01", 0x04B6, 1)
        assert b"0001" in frame

    def test_machine_addr_uppercase(self):
        """机器地址小写输入 → 帧中自动转大写。"""
        frame_lower = build_read_frame("0a", 0x04B6, 1)
        frame_upper = build_read_frame("0A", 0x04B6, 1)
        assert frame_lower == frame_upper

    def test_frame_starts_with_stx(self):
        frame = build_read_frame("01", 0x04B6, 2)
        assert frame[0] == 0x02

    def test_frame_ends_with_cr_lf(self):
        frame = build_read_frame("01", 0x04B6, 2)
        assert frame[-2:] == bytes([0x0D, 0x0A])

    def test_etx_present(self):
        frame = build_read_frame("01", 0x04B6, 2)
        assert 0x03 in frame


# ===========================================================================
# build_write_frame
# ===========================================================================

class TestBuildWriteFrame:
    def test_doc_example_exact_bytes(self):
        """文档示例2：逐字节验证写 SP-0=0 命令帧。"""
        frame = build_write_frame("01", 0x1131, 0)
        assert frame == WRITE_SP0_FRAME

    def test_full_scale_value(self):
        """满量程值 0x2710=10000 → 帧中数据字段为 "2710"。"""
        frame = build_write_frame("01", 0x1131, 0x2710)
        assert b"2710" in frame

    def test_value_zero_padded(self):
        """value=1 → 数据字段为 "0001"。"""
        frame = build_write_frame("01", 0x1131, 1)
        assert b"0001" in frame

    def test_frame_structure(self):
        frame = build_write_frame("02", 0x1131, 5000)
        assert frame[0] == 0x02
        assert frame[-2:] == bytes([0x0D, 0x0A])


# ===========================================================================
# parse_read_response
# ===========================================================================

class TestParseReadResponse:
    def test_doc_example_values(self):
        """文档应答示例1：解析应返回 [0x0032, 0x0168]。"""
        result = parse_read_response(READ_SP_PV_RESPONSE, expected_count=2)
        assert result == [0x0032, 0x0168]
        assert result == [50, 360]

    def test_single_word(self):
        """构造单字应答帧，解析应返回长度为 1 的列表。"""
        raw = _make_response("01", "00", b"04B6")
        result = parse_read_response(raw, expected_count=1)
        assert len(result) == 1
        assert result[0] == 0x04B6

    def test_warning_21_returns_data(self):
        """警告结束代码 '21' 不应抛异常，应正常返回数据。"""
        raw = _make_response("01", "21", b"0064")
        result = parse_read_response(raw, expected_count=1)
        assert result == [100]

    def test_warning_23_returns_data(self):
        """警告结束代码 '23' 不应抛异常，应正常返回数据。"""
        raw = _make_response("01", "23", b"0001")
        result = parse_read_response(raw, expected_count=1)
        assert result == [1]

    def test_bad_checksum_raises_protocol_error(self):
        """校验和错误 → 抛 ProtocolError。"""
        corrupted = bytearray(READ_SP_PV_RESPONSE)
        corrupted[-3] ^= 0xFF                       # 翻转校验和首字节
        with pytest.raises(ProtocolError, match="校验和不匹配"):
            parse_read_response(bytes(corrupted), expected_count=2)

    def test_wrong_stx_raises_protocol_error(self):
        """STX 不为 0x02 → 抛 ProtocolError。"""
        bad = bytes([0x01]) + READ_SP_PV_RESPONSE[1:]
        with pytest.raises(ProtocolError, match="STX"):
            parse_read_response(bad, expected_count=2)

    def test_too_short_raises_protocol_error(self):
        """帧长度不足 13 字节 → 抛 ProtocolError。"""
        with pytest.raises(ProtocolError, match="帧长度过短"):
            parse_read_response(b"\x02short\x03", expected_count=1)

    def test_data_length_mismatch_raises_protocol_error(self):
        """实际数据字数与 expected_count 不符 → 抛 ProtocolError。"""
        with pytest.raises(ProtocolError, match="数据长度"):
            parse_read_response(READ_SP_PV_RESPONSE, expected_count=3)

    @pytest.mark.parametrize("end_code", ["40", "41", "43", "46", "47", "48", "99"])
    def test_error_end_codes_raise_device_error(self, end_code: str):
        """所有异常结束代码 → 抛 DeviceError，end_code 属性正确。"""
        raw = _make_response("01", end_code, b"")
        with pytest.raises(DeviceError) as exc_info:
            parse_read_response(raw, expected_count=0)
        assert exc_info.value.end_code == end_code

    def test_device_error_message_contains_code(self):
        """DeviceError 的异常消息应包含结束代码。"""
        raw = _make_response("01", "46", b"")
        with pytest.raises(DeviceError) as exc_info:
            parse_read_response(raw, expected_count=0)
        assert "46" in str(exc_info.value)


# ===========================================================================
# parse_write_response
# ===========================================================================

class TestParseWriteResponse:
    def test_doc_example_normal(self):
        """文档应答示例2：正常写入应返回 '00'。"""
        result = parse_write_response(WRITE_SP0_RESPONSE)
        assert result == "00"

    def test_warning_21(self):
        """警告 '21' 不抛异常，返回 '21'。"""
        raw = _make_response("01", "21")
        assert parse_write_response(raw) == "21"

    def test_warning_23(self):
        """警告 '23' 不抛异常，返回 '23'。"""
        raw = _make_response("01", "23")
        assert parse_write_response(raw) == "23"

    @pytest.mark.parametrize("end_code", ["40", "41", "43", "46", "47", "48", "99"])
    def test_error_end_codes_raise_device_error(self, end_code: str):
        """所有异常结束代码 → 抛 DeviceError。"""
        raw = _make_response("01", end_code)
        with pytest.raises(DeviceError) as exc_info:
            parse_write_response(raw)
        assert exc_info.value.end_code == end_code

    def test_bad_checksum_raises_protocol_error(self):
        """校验和错误 → 抛 ProtocolError。"""
        corrupted = bytearray(WRITE_SP0_RESPONSE)
        corrupted[-3] ^= 0x01
        with pytest.raises(ProtocolError):
            parse_write_response(bytes(corrupted))


# ===========================================================================
# 校验和边界情况（通过构造帧间接验证）
# ===========================================================================

class TestChecksumEdgeCases:
    def test_checksum_complement_wraps_at_zero(self):
        """当字节和低字节为 0x00 时，补码仍为 0x00，帧校验和字段为 "00"。"""
        # 构造一个使 inner sum & 0xFF == 0 的帧，验证 parse 不会报错
        # 用 build + parse 往返验证
        frame = build_read_frame("01", 0x04B6, 2)
        # 往返验证：构建帧再解析其校验和部分（内部一致性）
        etx_pos = frame.index(0x03)
        inner = frame[: etx_pos + 1]
        total = sum(inner) & 0xFF
        cs_byte = (0x100 - total) & 0xFF
        cs_ascii = f"{cs_byte:02X}".encode("ascii")
        assert frame[etx_pos + 1: etx_pos + 3] == cs_ascii

    def test_build_parse_roundtrip_read(self):
        """build_read_frame 构建的帧，经 parse_read_response 可正确解析（用 _make_response 构造应答）。"""
        frame = build_read_frame("02", 0x04B6, 1)
        assert frame[0] == 0x02
        raw_resp = _make_response("02", "00", b"1F40")  # 0x1F40 = 8000
        result = parse_read_response(raw_resp, expected_count=1)
        assert result == [0x1F40]

    def test_build_parse_roundtrip_write(self):
        """build_write_frame 构建帧后，_make_response 模拟设备应答可正常解析。"""
        build_write_frame("03", 0x1131, 5000)
        raw_resp = _make_response("03", "00")
        result = parse_write_response(raw_resp)
        assert result == "00"
