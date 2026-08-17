import numpy as np
import pytest

from aksal import artifacts, ass, model_spec, readings, selection_state


def test_emission_key_tracks_exact_waveform_and_model():
    audio = np.array([0.0, 0.5, -0.25], dtype=np.float32)
    same = artifacts.emissions_key("model@a", 320, audio.copy())
    assert same == artifacts.emissions_key("model@a", 320, audio.copy())
    changed = audio.copy()
    changed[1] += 0.001
    assert same != artifacts.emissions_key("model@a", 320, changed)
    assert same != artifacts.emissions_key("model@b", 320, audio)


def test_local_model_decision_identity_changes_with_weights(tmp_path):
    model = tmp_path / "model.pt"
    model.write_bytes(b"first")
    before = model_spec.decision_identity(f"hiragana-asr:{model}")
    model.write_bytes(b"different weights")
    assert before != model_spec.decision_identity(f"hiragana-asr:{model}")


def test_manual_table_edits_survive_generated_rewrites(tmp_path):
    table = tmp_path / "readings.tsv"
    state_path = tmp_path / "selections.json"
    generated = [(7, "", "未だ", "まだ")]
    state = selection_state.load(state_path)
    readings.write_table(table, generated)
    selection_state.update_table_baseline(state, generated)
    selection_state.save(state_path, state)

    readings.write_table(table, [(7, "", "未だ", "いまだ")])
    state = selection_state.load(state_path)
    manual = selection_state.manual_overrides(table, state)
    assert manual.get_for(7, "未だ") == "いまだ"

    selection_state.update_table_baseline(
        state, [(7, "", "未だ", "いまだ")], manual)
    selection_state.save(state_path, state)
    assert selection_state.manual_overrides(
        table, selection_state.load(state_path)).get_for(7, "未だ") == "いまだ"


def test_duplicate_surfaces_have_independent_manual_readings(tmp_path):
    table = tmp_path / "readings.tsv"
    state = selection_state.load(tmp_path / "missing.json")
    generated = [(3, "", "未だ", "まだ"), (9, "", "未だ", "まだ")]
    readings.write_table(table, generated)
    selection_state.update_table_baseline(state, generated)
    readings.write_table(
        table, [(3, "", "未だ", "いまだ"), (9, "", "未だ", "まだ")])
    manual = selection_state.manual_overrides(table, state)
    assert manual.get_for(3, "未だ") == "いまだ"
    assert manual.get_for(9, "未だ") is None


def test_invalid_manual_reading_is_rejected_before_alignment(tmp_path):
    table = tmp_path / "readings.tsv"
    state = selection_state.load(tmp_path / "missing.json")
    generated = [(1, "", "未だ", "まだ")]
    readings.write_table(table, generated)
    selection_state.update_table_baseline(state, generated)
    readings.write_table(table, [(1, "", "未だ", "not kana")])
    with pytest.raises(SystemExit, match="invalid reading"):
        selection_state.manual_overrides(table, state)


def test_ass_event_format_can_be_reordered(tmp_path):
    path = tmp_path / "input.ass"
    path.write_text(
        "[Events]\n"
        "Format: Start, End, Text, Style, Layer, Effect\n"
        "Dialogue: 0:00:01.00,0:00:02.00,空,Alt,2,aksal-line:8\n",
        encoding="utf-8",
    )
    event = ass.read(path)[0]
    assert event.text == "空"
    assert event.style == "Alt"
    assert event.layer == "2"
    assert event.effect == "aksal-line:8"


def test_generated_ass_does_not_need_an_effect_value(tmp_path):
    path = tmp_path / "lines.ass"
    ass.write(path, [ass.Event(1.0, 2.0, "空")], [ass.STYLE_JP])
    event = ass.read(path)[0]
    assert event.effect == ""


def test_ass_timestamp_rounding_carries_into_next_minute():
    assert ass.ts(59.999) == "0:01:00.00"


def test_dense_karaoke_never_extends_past_the_event():
    text = ass.karaoke_text(list("abcdef"), [0.0] * 6, 0.0, 0.03)
    assert sum(ass.karaoke_durations(text)) == 3
