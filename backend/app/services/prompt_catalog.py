"""Prompt field registry: keys, UI labels, and default texts per language.

Placeholders in templates:
  {local_context}  — locality brief (+ optional district block)
  {requirements}   — demographic/attribute requirement lines
  {surname_block}  — optional taken-surnames block (may be empty)
  {voice_block}    — optional writing-trait / previous-persona block
  {free_text}      — user free text
  {field_guide}    — persona field guide (inserted by caller or nested)
  {count}          — number of personas
  {candidate_index}, {candidate_count}
  {demo_block}     — optional fixed demography block
  {persona_block}  — formatted persona profile lines
  {anecdote_context}
  {prev_block}     — previous anecdotes block
  {type_label}     — message type label
  {page_text}
  {angle_instruction}, {context_block}, {source_material}
  {day}, {tick_number}
  {display}, {type_label}  — injector
  {pack_list}, {other}
  $num_followers, $posts, … — OASIS string.Template variables
"""

from __future__ import annotations

from typing import Literal, TypedDict

ConfigurationLanguage = Literal["sv", "en", "nb"]
PromptSection = Literal[
    "persona",
    "chat",
    "messages",
    "oasis_env",
    "oasis_agents",
    "report",
]

PROMPT_SECTIONS: list[tuple[PromptSection, dict[str, str]]] = [
    ("persona", {"sv": "Persona", "en": "Persona"}),
    ("chat", {"sv": "Chat & intervju", "en": "Chat & interview"}),
    ("messages", {"sv": "Budskap", "en": "Messages"}),
    ("oasis_env", {"sv": "OASIS — miljö", "en": "OASIS — environment"}),
    ("oasis_agents", {"sv": "OASIS — agenter", "en": "OASIS — agents"}),
    ("report", {"sv": "Rapport", "en": "Report"}),
]


class PromptFieldDef(TypedDict):
    key: str
    section: PromptSection
    label: dict[str, str]
    hint: dict[str, str]
    defaults: dict[str, str]


def _f(
    key: str,
    section: PromptSection,
    label_sv: str,
    label_en: str,
    hint_sv: str,
    hint_en: str,
    default_sv: str,
    default_en: str,
) -> PromptFieldDef:
    return {
        "key": key,
        "section": section,
        "label": {"sv": label_sv, "en": label_en},
        "hint": {"sv": hint_sv, "en": hint_en},
        "defaults": {"sv": default_sv, "en": default_en, "nb": default_sv},
    }


