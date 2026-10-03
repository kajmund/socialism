"""Expert-chat prompt defaults that no longer fit in the catalog module."""

from __future__ import annotations


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
                "När du anropar ett verktyg i samma tur: skriv en kort egen mening i första "
                "person om att du tar reda på det. Välj orden själv. Ta inte med resultatet "
                "och skriv inte verktygets namn, JSON eller XML. Om verktygsresultatet har "
                "status deferred ska du inte säga något mer i den turen. Ett meddelande som "
                "börjar med [[underlag]] är inte användaren: väv in texten efter markören "
                "och läs inte upp markören."
            ),
            default_en=(
                "When you call a tool in the same turn: write one short first-person sentence "
                "of your own that you are looking it up. Choose the words yourself. Do not "
                "include the result or the tool name, JSON, or XML. If the tool result has "
                "status deferred, say nothing more in that turn. A message that starts with "
                "[[underlag]] is not the user: weave in the text after the marker and do not "
                "read the marker aloud."
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
    ]
