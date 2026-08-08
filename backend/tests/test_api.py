async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_persona_crud(client):
    create = await client.post(
        "/personas",
        json={
            "name": "Test Persona",
            "age": 40,
            "occ": "Lärare",
            "district": "Centrum",
            "quote": "En testquote",
            "origin": "manuell",
        },
    )
    assert create.status_code == 201
    persona = create.json()
    assert persona["name"] == "Test Persona"
    assert persona["profile"]["name"] == "Test Persona"
    persona_id = persona["id"]

    listed = await client.get("/personas")
    assert listed.status_code == 200
    assert any(p["id"] == persona_id for p in listed.json())

    updated = await client.put(
        f"/personas/{persona_id}",
        json={"quote": "Uppdaterad quote"},
    )
    assert updated.status_code == 200
    assert updated.json()["quote"] == "Uppdaterad quote"

    dup = await client.post(f"/personas/{persona_id}/duplicate")
    assert dup.status_code == 201
    assert dup.json()["id"] != persona_id
    assert "(kopia)" in dup.json()["name"]


async def test_population_and_members(client):
    persona = (
        await client.post(
            "/personas",
            json={
                "id": "tp",
                "name": "Test Persona",
                "age": 40,
                "occ": "Lärare",
                "district": "Centrum",
                "quote": "Quote",
                "origin": "manuell",
            },
        )
    ).json()

    create = await client.post(
        "/populations",
        json={
            "name": "Testpop",
            "fingerprint": [[33, 34, 33], [33, 34, 33], [33, 34, 33]],
            "recipe": {"note": "demo"},
            "members": [
                {
                    "persona_id": persona["id"],
                    "name": persona["name"],
                    "initials": "TP",
                    "age": 40,
                    "occ": "Lärare",
                    "district": "Centrum",
                    "trait": "Quote",
                }
            ],
        },
    )
    assert create.status_code == 201
    population = create.json()
    assert population["size"] == 1
    assert population["members"][0]["id"] == "tp"
    assert isinstance(population["members"][0]["member_id"], int)

    listed = await client.get("/populations")
    assert any(p["name"] == "Testpop" for p in listed.json())

    detail = await client.get(f"/populations/{population['id']}")
    assert detail.status_code == 200
    assert detail.json()["recipe"]["note"] == "demo"

    add = await client.post(
        f"/populations/{population['id']}/members",
        json={
            "name": "Extra Member",
            "initials": "EM",
            "age": 22,
            "occ": "Student",
            "district": "Innerstaden",
            "trait": "Ny",
        },
    )
    assert add.status_code == 201
    extra_member_id = add.json()["member_id"]

    refreshed = await client.get(f"/populations/{population['id']}")
    assert refreshed.json()["size"] == 2

    remove = await client.delete(
        f"/populations/{population['id']}/members/{population['members'][0]['member_id']}"
    )
    assert remove.status_code == 204

    after = await client.get(f"/populations/{population['id']}")
    assert after.json()["size"] == 1
    assert after.json()["members"][0]["member_id"] == extra_member_id

    dup = await client.post(f"/populations/{population['id']}/duplicate")
    assert dup.status_code == 201
    assert "(kopia)" in dup.json()["name"]

    # Deleting a persona must remove membership rows (not leave orphans)
    linked = (
        await client.post(
            "/personas",
            json={
                "id": "link-me",
                "name": "Linked",
                "age": 41,
                "occ": "Lärare",
                "district": "Centrum",
                "quote": "x",
                "origin": "manuell",
            },
        )
    ).json()
    await client.post(
        f"/populations/{population['id']}/members",
        json={
            "persona_id": linked["id"],
            "name": linked["name"],
            "initials": "LI",
            "age": 41,
            "occ": "Lärare",
            "district": "Centrum",
            "trait": "x",
        },
    )
    before = await client.get(f"/populations/{population['id']}")
    assert any(m["id"] == "link-me" for m in before.json()["members"])

    deleted = await client.delete("/personas/link-me")
    assert deleted.status_code == 204
    after_persona_delete = await client.get(f"/populations/{population['id']}")
    assert all(m["id"] != "link-me" for m in after_persona_delete.json()["members"])


