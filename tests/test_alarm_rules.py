from rka_desktop.core.alarm_rules import (
    alarm_text_from_word,
    decode_alarm_word,
    decode_interlock_word,
    has_active_interlock,
    has_interlock_alarm,
    interlock_text_from_word,
    is_interlock_resettable,
)


def test_decode_alarm_word_returns_configured_definitions():
    active = decode_alarm_word(0x000A)

    assert [alarm.code for alarm in active] == ["ALM-0002", "ALM-0008"]
    assert has_interlock_alarm(0x000A) is True
    assert "超压报警" in alarm_text_from_word(0x000A)


def test_decode_alarm_word_generates_unknown_alarm_definition():
    active = decode_alarm_word(0x0100)

    assert len(active) == 1
    assert active[0].code == "ALM-0100"
    assert active[0].interlock is True
    assert "未定义报警位" in active[0].message


def test_decode_interlock_word_returns_configured_definitions():
    active = decode_interlock_word(0x000A)

    assert [item.code for item in active] == ["ILK-0002", "ILK-0008"]
    assert has_active_interlock(0x000A) is True
    assert "超压联锁" in interlock_text_from_word(0x000A)
    assert is_interlock_resettable(0x000A) is True


def test_estop_interlock_is_not_resettable():
    active = decode_interlock_word(0x0010)

    assert len(active) == 1
    assert active[0].code == "ILK-0010"
    assert is_interlock_resettable(0x0010) is False
