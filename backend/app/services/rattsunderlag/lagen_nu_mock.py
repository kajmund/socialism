"""Deterministic lagen.nu corpus for tests and local research without MCP."""

from __future__ import annotations

from app.services.rattsunderlag.lagen_nu import LagenNuNotFoundError
from app.services.rattsunderlag.schemas import ForarbeteRef, LagtextRef, PraxisRef

_SFS: dict[str, LagtextRef] = {
    "2016:1145": LagtextRef(
        sfs_id="2016:1145",
        rubrik="Lag om offentlig upphandling",
        utdrag=(
            "4 kap. 1 § Upphandlande myndigheter ska behandla leverantörer "
            "på ett likvärdigt och icke-diskriminerande sätt samt genomföra "
            "upphandlingar på ett öppet sätt."
        ),
        url="https://lagen.nu/2016:1145",
        forarbete_referens="prop. 2015/16:195",
    ),
    "1972:207": LagtextRef(
        sfs_id="1972:207",
        rubrik="Skadeståndslag",
        utdrag=(
            "2 kap. 1 § Den som uppsåtligen eller av vårdslöshet vållar "
            "personskada eller sakskada ska ersätta skadan."
        ),
        url="https://lagen.nu/1972:207",
        forarbete_referens="prop. 1972:5",
    ),
    "1990:931": LagtextRef(
        sfs_id="1990:931",
        rubrik="Köplag",
        utdrag=(
            "17 § Varorna ska i fråga om art, mängd, kvalitet, andra "
            "egenskaper och förpackning stämma överens med avtalet."
        ),
        url="https://lagen.nu/1990:931",
    ),
}

_PRAXIS: dict[str, PraxisRef] = {
    "NJA 2018 s. 723": PraxisRef(
        referens="NJA 2018 s. 723",
        instans="Högsta domstolen",
        utdrag=(
            "Vid tolkning av ett kommersiellt avtal ska ordalydelsen ges "
            "avgörande betydelse om den är klar."
        ),
        url="https://lagen.nu/dom/nja/2018s723",
    ),
    "HFD 2019 ref. 65": PraxisRef(
        referens="HFD 2019 ref. 65",
        instans="Högsta förvaltningsdomstolen",
        utdrag=(
            "En upphandlande myndighet får inte utforma ett förfrågningsunderlag "
            "så att det otillbörligt gynnar eller missgynnar en leverantör."
        ),
        url="https://lagen.nu/dom/hfd/2019/ref.65",
    ),
    "NJA 2020 s. 3": PraxisRef(
        referens="NJA 2020 s. 3",
        instans="Högsta domstolen",
        utdrag=(
            "Skadeståndsskyldighet förutsätter adekvat kausalitet mellan "
            "den vårdslösa handlingen och skadan."
        ),
        url="https://lagen.nu/dom/nja/2020s3",
    ),
}

_FORARBETEN: dict[str, ForarbeteRef] = {
    "prop. 2015/16:195": ForarbeteRef(
        referens="prop. 2015/16:195",
        titel="Nytt rättsligt ramverk om offentlig upphandling",
        utdrag=(
            "Likabehandlingsprincipen innebär att alla leverantörer ska ges "
            "samma förutsättningar att delta i en upphandling."
        ),
        url="https://lagen.nu/prop/2015/16:195",
    ),
    "prop. 1972:5": ForarbeteRef(
        referens="prop. 1972:5",
        titel="Förslag till skadeståndslag",
        utdrag=(
            "Culparegeln i 2 kap. 1 § avses omfatta både uppsåt och vårdslöshet "
            "vid person- och sakskada."
        ),
        url="https://lagen.nu/prop/1972:5",
    ),
}


def _tokens(query: str) -> set[str]:
    return {part for part in query.lower().replace(":", " ").split() if part}


class MockLagenNuClient:
    async def search_law(self, query: str) -> list[LagtextRef]:
        tokens = _tokens(query)
        if not tokens or "xyzzy-no-hit" in tokens:
            return []
        hits: list[LagtextRef] = []
        if tokens & {"upphandling", "lou", "anbud", "leverantör", "leverantor"}:
            hits.append(_SFS["2016:1145"])
        if tokens & {"skadestånd", "skadestand", "skada", "vårdslöshet", "vardsloshet"}:
            hits.append(_SFS["1972:207"])
        if tokens & {"köp", "kop", "avtal", "vara", "fel"}:
            hits.append(_SFS["1990:931"])
        return hits

    async def get_sfs(self, sfs_id: str) -> LagtextRef:
        key = sfs_id.strip()
        if key not in _SFS:
            raise LagenNuNotFoundError(f"Unknown SFS id: {sfs_id}")
        return _SFS[key]

    async def search_case_law(self, query: str) -> list[PraxisRef]:
        tokens = _tokens(query)
        if not tokens or "xyzzy-no-hit" in tokens:
            return []
        hits: list[PraxisRef] = []
        if tokens & {"avtal", "köp", "kop", "tolkning"}:
            hits.append(_PRAXIS["NJA 2018 s. 723"])
        if tokens & {"upphandling", "lou", "anbud", "leverantör", "leverantor"}:
            hits.append(_PRAXIS["HFD 2019 ref. 65"])
        if tokens & {"skadestånd", "skadestand", "skada", "kausalitet"}:
            hits.append(_PRAXIS["NJA 2020 s. 3"])
        return hits

    async def get_forarbete(self, referens: str) -> ForarbeteRef:
        key = referens.strip()
        if key not in _FORARBETEN:
            raise LagenNuNotFoundError(f"Unknown förarbete: {referens}")
        return _FORARBETEN[key]
