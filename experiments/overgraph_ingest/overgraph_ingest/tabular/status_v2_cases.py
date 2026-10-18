"""Frozen P0_v2 eval cases. False ANSWERED is more expensive than UNCERTAIN."""

from __future__ import annotations

from dataclasses import dataclass

from overgraph_ingest.tabular.contract import ANSWERED, NOT_FOUND, UNCERTAIN
from overgraph_ingest.tabular.dense_errors import AVTAL_13_GOLD
from overgraph_ingest.tabular.prompt_dev import SELECTION_CELLS

# Product choice, documented before the run: Avtal 09/17 have topical
# nearby units but no general cap. Gold is UNCERTAIN, not NOT_FOUND.
NEARBY_IS_UNCERTAIN = True
COSTLIER_ERROR = "false_answered"

ROLE_TRUE = "selection_true"
ROLE_NEG = "selection_neg"
ROLE_ERROR = "error"
ROLE_HARD_POS = "hard_pos"
ROLE_HARD_NEG = "hard_neg"
ROLE_RETRIEVAL = "retrieval_error"


@dataclass(frozen=True)
class StatusCase:
    case_id: str
    relative_path: str
    question_id: str
    role: str
    list_name: str
    expected_status: str
    gold_contains: str = ""
    nearby_contains: tuple[str, ...] = ()
    candidate_keys: tuple[str, ...] | None = None
    prompt_scored: bool = True


def _sel(index: int, role: str, expected: str, *, gold: str = "", nearby: tuple[str, ...] = ()) -> StatusCase:
    path, question_id = SELECTION_CELLS[index]
    return StatusCase(
        case_id=f"{role}:{path}:{question_id}:hybrid",
        relative_path=path,
        question_id=question_id,
        role=role,
        list_name="hybrid",
        expected_status=expected,
        gold_contains=gold,
        nearby_contains=nearby,
    )


SELECTION_TRUE = (
    _sel(0, ROLE_TRUE, ANSWERED, gold="Annars förlängs det med [tre (3)] år i taget."),
    _sel(1, ROLE_TRUE, ANSWERED, gold="Uppsägningstiden är tre (3) månader för båda parter"),
    _sel(2, ROLE_TRUE, ANSWERED, gold="Ansvaret är begränsat till [100 %] av det totala arvodet"),
    _sel(3, ROLE_TRUE, ANSWERED, gold="Mottagaren ska hålla Konfidentiell Information hemlig"),
    _sel(4, ROLE_TRUE, ANSWERED, gold="dock inte vid uppsåt, grov vårdslöshet eller brott mot sekretessåtagandet"),
)

SELECTION_NEG = (
    _sel(5, ROLE_NEG, NOT_FOUND),
    _sel(6, ROLE_NEG, NOT_FOUND),
    _sel(7, ROLE_NEG, UNCERTAIN, nearby=("ansvarar för skador",)),
    _sel(8, ROLE_NEG, NOT_FOUND),
    _sel(9, ROLE_NEG, NOT_FOUND),
)

ERROR_CASES = (
    StatusCase(
        case_id="error:Avtal_13:confidentiality:dense",
        relative_path="Avtal_13_Avgangsvederlagsavtal.docx",
        question_id="confidentiality",
        role=ROLE_ERROR,
        list_name="dense",
        expected_status=ANSWERED,
        gold_contains=AVTAL_13_GOLD,
        nearby_contains=("Innehållet i detta avtal är konfidentiellt",),
    ),
    StatusCase(
        case_id="error:Avtal_09:liability-cap:dense",
        relative_path="Avtal_09_Kundbearbetningsforbud_varvningsforbud.docx",
        question_id="liability-cap",
        role=ROLE_ERROR,
        list_name="dense",
        expected_status=UNCERTAIN,
        nearby_contains=("Vite",),
    ),
    StatusCase(
        case_id="error:Avtal_17:liability-cap:dense",
        relative_path="Avtal_17_Hyresavtal_lokal.docx",
        question_id="liability-cap",
        role=ROLE_ERROR,
        list_name="dense",
        expected_status=UNCERTAIN,
        nearby_contains=("driftavbrott",),
    ),
)

RETRIEVAL_CASES = (
    StatusCase(
        case_id="retrieval:Avtal_13:confidentiality:hybrid",
        relative_path="Avtal_13_Avgangsvederlagsavtal.docx",
        question_id="confidentiality",
        role=ROLE_RETRIEVAL,
        list_name="hybrid",
        expected_status=ANSWERED,
        gold_contains=AVTAL_13_GOLD,
        nearby_contains=("Innehållet i detta avtal är konfidentiellt",),
        prompt_scored=False,
    ),
)

