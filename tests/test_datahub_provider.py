from data_wayfinder.providers.datahub_mcp import DataHubMcpProvider


def test_datahub_provider_keeps_raw_provenance():
    calls = []

    def call_tool(name, args):
        calls.append((name, args))
        if name == "get_entities":
            return {
                "entities": [
                    {
                        "urn": "urn:table",
                        "description": "Customer table",
                        "owner": "urn:li:corpuser:alice",
                        "tag": "urn:li:tag:PII",
                    }
                ]
            }
        if name == "get_dataset_queries":
            return {
                "queries": [
                    {
                        "properties": {
                            "statement": {"value": "select * from customers"}
                        }
                    }
                ]
            }
        return {"results": [{"urn": "urn:other"}]}

    provider = DataHubMcpProvider(call_tool)
    context = provider.table_context("urn:table")

    assert context.description == "Customer table"
    assert context.owner == "urn:li:corpuser:alice"
    assert context.observed_queries == ["select * from customers"]
    assert "entity" in context.raw
    assert {name for name, _ in calls} == {
        "get_entities",
        "get_lineage",
        "get_dataset_queries",
    }
    lineage_args = [args for name, args in calls if name == "get_lineage"]
    assert {"urn": "urn:table", "upstream": True, "max_hops": 1} in lineage_args
    assert {"urn": "urn:table", "upstream": False, "max_hops": 1} in lineage_args
