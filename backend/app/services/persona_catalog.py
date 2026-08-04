"""Shared Swedish name/district/job catalogs for stub + LLM slot sampling."""

NAMES_F = ["Margareta", "Eva", "Linnéa", "Birgitta", "Karin", "Amanda", "Yasmin", "Ingrid"]
NAMES_M = ["Bengt", "Erik", "Mikael", "Hassan", "Sven", "Johan", "Kalle", "Anders"]
LASTN = [
    "Hellström",
    "Karlsson",
    "Berg",
    "Lindqvist",
    "Andersson",
    "Svensson",
    "Nilsson",
    "Al-Amin",
]
JOB_BY_CAT: dict[str, str] = {
    "vard": "Undersköterska",
    "industri": "Lagerarbetare",
    "utbildning": "Lärare",
    "handel": "Butiksbiträde",
    "tjansteman": "Handläggare",
    "ovrigt": "Pensionär",
}
DISTRICT_LABEL: dict[str, str] = {
    "hageby": "Distrikt A",
    "navestad": "Distrikt B",
    "lindo": "Distrikt C",
    "klockaretorpet": "Distrikt D",
    "centrum": "Centrum",
    "ovriga": "Övriga",
}
LEAN_LABEL: dict[str, str] = {
    "vanster": "Vänster",
    "mvanster": "Mitt-vänster",
    "mitt": "Mitt",
    "mhoger": "Mitt-höger",
    "hoger": "Höger",
}
TRAIT_BY_LEAN: dict[str, str] = {
    "vanster": "Engagerad i lokal facklig verksamhet.",
    "mvanster": "Trött på partiledningen men röstar av vana.",
    "mitt": "Svårflirtad, byter parti mellan val.",
    "mhoger": "Vill se hårdare tag och lägre skatter.",
    "hoger": "Cynisk mot politiker, litar mest på siffror.",
}
WRITING_TRAITS: list[str] = [
    "Kort och rakt på sak, lite otålig.",
    "Varm men bestämd, gärna med personliga exempel.",
    "Sarkastisk och snabb att ifrågasätta.",
    "Eftertänksam, gärna med retoriska frågor.",
    "Emotionell och bildrik, ibland med vardagsanekdoter.",
    "Saklig och nyanserad, ogillar överdrifter.",
    "Ironisk humor, gillar att vända på frågor.",
    "Direkt och vardaglig, pratar som i kön.",
    "Försiktig men engagerad, vill höra fler sidor.",
    "Passionerad och principfast, ibland hård i tonen.",
    "Avslappnad och konversationell, som i en gruppchatt.",
    "Analytisk men jordnära, gärna med jämförelser.",
]