HARD_POS = (
    StatusCase(
        case_id="hard_pos:Avtal_19:auto-renewal",
        relative_path="Avtal_19_Andrahandsuthyrning_lokal.docx",
        question_id="auto-renewal",
        role=ROLE_HARD_POS,
        list_name="constructed",
        expected_status=ANSWERED,
        gold_contains="Därefter förlängs den med [tolv] månader i taget",
        nearby_contains=("Huvudavtalet upphör",),
        candidate_keys=(
            "39a306c4dc92aa21f509f4ff6bb05ef9c21dea4a163618345d5bfd59f6bf255c",
            "3e79ab2b3e4f1c30879756b7998b8324a23ddb2a65c856d26b2c534698384bcd",
            "3ee405d7af33918dab472677dcbc1b422e1846b0433bae36221671ea3f7c5f48",
            "036600d185e49b3b7c5d44a0f2642be00793f65121f9a2cc06877a7e87aaddee",
            "204bbce69eea81a57dd7c97033b48158c72803d9edf92d6481b130855e20487e",
        ),
    ),
    StatusCase(
        case_id="hard_pos:Avtal_21:notice-period",
        relative_path="Avtal_21_Parkeringsavtal.docx",
        question_id="notice-period",
        role=ROLE_HARD_POS,
        list_name="constructed",
        expected_status=ANSWERED,
        gold_contains="tre (3)] månaders uppsägningstid",
        nearby_contains=("tills vidare",),
        candidate_keys=(
            "59cfa09e285dc20e61aa5ccdf848ffa2c98280b75917e290bc4b4d3e379ff3b3",
            "e75dbeb1c12c9a811ca6135510f8c04480d838e99ec44e27ba79d950a396fdf2",
            "7bd5fe08f3dfd201e8abf5b2fa986088eca1cff06f7e4feb4dfcd9713e2767bc",
            "5d554377e10b4f2271d7e1bf1accd9ca6b965d37549f4edd8068280b5d56d54d",
            "b1df7435667e4ca5a46ad85c08599544096032a1b4f40f1521a4901acba166e8",
        ),
    ),
    StatusCase(
        case_id="hard_pos:Avtal_31:liability-cap",
        relative_path="Avtal_31_Leveransavtal.docx",
        question_id="liability-cap",
        role=ROLE_HARD_POS,
        list_name="constructed",
        expected_status=ANSWERED,
        gold_contains="sammanlagda ansvar enligt detta avtal är begränsat till köpeskillingen",
        nearby_contains=("vite med [0,5] procent",),
        candidate_keys=(
            "4f66b90f733f1c58f1ad063949e62751e0a8cdb95136d506e2572791cde82a02",
            "296eecedc2703fc48609e6818c44aef8f4f0a8f781efc8d146beb074f74d39d7",
            "a97666e550207f5fad05b16b9daf29615f4ae27d52e16cc1f0f12b1744cc0029",
            "62d85f844f80e5a50abd8cdc35eba8c7f6742ab5653b415eea9beae974eccbd9",
            "3dd30759ad5a3c93684efaa43b35b0414b17809ed28b55b5035f3c9d2d34e19e",
        ),
    ),
    StatusCase(
        case_id="hard_pos:Avtal_34:confidentiality",
        relative_path="Avtal_34_Aterforsaljaravtal.docx",
        question_id="confidentiality",
        role=ROLE_HARD_POS,
        list_name="constructed",
        expected_status=ANSWERED,
        gold_contains="behandla konfidentiell information om den andra parten",
        candidate_keys=(
            "4a5ffcfa7ca13933ed18e89e3c8c8b8933695d9ecc054cb5a5605cbc8a058362",
            "c75332c38d763bf2eacee8fd29d02ea42cbebb98477b71e3d147bcb20b3fff1e",
            "f8dfe9025e49928502fb657d64f144704c999e6882c07c5fe4db6009085ba470",
            "58e482bcb8cd2b1994f2d904e911a894265ba5b6709e44088177f67546dd8dca",
            "7980c1a8297fdd0504ae84c9f98693ee5135c405675becbf18bff3034969020b",
        ),
    ),
    StatusCase(
        case_id="hard_pos:Avtal_46:carveout",
        relative_path="Avtal_46_SaaS_avtal.docx",
        question_id="liability-secrecy-carveout",
        role=ROLE_HARD_POS,
        list_name="constructed",
        expected_status=ANSWERED,
        gold_contains="gäller inte vid uppsåt, grov vårdslöshet eller brott mot sekretess",
        nearby_contains=("sammanlagda ansvar per avtalsår är begränsat",),
        candidate_keys=(
            "c495f54e522a9f23af5ae814cbf0692715495d1d50b28e2879993b3456fc3ac8",
            "5966e3a929c10c11e8ba2307e1ab32df0d86962b02b16e2082ee62ea25393e55",
            "7a3e696af5e1199fd48a7e6d2d3e8af4e9b081119640ad0070be94a5dac198f1",
            "66f51762a124f14e8b3fc2748ea9c56e34c6df7094a360807a91fd85269214bc",
            "28c958463705452eafe67febca7f69c8a1e1f5080ad55df10630d3a1db158c16",
        ),
    ),
)

