"""Public OverGraph labels. Scope is a label so search can isolate before top-k."""

FACT = "Fact"
TEXT_UNIT = "TextUnit"
ENTITY = "Entity"
DOCUMENT_VERSION = "DocumentVersion"
IDENTIFIER = "Identifier"
MEMORY = "Memory"
MEMORY_ENTITY = "MemoryEntity"

SUBJECT = "SUBJECT"
OBJECT = "OBJECT"
CONTEXT = "CONTEXT"
SUPPORTS = "SUPPORTS"
CONTAINS = "CONTAINS"
NEXT = "NEXT"
CONTRADICTS = "CONTRADICTS"
LINKED = "LINKED"
DEPENDS_ON = "DEPENDS_ON"

KNOWLEDGE_TYPES = (FACT, TEXT_UNIT, ENTITY, DOCUMENT_VERSION, IDENTIFIER)


def scope_label(scope_key: str) -> str:
    return f"scope.{scope_key.replace(':', '.')}"


def user_label(user_id: str) -> str:
    return f"user.{user_id.replace(':', '.')}"


def agent_label(agent_id: str) -> str:
    return f"agent.{agent_id.replace(':', '.')}"


def visible_scope_keys(customer_id: int | None) -> tuple[str, ...]:
    if customer_id is None:
        return ("shared",)
    return ("shared", f"customer:{customer_id}")


def visible_scope_labels(customer_id: int | None) -> list[str]:
    return [scope_label(key) for key in visible_scope_keys(customer_id)]
