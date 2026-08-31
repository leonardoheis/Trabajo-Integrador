from classiflow.classification.nodes.second_opinion import SecondOpinionNode
from classiflow.pipeline.base import make_display_name


class TestMakeDisplayName:
    def test_returns_the_nodes_declared_name_without_needing_a_live_instance(self) -> None:
        display_name = make_display_name(SecondOpinionNode)

        # weave strips "self" from call.inputs before calling this, so it must never
        # need to read anything off the call object itself.
        assert display_name(object()) == "classification_second_opinion"
