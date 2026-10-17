"""Read a passage author from a citation snapshot.

Kept out of workspace.service so document context can import it while the
module registry is still loading.
"""


def marked_author(snapshot: dict | None) -> dict | None:
    author = (snapshot or {}).get("marked_by")
    if not isinstance(author, dict):
        return None
    kind, author_id, name = author.get("kind"), author.get("id"), author.get("name")
    if kind not in ("user", "expert") or not isinstance(author_id, str) or not author_id.strip():
        return None
    if not isinstance(name, str) or not name.strip():
        return None
    return {"kind": kind, "id": author_id.strip(), "name": " ".join(name.split())}
