from airflow.decorators import dag, task
from datetime import datetime, timedelta

default_args = {"retries": 2, "retry_delay": timedelta(minutes=2)}

@dag(
    dag_id="phase3_nlp_enrichment",
    schedule="*/30 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["phase3", "nlp"],
)
def phase3_nlp_enrichment():

    @task
    def process_batch():
        from phase2.phase3.nlp_pipeline import Phase3Pipeline
        from phase2.phase3.entity_linker import extract_entities, link_entity_to_supplier
        from phase2.phase3.config import LINKABLE_ENT_TYPE

        pipeline = Phase3Pipeline()
        try:
            events = pipeline.fetch_unprocessed_events()
            suppliers = pipeline.fetch_known_suppliers()
            print(f"DEBUG suppliers sample: {suppliers[:3]}")

            linked_count = 0
            for event in events:
                entities = extract_entities(event["description"])
                print(f"DEBUG entities: {[(e['text'], e['label']) for e in entities]}")
                for ent in entities:
                    if ent["label"] != LINKABLE_ENT_TYPE:
                        continue
                    match = link_entity_to_supplier(ent["text"], suppliers)
                    if match:
                        pipeline.write_mentions_relationship(
                            event["event_id"], match["supplier_id"], match["confidence"], match["method"]
                        )
                        linked_count += 1
                pipeline.mark_processed(event["event_id"])

            return {"processed": len(events), "linked": linked_count}
        finally:
            pipeline.close()

    process_batch()

phase3_nlp_enrichment()