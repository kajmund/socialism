"""Generate the Riksdag 2026 reference snabbrapport for local preview (no API keys).

Three väljargrupper (populationsprofiler) with the pilot scenario: an äldreomsorg
message on day 1 and an injected A-traktor news item on day 2. Embeddings are
stubbed, so tone and style values are not measurements — every other number comes
from the production generator.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.llm import set_structured_completer
from app.schemas.domain import Tick
from app.services.report.bundles import RunBundle
from app.services.report.generate import generate_report_html
from app.services.run_measurements import build_measurements
from app.services.ssr import set_embedder

CARE_INJECTION = (
    "Äldreomsorgen behöver personal och tryggare hemtjänst i hela kommunen."
)
TRACTOR_INJECTION = (
    "A-traktorer står bakom allvarliga olyckor i länet enligt Transportstyrelsen."
)

# (name, yrke, ålder, kön, ort, lutning, livssituation)
CITIZENS: tuple[tuple[str, str, str, str, str, str, str], ...] = (
    ("Krax Dahlen", "Frilansjournalist", "41", "Man", "Centrum", "Center", "Ensamhushåll"),
    ("Anders Lund", "IT-konsult", "48", "Man", "Lindö", "Center", "Sambo, barn"),
    ("Leo Ahmed", "Student", "23", "Man", "Centrum", "Vänster", "Ensamhushåll"),
    ("Lena Bergström", "Undersköterska", "52", "Kvinna", "Hageby", "Vänster", "Gift, vuxna barn"),
    ("Sofia Vinter", "Revisor", "37", "Kvinna", "Lindö", "Höger", "Sambo, inga barn"),
    ("Erik Bergström", "Lantbrukare", "58", "Man", "Vikbolandet", "Höger", "Gift, vuxna barn"),
    ("Lena Forsberg", "Förskollärare", "34", "Kvinna", "Hageby", "Vänster", "Sambo, barn"),
    ("Mikael Ohlsson", "Brandman", "45", "Man", "Vikbolandet", "Center", "Gift, vuxna barn"),
    ("Ingrid Palm", "Pensionär", "74", "Kvinna", "Centrum", "Vänster", "Ensamhushåll"),
    ("Bengt Sund", "Pensionär", "69", "Man", "Hageby", "Höger", "Gift, vuxna barn"),
    ("Nina Ek", "Butiksbiträde", "29", "Kvinna", "Hageby", "Center", "Ensamhushåll"),
    ("Omar Haddad", "Busschaufför", "44", "Man", "Centrum", "Vänster", "Sambo, barn"),
    ("Karin Ljung", "Sjuksköterska", "39", "Kvinna", "Lindö", "Vänster", "Sambo, barn"),
    ("Tobias Ranta", "Snickare", "31", "Man", "Vikbolandet", "Höger", "Sambo, inga barn"),
    ("Hanna Wik", "Gymnasielärare", "56", "Kvinna", "Centrum", "Center", "Gift, vuxna barn"),
    ("Petter Lind", "Åkeriägare", "51", "Man", "Vikbolandet", "Höger", "Gift, vuxna barn"),
    ("Yasmin Rahimi", "Ekonom", "33", "Kvinna", "Lindö", "Center", "Ensamhushåll"),
)

# Reactions per group: (citizen offset, day, text, likes)
CYNICAL_REACTIONS = (
    (0, 1, "Politikernas svar på personalbristen i äldreomsorgen: fler möten, inte en enda åtgärd.", 6),
    (0, 2, "Transportstyrelsen har alltså siffrorna om olyckor, och ingen följer upp besiktningen.", 9),
    (1, 1, "Det är som att torka upp ett läckande tak med fler hinkar, hemtjänst på papperet.", 5),
    (1, 2, "Olyckorna i länet ökar och vi diskuterar fortfarande vem som ska betala.", 4),
    (2, 2, "Enligt Transportstyrelsen är 47 procent av olyckorna kopplade till A-traktorer utan besiktning.", 0),
    (3, 1, "Jag jobbar i hemtjänsten, vi hinner inte det som står i beslutet om äldreomsorgen.", 4),
    (4, 2, "Reglerna om A-traktorer är inte problemet, uppföljningen av dem är det.", 3),
    (5, 2, "Bönderna i länet får skulden för olyckor som sker på riksvägen.", 0),
    (6, 1, "Skäms ni inte, ni struntar i äldreomsorgen och kommer med tomma löften.", 0),
    (7, 2, "Som brandman ser jag följderna av dessa olyckor varje sommar i länet.", 2),
    (8, 1, "Min make väntade nio timmar på hemtjänsten i tisdags.", 3),
    (9, 3, "Allt löser sig om vi bara jobbar tillsammans och slutar bråka.", 0),
    (10, 3, "Är det någon som ens minns att det handlade om äldreomsorgen?", 1),
    (11, 3, "Olyckorna kommer att fortsätta oavsett vad de lovar nu.", 0),
    (12, 2, "Vi på akuten tar emot ungdomarna efter dessa olyckor, det är inte statistik för oss.", 3),
    (13, 2, "Alla vet vilka fordon det gäller, ändå vågar ingen säga det rakt ut.", 1),
    (14, 3, "Länet borde kräva besiktning på plats, inte fler utredningar om olyckor.", 2),
    (15, 3, "Åkerierna i länet får böter medan olyckorna sker med helt andra fordon.", 0),
    (16, 3, "Transportstyrelsen mätte olyckor i fem år utan att någon agerade.", 1),
)
BALANCED_REACTIONS = (
    (0, 1, "Fina ord om äldreomsorgen, men var är personalen som ska utföra jobbet?", 5),
    (1, 1, "Hemtjänsten fungerar när bemanningen finns, annars är det bara schemakonst.", 4),
    (2, 2, "Transportstyrelsen redovisar olyckor per fordonstyp, det är värt att läsa.", 2),
    (3, 1, "Vi som arbetar i äldreomsorgen känner inte igen bilden av tryggare hemtjänst.", 6),
    (4, 2, "Om besiktningen av A-traktorer skärps borde olyckorna i länet minska.", 4),
    (7, 2, "Räddningstjänsten i länet larmas till dessa olyckor varje vecka.", 3),
    (8, 1, "Äldreomsorgen räddade min syster, personalen förtjänar bättre villkor.", 4),
    (12, 1, "Som sjuksköterska ser jag att äldreomsorgen behöver kontinuitet, inte kampanjer.", 5),
    (13, 2, "Ungdomarna behöver någonstans att ta vägen, inte bara hårdare regler om olyckor.", 1),
    (14, 3, "Debatten gled från äldreomsorgen till fordon på tre dagar.", 2),
    (15, 2, "Åkerinäringen i länet drabbas av olyckor vi inte orsakat.", 0),
    (16, 3, "Ingen har svarat på hur äldreomsorgen ska finansieras.", 1),
    (9, 2, "Olyckorna på vägen förbi gården har blivit fler varje sommar.", 2),
    (10, 2, "Ungdomarna kör ändå, oavsett vilka regler Transportstyrelsen sätter.", 1),
    (11, 3, "Bussarna möter dessa fordon dagligen, olyckorna är väntade.", 2),
    (12, 3, "Länet har inte råd att utreda olyckor i fem år till.", 1),
    (13, 3, "Besiktningen är svaret, inte nya kampanjer om olyckor.", 3),
)
REALISTIC_REACTIONS = (
    (0, 1, "Ännu ett löfte om äldreomsorgen strax före valet, vilken tajming.", 5),
    (1, 2, "Olyckorna i länet är verkliga, men förslagen är samma som förra mandatperioden.", 4),
    (5, 2, "Vi lantbrukare får stå för olyckor som sker på vägar vi inte äger.", 2),
    (9, 1, "Äldreomsorgen sköts bäst av kommunen, inte av kampanjmakare.", 3),
    (10, 2, "Ingen frågar oss som faktiskt kör bland dessa olyckor varje dag.", 1),
    (13, 2, "Skärp uppföljningen av besiktningen, sedan pratar vi om olyckor igen.", 2),
    (15, 2, "Åkerier i länet betalar redan för andras olyckor.", 0),
    (16, 1, "Äldreomsorgen kostar, och ingen vill säga vad det innebär i skatt.", 1),
    (5, 3, "Nu handlar allt om fordon, äldreomsorgen försvann på en dag.", 0),
    (13, 3, "Uppföljning kräver personal, det finns inte i budgeten.", 0),
    (0, 2, "Två veckor efter olyckorna i länet är rubrikerna borta igen.", 6),
    (2, 2, "Transportstyrelsen har siffror på olyckor per fordonstyp, läs dem.", 0),
    (10, 3, "Vi kör förbi dessa olyckor varje morgon, ingen politiker har frågat.", 2),
    (14, 2, "Skolan ser vilka som kör, olyckorna kommer inte som en överraskning.", 1),
    (16, 2, "Kostnaden för olyckorna i länet hamnar hos försäkringstagarna.", 1),
)

GROUPS = (
    ("Cynisk mix", CYNICAL_REACTIONS),
    ("Balanserad", BALANCED_REACTIONS),
    ("Realistisk modell", REALISTIC_REACTIONS),
)

TICKS = (
    Tick(key="d1", day=1, measurements=["opinion_snapshot"]),
    Tick(key="d2", day=2, measurements=["engagement_decay"]),
    Tick(key="d3", day=3, measurements=["phrase_propagation"]),
)


async def _stub_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic stand-in for OpenAI embeddings — shapes tone/style, not truth."""
    out: list[list[float]] = []
    for text in texts:
        vec = [0.0] * 16
        for i, ch in enumerate(text.lower()[:80]):
            vec[(ord(ch) + i) % 16] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        out.append([v / norm for v in vec])
    return out


