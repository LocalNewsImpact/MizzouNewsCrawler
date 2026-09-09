"""The label order is the model's class ids, and it must not move.

`_load_pt_classifier` builds the model's label map by position:

    label2id = {label: idx for idx, label in enumerate(
        CRITICAL_INFORMATION_NEEDS_LABELS)}

so index 0 means "Civic Life" because that is what index 0 meant when
`productionmodel.pt` was trained. The checkpoint's final layer is tied to
those positions.

Reordering the list does not raise, does not fail a build and does not
show up in any output that anybody reads. It silently relabels every
prediction -- Sports arriving as Health -- and the only symptom is that
the corpus slowly stops making sense.

The list now comes from lnic-contracts, which is right: three services
compare these strings and a rename in one is a silent mismatch in the
others. But it also means the order can now be changed in a different
repository, by somebody who cannot see this file. So it is pinned here
too, against the checkpoint rather than against the contract.
"""

from lnic_contracts import cin_labels

from src.ml.article_classifier import CRITICAL_INFORMATION_NEEDS_LABELS


def test_the_order_is_what_the_checkpoint_was_trained_with():
    """Written out rather than derived. Deriving it from the contract
    would assert only that the contract equals itself, which is what a
    reorder there would also satisfy."""
    assert CRITICAL_INFORMATION_NEEDS_LABELS == [
        "Civic Life",
        "Civic information",
        "Emergencies and Public Safety",
        "Health",
        "Transportation Systems",
        "Sports",
        "Environment and Planning",
        "Education",
        "Political life",
        "Economic Development",
    ]


def test_it_comes_from_the_contract():
    """Not a second copy. The console had already grown one in a
    different order before this moved."""
    assert CRITICAL_INFORMATION_NEEDS_LABELS == list(cin_labels.LABELS)


def test_the_class_ids_are_the_positions():
    """The property the order carries. If this ever fails, the
    checkpoint and the label map disagree and every prediction is
    mislabelled."""
    for expected, label in enumerate(CRITICAL_INFORMATION_NEEDS_LABELS):
        assert cin_labels.class_id_for(label) == expected


def test_there_are_ten_and_they_are_distinct():
    """`num_labels` is len() of this, and it has to match the
    checkpoint's final layer."""
    assert len(CRITICAL_INFORMATION_NEEDS_LABELS) == 10
    assert len(set(CRITICAL_INFORMATION_NEEDS_LABELS)) == 10


def test_the_label_map_is_built_by_position():
    """The reason any of the above matters, held to the source: if this
    ever stops using enumerate(), the order stops being load-bearing and
    these tests are guarding nothing."""
    import inspect

    from src.ml import article_classifier

    source = inspect.getsource(article_classifier)
    assert "enumerate(CRITICAL_INFORMATION_NEEDS_LABELS)" in source
