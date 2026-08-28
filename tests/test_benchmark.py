"""The STT benchmark harness: metrics, sample loading and reporting."""

from __future__ import annotations

from pathlib import Path

import pytest

from bob.dev.benchmark import (
    DEFAULT_MODELS,
    ModelReport,
    RunResult,
    character_error_rate,
    format_report,
    load_samples,
    load_wav,
    normalise_greek,
    word_error_rate,
)

from .audio_fixtures import tone, wav_bytes

# -- Greek normalisation ----------------------------------------------------


def test_normalisation_folds_case_and_accents() -> None:
    assert normalise_greek("Άνοιξε ΤΟ Spotify") == normalise_greek("ανοιξε το spotify")


def test_normalisation_drops_punctuation() -> None:
    assert normalise_greek("Άνοιξε, το Spotify!") == "ανοιξε το spotify"


def test_normalisation_collapses_whitespace() -> None:
    assert normalise_greek("  Άνοιξε   το \n Spotify ") == "ανοιξε το spotify"


def test_normalisation_keeps_latin_words_intact() -> None:
    """App names must survive; scoring them away would hide the thing we care about."""
    assert "visual studio code" in normalise_greek("Άνοιξε το Visual Studio Code")


# -- error metrics ----------------------------------------------------------


def test_identical_text_scores_zero() -> None:
    assert word_error_rate("Άνοιξε το Spotify", "άνοιξε το spotify") == 0.0
    assert character_error_rate("Άνοιξε το Spotify", "Άνοιξε το Spotify") == 0.0


def test_one_wrong_word_in_three() -> None:
    assert word_error_rate("Άνοιξε το Spotify", "Άνοιξε το Discord") == pytest.approx(1 / 3)


def test_a_missing_word_counts() -> None:
    assert word_error_rate("Άνοιξε το Spotify", "Άνοιξε Spotify") == pytest.approx(1 / 3)


def test_an_extra_word_counts() -> None:
    assert word_error_rate("Άνοιξε Spotify", "Άνοιξε το Spotify") == pytest.approx(0.5)


def test_completely_wrong_scores_high() -> None:
    assert word_error_rate("Άνοιξε το Spotify", "τίποτα") >= 1.0


def test_empty_hypothesis_scores_one() -> None:
    assert word_error_rate("Άνοιξε το Spotify", "") == 1.0


def test_empty_reference_is_handled() -> None:
    assert word_error_rate("", "") == 0.0
    assert word_error_rate("", "κάτι") == 1.0


def test_character_error_is_finer_grained_than_word_error() -> None:
    """One wrong letter should not score as a whole wrong word."""
    reference = "Άνοιξε το Spotify"
    hypothesis = "Άνοιξε το Spotifu"
    assert character_error_rate(reference, hypothesis) < word_error_rate(reference, hypothesis)


def test_mixed_greek_english_is_scored_sensibly() -> None:
    reference = "Θέλω να κάνουμε update το project"
    assert word_error_rate(reference, "Θέλω να κάνουμε απντέιτ το πρότζεκτ") > 0.0
    assert word_error_rate(reference, reference) == 0.0


# -- sample loading ---------------------------------------------------------


def test_wav_round_trip(tmp_path: Path) -> None:
    pcm = tone(16_000)
    path = tmp_path / "sample.wav"
    path.write_bytes(wav_bytes(pcm))
    loaded, rate = load_wav(path)
    assert rate == 16_000
    assert loaded == pcm


def test_stereo_is_downmixed(tmp_path: Path) -> None:
    mono = tone(1_000)
    stereo = b"".join(mono[i : i + 2] * 2 for i in range(0, len(mono), 2))
    path = tmp_path / "stereo.wav"
    path.write_bytes(wav_bytes(stereo, channels=2))
    loaded, _ = load_wav(path)
    assert len(loaded) == len(mono)


def test_samples_are_paired_with_reference_transcripts(tmp_path: Path) -> None:
    (tmp_path / "one.wav").write_bytes(wav_bytes(tone(16_000)))
    (tmp_path / "one.txt").write_text("Άνοιξε το Spotify", encoding="utf-8")
    (tmp_path / "two.wav").write_bytes(wav_bytes(tone(8_000)))

    samples = load_samples(tmp_path)
    assert [s.name for s in samples] == ["one", "two"]
    assert samples[0].reference == "Άνοιξε το Spotify"
    assert samples[1].reference == ""
    assert samples[0].duration_s == pytest.approx(1.0)


def test_missing_directory_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_samples(tmp_path / "nope")


def test_an_unreadable_sample_is_skipped_not_fatal(tmp_path: Path) -> None:
    (tmp_path / "good.wav").write_bytes(wav_bytes(tone(1_000)))
    (tmp_path / "bad.wav").write_bytes(b"not a wav file at all")
    assert [s.name for s in load_samples(tmp_path)] == ["good"]


# -- reporting --------------------------------------------------------------


def report_with(**kwargs: object) -> ModelReport:
    report = ModelReport(model="large-v3-turbo", device="cuda", compute_type="float16")
    report.load_s = 4.2
    report.runs = [
        RunResult(
            model="large-v3-turbo",
            device="cuda",
            compute_type="float16",
            sample="s1",
            duration_s=2.0,
            transcribe_s=0.5,
            transcript="Άνοιξε το Spotify",
            wer=0.0,
            cer=0.0,
        ),
        RunResult(
            model="large-v3-turbo",
            device="cuda",
            compute_type="float16",
            sample="s2",
            duration_s=4.0,
            transcribe_s=1.5,
            transcript="Τι τρώει τη RAM",
            wer=0.25,
            cer=0.1,
        ),
    ]
    for key, value in kwargs.items():
        setattr(report, key, value)
    return report


def test_real_time_factor_is_computed() -> None:
    assert report_with().runs[0].rtf == pytest.approx(0.25)


def test_mean_metrics_average_the_runs() -> None:
    report = report_with()
    assert report.mean_rtf == pytest.approx((0.25 + 0.375) / 2)
    assert report.mean_wer == pytest.approx(0.125)


def test_metrics_are_absent_without_references() -> None:
    report = report_with()
    for run in report.runs:
        run.wer = None
        run.cer = None
    assert report.mean_wer is None


def test_report_renders_the_key_columns() -> None:
    text = format_report([report_with()], verbose=False)
    for expected in ("large-v3-turbo", "cuda", "float16", "RTF", "WER"):
        assert expected in text


def test_report_includes_transcripts_when_verbose() -> None:
    assert "Άνοιξε το Spotify" in format_report([report_with()], verbose=True)


def test_report_shows_a_failed_model_without_crashing() -> None:
    failed = ModelReport(model="large-v3", device="cuda", compute_type="float16")
    failed.error = "out of memory"
    text = format_report([failed], verbose=True)
    assert "FAILED" in text and "out of memory" in text


def test_report_explains_missing_references() -> None:
    report = report_with()
    for run in report.runs:
        run.wer = None
        run.cer = None
    assert "No reference transcripts" in format_report([report], verbose=False)


def test_default_candidates_cover_the_useful_range() -> None:
    assert "large-v3-turbo" in DEFAULT_MODELS
    assert "large-v3" in DEFAULT_MODELS
    assert "medium" in DEFAULT_MODELS