HARD_NEG = (
    StatusCase(
        case_id="hard_neg:Avtal_38:liability-cap",
        relative_path="Avtal_38_Projektavtal_fast_pris.docx",
        question_id="liability-cap",
        role=ROLE_HARD_NEG,
        list_name="constructed",
        expected_status=UNCERTAIN,
        nearby_contains=("Förseningsvite",),
        candidate_keys=(
            "5ac9fe84caf5a6b92640c2f9df33ea9c4766340fc4d73281a841aa354fa5e857",
            "2c3f2b306778bb588e1368241c65bf74b1b07e1c0a19e091a11d0327a6441b07",
            "3fed5d53e1801697457194b7e207f4502792bcf4cac0433a55d229b8d00b1028",
            "9f845a5482ab9478b93b9192a90c4bd00e9cdab628427d2cf62505a7dd574fd6",
            "3040f786c421a081b0a15593f6512ea7deb0a9540014720ec28b1519bb091d9c",
        ),
    ),
    StatusCase(
        case_id="hard_neg:Avtal_70:confidentiality",
        relative_path="Avtal_70_Offertvillkor_orderbekraftelse.docx",
        question_id="confidentiality",
        role=ROLE_HARD_NEG,
        list_name="constructed",
        expected_status=UNCERTAIN,
        nearby_contains=("Offertens innehåll, inklusive priser, är konfidentiellt",),
        candidate_keys=(
            "c19ccc5e31c39bd8747a7f88454c39f662a08c22b5913690e0c54ff254d16248",
            "59f65dd39f16cef4bb9c588bb0de59fae01c6c048086cfb2ec422e26a0cf5dbf",
            "8caacf9f3a000fb1d6b40e66a315904b03b6799448c51142ffcc1aed34b8ee60",
            "d360a88c4fdd6b8fba56a1f27361d398bf701f3dd8352bdcafac5421df5be389",
            "180fca1f76c058478662f80b395f30c7aad7edce2d082c091c40c48d1efcc79e",
        ),
    ),
    StatusCase(
        case_id="hard_neg:Avtal_14:auto-renewal",
        relative_path="Avtal_14_Tjanstebilsavtal.docx",
        question_id="auto-renewal",
        role=ROLE_HARD_NEG,
        list_name="constructed",
        expected_status=UNCERTAIN,
        nearby_contains=("tills vidare",),
        candidate_keys=(
            "2cc0a83423c5d8f1422205ac219ba0b48c1fb38e1f88c0501ae80667c6dec11a",
            "c96bf3a67d209f06a0a4ddd1952224595c41b25b39c71ae7550ebb8ef4108e10",
            "dd60b434b1bc7894270f69346889da53244680ac9c61045b6707e1bbf0de851b",
            "bc27e374df044b39bf16dbd0fb8307f683ed88939cbc2242117c7b36af777f18",
            "e84065bce831d9f5d29478e726c68eaf3f998af1cc3fe6e8cf4b3484eddd73cb",
        ),
    ),
    StatusCase(
        case_id="hard_neg:Avtal_19:notice-period",
        relative_path="Avtal_19_Andrahandsuthyrning_lokal.docx",
        question_id="notice-period",
        role=ROLE_HARD_NEG,
        list_name="constructed",
        expected_status=UNCERTAIN,
        nearby_contains=("Huvudavtalet upphör",),
        candidate_keys=(
            "3e79ab2b3e4f1c30879756b7998b8324a23ddb2a65c856d26b2c534698384bcd",
            "3ee405d7af33918dab472677dcbc1b422e1846b0433bae36221671ea3f7c5f48",
            "036600d185e49b3b7c5d44a0f2642be00793f65121f9a2cc06877a7e87aaddee",
            "204bbce69eea81a57dd7c97033b48158c72803d9edf92d6481b130855e20487e",
            "8a3f3d1cd8ae0accdb5dfcb0be0f2f3a45230fb8a1f6df125d16792d779c095a",
        ),
    ),
    StatusCase(
        case_id="hard_neg:Avtal_45:auto-renewal",
        relative_path="Avtal_45_Fullmakt.docx",
        question_id="auto-renewal",
        role=ROLE_HARD_NEG,
        list_name="constructed",
        expected_status=UNCERTAIN,
        nearby_contains=("tills vidare",),
        candidate_keys=(
            "bcaa00dec350a1125022356096c7d9eb6c8bad02c42454db77364520dfadf97e",
            "c3e5409e8fd42d58b0b95da0d5484804950d8b89e0993317a9cc492d625e1fd0",
            "22d85a25ecb0bdbf774e25ae79b7b7e3cb2c3920c28b170e0cd86816bc3b4bab",
            "21fccdc0ca30316c60e4e0478330d03aca815d0257d55a36fba00580d0179293",
            "2c3c228a4186f325349fd305f8753a86d32619f0945fb3d27fbef56b02a328be",
        ),
    ),
)

