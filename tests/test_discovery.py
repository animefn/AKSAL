"""Finding the song: databases, lyric hints, and the reference track.

Every service involved here fails in a way that LOOKS like success, which is
what these tests are really about. Nothing touches the network -- the parsers
and the verification rules are pure functions over payloads, which is the point
of separating them.
"""
from __future__ import annotations

import pytest

from aksal import catalog, fetch, lyrics


# --- catalog: parsing ---------------------------------------------------------

@pytest.mark.parametrize("text,title,artist", [
    ('"Narrative" by Tsukuyomi', "Narrative", "Tsukuyomi"),
    ('&quot;Narrative&quot; by Tsukuyomi', "Narrative", "Tsukuyomi"),
    ('"TRUTH" by Rin (eps 1-13)', "TRUTH", "Rin"),
    ("Plain Title by Someone", "Plain Title", "Someone"),
    ("Just A Title", "Just A Title", ""),
])
def test_theme_text_is_split_into_title_and_artist(text, title, artist):
    got_title, got_artist, _eps = catalog.parse_theme_text(text)
    assert (got_title, got_artist) == (title, artist)


def test_episode_range_is_kept_when_present():
    _t, _a, eps = catalog.parse_theme_text('"TRUTH" by Rin (eps 1-13)')
    assert "1-13" in eps


@pytest.mark.parametrize("raw,kind,seq", [
    ("Opening Theme", "OP", ""), ("OP2", "OP", "2"),
    ("Ending Theme", "ED", ""), ("ED3", "ED", "3"),
])
def test_theme_kind_and_sequence(raw, kind, seq):
    assert catalog.split_kind(raw) == (kind, seq)


def test_animethemes_payload_keeps_the_series_it_matched():
    """The single most important field. AnimeThemes' fuzzy search answers a
    query for one show with another show's songs and flags nothing, so the
    series name has to travel with every result."""
    payload = {"anime": [{"name": "Duel Masters VSR", "year": 2015,
                          "animethemes": [{"type": "OP", "sequence": 1,
                                           "song": {"title": "Luv it!!",
                                                    "artists": []}}]}]}
    themes = catalog.parse_animethemes(payload)
    assert themes[0].series == "Duel Masters VSR"
    assert themes[0].title == "Luv it!!"


def test_a_wrong_series_scores_below_a_right_one():
    right = catalog.series_score("Cross Fight B-Daman eS", "Cross Fight B-Daman")
    wrong = catalog.series_score("Cross Fight B-Daman eS", "Cross Game")
    assert right > wrong
    assert wrong < 0.6


def test_ranking_puts_the_closest_series_first():
    themes = [catalog.Theme(kind="OP", title="Summer Rain", series="Cross Game"),
              catalog.Theme(kind="OP", title="TRUTH", series="Cross Fight B-Daman")]
    assert catalog.rank(themes, "Cross Fight B-Daman")[0].title == "TRUTH"


def test_dedupe_merges_an_artist_in_from_a_second_database():
    themes = [catalog.Theme(kind="OP", title="TRUTH", source="animethemes"),
              catalog.Theme(kind="OP", title="TRUTH", artist="Rin", source="ann")]
    out = catalog.dedupe(themes)
    assert len(out) == 1
    assert out[0].artist == "Rin"


# --- LRCLIB verification ------------------------------------------------------

def hit(name, artist, duration):
    return {"trackName": name, "artistName": artist, "duration": duration,
            "syncedLyrics": "[00:01.00] x"}


def test_a_same_titled_song_by_another_artist_is_rejected():
    """Not hypothetical: searching "Ray of light" offers Madonna at 250.4s
    against the real track's 242s -- inside any tolerance loose enough to accept
    a genuine match. The artist is what separates them."""
    results = [hit("Ray Of Light", "Madonna", 250.4)]
    assert lyrics.verify_lrclib(results, 242.0, "OUTER-TRIBE") is None


def test_a_matching_artist_and_duration_is_accepted():
    results = [hit("Narrative", "Tsukuyomi", 198.0)]
    assert lyrics.verify_lrclib(results, 194.3, "Tsukuyomi") is not None


def test_without_an_artist_the_duration_must_be_tight():
    """No artist is 'unknown', not 'anything goes'."""
    assert lyrics.verify_lrclib([hit("X", "Whoever", 250.4)], 242.0, "") is None
    assert lyrics.verify_lrclib([hit("X", "Whoever", 196.0)], 194.3, "") is not None