def _agents() -> list[dict[str, object]]:
    agents: list[dict[str, object]] = [
        {"index": 0, "member_name": "Partikontot", "role": "injector"},
        {"index": 1, "member_name": "Nyhetskanalen", "role": "injector"},
    ]
    for offset, (name, *_rest) in enumerate(CITIZENS):
        agents.append(
            {
                "index": 2 + offset,
                "member_name": name,
                "persona_id": f"p-{offset}",
                "role": "population",
            }
        )
    return agents


def _personas() -> list[dict[str, object]]:
    return [
        {
            "persona_id": f"p-{offset}",
            "name": name,
            "bio": {
                "yrke": yrke,
                "age": age,
                "kön": kon,
                "ort": ort,
                "lutning": lutning,
                "livssituation": livssituation,
            },
        }
        for offset, (name, yrke, age, kon, ort, lutning, livssituation) in enumerate(CITIZENS)
    ]


def _bundle(label: str, reactions: tuple[tuple[int, int, str, int], ...]) -> RunBundle:
    posts = [
        {
            "post_id": 1,
            "user_id": 0,
            "content": CARE_INJECTION,
            "num_likes": 0,
            "num_shares": 1,
            "num_dislikes": 2,
            "created_at": 1,
            "role": "injector",
        },
        {
            "post_id": 2,
            "user_id": 1,
            "content": TRACTOR_INJECTION,
            "num_likes": 11,
            "num_shares": 4,
            "created_at": 5,
            "role": "injector",
        },
    ]
    comments = [
        {
            "comment_id": idx,
            "post_id": 1 if day == 1 else 2,
            "user_id": 2 + offset,
            "content": text,
            "num_likes": likes,
            "created_at": day * 4,
        }
        for idx, (offset, day, text, likes) in enumerate(reactions, start=1)
    ]
    bundle = RunBundle(
        label=label,
        run_id=101,
        run_name="Riksdag 2026 — äldreomsorg & A-traktorer",
        attempt_id=f"att_{label.split()[0].lower()}",
        seed=f"seed-{label}",
        engine="oasis",
        agents=_agents(),
        personas=_personas(),
        posts=posts,
        comments=comments,
        ticks_run=3,
        injection_texts=[CARE_INJECTION, TRACTOR_INJECTION],
        tick_markers=[
            {"tick_index": 0, "day": 1, "silent": False, "key": "d1", "rounds": 3, "time_start": 0, "time_end": 4},
            {"tick_index": 1, "day": 2, "silent": False, "key": "d2", "rounds": 3, "time_start": 5, "time_end": 9},
            {"tick_index": 2, "day": 3, "silent": True, "key": "d3", "rounds": 2, "time_start": 10, "time_end": 14},
        ],
        follows=[
            {"follower_id": 4, "followee_id": 2},
            {"follower_id": 5, "followee_id": 2},
            {"follower_id": 6, "followee_id": 3},
        ],
        action_histogram=[
            {"action": "like_post", "count": 34},
            {"action": "comment_post", "count": len(reactions)},
            {"action": "dislike_post", "count": 5},
            {"action": "follow", "count": 3},
        ],
        trace=[
            {
                "user_id": 5,
                "created_at": 6,
                "action": "interview",
                "info": '{"prompt": "Vad tänker du om budskapet om äldreomsorgen?", "response": "Det låter bra, men jag har hört det förut och bemanningen är kvar på samma nivå."}',
            },
            {
                "user_id": 9,
                "created_at": 7,
                "action": "interview",
                "info": '{"prompt": "Vilken fråga engagerar dig mest just nu?", "response": "Trafiken på vägarna här ute, den märks varje dag."}',
            },
        ],
    )
    bundle.measurements = build_measurements(
        list(TICKS),
        posts=bundle.posts,
        comments=bundle.comments,
        agents=bundle.agents,
        follows=bundle.follows,
        ticks_run=bundle.ticks_run,
    )
    return bundle


async def main() -> None:
    out_dir = Path("/opt/cursor/artifacts/riksdag-2026-snabbrapport")

    async def _no_llm(_messages, _model):
        raise AssertionError("quick report must not call DeepSeek")

    set_structured_completer(_no_llm)
    set_embedder(_stub_embed)
    try:
        html_path, _slots_path, _slots, timing = await generate_report_html(
            [_bundle(label, reactions) for label, reactions in GROUPS],
            out_dir=out_dir,
            title=(
                "Riksdag 2026 — äldreomsorg & A-traktorer "
                "(demo: 3 väljargrupper, stubbade embeddings)"
            ),
            locale="sv",
        )
        print(html_path, timing)
    finally:
        set_structured_completer(None)
        set_embedder(None)


if __name__ == "__main__":
    asyncio.run(main())
