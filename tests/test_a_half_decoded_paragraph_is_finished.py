"""A paragraph that is part plaintext, part ciphertext is decoded word by word.

970 March 2026 bodies held ROT47 in `text`; the decoder cleared 954 and
refused 16. Two shapes, both from production:

- MIXED: an earlier word-level pass decoded some words of a paragraph and
  not others ("y2J&gt;6D@? qC@H? H2D E96 winner, throwing"). Decoding it
  whole turns the plaintext half into ciphertext.
- SHORT: "qJi" -> "By:", "r~}%pr%i" -> "CONTACT:". Correct decodes refused
  on a tie: neither side has marker characters, so density cannot fall.
"""

from src.pipeline.text_cleaning import decode_rot47_segments


def test_short_labels_decode():
    assert decode_rot47_segments("kAmqJik^Am") == "By:"
    assert decode_rot47_segments("kAmr~}%pr%ik^Am") == "CONTACT:"
    assert decode_rot47_segments("kAm'x}i r{p_c_egg%}k^Am") == "VIN: CLA040688TN"
    assert decode_rot47_segments("kAmw6C6 2C6 E9C66 E2<62H2JDik^Am") == (
        "Here are three takeaways:"
    )


def test_the_plaintext_half_is_kept():
    seg = "kA 4=2DDlQAcQm}@CE9 !@:?E’D y2J&gt;6D@? qC@H? H2D E96 winner, throwingk^Am"
    assert decode_rot47_segments(seg) == (
        "North Point’s Jaymeson Brown was the winner, throwing"
    )


def test_numbers_inside_a_mixed_paragraph_decode():
    seg = "kA 4=2DDlQAcQmy2I@? SpillenU=Ejothen singled twice, scored `_ runsk^Am"
    assert (
        decode_rot47_segments(seg)
        == "Jaxon Spillenkothen singled twice, scored 10 runs"
    )


def test_a_wholly_encoded_paragraph_still_decodes_whole():
    assert decode_rot47_segments("kAm%96 4@F?4:= >6E %F6D52Jk^Am") == (
        "The council met Tuesday"
    )


def test_an_orphan_closer_is_decoded_too():
    """Ciphertext ending in `k^Am` whose opener was lost matches no
    paragraph; four March bodies kept one each."""
    text = (
        "kAm%96 4@F?4:= >6E %F6D52Jk^Am "
        "The Knights committed four errors. %96J A=2J uC:52J]k^Am"
    )
    out = decode_rot47_segments(text)
    assert "k^Am" not in out
    assert "The council met Tuesday" in out
    assert "The Knights committed four errors." in out
    assert "They play Friday." in out
