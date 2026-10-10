"""Register OverGraph as a mem0 vector-store provider. Mem0 has no register API."""

import sys
import types

from mem0.utils.factory import VectorStoreFactory
from mem0.vector_stores.configs import VectorStoreConfig

from app.services.overgraph.mem0_store import OverGraphMem0Config

PROVIDER = "overgraph"
CONFIG_CLASS = "OverGraphMem0Config"
_INSTALLED = False


def install_mem0_overgraph() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    # Pydantic compiles VectorStoreConfig.validate_and_create_config into the
    # model schema at class creation. Replacing the method leaves that schema
    # in place, so MemoryConfig still rejects unknown providers. The compiled
    # validator reads this private default map, then imports
    # mem0.configs.vector_stores.<provider>.
    providers = VectorStoreConfig.__private_attributes__["_provider_configs"].default
    providers[PROVIDER] = CONFIG_CLASS
    module_name = f"mem0.configs.vector_stores.{PROVIDER}"
    module = types.ModuleType(module_name)
    setattr(module, CONFIG_CLASS, OverGraphMem0Config)
    sys.modules[module_name] = module
    VectorStoreFactory.provider_to_class[PROVIDER] = (
        "app.services.overgraph.mem0_store.OverGraphVectorStore"
    )
    _INSTALLED = True
