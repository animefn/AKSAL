"""Lyrics input: file, Uta-Net page, LRCLIB lookup.

Parsers are pure functions over text, so none of this touches the network.
Fixture text is invented, not real lyrics.
"""
from __future__ import annotations

import pytest

from aksal import lyrics


# --- clean_lines --------------------------------------------------------------

def test_interior_blank_lines_are_kept():
    """Blank lines mark verse boundaries, and line numbers are what the
    readings table and the user's corrections key on."""
    out = lyrics.clean_lines("いち\n\nに\n\n\nさん")
    assert out == ["いち", "", "に", "", "", "さん"]


def test_edge_blank_lines_are_dropped():
    assert lyrics.clean_lines("\n\nいち\nに\n\n\n") == ["いち", "に"]


def test_full_width_spaces_become_normal_ones():
    assert lyrics.clean_lines("いち　に") == ["いち に"]


def test_html_entities_are_unescaped():
    assert lyrics.clean_lines("A &amp; B") == ["A & B"]


def test_crlf_and_cr_are_normalised():
    assert lyrics.clean_lines("いち\r\nに\rさん") == ["いち", "に", "さん"]


# --- LRC ----------------------------------------------------------------------

def test_parse_lrc_extracts_text_and_timings():
    lines, timings = lyrics.parse_lrc(
        "[00:01.00]いち\n[00:12.34]に\n[01:05.50]さん")
    assert lines == ["いち", "に", "さん"]
    assert [round(t, 2) for t, _ in timings] == [1.0, 12.34, 65.5]


def test_parse_lrc_handles_a_line_with_several_stamps():
    """A repeated refrain is stored once with multiple timestamps."""
    _, timings = lyrics.parse_lrc("[00:10.00][01:20.00]リフレイン")
    assert [round(t, 2) for t, _ in timings] == [10.0, 80.0]
    assert all(text == "リフレイン" for _, text in timings)


def test_parse_lrc_sorts_timings():
    _, timings = lyrics.parse_lrc("[01:00.00]あと\n[00:05.00]さき")
    assert [t for t, _ in timings] == sorted(t for t, _ in timings)


def test_plain_text_passes_through_untouched():
    lines, timings = lyrics.parse_lrc("いち\nに\nさん")
    assert lines == ["いち", "に", "さん"]
    assert timings == []


def test_lrc_metadata_tags_are_not_mistaken_for_timings():
    lines, timings = lyrics.parse_lrc("[ar:歌手]\n[00:01.00]いち")
    assert timings == [(1.0, "いち")]
    assert "いち" in lines


def test_lrc_accepts_colon_as_fraction_separator():
    _, timings = lyrics.parse_lrc("[00:01:50]いち")
    assert timings[0][0] == pytest.approx(1.5)


# --- Uta-Net ------------------------------------------------------------------

UTANET_PAGE = """<html><head>
<script type="application/ld+json">{"@type":"WebPage","name":"歌手 曲 歌詞 - 歌ネット"}</script>
<script type="application/ld+json">
{"@type":"MusicComposition","name":"きょくめい","byArtist":{"@type":"Person","name":"かしゅ"}}
</script>
</head><body>
<h2>きょくめい</h2>
<div itemprop="text">いちぎょうめ<br>にぎょうめ<br><br>さんぎょうめ</div>
</body></html>"""


def test_utanet_extracts_lines_from_the_microdata_container():
    r = lyrics.parse_utanet(UTANET_PAGE)
    assert r.lines == ["いちぎょうめ", "にぎょうめ", "", "さんぎょうめ"]
    assert r.source == "uta-net"


def test_utanet_takes_the_song_name_not_the_page_title():
    """The first ld+json `name` is the WebPage's browser title. Taking it gives
    '<artist> <song> 歌詞 - 歌ネット' instead of the song."""
    r = lyrics.parse_utanet(UTANET_PAGE)
    assert r.title == "きょくめい"
    assert r.artist == "かしゅ"


def test_utanet_falls_back_to_the_kashi_area_id():
    page = '<div id="kashi_area">いち<br>に</div>'
    assert lyrics.parse_utanet(page).lines == ["いち", "に"]


def test_utanet_falls_back_to_h2_when_no_microdata():
    page = '<h2>きょくめい</h2><div id="kashi_area">いち</div>'
    assert lyrics.parse_utanet(page).title == "きょくめい"