async def test_run_lifecycle(client):
    from app.services import jobs as jobs_service

    jobs_service.set_schedule_hook(lambda _job_id: None)

    pop = (
        await client.post(
            "/populations",
            json={"name": "Runpop", "members": []},
        )
    ).json()

    create = await client.post(
        "/runs",
        json={
            "name": "Testkörning",
            "population_id": pop["id"],
            "main_ticks": [
                {
                    "key": "t1",
                    "day": 1,
                    "silent": False,
                    "injections": [],
                    "rounds": 1,
                    "measurements": ["opinion_snapshot"],
                }
            ],
            "branch": None,
        },
    )
    assert create.status_code == 201
    run = create.json()
    assert run["status"] == "draft"
    assert run["population"] == "Runpop"
    assert run["ticks"] == 1
    assert run["variants"] == 1

    started = await client.post(f"/runs/{run['id']}/start")
    assert started.status_code == 202
    body = started.json()
    assert body["status"] == "running"
    assert body["job_id"]

    listed = await client.get("/runs", params={"status": "running"})
    assert any(r["id"] == run["id"] for r in listed.json())

    options = await client.get("/runs/populations")
    assert options.status_code == 200
    assert any(p["name"] == "Runpop" for p in options.json())

    dup = await client.post(f"/runs/{run['id']}/duplicate")
    assert dup.status_code == 201
    assert dup.json()["status"] == "draft"

    delete = await client.delete(f"/runs/{run['id']}")
    assert delete.status_code == 204


async def test_start_oasis_without_package_returns_503(client, monkeypatch):
    from app.config import settings
    import app.api.runs as runs_api

    monkeypatch.setattr(runs_api, "oasis_installed", lambda: False)

    pop = (
        await client.post(
            "/populations",
            json={"name": "Oasispop", "members": []},
        )
    ).json()
    create = await client.post(
        "/runs",
        json={
            "name": "Oasis test",
            "population_id": pop["id"],
            "main_ticks": [],
        },
    )
    run_id = create.json()["id"]

    settings.simulation_engine = "oasis"
    settings.deepseek_api_key = "sk-test"
    try:
        started = await client.post(f"/runs/{run_id}/start")
        assert started.status_code == 503
        assert "camel-oasis" in started.json()["detail"]
    finally:
        settings.simulation_engine = "none"
        settings.deepseek_api_key = "test-key-not-real"


def _sample_recipe(size: int = 6, seed: int = 42) -> dict:
    return {
        "size": size,
        "locale": "norrkoping",
        "seed": seed,
        "dist": {
            "age": {
                "label": "Ålder",
                "rows": [
                    {"k": "ung", "l": "Ung", "v": 30},
                    {"k": "medel", "l": "Medel", "v": 45},
                    {"k": "aldre", "l": "Äldre", "v": 25},
                ],
            },
            "district": {
                "label": "Ort",
                "rows": [
                    {"k": "centrum", "l": "Centrum", "v": 50},
                    {"k": "ovriga", "l": "Övriga", "v": 50},
                ],
            },
            "occupation": {
                "label": "Yrke",
                "rows": [
                    {"k": "vard", "l": "Vård", "v": 50},
                    {"k": "ovrigt", "l": "Övrigt", "v": 50},
                ],
            },
            "leaning": {
                "label": "Lutning",
                "rows": [
                    {"k": "vanster", "l": "Vänster", "v": 20},
                    {"k": "mvanster", "l": "Mitt-vänster", "v": 20},
                    {"k": "mitt", "l": "Mitt", "v": 20},
                    {"k": "mhoger", "l": "Mitt-höger", "v": 20},
                    {"k": "hoger", "l": "Höger", "v": 20},
                ],
            },
        },
    }


async def test_generate_and_create_from_generation(client):
    generated = await client.post(
        "/populations/generate",
        json={"recipe": _sample_recipe(size=5, seed=7), "mode": "replace"},
    )
    assert generated.status_code == 200
    payload = generated.json()
    assert payload["generation_id"].startswith("gen_")
    assert len(payload["candidates"]) == 5
    assert len(payload["fingerprint"]) == 3
    assert all(c["source"] == "generated" for c in payload["candidates"])

    keep = [c["key"] for c in payload["candidates"][:4]]
    create = await client.post(
        "/populations",
        json={
            "name": "Generated pop",
            "generation_id": payload["generation_id"],
            "keep_keys": keep,
        },
    )
    assert create.status_code == 201
    population = create.json()
    assert population["size"] == 4
    assert population["recipe"]["size"] == 5
    assert len(population["fp"]) == 3

    personas = await client.get("/personas")
    assert len([p for p in personas.json() if p["origin"] == "population"]) == 4

    reuse = await client.post(
        "/populations",
        json={
            "name": "Reuse expired",
            "generation_id": payload["generation_id"],
        },
    )
    assert reuse.status_code == 404


