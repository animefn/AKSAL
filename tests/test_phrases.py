"""Lexicalised phrases: sequences UniDic splits that are really one word.

UniDic emits short unit words -- it segments grammar, and grammatically 共に is
共 + に. That is correct as grammar and wrong as a word: every dictionary lists
these as single entries.

This is a convention, not a correctness fix, so what the tests pin is the
BOUNDARY of the convention: which things join, which deliberately do not, and
that joining never touches the timing.
"""
from aksal import moras, readings


def words(text: str) -> list[str]:
    return [s for s, _k in readings.analyse_words(readings.normalise_surface(text))]


def reading(text: str) -> str:
    return " ".join(k for _s, k in
                    readings.analyse_words(readings.normalise_surface(text)))


def test_indefinites_join():
    assert words("誰か") == ["誰か"]
    assert words("いつか") == ["いつか"]
    assert words("どこか") == ["どこか"]


def test_a_noun_plus_a_particle_does_not_join():
    """The distinction a part-of-speech rule cannot make.

    君も and どれも are grammatically identical to いつも and どこか -- pronoun
    plus particle -- but they are two words, not one. Only a lexicon separates
    them, which is why this is a list and not a rule. An earlier attempt at the
    rule cost five new run-ons.
    """
    assert words("君も") == ["君", "も"]
    assert words("どれも") == ["どれ", "も"]
    assert words("どこも") == ["どこ", "も"]


def test_何_keeps_its_sung_reading_when_joined():
    """Concatenating the parts' readings would be wrong here.

    The analyser reads 何 as ナン, so 何か and 何も would come out nanka and
    nanmo. Sung they are nanika and nanimo, so the table carries an explicit
    reading for exactly those two.
    """
    assert reading("何か") == "なにか"
    assert reading("何も") == "なにも"


def test_adverbs_written_as_particle_strings_join():
    assert words("どうにか") == ["どうにか"]
    assert words("そんなに") == ["そんなに"]
    assert words("どんなに") == ["どんなに"]


def test_adverbial_ni_forms():
    assert words("共に") == ["共に"]
    assert words("すぐに") == ["すぐに"]
    # Left split on purpose: these read naturally as a noun plus に.
    assert words("本当に") == ["本当", "に"]
    assert words("同時に") == ["同時", "に"]


def test_conjunctions_join():
    # Split, these come out "da tte" / "da kedo" / "da kara".
    assert words("だって") == ["だって"]
    assert words("だけど") == ["だけど"]
    assert words("だから") == ["だから"]


def test_an_explicit_space_still_stops_a_join():
    """The writer's spacing outranks the list.

    Joining runs inside a chunk, and a space in the lyric sheet is a hard
    boundary -- sheets use it to mark phrasing, and that intent should not be
    overridden by a lexicon.
    """
    assert words("共 に") == ["共", "に"]


def test_joining_never_changes_the_mora_count():
    """Phrases change where the spaces go, never what is sung.

    Word boundaries move; the syllables and therefore the \\k values do not.
    Verified across the corpus at zero lines changed, and pinned here.
    """
    for text in ("誰か", "どうにか", "共に", "だから", "何も"):
        joined = readings.analyse_words(readings.normalise_surface(text))
        saved = readings.PHRASES
        readings.PHRASES = {}
        try:
            split = readings.analyse_words(readings.normalise_surface(text))
        finally:
            readings.PHRASES = saved
        assert (len(moras.split("".join(k for _s, k in joined)))
                == len(moras.split("".join(k for _s, k in split)))), text


def test_the_list_can_be_extended_and_trimmed(tmp_path, monkeypatch):
    """Which sequences are one word is a convention, so it must be editable.

    The built-in list leaves 本当に split and someone will reasonably disagree.
    A DELETE row removes a built-in entry, so the file can trim as well as
    extend -- otherwise a user who dislikes one of my choices has no recourse
    short of editing the source.
    """
    from aksal import tools

    rows = [
        "# surface<TAB>reading (blank means concatenate the parts)",
        "本当に\t",
        "誰か\tDELETE",
    ]
    (tmp_path / "aksal.phrases.tsv").write_text("\n".join(rows) + "\n",
                                                encoding="utf-8")
    monkeypatch.setattr(tools, "home", lambda: tmp_path)
    monkeypatch.setattr(readings, "_USER_PHRASES_LOADED", False)
    saved = dict(readings.PHRASES)
    try:
        readings.load_user_phrases()
        assert words("本当に") == ["本当に"]
        assert words("誰か") == ["誰", "か"]
    finally:
        readings.PHRASES.clear()
        readings.PHRASES.update(saved)
        readings._USER_PHRASES_LOADED = True
