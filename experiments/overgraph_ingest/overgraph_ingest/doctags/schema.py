"""OverGraph labels for document tags. Same catalog, no separate database."""

TAG = "Tag"
TAG_CLASS = "TagClass"
HAS_TAG = "HAS_TAG"
HAS_CLASS = "HAS_CLASS"

ORIGIN_JEV = "jev"
ORIGIN_STRUCTURE = "structure"
ORIGIN_USER = "user"

KIND_EXTRACTED = "extracted_property"
KIND_USER_LABEL = "user_label"

UNREVIEWED = "unreviewed"
USER_VERIFIED = "user_verified"
USER_CORRECTED = "user_corrected"
REJECTED = "rejected"
WITHDRAWN = "withdrawn"

TYPE_ORIGIN_MODEL = "model"
TYPE_ORIGIN_USER = "user"

LIFECYCLE_ACTIVE = "active"
LIFECYCLE_DELETED = "deleted"

LOCKED_REVIEW = {REJECTED, USER_VERIFIED, USER_CORRECTED}
HIDDEN_REVIEW = {REJECTED, WITHDRAWN}
