from itertools import islice

from streamcatcher.player.reconnect import ReconnectPolicy, backoff_delays


def test_policy_defaults():
    policy = ReconnectPolicy()
    assert policy.enabled is True
    assert policy.base_delay == 1.0
    assert policy.factor == 2.0
    assert policy.max_delay == 30.0


def test_backoff_ramps_then_caps():
    delays = list(islice(backoff_delays(ReconnectPolicy()), 8))
    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]


def test_backoff_respects_custom_policy():
    policy = ReconnectPolicy(base_delay=0.5, factor=3.0, max_delay=5.0)
    delays = list(islice(backoff_delays(policy), 5))
    assert delays == [0.5, 1.5, 4.5, 5.0, 5.0]


def test_backoff_is_infinite():
    gen = backoff_delays(ReconnectPolicy(max_delay=2.0))
    # Pulling many values never raises StopIteration and stays capped.
    tail = list(islice(gen, 100))[-1]
    assert tail == 2.0
