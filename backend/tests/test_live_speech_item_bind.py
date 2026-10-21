from app.services.live_speech_item_bind import ProviderItemBinder


def test_first_provider_item_binds_to_current_utterance() -> None:
    binder = ProviderItemBinder()
    binder.start_utterance("1")
    binder.commit(1)
    assert binder.observe("prov-a", final=True) == (1, "1")
    assert binder.observe("prov-a", final=True) == (1, "1")


def test_late_final_after_newer_utterance_is_dropped_if_unbound() -> None:
    binder = ProviderItemBinder()
    binder.start_utterance("1")
    binder.commit(1)
    binder.start_utterance("3")
    binder.commit(2)
    assert binder.observe("prov-a", final=True) is None


def test_late_final_keeps_the_original_binding() -> None:
    binder = ProviderItemBinder()
    binder.start_utterance("1")
    binder.commit(1)
    assert binder.observe("prov-a", final=False) == (1, "1")
    binder.start_utterance("3")
    binder.commit(2)
    assert binder.observe("prov-a", final=True) == (1, "1")
    assert binder.observe("prov-b", final=False) == (2, "3")


def test_newer_partial_can_bind_while_an_older_commit_is_unbound() -> None:
    binder = ProviderItemBinder()
    binder.start_utterance("1")
    binder.commit(1)
    binder.start_utterance("3")
    assert binder.observe("prov-b", final=False) == (1, "3")
    binder.commit(2)
    assert binder.observe("prov-b", final=True) == (2, "3")