PROMPT_FIELDS: list[PromptFieldDef] = [
    _f(
        "persona.field_guide",
        "persona",
        "Persona — fältguide",
        "Persona — field guide",
        "Lista över profilfält som modellen ska fylla i.",
        "List of profile fields the model should fill in.",
        """Fält att fylla i (svenska strängar, korta och konkreta):
- name: för- och efternamn (svenskt eller vanligt i Sverige; matcha kön)
- initials: två bokstäver
- age: ålder som sträng (siffra)
- kön: Kvinna, Man eller Icke-binär
- ort: stadsdel/ort
- yrke: yrke
- utbildning, livssituation, lutning, sakfragor, fortroende, ton, sprak, medievanor, parti, valdeltagande
(Lämna anekdot som "—" — genereras separat.)""",
        """Fields to fill (English strings, short and concrete):
- name: first and last name
- initials: two letters
- age: age as a string (digits)
- kön: Woman, Man, or Non-binary
- ort: district/place
- yrke: occupation
- utbildning, livssituation, lutning, sakfragor, fortroende, ton, sprak, medievanor, parti, valdeltagande
(Leave anekdot as "—" — generated separately.)""",
    ),
    _f(
        "persona.from_slot.system",
        "persona",
        "Persona från recept — systemprompt",
        "Persona from recipe — system prompt",
        "Platshållare: {local_context}",
        "Placeholder: {local_context}",
        (
            "Du skapar politiska testpersonas för Opinionssimulator. "
            "Svara endast med det strukturerade objektet.\n\n"
            "Lokal kontext:\n{local_context}"
        ),
        (
            "You create political test personas for Opinionssimulator. "
            "Reply only with the structured object.\n\n"
            "Local context:\n{local_context}"
        ),
    ),
    _f(
        "persona.from_slot.user",
        "persona",
        "Persona från recept — användarprompt",
        "Persona from recipe — user prompt",
        "Platshållare: {requirements}, {surname_block}, {voice_block}, {free_text}, {field_guide}",
        "Placeholders: {requirements}, {surname_block}, {voice_block}, {free_text}, {field_guide}",
        """Skapa en trovärdig Norrköpingspersona.

Demografiska och attributkrav (följ dessa):
{requirements}
{surname_block}{voice_block}
Extra önskemål från användaren:
{free_text}

{field_guide}""",
        """Create a credible local persona.

Demographic and attribute requirements (follow these):
{requirements}
{surname_block}{voice_block}
Extra user requests:
{free_text}

{field_guide}""",
    ),
    _f(
        "persona.from_description.system",
        "persona",
        "Persona från beskrivning — systemprompt",
        "Persona from description — system prompt",
        "Platshållare: {candidate_index}, {candidate_count}, {local_context}",
        "Placeholders: {candidate_index}, {candidate_count}, {local_context}",
        (
            "Du skapar politiska testpersonas för Opinionssimulator. "
            "Detta är kandidat {candidate_index} av {candidate_count}.\n\n"
            "Lokal kontext:\n{local_context}"
        ),
        (
            "You create political test personas for Opinionssimulator. "
            "This is candidate {candidate_index} of {candidate_count}.\n\n"
            "Local context:\n{local_context}"
        ),
    ),
    _f(
        "persona.from_description.user",
        "persona",
        "Persona från beskrivning — användarprompt",
        "Persona from description — user prompt",
        "Platshållare: {count}, {free_text}, {demo_block}, {field_guide}",
        "Placeholders: {count}, {free_text}, {demo_block}, {field_guide}",
        """Generera {count} distinkta kandidatpersonas.

Beskrivning:
{free_text}

{demo_block}

{field_guide}

Returnera EN persona (vi anropar dig {count} gånger). Variera namn och detaljer.""",
        """Generate {count} distinct candidate personas.

Description:
{free_text}

{demo_block}

{field_guide}

Return ONE persona (we call you {count} times). Vary names and details.""",
    ),
    _f(
        "persona.anecdote.system",
        "persona",
        "Anekdot — systemprompt",
        "Anecdote — system prompt",
        "Platshållare: {local_context}",
        "Placeholder: {local_context}",
        (
            "Du skriver korta svenska vardagsanekdoter för simulerade medborgare. "
            "Svara endast med JSON.\n\n"
            "Lokal kontext:\n{local_context}"
        ),
        (
            "You write short everyday anecdotes for simulated citizens. "
            "Reply only with JSON.\n\n"
            "Local context:\n{local_context}"
        ),
    ),
    _f(
        "persona.anecdote.user",
        "persona",
        "Anekdot — användarprompt",
        "Anecdote — user prompt",
        "Platshållare: {persona_block}, {prev_block}. Maxord är 20 i koden.",
        "Placeholders: {persona_block}, {prev_block}. Max words is 20 in code.",
        """Skriv EN kort vardagsanekdot för denna persona.

Persona:
{persona_block}

Krav:
- Exakt en mening, max 20 ord.
- Koppla till yrke, ort eller livssituation — inte generisk "alla vet att…".
- Ska kunna vävas in naturligt i en kommentar (t.ex. "min syster jobbar…", "förra veckan såg jag…").
- INGEN politisk ståndpunkt, inget parti, ingen lutning — bara en konkret vardagsdetalj.
- Ingen moral om politik, skatter eller partier.
{prev_block}
Returnera JSON med fältet anekdot.""",
        """Write ONE short everyday anecdote for this persona.

Persona:
{persona_block}

Requirements:
- Exactly one sentence, max 20 words.
- Tie to occupation, place, or life situation — not a generic cliché.
- Should weave naturally into a comment.
- NO political stance, party, or lean — only a concrete everyday detail.
{prev_block}
Return JSON with field anekdot.""",
    ),
    _f(
        "chat.mode.interview",
        "chat",
        "Chat — intervjuläge",
        "Chat — interview mode",
        "Regler som sätts när läget är intervju.",
        "Rules applied in interview mode.",
        (
            "Läge: INTERVJU. En analytiker intervjuar dig. Svara i första person som personan. "
            "Var kort (1–4 meningar), konkret, och håll dig till din bakgrund. "
            "Hitta inte på statistik du inte skulle kunna. Svara på svenska."
        ),
        (
            "Mode: INTERVIEW. An analyst interviews you. Answer in first person as the persona. "
            "Be short (1–4 sentences), concrete, and stay within your background. "
            "Do not invent statistics you would not know. Answer in English."
        ),
    ),
    _f(
        "chat.mode.in_character",
        "chat",
        "Chat — in-character-läge",
        "Chat — in-character mode",
        "Regler för vardags-/flödesläge.",
        "Rules for everyday/feed mode.",
        (
            "Läge: IN-CHARACTER. Användaren pratar med dig som i din vardag/sociala flöde. "
            "Svara i första person, naturligt talspråk, kort. Svara på svenska."
        ),
        (
            "Mode: IN-CHARACTER. The user talks to you as in everyday life / a social feed. "
            "Answer in first person, natural speech, briefly. Answer in English."
        ),
    ),
    _f(
        "chat.run_interview.header",
        "chat",
        "Körningsintervju — rubrik",
        "Run interview — header",
        "Platshållare: {day}, {tick_number}",
        "Placeholders: {day}, {tick_number}",
        (
            "Du befinner dig efter dag {day} (tick {tick_number}) i en "
            "simulering av ett socialt flöde. En analytiker intervjuar dig."
        ),
        (
            "You are after day {day} (tick {tick_number}) in a "
            "social-feed simulation. An analyst is interviewing you."
        ),
    ),
    _f(
        "chat.simulation_context.footer",
        "chat",
        "Chat — simuleringskontext (avslutning)",
        "Chat — simulation context footer",
        "Läggs efter flödeskontexten i systemprompten.",
        "Appended after feed context in the system prompt.",
        (
            "Viktigt: Du befinner dig vid tidpunkten ovan. Du har inte sett något "
            "som hände efteråt. Hitta inte på händelser som inte finns i flödet."
        ),
        (
            "Important: You are at the moment above. You have not seen anything "
            "that happened later. Do not invent events that are not in the feed."
        ),
    ),
    _f(
        "messages.summarize_url.system",
        "messages",
        "Sammanfatta URL — systemprompt",
        "Summarize URL — system prompt",
        "Systemprompt för att sammanfatta webbinnehåll.",
        "System prompt for summarizing web content.",
        (
            "Du sammanfattar webbinnehåll på svenska för politisk budskapsutveckling. "
            "Fokusera på artikelns faktiska innehåll (titel, ingress, brödtext). "
            "Ignorera navigering, menyer, cookies och reklam. "
            "Returnera endast sammanfattningen, ingen meta-kommentar."
        ),
        (
            "You summarize web content in English for political message development. "
            "Focus on the article body (title, lead, text). "
            "Ignore navigation, menus, cookies, and ads. "
            "Return only the summary, no meta commentary."
        ),
    ),
    _f(
        "messages.summarize_url.user",
        "messages",
        "Sammanfatta URL — användarprompt",
        "Summarize URL — user prompt",
        "Platshållare: {type_label}, {page_text}",
        "Placeholders: {type_label}, {page_text}",
        (
            "Sammanfatta följande innehåll kort (5–8 meningar) som underlag för en "
            "{type_label}:\n\n{page_text}"
        ),
        (
            "Summarize the following content briefly (5–8 sentences) as material for a "
            "{type_label}:\n\n{page_text}"
        ),
    ),
    _f(
        "messages.variant.system",
        "messages",
        "Budskapsvariant — systemprompt",
        "Message variant — system prompt",
        "Gemensam systemprompt för variantgenerering.",
        "Shared system prompt for variant generation.",
        (
            "Du skriver politiska budskap på svenska för Opinionssimulator. "
            "Returnera endast budskapstexten, ingen rubrik eller meta-kommentar."
        ),
        (
            "You write political messages in English for Opinionssimulator. "
            "Return only the message text, no title or meta commentary."
        ),
    ),
    _f(
        "messages.variant.user",
        "messages",
        "Budskapsvariant — användarprompt",
        "Message variant — user prompt",
        "Platshållare: {type_label}, {angle_instruction}, {context_block}, {source_material}",
        "Placeholders: {type_label}, {angle_instruction}, {context_block}, {source_material}",
        (
            "Skriv en {type_label}.\n"
            "{angle_instruction}\n\n"
            "Kontext:\n{context_block}\n\n"
            "Underlag:\n{source_material}"
        ),
        (
            "Write a {type_label}.\n"
            "{angle_instruction}\n\n"
            "Context:\n{context_block}\n\n"
            "Source material:\n{source_material}"
        ),
    ),
    _f(
        "messages.variant.analytical",
        "messages",
        "Variantvinkel — analytisk",
        "Variant angle — analytical",
        "Instruktion för den analytiska varianten.",
        "Instruction for the analytical variant.",
        "Skriv med en professionell, analytisk vinkel. Tydliga argument, saklig ton.",
        "Write with a professional, analytical angle. Clear arguments, factual tone.",
    ),
    _f(
        "messages.variant.narrative",
        "messages",
        "Variantvinkel — berättande",
        "Variant angle — narrative",
        "Instruktion för den berättande varianten.",
        "Instruction for the narrative variant.",
        "Skriv med en personlig, berättande vinkel. Mänsklig röst, konkret vardag.",
        "Write with a personal, narrative angle. Human voice, concrete everyday detail.",
    ),
    _f(
        "messages.variant.concise",
        "messages",
        "Variantvinkel — koncis",
        "Variant angle — concise",
        "Instruktion för den korta varianten.",
        "Instruction for the concise variant.",
        "Skriv kort och koncist. Max 2–3 meningar, hög densitet, ingen fluff.",
        "Write short and concise. Max 2–3 sentences, high density, no fluff.",
    ),
    _f(
        "oasis.env.followers",
        "oasis_env",
        "OASIS — följare",
        "OASIS — followers",
        "string.Template: $num_followers",
        "string.Template: $num_followers",
        "Jag har $num_followers följare.",
        "I have $num_followers followers.",
    ),
    _f(
        "oasis.env.follows",
        "oasis_env",
        "OASIS — följningar",
        "OASIS — following",
        "string.Template: $num_follows",
        "string.Template: $num_follows",
        "Jag har $num_follows följningar.",
        "I am following $num_follows accounts.",
    ),
    _f(
        "oasis.env.posts",
        "oasis_env",
        "OASIS — flödesinlägg",
        "OASIS — feed posts",
        "string.Template: $posts",
        "string.Template: $posts",
        (
            "Efter uppdatering ser du följande inlägg. "
            "Varje inlägg och kommentar har author_name (visningsnamn) — "
            "använd det om du refererar till avsändaren, inte user_id: $posts"
        ),
        (
            "After refresh you see the following posts. "
            "Each post and comment has author_name (display name) — "
            "use that when referring to the author, not user_id: $posts"
        ),
    ),
    _f(
        "oasis.env.groups",
        "oasis_env",
        "OASIS — grupper",
        "OASIS — groups",
        "string.Template: $all_groups, $joined_groups, $messages",
        "string.Template: $all_groups, $joined_groups, $messages",
        (
            "Det finns gruppkanaler: $all_groups\n"
            "Du är redan med i vissa grupper: $joined_groups\n"
            "Meddelanden: $messages\n"
            "Du kan gå med i grupper du vill, lämna grupper du är i och skriva "
            "till grupper du redan tillhör."
        ),
        (
            "There are group channels: $all_groups\n"
            "You already joined some groups: $joined_groups\n"
            "Messages: $messages\n"
            "You may join groups, leave groups you are in, and write "
            "to groups you already belong to."
        ),
    ),
    _f(
        "oasis.env.main",
        "oasis_env",
        "OASIS — huvudmiljö",
        "OASIS — main environment",
        "string.Template: $groups_env, $posts_env (följare/följningar läggs till av motorn)",
        "string.Template: $groups_env, $posts_env",
        (
            "$groups_env\n"
            "$posts_env\n"
            "Välj den åtgärd som bäst speglar din bakgrund och vad du ser i flödet. "
            "Du behöver inte göra något om inget engagerar dig. "
            "Gilla (like) bara när du faktiskt stöder inlägget eller håller med. "
            "Ogilla (dislike) när du tar avstånd. "
            "Om du kritiserar eller sarkastiskt kommenterar ett inlägg: gilla det inte. "
            "Du kan följa, avfölja, mutea, söka, rapportera, dela eller kommentera "
            "när det passar — eller göra inget. "
            "Om du skriver text: variera formulering; upprepa inte samma inledning "
            "eller avslutning varje gång."
        ),
        (
            "$groups_env\n"
            "$posts_env\n"
            "Choose the action that best matches your background and what you see. "
            "You need not act if nothing engages you. "
            "Like only when you truly support or agree. "
            "Dislike when you distance yourself. "
            "If you criticize or sarcastically comment: do not like. "
            "You may follow, unfollow, mute, search, report, share, or comment "
            "when it fits — or do nothing. "
            "When writing: vary phrasing; do not repeat the same opening or closing."
        ),
    ),
    _f(
        "oasis.env.empty_posts",
        "oasis_env",
        "OASIS — tomt flöde",
        "OASIS — empty feed",
        "Text när flödet är tomt.",
        "Text when the feed is empty.",
        "Efter uppdatering finns inga inlägg att visa.",
        "After refresh there are no posts to show.",
    ),
    _f(
        "oasis.env.empty_groups",
        "oasis_env",
        "OASIS — inga grupper",
        "OASIS — no groups",
        "Text när gruppchatt saknas.",
        "Text when group chat is unavailable.",
        "Inga gruppchattar.",
        "No group chats.",
    ),
    _f(
        "oasis.env.empty_followers",
        "oasis_env",
        "OASIS — inga följare",
        "OASIS — no followers",
        "Text när följarlista hoppas över.",
        "Text when follower list is skipped.",
        "Inga följare listade.",
        "No followers listed.",
    ),
    _f(
        "oasis.env.empty_follows",
        "oasis_env",
        "OASIS — inga följningar",
        "OASIS — no following",
        "Text när följningslista hoppas över.",
        "Text when following list is skipped.",
        "Inga följningar listade.",
        "No following listed.",
    ),
    _f(
        "oasis.agents.action_rules",
        "oasis_agents",
        "Population — åtgärdsregler",
        "Population — action rules",
        "Basregler. Create-post-raden injiceras efter raden «ÅTGÄRDER (viktigt):».",
        "Base rules. The create-post line is injected after «ÅTGÄRDER (viktigt):».",
        """ÅTGÄRDER (viktigt):
- Gilla (like_post / like_comment) BARA när du faktiskt stöder eller håller med.
- Ogilla (dislike_post / dislike_comment) när du tar avstånd eller tycker illa om innehållet.
- Om du kommenterar kritiskt, sarkastiskt eller ifrågasättande: gilla INTE samma inlägg.
- Du får gärna kommentera utan att gilla/ogilla — kommentar och reaktion ska peka åt samma håll.
- Följ (follow) personer vars röst du vill höra mer av; avfölj (unfollow) om de inte längre passar.
- Mutea konton som bara stör dig; sök efter användare eller inlägg om du vill hitta något specifikt.
- Rapportera (report_post) bara tydligt olämpligt innehåll.
- Gör inget (do_nothing) om inget i flödet engagerar dig. Scrolla förbi är normalt.
- Gilla inte bara för att visa att du sett något.

HUR DU SKRIVER KOMMENTARER:
- Vardagssvenska i din egen röst. Oftast 1–4 meningar. Inga punktlistor, rubriker eller "sammanfattningsvis".
- Börja ALDRIG med: "Intressant att…", "Viktiga frågor", "Tack för", "Som [yrke] ser jag",
  "Jag håller med om att…", "Håller med om att…", ensam "Precis." / "Exakt!" som öppning,
  eller numrerade hänvisningar ("Kommentar 3…", "Kommentar 12 har rätt").
- Du FÅR (och bör ibland) nämna andra personer vid namn när du hakar på dem — skriv
  @ följt av author_first_name från flödet. Kopiera exakt från flödet; gissa ALDRIG namn,
  blanda ALDRIG ihop avsändare, och återanvänd inte user_id som namn.
- Välj EN struktur per kommentar: invändning, ny vinkel, konkret exempel, kort anekdot,
  retorisk fråga, eller kort instämmande/avståndstagande med namngiven person.
- Upprepa inte samma inledning/avslutning mellan inlägg. Variera språket; håll åsikten konsekvent.
- Undvik att upprepa politikerns eller nyhetens exakta ordval och slogans. Reagera med
  dina egna ord och din egen röst — sakinnehållet kan vara detsamma, men formuleringen
  ska vara din.""",
        """ACTIONS (important):
- Like (like_post / like_comment) ONLY when you truly support or agree.
- Dislike when you distance yourself or dislike the content.
- If you comment critically or sarcastically: do NOT like the same post.
- You may comment without liking/disliking — comment and reaction should point the same way.
- Follow people whose voice you want more of; unfollow if they no longer fit.
- Mute accounts that only annoy you; search when you want to find something.
- Report only clearly inappropriate content.
- Do nothing if nothing engages you. Scrolling past is normal.
- Do not like just to show you saw something.

HOW YOU WRITE COMMENTS:
- Everyday language in your own voice. Usually 1–4 sentences. No bullet lists or headings.
- NEVER start with stock openers like "Interesting that…", "Important questions", "Thanks for".
- You MAY @mention author_first_name from the feed — copy exactly; never guess names.
- Pick ONE structure per comment; vary openings; keep your opinion consistent.
- Avoid repeating politicians' or news slogans verbatim — react in your own words.""",
    ),
    _f(
        "oasis.agents.create_post.allow",
        "oasis_agents",
        "Create post — tillåten",
        "Create post — allowed",
        "Rad som injiceras när populationen får skapa inlägg.",
        "Line injected when the population may create posts.",
        (
            "- Du FÅR skapa egna inlägg (create_post) när du har något eget att säga — "
            "kort, i din röst, utan att kopiera andras budskap ordagrant."
        ),
        (
            "- You MAY create your own posts (create_post) when you have something to say — "
            "short, in your voice, without copying others verbatim."
        ),
    ),
    _f(
        "oasis.agents.create_post.deny_twitter",
        "oasis_agents",
        "Create post — förbjuden (Twitter)",
        "Create post — denied (Twitter)",
        "När create_post är avstängt på Twitter-plattformen.",
        "When create_post is off on the Twitter platform.",
        (
            "- Skapa INTE egna inlägg (create_post). Reagera bara på det du ser: "
            "gilla, ogilla, kommentera, dela, följ eller gör inget."
        ),
        (
            "- Do NOT create your own posts (create_post). Only react to what you see: "
            "like, dislike, comment, share, follow, or do nothing."
        ),
    ),
    _f(
        "oasis.agents.create_post.deny_reddit",
        "oasis_agents",
        "Create post — förbjuden (Reddit)",
        "Create post — denied (Reddit)",
        "När create_post är avstängt på Reddit-plattformen.",
        "When create_post is off on the Reddit platform.",
        (
            "- Skapa INTE egna inlägg (create_post). Reagera bara på det du ser: "
            "gilla, ogilla, kommentera, följ eller gör inget."
        ),
        (
            "- Do NOT create your own posts (create_post). Only react to what you see: "
            "like, dislike, comment, follow, or do nothing."
        ),
    ),
    _f(
        "oasis.agents.injector.user_char",
        "oasis_agents",
        "Injektor — karaktärsprompt",
        "Injector — character prompt",
        "Platshållare: {display}, {type_label}",
        "Placeholders: {display}, {type_label}",
        (
            "Du är det officiella kontot {display} på en svensk social medietjänst. "
            "Kontotyp: {type_label}. "
            "Du publicerar endast förberedda budskap och är inte en privatperson eller väljare. "
            "Du deltar inte i diskussioner, gillar inte, ogillar inte andras inlägg och svarar inte."
        ),
        (
            "You are the official account {display} on a social media service. "
            "Account type: {type_label}. "
            "You only publish prepared messages and are not a private person or voter. "
            "You do not join discussions, like, dislike, or reply."
        ),
    ),
    _f(
        "oasis.agents.population.closing",
        "oasis_agents",
        "Population — avslutande identitet",
        "Population — closing identity",
        "Läggs sist i populationens user_char före åtgärdsregler.",
        "Appended near the end of population user_char before action rules.",
        (
            "Du är en vanlig svensk person på en social medietjänst — inte debattör, "
            "assistent eller balanserad analytiker. "
            "Reagera autentiskt på politiska budskap utifrån din bakgrund."
        ),
        (
            "You are an ordinary person on a social media service — not a debater, "
            "assistant, or balanced analyst. "
            "React authentically to political messages from your background."
        ),
    ),
    _f(
        "report.narrative.system_meta",
        "report",
        "Rapport — systemprompt (jämförelse)",
        "Report — system prompt (comparison)",
        "När rapporten jämför flera källor / A/B.",
        "When the report compares multiple sources / A/B.",
        """Du är samhällsvetare som jämför simulerade politiska diskussioner.
När källorna är Version A och Version B (A/B-test av budskap): jämför ALLTID A mot B
uttryckligen — vad skiljde i engagemang, ton, ämne och stil? Vilken arm fungerade bättre och varför?
När det är flera oberoende körningar: rapportera alltid hur många körningar ett fynd bygger på.
Ett mönster i en arm/körning = observation. I båda/alla = tendens, inte bevis.
Svara på svenska. Fyll varje slot enligt instruktionen — ingen inledning utanför slotvärdena.""",
        """You are a social scientist comparing simulated political discussions.
When the sources are Version A and Version B (A/B message test): ALWAYS compare A vs B
explicitly — what differed in engagement, tone, topic, and style? Which arm worked better and why?
When there are several independent runs: always report how many runs a finding rests on.
A pattern in one arm/run = observation. In both/all = tendency, not proof.
Answer in English. Fill each slot per the instruction — no preamble outside slot values.""",
    ),
    _f(
        "report.narrative.system_single",
        "report",
        "Rapport — systemprompt (enskild)",
        "Report — system prompt (single)",
        "När rapporten analyserar en källa.",
        "When the report analyzes a single source.",
        """Du är samhällsvetare som analyserar EN simulerad politisk diskussion.
Var ärlig om osäkerhet. En körning ger observationer, inte bevis.
Svara på svenska. Fyll varje slot enligt instruktionen — ingen inledning utanför slotvärdena.""",
        """You are a social scientist analyzing ONE simulated political discussion.
Be honest about uncertainty. One run yields observations, not proof.
Answer in English. Fill each slot per the instruction — no preamble outside slot values.""",
    ),
    _f(
        "report.fill_slots.intro",
        "report",
        "Rapport — slotfyllnad (intro)",
        "Report — slot fill intro",
        "Inledning innan slotlistan i batch-anropet.",
        "Intro before the slot list in batch calls.",
        "Fyll följande slots. Nycklar i slots måste vara exakt dessa namn:\n",
        "Fill the following slots. Keys in slots must be exactly these names:\n",
    ),
    _f(
        "report.classify.topic_packs.system",
        "report",
        "Klassificering — härled ämnen",
        "Classification — derive topics",
        "Systemprompt för att skapa ämnespaket från injektioner.",
        "System prompt for deriving topic packs from injections.",
        (
            "Du härleder ämnesetiketter för en svensk politisk debattsimulering. "
            "Returnera 2–4 ämnen med korta svenska etiketter som fångar "
            "injektionernas innehåll. Undvik generiska partinamn ensamma. "
            "keywords är valfria hjälpord (behövs inte för klassning)."
        ),
        (
            "You derive topic labels for a political debate simulation. "
            "Return 2–4 topics with short English labels that capture "
            "the injection content. Avoid generic party names alone. "
            "keywords are optional helper words (not required for classification)."
        ),
    ),
    _f(
        "report.classify.topics.system",
        "report",
        "Klassificering — ämne per text",
        "Classification — topic per text",
        "Platshållare: {pack_list}, {other}",
        "Placeholders: {pack_list}, {other}",
        (
            "Klassificera varje svensk kommentar/inlägg efter ämne. "
            "Tillåtna värden: {pack_list}, eller '{other}'. "
            "Välj efter mening och kontext — inte enbart nyckelord. "
            "Sarkasm och omskrivningar räknas till det ämne de egentligen handlar om. "
            "Returnera index 0..n-1 för batchen."
        ),
        (
            "Classify each comment/post by topic. "
            "Allowed values: {pack_list}, or '{other}'. "
            "Choose by meaning and context — not keywords alone. "
            "Sarcasm and paraphrase count toward the topic they really address. "
            "Return index 0..n-1 for the batch."
        ),
    ),
    _f(
        "report.classify.tones.system",
        "report",
        "Klassificering — tonbedömning (fritext)",
        "Classification — tone judgment (free text)",
        "",
        "",
        (
            "Bedöm tonen i varje svensk kommentar/inlägg med 1–2 korta meningar fritext "
            "(hur positiv/negativ/kritisk/hoppfull texten är mot budskapet). "
            "Använd INTE fasta kategori-etiketter. "
            "Sarkasm, valfläsk-misstro och skarp kritik ska beskrivas som negativ/kritisk. "
            "Returnera index 0..n-1 och fältet judgment för varje rad i batchen."
        ),
        (
            "Judge the tone of each comment/post in 1–2 short free-text sentences "
            "(how positive/negative/critical/hopeful the text is toward the message). "
            "Do NOT use fixed category labels. "
            "Sarcasm, campaign distrust, and sharp criticism should be described as negative/critical. "
            "Return index 0..n-1 and a judgment field for each row in the batch."
        ),
    ),
    _f(
        "report.classify.styles.system",
        "report",
        "Klassificering — stilbedömning (fritext)",
        "Classification — style judgment (free text)",
        "",
        "",
        (
            "Beskriv kommunikationsstilen i varje svensk kommentar/inlägg med 1–2 korta "
            "meningar fritext (t.ex. sarkastisk+konkret, uppgiven+metafor, fakta/auktoritet, "
            "personlig berättelse, optimistisk/lösning, provocerande). "
            "Använd INTE fasta kategori-etiketter. "
            "Returnera index 0..n-1 och fältet judgment för varje rad i batchen."
        ),
        (
            "Describe the communication style of each comment/post in 1–2 short free-text "
            "sentences (e.g. sarcastic+concrete, resigned+metaphor, facts/authority, "
            "personal story, optimistic/solution, provocative). "
            "Do NOT use fixed category labels. "
            "Return index 0..n-1 and a judgment field for each row in the batch."
        ),
    ),
]

