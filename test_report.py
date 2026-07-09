from neo4j import GraphDatabase
from phase2.phase6.generate_report import generate_customer_report

driver = GraphDatabase.driver('bolt://neo4j:7687', auth=('neo4j', 'supply_chain_secret'))
with driver.session() as session:
    report_id = generate_customer_report(
        session,
        customer_id='cust_monsoon_001',
        period_start='2026-07-03T00:00:00+00:00',
        period_end='2026-07-09T00:00:00+00:00',
    )
    print('Generated:', report_id)

    result = session.run(
        'MATCH (r:ExecutiveReport {report_id: $id}) RETURN r.status, r.content, r.theme_count, r.escalation_rate',
        {'id': report_id}
    )
    record = result.single()
    print('status:', record['r.status'])
    print('theme_count:', record['r.theme_count'])
    print('escalation_rate:', record['r.escalation_rate'])
    print('---CONTENT---')
    print(record['r.content'])
driver.close()