# Named exclusions were written after these measured or gold-noted errors.
EXCLUSION_PROVENANCE = {
    "vite": "Avtal_09 and Avtal_08 dense false ANSWERED",
    "friskrivning för en enskild skadetyp": "Avtal_17 dense driftavbrott",
    "avtalets eget innehåll är konfidentiellt": "Avtal_13 cited 6.3",
    "tills vidare": "Avtal_04 gold_narrow, plus padding so Räknas inte is not NOT_FOUND",
    "uppsägning vid avtalsbrott, hävning, tilläggsavtal": "Avtal_36 and Avtal_10",
    "undantag från en slutlig uppgörelse": "Avtal_12 carveout",
}

HARD_NEG_SPLIT = {
    "hard_neg:Avtal_38:liability-cap": "in_distribution:vite",
    "hard_neg:Avtal_70:confidentiality": "in_distribution:avtalets_innehall",
    "hard_neg:Avtal_14:auto-renewal": "in_distribution:tills_vidare",
    "hard_neg:Avtal_19:notice-period": "in_distribution:havning_huvudavtal",
    "hard_neg:Avtal_45:auto-renewal": "in_distribution:tills_vidare",
}

# Near-misses whose wording is not a named D exclusion. The exclusions
# were written before these documents were examined.
HOLDOUT_SPLIT = {
    "holdout:Avtal_35:auto-renewal": "unseen:optional_renewal_right",
    "holdout:Avtal_92:liability-cap": "unseen:settlement_no_further_claims",
    "holdout:Avtal_20:liability-cap": "unseen:liability_insurance",
    "holdout:Avtal_76:liability-cap": "unseen:abl_statutory_liability",
    "holdout:Avtal_52:liability-cap": "unseen:hold_harmless_product_insurance",
}

NAMED_EXCLUSION_NEEDLES = (
    "vite",
    "straffavgift",
    "sanktion",
    "tills vidare",
    "avtalets eget innehåll",
    "hävning",
    "tilläggsavtal",
    "avtalsbrott",
    "enskild skadetyp",
    "slutlig uppgörelse",
)