async def test_persona_generate_and_chat(client):
    generated = await client.post(
        "/personas/generate",
        json={"mode": "beskrivning", "freeText": "cynisk undersköterska", "count": 2},
    )
    assert generated.status_code == 200
    candidates = generated.json()["candidates"]
    assert len(candidates) == 2
    assert candidates[0]["name"]

    created = await client.post(
        "/personas",
        json={
            "name": candidates[0]["name"],
            "age": int("".join(ch for ch in candidates[0]["age"] if ch.isdigit()) or "40"),
            "occ": candidates[0]["yrke"],
            "district": candidates[0]["ort"],
            "quote": candidates[0].get("ton", ""),
            "origin": "beskrivning",
            "profile": candidates[0],
        },
    )
    assert created.status_code == 201
    persona_id = created.json()["id"]

    chat = await client.post(
        f"/personas/{persona_id}/chat",
        json={"mode": "interview", "message": "Vad tycker du om skolan?"},
    )
    assert chat.status_code == 200
    body = chat.json()
    assert body["reply"]
    assert len(body["messages"]) == 2

    listed = await client.get(f"/personas/{persona_id}/messages", params={"mode": "interview"})
    assert listed.status_code == 200
    assert len(listed.json()) == 2

    other = await client.get(f"/personas/{persona_id}/messages", params={"mode": "character"})
    assert other.json() == []

    cleared = await client.delete(
        f"/personas/{persona_id}/messages",
        params={"mode": "interview"},
    )
    assert cleared.status_code == 204
    after = await client.get(f"/personas/{persona_id}/messages", params={"mode": "interview"})
    assert after.json() == []

    chat2 = await client.post(
        f"/personas/{persona_id}/chat",
        json={"mode": "interview", "message": "Andra frågan?"},
    )
    assert chat2.status_code == 200
    msg_id = chat2.json()["messages"][0]["id"]

    deleted = await client.delete(f"/personas/{persona_id}/messages/{msg_id}")
    assert deleted.status_code == 200
    deleted_ids = deleted.json()["deleted_ids"]
    assert msg_id in deleted_ids
    assert len(deleted_ids) == 2  # user + paired assistant
    remaining = await client.get(f"/personas/{persona_id}/messages", params={"mode": "interview"})
    assert remaining.json() == []

    cleared_again = await client.delete(
        f"/personas/{persona_id}/messages",
        params={"mode": "interview"},
    )
    assert cleared_again.status_code == 204

    turn1 = await client.post(
        f"/personas/{persona_id}/chat",
        json={"mode": "interview", "message": "Fråga ett?"},
    )
    assert turn1.status_code == 200
    turn2 = await client.post(
        f"/personas/{persona_id}/chat",
        json={"mode": "interview", "message": "Fråga två?"},
    )
    assert turn2.status_code == 200
    thread = turn2.json()["messages"]
    assert len(thread) == 4
    first_user_id = thread[0]["id"]

    resent_user = await client.post(
        f"/personas/{persona_id}/messages/{first_user_id}/resend",
    )
    assert resent_user.status_code == 200
    after_user_resend = resent_user.json()["messages"]
    assert len(after_user_resend) == 2
    assert after_user_resend[0]["content"] == "Fråga ett?"

    turn3 = await client.post(
        f"/personas/{persona_id}/chat",
        json={"mode": "interview", "message": "Fråga tre?"},
    )
    assert turn3.status_code == 200
    extended = turn3.json()["messages"]
    assert len(extended) == 4
    first_assistant_id = extended[1]["id"]

    resent_assistant = await client.post(
        f"/personas/{persona_id}/messages/{first_assistant_id}/resend",
    )
    assert resent_assistant.status_code == 200
    after_assistant_resend = resent_assistant.json()["messages"]
    assert len(after_assistant_resend) == 2
    assert after_assistant_resend[0]["content"] == "Fråga ett?"
    assert after_assistant_resend[1]["role"] == "assistant"


async def test_generate_replace_key_and_library(client):
    persona = (
        await client.post(
            "/personas",
            json={
                "id": "lib1",
                "name": "Library One",
                "age": 33,
                "occ": "Lärare",
                "district": "Centrum",
                "quote": "Från bibliotek",
                "origin": "manuell",
            },
        )
    ).json()

    first = await client.post(
        "/populations/generate",
        json={
            "recipe": _sample_recipe(size=4, seed=1),
            "include_persona_ids": [persona["id"]],
            "mode": "replace",
        },
    )
    assert first.status_code == 200
    body = first.json()
    assert len(body["candidates"]) == 4
    assert sum(1 for c in body["candidates"] if c["source"] == "library") == 1

    target = next(c for c in body["candidates"] if c["source"] == "generated")
    second = await client.post(
        "/populations/generate",
        json={
            "recipe": _sample_recipe(size=4, seed=99),
            "generation_id": body["generation_id"],
            "existing": body["candidates"],
            "replace_keys": [target["key"]],
        },
    )
    assert second.status_code == 200
    replaced = second.json()
    assert replaced["generation_id"] == body["generation_id"]
    assert len(replaced["candidates"]) == 4
    new_target = next(c for c in replaced["candidates"] if c["key"] == target["key"])
    assert new_target["source"] == "generated"