def test_nothing_is_returned_when_the_duration_is_unknown():
    """Unverifiable means unused, never 'probably fine'."""
    assert lyrics.verify_lrclib([hit("X", "Y", 200.0)], None, "Y") is None


def test_unsynced_results_are_ignored():
    plain = {"trackName": "X", "artistName": "Y", "duration": 194.0,
             "plainLyrics": "words"}
    assert lyrics.verify_lrclib([plain], 194.0, "Y") is None


def test_a_romanised_artist_still_matches_a_japanese_one():
    """LRCLIB files Japanese artists romanised far more often than not."""
    assert "tsukiyomi" in lyrics.artist_keys("月詠み") or \
           "tsukuyomi" in lyrics.artist_keys("月詠み")


# --- pairing LRCLIB timings to another sheet's lines --------------------------

def test_timings_are_matched_by_TEXT_not_by_index():
    """The two sheets disagree about where lines break, so pairing by position
    would put one sheet's timing on the other's words and be wrong from the
    first mismatch on."""
    lines = ["alpha", "MISSING FROM LRC", "beta"]
    timings = [(1.0, "alpha"), (5.0, "beta")]
    assert lyrics.match_timings(lines, timings) == {0: 1.0, 2: 5.0}


def test_a_line_absent_from_the_timings_simply_goes_unanchored():
    got = lyrics.match_timings(["one", "two"], [(1.0, "one")])
    assert got == {0: 1.0}


def test_matching_is_monotonic_so_a_refrain_cannot_pull_a_line_backwards():
    lines = ["hook", "verse", "hook"]
    timings = [(1.0, "hook"), (5.0, "verse"), (9.0, "hook")]
    assert lyrics.match_timings(lines, timings) == {0: 1.0, 1: 5.0, 2: 9.0}


def test_punctuation_and_case_do_not_prevent_a_match():
    assert lyrics.match_timings(["Hello, world!"], [(2.0, "hello world")]) == {0: 2.0}


# --- fetch --------------------------------------------------------------------

def test_search_output_is_parsed_and_junk_lines_ignored():
    out = ('{"id":"abc","title":"T","uploader":"U","duration":200}\n'
           'WARNING: something\n'
           '{"id":"def","title":"T2","uploader":"U2","duration":190}\n')
    got = fetch.parse_search(out)
    assert [c.ident for c in got] == ["abc", "def"]
    assert got[0].duration == 200


def test_implausible_durations_are_dropped():
    cands = [fetch.Candidate("a", "clip", "", 12),
             fetch.Candidate("b", "single", "", 200),
             fetch.Candidate("c", "concert", "", 4000)]
    assert [c.ident for c in fetch.plausible(cands)] == ["b"]


def test_candidates_sort_towards_a_wanted_duration():
    cands = [fetch.Candidate("far", "", "", 300), fetch.Candidate("near", "", "", 196)]
    assert fetch.plausible(cands, want=194.0)[0].ident == "near"


def test_the_anime_name_is_used_when_the_artist_is_unknown():
    """A bare "TRUTH" finds a rapper and a news clip; the series name fixes it,
    and AnimeThemes very often has no artist."""
    assert fetch.normalise_query("TRUTH", "", "Cross Fight B-Daman") == \
        "Cross Fight B-Daman TRUTH"
    assert fetch.normalise_query("TRUTH", "Rin", "Cross Fight B-Daman") == "Rin TRUTH"


def test_search_invokes_the_resolved_ytdlp_binary(monkeypatch):
    seen = []
    monkeypatch.setattr(fetch, "require_ytdlp", lambda: "/opt/aksal/yt-dlp")
    monkeypatch.setattr(fetch, "_run",
                        lambda args, timeout=0: seen.append(args) or "")
    fetch.search("a song")
    assert seen[0][0] == "/opt/aksal/yt-dlp"


def test_download_invokes_the_resolved_ytdlp_binary(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(fetch, "require_ytdlp", lambda: "/opt/aksal/yt-dlp")

    def fake_run(args, timeout=0):
        seen.append(args)
        (tmp_path / "reference.m4a").write_bytes(b"audio")
        return ""

    monkeypatch.setattr(fetch, "_run", fake_run)
    assert fetch.download_audio("https://example.test/song",
                                tmp_path / "reference.m4a").exists()
    assert seen[0][0] == "/opt/aksal/yt-dlp"
