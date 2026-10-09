"""Expert-chat prompt defaults that no longer fit in the catalog module."""

from __future__ import annotations

import json


def _field(
    *,
    key: str,
    label_sv: str,
    label_en: str,
    hint_sv: str,
    hint_en: str,
    default_sv: str,
    default_en: str,
) -> dict:
    return {
        "key": key,
        "section": "chat",
        "label": {"sv": label_sv, "en": label_en},
        "hint": {"sv": hint_sv, "en": hint_en},
        "defaults": {"sv": default_sv, "en": default_en, "nb": default_sv},
    }


def expert_chat_prompt_fields() -> list[dict]:
    return [
        _field(
            key="chat.expert.reasoning_assessment",
            label_sv="Expertchatt — bedöm resonemangsbehov",
            label_en="Expert chat — assess reasoning need",
            hint_sv="Jev-kriterier för automatisk val av Snabb, Balanserad eller Djup.",
            hint_en="Jev criteria for automatic Fast, Balanced, or Deep selection.",
            default_sv=_reasoning_assessment_questions("sv"),
            default_en=_reasoning_assessment_questions("en"),
        ),
        _field(
            key="chat.expert.spawn_workers",
            label_sv="Expertchatt — delegera deluppgifter",
            label_en="Expert chat — delegate subtasks",
            hint_sv="Beskrivning av verktyget spawn_workers.",
            hint_en="Description of the spawn_workers tool.",
            default_sv=(
                "spawn_workers delegerar avgränsade undersökningar till tillfälliga "
                "workers. Använd det när uppgiften kan delas och köras parallellt. "
                "Workers får bara läsa och returnera JSON. Du syntetiserar, svarar "
                "användaren och gör sidoeffekter som markering. Ett anrop är en batch. "
                "worker_profile är fast eller balanced. Varje task kräver task, scope "
                "(source_id och ids från outline), context, allowed_tools och "
                "output_schema. allowed_tools får bara vara read_source och "
                "search_knowledge."
            ),
            default_en=(
                "spawn_workers delegates bounded investigations to temporary workers. "
                "Use it when the task can be split and run in parallel. Workers may "
                "only read and return JSON. You synthesize, answer the user, and "
                "perform side effects such as highlighting. One call is one batch. "
                "worker_profile is fast or balanced. Each task requires task, scope "
                "(source_id and ids from the outline), context, allowed_tools, and "
                "output_schema. allowed_tools may only be read_source and "
                "search_knowledge."
            ),
        ),
        _field(
            key="chat.expert.worker_task",
            label_sv="Expertchatt — worker-instruktion",
            label_en="Expert chat — worker instruction",
            hint_sv="Platshållare: {expert_name}, {task}, {context}, {scope_json}, {schema_json}.",
            hint_en="Placeholders: {expert_name}, {task}, {context}, {scope_json}, {schema_json}.",
            default_sv=(
                "Du är en tillfällig worker åt experten {expert_name}. Undersök bara "
                "din deluppgift. Returnera enbart JSON som matchar schemat. Ingen "
                "användartext. Stanna inom scope. Skapa, markera eller delegera inte.\n"
                "Uppgift: {task}\n"
                "Kontext: {context}\n"
                "Scope: {scope_json}\n"
                "Schema: {schema_json}"
            ),
            default_en=(
                "You are a temporary worker for expert {expert_name}. Investigate only "
                "your subtask. Return JSON that matches the schema and nothing else. "
                "No user-facing text. Stay inside scope. Do not create, highlight, or "
                "delegate.\n"
                "Task: {task}\n"
                "Context: {context}\n"
                "Scope: {scope_json}\n"
                "Schema: {schema_json}"
            ),
        ),
        _field(
            key="chat.expert.consult_tool",
            label_sv="Expertchatt — fråga en kollega",
            label_en="Expert chat — ask a colleague",
            hint_sv="Instruktion för verktyget ask_expert.",
            hint_en="Instruction for the ask_expert tool.",
            default_sv=(
                "ask_expert är ett verktygsanrop. Det är det enda sättet en kollega får "
                "frågan. I samma tur: skriv en kort egen mening i första person om att "
                "du frågar en kollega, och anropa ask_expert. Välj orden själv. Ta inte "
                "med kollegans svar i den meningen. Sätt argumentet question till en "
                "fristående och tydlig formulering. Gör anropet när frågan ligger "
                "utanför din kompetens, när användaren ber dig fråga en kollega, när "
                "användaren bekräftar en formulering, och när användaren säger att "
                "frågan inte skickades eller ber dig skicka den igen. En mening utan "
                "verktygsanropet når ingen. Härma inte svar som bara säger att frågan "
                "är skickad. Fråga inte om lov igen när användaren redan bett dig "
                "skicka. Anropa inte verktyget när du själv kan besvara frågan. Skriv "
                "inte verktygets namn, JSON eller XML."
            ),
            default_en=(
                "ask_expert is a tool call. It is the only way a colleague receives the "
                "question. In the same turn: write one short first-person sentence of "
                "your own that you are asking a colleague, and call ask_expert. Choose "
                "the words yourself. Do not include the colleague's answer in that "
                "sentence. Set question to a clear, standalone formulation. Make the "
                "call when the question is outside your competence, when the user asks "
                "you to ask a colleague, when the user confirms a formulation, and when "
                "the user says the question was never sent or asks you to send it "
                "again. A sentence without the tool call reaches no one. Do not imitate "
                "replies that only say the question was sent. Do not ask permission "
                "again when the user has already asked you to send it. Do not call the "
                "tool when you can answer the question yourself. Do not write the tool "
                "name, JSON, or XML."
            ),
        ),
        _field(
            key="chat.expert.tool_ack",
            label_sv="Expertchatt — kort koll",
            label_en="Expert chat — short check",
            hint_sv="Meningen experten själv väljer innan ett verktyg.",
            hint_en="The sentence the expert chooses before a tool.",
            default_sv=(
                "När frågan kräver ett uppslag räcker inte en mening. Anropa verktyget i "
                "samma tur. Skriv en kort egen mening i första person om att du tar reda "
                "på det. Välj orden själv. Ta inte med resultatet och skriv inte "
                "verktygets namn, JSON eller XML. Om verktygsresultatet har status "
                "deferred ska du inte säga något mer i den turen. Ett meddelande som "
                "börjar med [[underlag]] är inte användaren: väv in texten efter markören "
                "och läs inte upp markören."
            ),
            default_en=(
                "When the question needs a lookup, a sentence is not enough. Call the tool "
                "in the same turn. Write one short first-person sentence of your own that "
                "you are looking it up. Choose the words yourself. Do not include the "
                "result or the tool name, JSON, or XML. If the tool result has status "
                "deferred, say nothing more in that turn. A message that starts with "
                "[[underlag]] is not the user: weave in the text after the marker and do "
                "not read the marker aloud."
            ),
        ),
        _field(
            key="chat.expert.tool_result",
            label_sv="Expertchatt — väv in verktygsresultat",
            label_en="Expert chat — weave in a tool result",
            hint_sv="Platshållare: {result}",
            hint_en="Placeholder: {result}",
            default_sv=(
                "Underlag som just kom tillbaka:\n{result}\n\nSvara i första person och väv "
                "in underlaget. Om användaren har sagt något mer, svara på det också. Hitta "
                "inte på utöver underlaget. Skriv inte verktygets namn, JSON eller XML."
            ),
            default_en=(
                "Material that just came back:\n{result}\n\nAnswer in first person and weave "
                "in the material. If the user has said something more, answer that too. Do "
                "not invent anything beyond the material. Do not write the tool name, JSON, "
                "or XML."
            ),
        ),
        _field(
            key="chat.expert.evidence_tool",
            label_sv="Expertchatt — slå upp tidigare research",
            label_en="Expert chat — look up previous research",
            hint_sv="Instruktion för verktyget lookup_research_evidence.",
            hint_en="Instruction for the lookup_research_evidence tool.",
            default_sv=(
                "Du har verktyget lookup_research_evidence. Anropa det när frågan kan "
                "besvaras av tidigare fryst research för kunden. Anropa det inte för "
                "småprat eller när du redan kan svara utan källor. Sätt argumentet "
                "question till en fristående formulering av det som ska slås upp. "
                "Använd bara evidens som faktiskt besvarar frågan och hänvisa till "
                "använda belägg med [R1], [R2] och så vidare. Om verktyget inte hittar "
                "något ska du säga det. Starta inte research och fyll inte luckan med "
                "antaganden. Skriv inte verktygets namn, JSON eller XML i svaret."
            ),
            default_en=(
                "You have the lookup_research_evidence tool. Call it when the question "
                "can be answered from the customer's previously frozen research. Do not "
                "call it for small talk or when you can already answer without sources. "
                "Set the question argument to a standalone formulation of what to look "
                "up. Use evidence only when it actually answers the question and cite "
                "used support as [R1], [R2], and so on. If the tool finds nothing, say "
                "so. Do not start research or fill the gap with assumptions. Do not "
                "write the tool name, JSON, or XML in the reply."
            ),
        ),
        _field(
            key="chat.expert.tool_relevance",
            label_sv="Expertchatt — verktygsrelevans",
            label_en="Expert chat — tool relevance",
            hint_sv="Jev-fråga för hur väl ett verktygs syfte matchar den aktuella intentionen. Platshållare: {name}, {description}.",
            hint_en="Jev question for how well a tool's purpose matches the current intention. Placeholders: {name}, {description}.",
            default_sv=_tool_relevance("sv"),
            default_en=_tool_relevance("en"),
        ),
        _field(
            key="chat.expert.tool_relevance_rank",
            label_sv="Expertchatt — rådgivande verktygsrankning",
            label_en="Expert chat — advisory tool ranking",
            hint_sv="Instruktion som följer med jev_relevance på exponerade verktyg.",
            hint_en="Instruction that accompanies jev_relevance on exposed tools.",
            default_sv=(
                "jev_relevance anger hur starkt verktygets syfte semantiskt matchar den "
                "aktuella intentionen. Den är inte sannolikheten att anropet lyckas och "
                "inte confidence för resultatet. Om frågan kräver uppslag i dokument, "
                "kunskap, bolag eller andra livekällor måste du anropa minst ett verktyg "
                "i samma tur. Välj det högst rankade eller ett lägre rankat som faktiskt "
                "hämtar det som saknas. Hoppa över verktyg bara vid hälsning, bekräftelse "
                "eller något som redan står i den här turens synliga kontext."
            ),
            default_en=(
                "jev_relevance says how strongly the tool's purpose semantically matches "
                "the current intention. It is not the probability that the call succeeds "
                "and not confidence in the result. If the question needs a lookup in "
                "documents, knowledge, companies, or other live sources, you must call at "
                "least one tool in the same turn. Choose the highest ranked tool or a "
                "lower ranked one that actually fetches what is missing. Skip tools only "
                "for a greeting, an acknowledgement, or something already in this turn's "
                "visible context."
            ),
        ),
        _field(
            key="chat.expert.live_speech_delivery",
            label_sv="Expertchatt — uttryck i Live Speech",
            label_en="Expert chat — Live Speech delivery",
            hint_sv="Känslo- och framförandetaggar för Eleven v4 Turbo.",
            hint_en="Emotion and delivery tags for Eleven v4 Turbo.",
            default_sv=(
                "Svaret ska läsas upp med Eleven v4 Turbo. Lägg sparsamt in naturliga "
                "framförandetaggar där de förbättrar uttrycket. Tillåtna taggar är "
                "[curious], [crying], [mischievously], [whispers], [shouts], [laughs], "
                "[clears throat] och [sighs]. Använd exakt hakparentesformatet. "
                "Taggarna är styrdata för rösten, inte text som ska förklaras för användaren."
            ),
            default_en=(
                "The response will be spoken with Eleven v4 Turbo. Sparingly add natural "
                "delivery tags where they improve expression. Allowed tags are [curious], "
                "[crying], [mischievously], [whispers], [shouts], [laughs], [clears throat], "
                "and [sighs]. Use the exact square-bracket format. The "
                "tags are voice control data, not text to explain to the user."
            ),
        ),
        _field(
            key="chat.expert.live_speech_opening",
            label_sv="Expertchatt — öppning i Live Speech",
            label_en="Expert chat — Live Speech opening",
            hint_sv="Första talade repliken när röstsamtalet startar.",
            hint_en="First spoken line when the voice session starts.",
            default_sv=(
                "Du öppnar röstsamtalet. Svara med JSON {\"phrase\":\"...\",\"silence\":false} "
                "eller silence. En eller två korta talade meningar som tar upp tråden från "
                "senaste chatten. Var konkret om det ni just pratade om. Hitta inte på nya "
                "fakta. Ingen sammanfattning, ingen verktygsplan och inte hur kan jag hjälpa. "
                "Om historiken saknas, hälsa kort som experten."
            ),
            default_en=(
                "You are opening the voice session. Reply with JSON "
                "{\"phrase\":\"...\",\"silence\":false} or silence. One or two short spoken "
                "sentences that pick up the latest chat. Be concrete about what you just "
                "discussed. Do not invent facts. No summary, no tool plan, and no how can I "
                "help. If there is no history, greet briefly as the expert."
            ),
        ),
        _field(
            key="chat.expert.live_speech_listener",
            label_sv="Expertchatt — lyssnarsignal i Live Speech",
            label_en="Expert chat — Live Speech listener cue",
            hint_sv="Kort ljud medan användaren talar länge.",
            hint_en="Short cue while the user speaks at length.",
            default_sv=(
                "Du lyssnar på användaren. Svara med JSON {\"phrase\":\"...\",\"silence\":false} "
                "eller {\"phrase\":\"\",\"silence\":true}. phrase är en till tre ord, en "
                "lyssnarsignal som mm, okej eller intressant. Hitta på en naturlig variant. "
                "Svara inte på innehållet, ställ ingen fråga och upprepa inte en redan sagd fras."
            ),
            default_en=(
                "You are listening to the user. Reply with JSON {\"phrase\":\"...\",\"silence\":false} "
                "or {\"phrase\":\"\",\"silence\":true}. phrase is one to three words, a listener "
                "cue such as mm, okay, or interesting. Invent a natural variant. Do not answer "
                "the content, ask a question, or repeat a phrase already spoken."
            ),
        ),
        _field(
            key="chat.expert.live_speech_progress",
            label_sv="Expertchatt — framstegstal i Live Speech",
            label_en="Expert chat — Live Speech progress talk",
            hint_sv="Naturligt tal medan ett verktyg eller en sammanställning pågår.",
            hint_en="Natural speech while a tool or compilation is running.",
            default_sv=(
                "Huvudsvaret är inte klart. Svara med JSON {\"phrase\":\"...\",\"silence\":false} "
                "eller silence. Formulera en eller två naturliga meningar om det läge du får: "
                "att svaret dröjer, att ett namngivet verktyg fortfarande kör, eller att ett "
                "delsvar kommit och mer återstår. Hitta inte på källor, siffror eller att "
                "arbetet är klart. Upprepa inte redan sagd text. Inga frågor."
            ),
            default_en=(
                "The main reply is not ready. Reply with JSON {\"phrase\":\"...\",\"silence\":false} "
                "or silence. Write one or two natural sentences about the state you are given: "
                "the reply is late, a named tool is still running, or a partial result arrived "
                "and more remains. Do not invent sources, figures, or that the work is done. "
                "Do not repeat text already spoken. No questions."
            ),
        ),
        _field(
            key="chat.expert.live_speech_backchannel",
            label_sv="Expertchatt — turtagning i Live Speech",
            label_en="Expert chat — Live Speech turn-taking",
            hint_sv="Klassificera oklart tal medan experten pratar.",
            hint_en="Classify unclear speech while the expert is talking.",
            default_sv=(
                "Användaren talar medan experten pratar. Svara med JSON "
                "{\"classification\":\"backchannel|interruption|new_question|uncertain\"}. "
                "backchannel är korta lyssnarsignaler. interruption är stopp, nej, vänta, "
                "korrigering eller ja men. new_question är en ny fråga. Gissa inte innehåll."
            ),
            default_en=(
                "The user is speaking while the expert talks. Reply with JSON "
                "{\"classification\":\"backchannel|interruption|new_question|uncertain\"}. "
                "backchannel is a short listener cue. interruption is stop, no, wait, a "
                "correction, or yes but. new_question is a new question. Do not guess content."
            ),
        ),
    ]