HOLDOUT_NEG = (
    StatusCase(
        case_id="holdout:Avtal_35:auto-renewal",
        relative_path="Avtal_35_Franchiseavtal.docx",
        question_id="auto-renewal",
        role=ROLE_HARD_NEG,
        list_name="constructed",
        expected_status=UNCERTAIN,
        nearby_contains=("rätt att förlänga",),
        candidate_keys=(
            "b6692921837876dd01cb7e98b7b534f0d7598d42c8a64b1e54ddd90d15f80d5a",
            "8c6e08a36fcf37612abdc519982d95d0b60a78c0254eefa3dc10119aff0b2016",
            "55db6ae059cf053a87d9d7d07741860841666531fab3a4eed6104ef3c8f3ed4d",
            "9a9c0a99fff073651c7fd482b8a92d3c46d269b990d1fa2939afb3e65c44c5c9",
            "474bc222f00805b4c198dfb829bfae447318deb86923df114a6346646a3acaa8",
        ),
    ),
    StatusCase(
        case_id="holdout:Avtal_92:liability-cap",
        relative_path="Avtal_92_Forlikningsavtal.docx",
        question_id="liability-cap",
        role=ROLE_HARD_NEG,
        list_name="constructed",
        expected_status=UNCERTAIN,
        nearby_contains=("slutligt reglerade",),
        candidate_keys=(
            "a1462f395082e36207eafd2145becb31e1bcbf08c59e8ff1a07f50707a4cea87",
            "16fc7c0cca4e8f15ff475bebb950f7d098fadfaa29f443ce58fadd9258ea8ca6",
            "f5a281e7693c406e76833d99fe33c36f47c07460dfcda5f292853b3538bdf33d",
            "cab41c69de1817f24762f4021bee07bc516c93e9ab0580f5dc3ded5f7078e067",
            "8a69e55c0cea21cab9cd54e30a2c4e5da47dddb378d680544d833d08e9db99fa",
        ),
    ),
    StatusCase(
        case_id="holdout:Avtal_20:liability-cap",
        relative_path="Avtal_20_Arrendeavtal_lagenhetsarrende.docx",
        question_id="liability-cap",
        role=ROLE_HARD_NEG,
        list_name="constructed",
        expected_status=UNCERTAIN,
        nearby_contains=("ansvarsförsäkring",),
        candidate_keys=(
            "2f421e333cda20a170e3444123032f7296f751925be5cd7094bd62c633b45b63",
            "1a9eb9c9490635c10fa1bb4fdbe69cff3d8776be276b768c43b05aad6dd6f8f3",
            "f42f95a3fa14f2daffbe367a31400b8f0a15e14212fef94ff0483b1321779bed",
            "674d198a99651a928658e955c8310ee64972a83315d35127141956c803d57662",
            "1264acaf1cacc616c6c9b8486394ba2c82876a871b7c7ef4781f0deb896f8da4",
        ),
    ),
    StatusCase(
        case_id="holdout:Avtal_76:liability-cap",
        relative_path="Avtal_76_Uppdragsbrev_revision.docx",
        question_id="liability-cap",
        role=ROLE_HARD_NEG,
        list_name="constructed",
        expected_status=UNCERTAIN,
        nearby_contains=("29 kap. aktiebolagslagen",),
        candidate_keys=(
            "a2dde74f10286c2b7e235eaa784b2de25cad65418a410d4f4cb6c4dca5c0130b",
            "dca1dd5b247e433917d2ba5a058417780af74ae1c9afcff4f154bf69d457c4b3",
            "4ecdcdf3e5ba1d923ab5f473e06771d4e2c7072a9241a13b7571f8f4517f353b",
            "7c94c5e1d79d2fab251a8aeb0921c390e7402f928742cf1b505535d4f963298d",
            "126749285f87e44ffbedd063e42d6e9410c028ce5188e21c06320d34c9ef7128",
        ),
    ),
    StatusCase(
        case_id="holdout:Avtal_52:liability-cap",
        relative_path="Avtal_52_Licensavtal_varumarke.docx",
        question_id="liability-cap",
        role=ROLE_HARD_NEG,
        list_name="constructed",
        expected_status=UNCERTAIN,
        nearby_contains=("skadeslös",),
        candidate_keys=(
            "05e29ff99947cd215715e0c3f10ae4e79e9b212808a61424659b45eac1d1f883",
            "17479ac3784fe9f0c4b33a7a95d282360bd3fbf43fdf8ed38e244349aac997e7",
            "ae2423ec1cf4bc1ab5e0b31834c4efd9d525dcbdb8d054f01ffc99f0359b1d46",
            "f90d48a99e75cbddde305081d350aafae5986d70afaac30380368d73f8702bed",
            "7fa30182b8e7e8748985b5d96be3ae3f68ad171aaa363545ab037ad826ecc0cc",
        ),
    ),
)

EVAL_CASES = SELECTION_TRUE + SELECTION_NEG + ERROR_CASES + RETRIEVAL_CASES + HARD_POS + HARD_NEG
REPEAT_CASE_IDS = (
    "error:Avtal_09:liability-cap:dense",
    "error:Avtal_17:liability-cap:dense",
)
PERM_CASE_ID = "error:Avtal_13:confidentiality:dense"