PROMPT_KEYS: tuple[str, ...] = tuple(f["key"] for f in PROMPT_FIELDS)
PROMPT_KEY_SET: frozenset[str] = frozenset(PROMPT_KEYS)


def default_prompts(language: ConfigurationLanguage) -> dict[str, str]:
    out: dict[str, str] = {}
    for field in PROMPT_FIELDS:
        defaults = field["defaults"]
        text = defaults.get(language) or defaults.get("sv")
        if not text:
            raise RuntimeError(f"No default prompt for {field['key']} ({language})")
        out[field["key"]] = text
    return out


def _is_obsolete_forced_label_tone_prompt(text: str) -> bool:
    """Pre-SSR tone prompts forced category labels via {quoted}/{sharp_tone}."""
    return (
        "{quoted}" in text
        or "{sharp_tone}" in text
        or "Tillåtna värden:" in text
        or "Allowed values:" in text
    )


def refresh_ssr_classify_prompts(
    prompts: dict[str, str],
    *,
    language: ConfigurationLanguage,
) -> dict[str, str]:
    """Replace obsolete forced-label tone prompts with free-text SSR defaults."""
    defaults = default_prompts(language)
    out = dict(prompts)
    tone = out.get("report.classify.tones.system", "")
    if tone and _is_obsolete_forced_label_tone_prompt(tone):
        out["report.classify.tones.system"] = defaults["report.classify.tones.system"]
    return out


def normalize_prompts(
    raw: dict[str, str] | None,
    *,
    language: ConfigurationLanguage,
    fill_missing: bool = True,
) -> dict[str, str]:
    """Return a complete prompts map. Optionally fill gaps from defaults."""
    base = default_prompts(language) if fill_missing else {k: "" for k in PROMPT_KEYS}
    if raw:
        for key, value in raw.items():
            if key in PROMPT_KEY_SET and isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    base[key] = stripped
    complete = {k: base[k] for k in PROMPT_KEYS}
    return refresh_ssr_classify_prompts(complete, language=language)


def render_prompt(prompts: dict[str, str], key: str, **kwargs: object) -> str:
    text = prompts.get(key)
    if text is None or not str(text).strip():
        raise RuntimeError(f"Active configuration is missing prompt '{key}'")
    try:
        return str(text).format(**kwargs)
    except KeyError as exc:
        raise RuntimeError(f"Prompt '{key}' missing placeholder {exc}") from exc