async def test_message_crud_and_filters(client):
    news_raw = await client.post(
        "/messages",
        json={"type": "news", "title": "Råtextnyhet", "body": "Bara text, ingen länk."},
    )
    assert news_raw.status_code == 201
    assert news_raw.json()["source_url"] is None

    post = await client.post(
        "/messages",
        json={
            "type": "post",
            "title": "Trygghet i vardagen",
            "body": "Trygghet börjar nära dig.",
            "metadata": {"variant": "concise"},
        },
    )
    assert post.status_code == 201
    post_body = post.json()
    assert post_body["type"] == "post"
    assert post_body["source_url"] is None
    assert post_body["metadata"]["variant"] == "concise"
    post_id = post_body["id"]

    news = await client.post(
        "/messages",
        json={
            "type": "news",
            "title": "Lokal nyhet",
            "body": "Kommunen öppnar ny vårdcentral.",
            "source_url": "example.com/nyhet",
        },
    )
    assert news.status_code == 201
    assert news.json()["source_url"].startswith("https://")

    listed = await client.get("/messages")
    assert listed.status_code == 200
    assert len(listed.json()) == 3

    only_post = await client.get("/messages", params={"type": "post"})
    assert len(only_post.json()) == 1
    assert only_post.json()[0]["id"] == post_id

    searched = await client.get("/messages", params={"q": "vårdcentral"})
    assert len(searched.json()) == 1
    assert searched.json()[0]["type"] == "news"

    patched = await client.patch(
        f"/messages/{post_id}",
        json={"title": "Uppdaterad trygghet", "body": "Ny brödtext."},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Uppdaterad trygghet"

    got = await client.get(f"/messages/{post_id}")
    assert got.json()["body"] == "Ny brödtext."

    deleted = await client.delete(f"/messages/{post_id}")
    assert deleted.status_code == 204
    assert (await client.get(f"/messages/{post_id}")).status_code == 404


async def test_configuration_crud(client):
    catalog = await client.get("/configurations/catalog", params={"language": "sv"})
    assert catalog.status_code == 200
    cat = catalog.json()
    assert len(cat["fields"]) >= 10
    assert "persona.field_guide" in cat["defaults"]

    listed = await client.get("/configurations")
    assert listed.status_code == 200
    # Seeded Standard configs for sv + en; exactly one active globally
    configs = listed.json()
    assert len(configs) >= 2
    active = [c for c in configs if c["is_active"]]
    assert len(active) == 1
    assert active[0]["language"] == "sv"

    create = await client.post(
        "/configurations",
        json={
            "name": "  Alternativ SV  ",
            "language": "sv",
            "prompts": {"persona.field_guide": "  Egen fältguide  "},
            "is_active": True,
        },
    )
    assert create.status_code == 201
    row = create.json()
    assert row["name"] == "Alternativ SV"
    assert row["language"] == "sv"
    assert row["is_active"] is True
    assert row["prompts"]["persona.field_guide"] == "Egen fältguide"
    assert row["prompts"]["chat.mode.interview"]  # filled from defaults
    config_id = row["id"]

    listed2 = await client.get("/configurations")
    active_all = [c for c in listed2.json() if c["is_active"]]
    assert len(active_all) == 1
    assert active_all[0]["id"] == config_id

    # Activating an English config deactivates the Swedish one (global, not per language)
    en_row = next(c for c in listed2.json() if c["language"] == "en")
    activated_en = await client.post(f"/configurations/{en_row['id']}/activate")
    assert activated_en.status_code == 200
    assert activated_en.json()["is_active"] is True
    listed3 = await client.get("/configurations")
    active_after = [c for c in listed3.json() if c["is_active"]]
    assert len(active_after) == 1
    assert active_after[0]["id"] == en_row["id"]

    patched = await client.patch(
        f"/configurations/{config_id}",
        json={
            "name": "Uppdaterad",
            "prompts": {"chat.mode.interview": "Ny intervjuregel."},
            "is_active": True,
        },
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Uppdaterad"
    assert patched.json()["prompts"]["chat.mode.interview"] == "Ny intervjuregel."
    assert patched.json()["is_active"] is True
    listed4 = await client.get("/configurations")
    assert len([c for c in listed4.json() if c["is_active"]]) == 1

    activated = await client.post(f"/configurations/{config_id}/activate")
    assert activated.status_code == 200
    assert activated.json()["is_active"] is True

    deleted = await client.delete(f"/configurations/{config_id}")
    assert deleted.status_code == 204
    assert (await client.get(f"/configurations/{config_id}")).status_code == 404


async def test_configuration_rejects_invalid_language(client):
    blank_name = await client.post(
        "/configurations",
        json={"name": "   ", "language": "sv"},
    )
    assert blank_name.status_code == 422

    bad_lang = await client.post(
        "/configurations",
        json={"name": "Namn", "language": "de"},
    )
    assert bad_lang.status_code == 422

    missing = await client.get("/configurations/999999")
    assert missing.status_code == 404


async def test_message_rejects_whitespace_and_null_type_clears_url(client):
    blank = await client.post(
        "/messages",
        json={"type": "post", "title": "   ", "body": "ok"},
    )
    assert blank.status_code == 422

    news = await client.post(
        "/messages",
        json={
            "type": "news",
            "title": "  Nyhet  ",
            "body": "  Brödtext  ",
            "source_url": "example.com/a",
        },
    )
    assert news.status_code == 201
    news_id = news.json()["id"]
    assert news.json()["title"] == "Nyhet"
    assert news.json()["body"] == "Brödtext"

    cleared = await client.patch(
        f"/messages/{news_id}",
        json={"type": None, "source_url": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["type"] == "news"
    assert cleared.json()["source_url"] is None

    blank_body = await client.patch(
        f"/messages/{news_id}",
        json={"body": " \n\t "},
    )
    assert blank_body.status_code == 422


async def test_generate_variants_parallel_stub(client):
    from app.llm import set_text_completer

    calls: list[str] = []

    async def stub(messages):
        content = messages[-1]["content"]
        calls.append(content)
        if "analytisk" in content.lower():
            return "Analytisk variant"
        if "berättande" in content.lower():
            return "Berättande variant"
        return "Kort variant"

    set_text_completer(stub)
    try:
        res = await client.post(
            "/messages/generate-variants",
            json={
                "type": "post",
                "raw_text": "Satsa på skolan i Norrköping",
                "audience": "föräldrar",
                "purpose": "bygga auktoritet",
                "tone": "saklig",
            },
        )
        assert res.status_code == 200
        variants = res.json()["variants"]
        assert len(variants) == 3
        keys = {v["key"] for v in variants}
        assert keys == {"analytical", "narrative", "concise"}
        assert len(calls) == 3
    finally:
        set_text_completer(None)


async def test_run_start_snapshots_message_body(client):
    from app.services import jobs as jobs_service

    jobs_service.set_schedule_hook(lambda _job_id: None)

    msg = (
        await client.post(
            "/messages",
            json={
                "type": "post",
                "title": "Snapshot budskap",
                "body": "Original body from library",
            },
        )
    ).json()

    pop = (
        await client.post(
            "/populations",
            json={"name": "Snap pop", "members": []},
        )
    ).json()

    run = (
        await client.post(
            "/runs",
            json={
                "name": "Snap run",
                "population_id": pop["id"],
                "main_ticks": [
                    {
                        "key": "t1",
                        "day": 1,
                        "silent": False,
                        "injections": [
                            {
                                "key": "i1",
                                "type": "party_post",
                                "sender": "@parti",
                                "text": "Stale draft text",
                                "mode": "text",
                                "url": "",
                                "fetching": False,
                                "sourceDomain": "",
                                "isVideo": False,
                                "message_id": msg["id"],
                            }
                        ],
                        "rounds": 1,
                        "measurements": [],
                    }
                ],
            },
        )
    ).json()

    # Edit library after run was saved — start must re-snapshot current body
    await client.patch(
        f"/messages/{msg['id']}",
        json={"body": "Frozen body at start"},
    )

    started = await client.post(f"/runs/{run['id']}/start")
    assert started.status_code == 202
    inj = started.json()["main_ticks"][0]["injections"][0]
    assert inj["message_id"] == msg["id"]
    assert inj["text"] == "Frozen body at start"

    missing = (
        await client.post(
            "/runs",
            json={
                "name": "Missing msg run",
                "population_id": pop["id"],
                "main_ticks": [
                    {
                        "key": "t1",
                        "day": 1,
                        "silent": False,
                        "injections": [
                            {
                                "key": "i1",
                                "type": "party_post",
                                "text": "x",
                                "message_id": "00000000-0000-0000-0000-000000000099",
                            }
                        ],
                        "rounds": 1,
                        "measurements": [],
                    }
                ],
            },
        )
    ).json()
    bad = await client.post(f"/runs/{missing['id']}/start")
    assert bad.status_code == 400
    assert "not found" in bad.json()["detail"]


async def test_catalog_lists(client):
    listed = await client.get("/catalog")
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) >= 13
    keys = {row["key"] for row in rows}
    assert "parti" in keys
    assert "ort" in keys
    assert "lutning" in keys
    assert "avsandare" in keys

    parti = next(row for row in rows if row["key"] == "parti")
    assert any(item["label"] == "Socialdemokraterna" for item in parti["items"])

    ort = next(row for row in rows if row["key"] == "ort")
    centrum = next(item for item in ort["items"] if item["label"] == "Centrum")
    assert centrum["description"]
    assert centrum["bounds"] is not None
    assert centrum["bounds"]["south"] < centrum["bounds"]["north"]

    updated = await client.put(
        "/catalog/parti",
        json={
            "items": [
                {"label": "Socialdemokraterna"},
                {"label": "Moderaterna"},
                {"label": "  "},
                {"label": "Socialdemokraterna"},
            ]
        },
    )
    assert updated.status_code == 200
    assert [item["label"] for item in updated.json()["items"]] == [
        "Socialdemokraterna",
        "Moderaterna",
    ]

    # Legacy string items are coerced on write.
    legacy = await client.put(
        "/catalog/ton",
        json={"items": ["Sarkastisk", "Direkt"]},
    )
    assert legacy.status_code == 200
    assert legacy.json()["items"] == [
        {"label": "Sarkastisk", "description": "", "bounds": None},
        {"label": "Direkt", "description": "", "bounds": None},
    ]

    bounds_ok = await client.put(
        "/catalog/ort",
        json={
            "items": [
                {
                    "label": "Centrum",
                    "description": "Innerstad",
                    "bounds": {
                        "south": 58.58,
                        "west": 16.17,
                        "north": 58.59,
                        "east": 16.19,
                    },
                }
            ]
        },
    )
    assert bounds_ok.status_code == 200
    saved = bounds_ok.json()["items"][0]
    assert saved["description"] == "Innerstad"
    assert saved["bounds"]["east"] == 16.19

    bad_bounds = await client.put(
        "/catalog/ort",
        json={
            "items": [
                {
                    "label": "Centrum",
                    "bounds": {
                        "south": 58.59,
                        "west": 16.17,
                        "north": 58.58,
                        "east": 16.19,
                    },
                }
            ]
        },
    )
    assert bad_bounds.status_code == 422

    missing = await client.put(
        "/catalog/does-not-exist",
        json={"items": [{"label": "x"}]},
    )
    assert missing.status_code == 404


async def test_catalog_scoped_per_configuration(client):
    listed = await client.get("/configurations")
    assert listed.status_code == 200
    configs = listed.json()
    assert len(configs) >= 2
    active = next(c for c in configs if c["is_active"])
    other = next(c for c in configs if not c["is_active"])

    scoped_a = await client.get(f"/configurations/{active['id']}/catalog")
    assert scoped_a.status_code == 200
    assert len(scoped_a.json()) >= 13

    # Edit active config's parti list via scoped API.
    put_a = await client.put(
        f"/configurations/{active['id']}/catalog/parti",
        json={"items": [{"label": "EndastAktiv"}]},
    )
    assert put_a.status_code == 200
    assert [i["label"] for i in put_a.json()["items"]] == ["EndastAktiv"]

    # Other config keeps its own defaults.
    scoped_b = await client.get(f"/configurations/{other['id']}/catalog/parti")
    assert scoped_b.status_code == 200
    labels_b = [i["label"] for i in scoped_b.json()["items"]]
    assert "EndastAktiv" not in labels_b
    assert "Socialdemokraterna" in labels_b

    # Runtime /catalog mirrors the active configuration.
    runtime = await client.get("/catalog/parti")
    assert runtime.status_code == 200
    assert [i["label"] for i in runtime.json()["items"]] == ["EndastAktiv"]

    # Activating the other config switches /catalog.
    activated = await client.post(f"/configurations/{other['id']}/activate")
    assert activated.status_code == 200
    runtime2 = await client.get("/catalog/parti")
    assert runtime2.status_code == 200
    assert "Socialdemokraterna" in [i["label"] for i in runtime2.json()["items"]]
    assert "EndastAktiv" not in [i["label"] for i in runtime2.json()["items"]]


async def test_catalog_ort_cleared_description_persists(client):
    """Clearing an ort description must not be reverted by ensure on GET."""
    listed = await client.get("/configurations")
    active = next(c for c in listed.json() if c["is_active"])

    cleared = await client.put(
        f"/configurations/{active['id']}/catalog/ort",
        json={
            "items": [
                {
                    "label": "Centrum",
                    "description": "",
                    "bounds": {
                        "south": 58.58,
                        "west": 16.17,
                        "north": 58.59,
                        "east": 16.19,
                    },
                }
            ]
        },
    )
    assert cleared.status_code == 200
    assert cleared.json()["items"][0]["description"] == ""

    after_get = await client.get(f"/configurations/{active['id']}/catalog/ort")
    assert after_get.status_code == 200
    assert after_get.json()["items"][0]["description"] == ""


def test_format_area_block_includes_relative_hint():
    from app.schemas.domain import GeoBounds
    from app.services.district_context import DistrictContext, format_area_block

    centrum = DistrictContext(
        label="Centrum",
        description="Innerstad",
        bounds=GeoBounds(south=58.58, west=16.17, north=58.59, east=16.19),
    )
    south = DistrictContext(
        label="Distrikt A",
        description="Miljonprogram söderut",
        bounds=GeoBounds(south=58.56, west=16.17, north=58.57, east=16.19),
    )
    text = format_area_block(south, centrum=centrum)
    assert "Distrikt A" in text
    assert "Miljonprogram" in text
    assert "mittpunkt" in text.lower()
    assert "Centrum" in text


async def test_population_generate_job_creates_population(client):
    from app.services import jobs as jobs_service

    # Run worker inline so the test does not race asyncio.create_task.
    jobs_service.set_schedule_hook(lambda _job_id: None)

    created = await client.post(
        "/jobs",
        json={
            "kind": "population_generate",
            "label": "Jobb-pop A",
            "request": {
                "name": "Jobb-pop A",
                "recipe": _sample_recipe(size=4, seed=11),
            },
        },
    )
    assert created.status_code == 202
    job_id = created.json()["id"]
    assert created.json()["status"] == "pending"

    await jobs_service._run_job(job_id)

    got = await client.get(f"/jobs/{job_id}")
    assert got.status_code == 200
    payload = got.json()
    assert payload["status"] == "succeeded"
    assert payload["result"]["member_count"] == 4
    pop_id = payload["result"]["population_id"]
    assert isinstance(pop_id, int)

    pop = await client.get(f"/populations/{pop_id}")
    assert pop.status_code == 200
    assert pop.json()["name"] == "Jobb-pop A"
    assert len(pop.json()["members"]) == 4

    listed = await client.get("/jobs")
    assert listed.status_code == 200
    assert any(j["id"] == job_id for j in listed.json())


async def test_population_generate_job_fails_missing_population(client):
    from app.services import jobs as jobs_service

    jobs_service.set_schedule_hook(lambda _job_id: None)

    created = await client.post(
        "/jobs",
        json={
            "kind": "population_generate",
            "label": "Saknad pop",
            "request": {
                "name": "Saknad pop",
                "recipe": _sample_recipe(size=3, seed=3),
                "population_id": 99999,
            },
        },
    )
    assert created.status_code == 202
    job_id = created.json()["id"]
    await jobs_service._run_job(job_id)

    got = await client.get(f"/jobs/{job_id}")
    assert got.status_code == 200
    payload = got.json()
    assert payload["status"] == "failed"
    assert payload["error"]
    assert "not found" in payload["error"].lower() or "Population" in payload["error"]


async def test_population_generate_job_mixes_library_personas(client):
    from app.services import jobs as jobs_service

    jobs_service.set_schedule_hook(lambda _job_id: None)

    persona = (
        await client.post(
            "/personas",
            json={
                "id": "joblib1",
                "name": "Jobb Library One",
                "age": 41,
                "occ": "Lärare",
                "district": "Centrum",
                "quote": "Från bibliotek",
                "origin": "manuell",
            },
        )
    ).json()

    created = await client.post(
        "/jobs",
        json={
            "kind": "population_generate",
            "label": "Mix-pop",
            "request": {
                "name": "Mix-pop",
                "recipe": _sample_recipe(size=4, seed=21),
                "include_persona_ids": [persona["id"]],
            },
        },
    )
    assert created.status_code == 202
    job_id = created.json()["id"]
    await jobs_service._run_job(job_id)

    got = await client.get(f"/jobs/{job_id}")
    assert got.status_code == 200
    payload = got.json()
    assert payload["status"] == "succeeded"
    assert payload["result"]["member_count"] == 4

    pop = await client.get(f"/populations/{payload['result']['population_id']}")
    assert pop.status_code == 200
    members = pop.json()["members"]
    assert len(members) == 4
    assert sum(1 for m in members if m["id"] == persona["id"]) == 1


async def test_population_generate_job_library_only(client):
    from app.services import jobs as jobs_service

    jobs_service.set_schedule_hook(lambda _job_id: None)

    a = (
        await client.post(
            "/personas",
            json={
                "id": "jobliba",
                "name": "Library A",
                "age": 30,
                "occ": "Lärare",
                "district": "Centrum",
                "origin": "manuell",
            },
        )
    ).json()
    b = (
        await client.post(
            "/personas",
            json={
                "id": "joblibb",
                "name": "Library B",
                "age": 45,
                "occ": "Sjuksköterska",
                "district": "Övriga",
                "origin": "manuell",
            },
        )
    ).json()

    created = await client.post(
        "/jobs",
        json={
            "kind": "population_generate",
            "label": "Lib-only",
            "request": {
                "name": "Lib-only",
                "recipe": _sample_recipe(size=2, seed=22),
                "include_persona_ids": [a["id"], b["id"]],
            },
        },
    )
    assert created.status_code == 202
    job_id = created.json()["id"]
    await jobs_service._run_job(job_id)

    got = await client.get(f"/jobs/{job_id}")
    assert got.status_code == 200
    payload = got.json()
    assert payload["status"] == "succeeded"
    assert payload["result"]["member_count"] == 2

    pop = await client.get(f"/populations/{payload['result']['population_id']}")
    assert pop.status_code == 200
    member_ids = {m["id"] for m in pop.json()["members"]}
    assert member_ids == {a["id"], b["id"]}


async def test_start_run_queues_simulate_job(client):
    from app.services import jobs as jobs_service

    jobs_service.set_schedule_hook(lambda _job_id: None)

    pop = (
        await client.post(
            "/populations",
            json={"name": "Simpop", "members": []},
        )
    ).json()
    run = (
        await client.post(
            "/runs",
            json={
                "name": "Bakgrundssim",
                "population_id": pop["id"],
                "main_ticks": [],
            },
        )
    ).json()

    started = await client.post(f"/runs/{run['id']}/start")
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    assert job_id
    assert started.json()["status"] == "running"

    await jobs_service._run_job(job_id)

    got = await client.get(f"/jobs/{job_id}")
    assert got.status_code == 200
    payload = got.json()
    assert payload["status"] == "succeeded"
    assert payload["kind"] == "run_simulate"
    assert payload["result"]["run_id"] == run["id"]

    detail = await client.get(f"/runs/{run['id']}")
    assert detail.json()["status"] == "done"
    results = detail.json()["results"]
    assert results["engine"] == "none"
    assert len(results["attempts"]) == 1
    assert len(results["attempts"][0]["variants"]) == 1
    assert results["attempts"][0]["variants"][0]["id"] == "main"
    assert "measurements" in results["attempts"][0]["variants"][0]


async def test_start_run_rejects_while_already_running(client):
    from app.services import jobs as jobs_service

    jobs_service.set_schedule_hook(lambda _job_id: None)

    pop = (
        await client.post(
            "/populations",
            json={"name": "RunLockPop", "members": []},
        )
    ).json()
    run = (
        await client.post(
            "/runs",
            json={
                "name": "Locked sim",
                "population_id": pop["id"],
                "main_ticks": [],
            },
        )
    ).json()

    first = await client.post(f"/runs/{run['id']}/start")
    assert first.status_code == 202

    second = await client.post(f"/runs/{run['id']}/start")
    assert second.status_code == 409


async def test_merge_attempt_appends_to_fresh_results(client):
    from app.database.models import Run
    from app.services import jobs as jobs_service
    from app.services.oasis_run import merge_attempt

    pop = (
        await client.post(
            "/populations",
            json={"name": "MergePop", "members": []},
        )
    ).json()
    run = (
        await client.post(
            "/runs",
            json={
                "name": "Merge sim",
                "population_id": pop["id"],
                "main_ticks": [],
            },
        )
    ).json()

    existing = {
        "engine": "none",
        "attempts": [{"id": "att_existing", "variants": []}],
    }
    factory = jobs_service.job_session_factory()
    async with factory() as session:
        row = await session.get(Run, run["id"])
        row.results = existing
        await session.commit()

    async with factory() as session:
        row = await session.get(Run, run["id"])
        await session.refresh(row)
        merged = merge_attempt(
            row.results if isinstance(row.results, dict) else None,
            {"id": "att_new", "variants": []},
            engine="none",
        )

    assert [a["id"] for a in merged["attempts"]] == ["att_new", "att_existing"]


async def test_start_run_with_branch_stores_a_and_b_variants(client):
    from app.services import jobs as jobs_service

    jobs_service.set_schedule_hook(lambda _job_id: None)

    pop = (
        await client.post(
            "/populations",
            json={"name": "ABpop", "members": []},
        )
    ).json()
    run = (
        await client.post(
            "/runs",
            json={
                "name": "AB sim",
                "population_id": pop["id"],
                "main_ticks": [
                    {
                        "key": "m1",
                        "day": 1,
                        "silent": False,
                        "injections": [],
                        "rounds": 1,
                        "measurements": [],
                    }
                ],
                "branch": {
                    "afterIndex": 0,
                    "a": [
                        {
                            "key": "a2",
                            "day": 2,
                            "silent": False,
                            "injections": [],
                            "rounds": 1,
                            "measurements": [],
                        }
                    ],
                    "b": [
                        {
                            "key": "b2",
                            "day": 2,
                            "silent": False,
                            "injections": [],
                            "rounds": 1,
                            "measurements": [],
                        }
                    ],
                },
            },
        )
    ).json()

    started = await client.post(f"/runs/{run['id']}/start")
    job_id = started.json()["job_id"]
    await jobs_service._run_job(job_id)

    # Re-run to verify attempts are appended, not replaced
    started2 = await client.post(f"/runs/{run['id']}/start")
    assert started2.status_code == 202
    await jobs_service._run_job(started2.json()["job_id"])

    detail = await client.get(f"/runs/{run['id']}")
    results = detail.json()["results"]
    assert len(results["attempts"]) == 2
    variants = results["attempts"][0]["variants"]
    assert [v["id"] for v in variants] == ["a", "b"]
    assert [v["label"] for v in variants] == ["Version A", "Version B"]

    first_id = results["attempts"][0]["id"]
    deleted = await client.delete(f"/runs/{run['id']}/results/attempts/{first_id}")
    assert deleted.status_code == 200
    assert len(deleted.json()["results"]["attempts"]) == 1

    second_id = deleted.json()["results"]["attempts"][0]["id"]
    cleared = await client.delete(f"/runs/{run['id']}/results/attempts/{second_id}")
    assert cleared.status_code == 200
    assert cleared.json()["results"] is None


