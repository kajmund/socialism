from random import Random

from app.services.population_generate import sample_expert_identity


def test_sample_expert_identity_age_range_and_name():
    rng = Random(7)
    for _ in range(20):
        name, age, kon = sample_expert_identity(rng)
        assert 30 <= age <= 60
        assert " " in name
        assert kon in {"Kvinna", "Man", "Ickebinär"}
