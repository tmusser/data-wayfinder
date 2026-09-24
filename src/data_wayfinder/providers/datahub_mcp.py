from __future__ import annotations

from collections.abc import Callable
from typing import Any

from data_wayfinder.models import CatalogContext, FieldCatalogContext

ToolInvoker = Callable[[str, dict[str, Any]], dict[str, Any]]


def _walk_strings(value: Any, *, keys: set[str]) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in keys and isinstance(child, str):
                found.append(child)
            else:
                found.extend(_walk_strings(child, keys=keys))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_strings(child, keys=keys))
    return list(dict.fromkeys(found))


class DataHubMcpProvider:
    """Normalize DataHub MCP reads behind Wayfinder contracts.

    The caller owns MCP transport/authentication. `call_tool` should accept a
    DataHub MCP tool name and its JSON arguments and return the decoded payload.
    This keeps Wayfinder compatible with hosted agents, local MCP clients, and
    future transports without embedding credentials.
    """

    def __init__(self, call_tool: ToolInvoker):
        self.call_tool = call_tool

    def table_context(self, table_urn: str) -> CatalogContext:
        entity = self.call_tool("get_entities", {"urns": [table_urn]})
        lineage_up = self.call_tool(
            "get_lineage",
            {"urn": table_urn, "upstream": True, "max_hops": 1},
        )
        lineage_down = self.call_tool(
            "get_lineage",
            {"urn": table_urn, "upstream": False, "max_hops": 1},
        )
        queries = self.call_tool(
            "get_dataset_queries",
            {"urn": table_urn, "count": 20},
        )

        owners = _walk_strings(entity, keys={"owner", "ownerUrn", "owner_urn"})
        tags = _walk_strings(entity, keys={"tag", "tagUrn", "tag_urn"})
        terms = _walk_strings(
            entity,
            keys={"term", "glossaryTerm", "termUrn", "term_urn"},
        )
        descriptions = _walk_strings(
            entity,
            keys={"description", "documentation"},
        )
        upstream = _walk_strings(lineage_up, keys={"urn"})
        downstream = _walk_strings(lineage_down, keys={"urn"})
        observed_queries = _walk_strings(queries, keys={"query", "sql"})

        def collect_statement_values(value: Any) -> list[str]:
            found: list[str] = []
            if isinstance(value, dict):
                statement = value.get("statement")
                if isinstance(statement, dict) and isinstance(statement.get("value"), str):
                    found.append(statement["value"])
                for child in value.values():
                    found.extend(collect_statement_values(child))
            elif isinstance(value, list):
                for child in value:
                    found.extend(collect_statement_values(child))
            return found

        observed_queries = list(
            dict.fromkeys(observed_queries + collect_statement_values(queries))
        )

        return CatalogContext(
            description=descriptions[0] if descriptions else None,
            owner=owners[0] if owners else None,
            owners=owners,
            tags=tags,
            glossary_terms=terms,
            upstream=[urn for urn in upstream if urn != table_urn],
            downstream=[urn for urn in downstream if urn != table_urn],
            observed_queries=observed_queries[:20],
            raw={
                "entity": entity,
                "lineage_upstream": lineage_up,
                "lineage_downstream": lineage_down,
                "queries": queries,
            },
        )

    def field_context(
        self,
        table_urn: str,
        field_name: str,
    ) -> FieldCatalogContext:
        payload = self.call_tool(
            "list_schema_fields",
            {"urn": table_urn, "keywords": [field_name], "limit": 20},
        )
        descriptions = _walk_strings(
            payload,
            keys={"description", "documentation"},
        )
        tags = _walk_strings(payload, keys={"tag", "tagUrn", "tag_urn"})
        terms = _walk_strings(
            payload,
            keys={"term", "glossaryTerm", "termUrn", "term_urn"},
        )
        return FieldCatalogContext(
            description=descriptions[0] if descriptions else None,
            tags=tags,
            glossary_terms=terms,
        )
