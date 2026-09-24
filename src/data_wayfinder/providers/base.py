from __future__ import annotations

from typing import Protocol

from data_wayfinder.models import CatalogContext, FieldCatalogContext


class MetadataProvider(Protocol):
    def table_context(self, table_urn: str) -> CatalogContext: ...

    def field_context(
        self,
        table_urn: str,
        field_name: str,
    ) -> FieldCatalogContext: ...
