"""Microphone selection, level metering and the dead-microphone detector."""

from __future__ import annotations

from bob.audio.devices import (
    AudioDevice,
    describe_devices,
    same_named,
    select_device,
)
from bob.audio.levels import LevelConfig, LevelMeter

from .audio_fixtures import FRAME_MS, silence, tone

WASAPI = "Windows WASAPI"
MME = "MME"


def devices() -> list[AudioDevice]:
    """A realistic Windows enumeration: one device seen through several APIs."""
    return [
        AudioDevice(0, "Microphone Array", 2, 48000.0, MME, is_default=True),
        AudioDevice(1, "Blue Yeti", 1, 44100.0, MME),
        AudioDevice(5, "Microphone Array", 2, 48000.0, WASAPI),
        AudioDevice(6, "Blue Yeti", 1, 44100.0, WASAPI),
        AudioDevice(9, "Headset", 1, 16000.0, "Windows DirectSound"),
    ]


# -- selection --------------------------------------------------------------


def test_no_devices_selects_nothing() -> None:
    assert select_device([], None) is None
    assert select_device([], "Blue Yeti") is None


def test_default_device_keeps_its_identity_but_upgrades_the_host_api() -> None:
    """The Windows default is usually the MME entry; MME costs ~100ms latency."""
    chosen = select_device(devices(), None)
    assert chosen is not None
    assert chosen.name == "Microphone Array"
    assert chosen.host_api == WASAPI


def test_configured_name_is_honoured() -> None:
    chosen = select_device(devices(), "Blue Yeti")
    assert chosen is not None and chosen.name == "Blue Yeti"


def test_name_matching_is_case_insensitive_and_partial() -> None:
    for query in ("blue yeti", "YETI", "Blue"):
        chosen = select_device(devices(), query)
        assert chosen is not None and chosen.name == "Blue Yeti", query


def test_named_selection_also_prefers_the_best_host_api() -> None:
    chosen = select_device(devices(), "Blue Yeti")
    assert chosen is not None and chosen.host_api == WASAPI


def test_unknown_name_falls_back_to_the_default() -> None:
    """A renamed or unplugged microphone must not stop B.O.B. from listening."""
    chosen = select_device(devices(), "Nonexistent Microphone")
    assert chosen is not None and chosen.name == "Microphone Array"


def test_selection_without_a_default_still_picks_something() -> None:
    without = [d for d in devices() if not d.is_default]
    chosen = select_device(without, None)
    assert chosen is not None
    assert chosen.host_api_rank <= AudioDevice(0, "x", 1, 16000, MME).host_api_rank


def test_host_api_ranking_prefers_low_latency_apis() -> None:
    ranks = {
        api: AudioDevice(0, "x", 1, 16000.0, api).host_api_rank
        for api in (WASAPI, "Windows DirectSound", MME, "Something Else")
    }
    assert ranks[WASAPI] < ranks["Windows DirectSound"] < ranks[MME]
    assert ranks[MME] < ranks["Something Else"]


def test_same_named_groups_a_device_across_apis() -> None:
    assert len(same_named(devices(), "Blue Yeti")) == 2


def test_device_label_includes_the_host_api() -> None:
    assert AudioDevice(0, "Blue Yeti", 1, 44100.0, WASAPI).label == f"Blue Yeti ({WASAPI})"


def test_describe_devices_is_readable_and_warns_against_indices() -> None:
    text = describe_devices(devices())
    assert "Blue Yeti" in text
    assert "not an index" in text


def test_describe_devices_handles_an_empty_list() -> None:
    assert "No input devices" in describe_devices([])


# -- level meter ------------------------------------------------------------


def test_level_rises_with_signal_and_falls_with_silence() -> None:
    meter = LevelMeter(LevelConfig(update_hz=1000))
    now = 0.0
    for _ in range(30):
        meter.push(tone(amplitude=0.4), now=now, duration_s=FRAME_MS / 1000)
        now += FRAME_MS / 1000
    loud = meter.level
    assert loud > 0.4

    for _ in range(60):
        meter.push(silence(), now=now, duration_s=FRAME_MS / 1000)
        now += FRAME_MS / 1000
    assert meter.level < loud * 0.25


def test_level_stays_within_range() -> None:
    meter = LevelMeter(LevelConfig(update_hz=1000))
    for index in range(50):
        level = meter.push(tone(amplitude=1.0), now=index * 0.032, duration_s=0.032)
        assert level is None or 0.0 <= level <= 1.0


def test_updates_are_rate_limited_for_the_ui() -> None:
    """Publishing per audio frame would be ~31 events/s of pointless churn."""
    meter = LevelMeter(LevelConfig(update_hz=10.0))
    emitted = sum(
        1
        for index in range(100)
        if meter.push(tone(), now=index * 0.032, duration_s=0.032) is not None
    )
    # 100 frames = 3.2 s of audio; at 10 Hz that is roughly 32 updates.
    assert 25 <= emitted <= 40


def test_a_higher_rate_emits_more_often() -> None:
    def count(hz: float) -> int:
        meter = LevelMeter(LevelConfig(update_hz=hz))
        return sum(
            1 for i in range(100) if meter.push(tone(), now=i * 0.032, duration_s=0.032) is not None
        )

    assert count(30.0) > count(5.0)


def test_attack_is_faster_than_release() -> None:
    """The orb should jump with the voice and settle gently, like an ear."""
    meter = LevelMeter(LevelConfig(update_hz=1000, attack_s=0.02, release_s=0.4))
    meter.push(tone(amplitude=0.6), now=0.0, duration_s=0.032)
    after_one_loud_frame = meter.level
    meter.push(silence(), now=0.032, duration_s=0.032)
    dropped = after_one_loud_frame - meter.level
    assert after_one_loud_frame > dropped


# -- dead microphone --------------------------------------------------------


def test_sustained_digital_silence_raises_the_alarm() -> None:
    """Windows revokes microphone access by delivering zeros, not an error."""
    meter = LevelMeter(LevelConfig(update_hz=1000, silence_alarm_s=1.0))
    now = 0.0
    for _ in range(40):  # 1.28 s
        meter.push(silence(), now=now, duration_s=0.032)
        now += 0.032
    assert meter.check_dead_microphone() is True


def test_the_alarm_fires_only_once() -> None:
    meter = LevelMeter(LevelConfig(update_hz=1000, silence_alarm_s=0.5))
    for index in range(40):
        meter.push(silence(), now=index * 0.032, duration_s=0.032)
    assert meter.check_dead_microphone() is True
    assert meter.check_dead_microphone() is False


def test_quiet_room_tone_is_not_a_dead_microphone() -> None:
    """Real silence still has dither; only digital zero means broken."""
    from .audio_fixtures import noise

    meter = LevelMeter(LevelConfig(update_hz=1000, silence_alarm_s=0.5))
    for index in range(60):
        meter.push(noise(amplitude=0.002), now=index * 0.032, duration_s=0.032)
    assert meter.check_dead_microphone() is False


def test_signal_clears_the_silence_timer() -> None:
    meter = LevelMeter(LevelConfig(update_hz=1000, silence_alarm_s=1.0))
    for index in range(20):
        meter.push(silence(), now=index * 0.032, duration_s=0.032)
    meter.push(tone(), now=0.7, duration_s=0.032)
    assert meter.silent_seconds == 0.0


def test_reset_clears_everything() -> None:
    meter = LevelMeter(LevelConfig(update_hz=1000))
    meter.push(tone(), now=0.0, duration_s=0.032)
    meter.reset()
    assert meter.level == 0.0
    assert meter.silent_seconds == 0.0
