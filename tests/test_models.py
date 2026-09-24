from data_wayfinder.models import (
    Confidence,
    RelationshipAudit,
    RelationshipEvidence,
    TableAudit,
    TableRef,
)


def test_contract_round_trip():
    audit = TableAudit(
        table=TableRef(name="analytics.customers"),
        relationships=[
            RelationshipAudit(
                left_table="analytics.customers",
                left_field="customer_id",
                right_table="fact.orders",
                right_field="customer_id",
                confidence=Confidence.HIGH,
                evidence=[
                    RelationshipEvidence(
                        source="datahub_lineage",
                        kind="column_lineage",
                    )
                ],
            )
        ],
    )

    restored = TableAudit.model_validate_json(audit.model_dump_json())
    assert restored.table.name == "analytics.customers"
    assert restored.relationships[0].confidence == Confidence.HIGH