def test_utanet_raises_clearly_when_markup_changed():
    with pytest.raises(ValueError, match="Uta-Net"):
        lyrics.parse_utanet("<html><body>nothing here</body></html>")


def test_utanet_strips_nested_tags():
    page = '<div itemprop="text">いち<span class="x">に</span><br>さん</div>'
    assert lyrics.parse_utanet(page).lines == ["いちに", "さん"]


# --- LRCLIB result selection --------------------------------------------------

def test_synced_beats_plain():
    chosen = lyrics.pick_lrclib([
        {"trackName": "a", "plainLyrics": "x" * 500},
        {"trackName": "b", "syncedLyrics": "[00:01.00]x"},
    ], "q")
    assert chosen["trackName"] == "b"


def test_instrumental_entries_are_rejected():
    assert lyrics.pick_lrclib(
        [{"trackName": "a", "instrumental": True, "plainLyrics": "x"}], "q") is None


def test_empty_results_return_none():
    assert lyrics.pick_lrclib([], "q") is None
    assert lyrics.pick_lrclib([{"trackName": "a"}], "q") is None


def test_artist_is_not_used_to_filter():
    """LRCLIB often stores a romanised artist where the query is Japanese, so
    filtering on artist silently drops exactly the songs we want."""
    chosen = lyrics.pick_lrclib(
        [{"trackName": "朔日", "artistName": "Tsukuyomi",
          "syncedLyrics": "[00:01.00]x"}], "朔日 月詠み")
    assert chosen is not None


def test_longer_lyrics_win_among_equally_synced_entries():
    chosen = lyrics.pick_lrclib([
        {"trackName": "short", "syncedLyrics": "[00:01.00]x"},
        {"trackName": "long", "syncedLyrics": "[00:01.00]" + "x" * 200},
    ], "q")
    assert chosen["trackName"] == "long"


# --- resolve dispatch ---------------------------------------------------------

def test_resolve_reads_a_local_file(tmp_path):
    p = tmp_path / "l.txt"
    p.write_text("いち\nに\n", encoding="utf-8")
    r = lyrics.resolve(str(p), log=lambda *a, **k: None)
    assert r.lines == ["いち", "に"]


def test_resolve_reads_an_lrc_file_with_its_timings(tmp_path):
    p = tmp_path / "l.lrc"
    p.write_text("[00:02.50]いち\n", encoding="utf-8")
    r = lyrics.resolve(str(p), log=lambda *a, **k: None)
    assert r.lines == ["いち"]
    assert r.timings[0][0] == pytest.approx(2.5)


def test_resolve_writes_a_cache_you_can_edit(tmp_path):
    src = tmp_path / "l.txt"
    src.write_text("いち\n", encoding="utf-8")
    cache = tmp_path / "work" / "lyrics.txt"
    lyrics.resolve(str(src), cache=cache, log=lambda *a, **k: None)
    assert cache.read_text(encoding="utf-8").strip() == "いち"


def test_cache_wins_over_refetching(tmp_path):
    """Hand-corrected lyrics must not be silently overwritten."""
    cache = tmp_path / "lyrics.txt"
    cache.write_text("corrected\n", encoding="utf-8")
    r = lyrics.resolve("https://www.uta-net.com/song/1/", cache=cache,
                       log=lambda *a, **k: None)
    assert r.lines == ["corrected"]


def test_refresh_bypasses_the_cache(tmp_path, monkeypatch):
    cache = tmp_path / "lyrics.txt"
    cache.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(lyrics, "fetch_utanet",
                        lambda url: lyrics.LyricsResult(lines=["new"],
                                                        source="uta-net"))
    r = lyrics.resolve("https://www.uta-net.com/song/1/", cache=cache,
                       refresh=True, log=lambda *a, **k: None)
    assert r.lines == ["new"]
    assert cache.read_text(encoding="utf-8").strip() == "new"


def test_unsupported_url_is_rejected_by_name(tmp_path):
    with pytest.raises(ValueError, match="no parser"):
        lyrics.resolve("https://example.com/song", log=lambda *a, **k: None)


def test_non_utanet_url_rejected_by_fetch_utanet():
    with pytest.raises(ValueError, match="not a Uta-Net"):
        lyrics.fetch_utanet("https://example.com/x")