def _tool_relevance(language: str) -> str:
    if language == "sv":
        instructions = (
            "Hur relevant är verktyget {name} för att uppfylla användarens aktuella "
            "intention?\n\nBeskrivning:\n{description}\n\nBedöm semantisk matchning mellan "
            "verktygets syfte och intentionen. Det är inte sannolikheten att anropet "
            "lyckas och inte confidence för ett verktygsresultat."
        )
        true = "Verktygets syfte matchar intentionen."
        false = "Verktygets syfte matchar inte intentionen."
    else:
        instructions = (
            "How relevant is the tool {name} to the user's current intention?\n\n"
            "Description:\n{description}\n\nJudge the semantic match between the tool's "
            "purpose and the intention. This is not the probability that the call "
            "succeeds and not confidence in a tool result."
        )
        true = "The tool's purpose matches the intention."
        false = "The tool's purpose does not match the intention."
    return json.dumps(
        {"instructions": instructions, "criteria": {"true": true, "false": false}},
        ensure_ascii=False,
    )


def _reasoning_assessment_questions(language: str) -> str:
    if language == "sv":
        criteria = {
            "simple_operation": (
                "Är uppgiften en direkt hälsning, faktakoll, tydlig dokumentnavigation "
                "eller uppenbar verktygsoperation som inte kräver egentlig analys?"
            ),
            "analysis": "Kräver uppgiften tolkning, bedömning eller analys?",
            "multi_step": "Kräver uppgiften flera beroende steg eller samordnade verktygsanrop?",
            "comparison": "Kräver uppgiften att alternativ, dokument eller bestämmelser jämförs?",
            "synthesis": "Kräver uppgiften att flera källor eller slutsatser vägs ihop?",
            "conflicting_information": "Finns eller antyds motstridiga uppgifter som måste lösas?",
            "decomposable": (
                "Kan uppgiften delas i avgränsade deluppgifter vars resultat sedan "
                "kan vägas ihop?"
            ),
            "parallelizable": (
                "Kan deluppgifterna utföras samtidigt utan att nästa del beror på "
                "föregående dels resultat?"
            ),
        }
    else:
        criteria = {
            "simple_operation": (
                "Is this a direct greeting, fact lookup, clear document navigation, or "
                "obvious tool operation that requires no real analysis?"
            ),
            "analysis": "Does the task require interpretation, judgment, or analysis?",
            "multi_step": "Does the task require dependent steps or coordinated tool calls?",
            "comparison": "Must alternatives, documents, or provisions be compared?",
            "synthesis": "Must multiple sources or conclusions be combined?",
            "conflicting_information": "Is conflicting information present or implied and in need of resolution?",
            "decomposable": (
                "Can the task be split into bounded subtasks whose results can then "
                "be combined?"
            ),
            "parallelizable": (
                "Can those subtasks run at the same time without the next part "
                "depending on the previous part's result?"
            ),
        }
    return json.dumps(
        {
            key: {
                "type": "noul",
                "instructions": instruction,
                "criteria": {
                    "true": "Uppgiften matchar kriteriet." if language == "sv" else "The task matches the criterion.",
                    "false": "Uppgiften matchar inte kriteriet." if language == "sv" else "The task does not match the criterion.",
                },
            }
            for key, instruction in criteria.items()
        },
        ensure_ascii=False,
    )
