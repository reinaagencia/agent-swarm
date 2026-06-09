"""Run swarm and save output to disk for comparison."""
import asyncio, json, os, sys
os.chdir('/Users/isabeldiaz/Dev/agent-swarm')
sys.path.insert(0, '.')

from src.state import TeamState
from src.graph import get_graph

OUTPUT_DIR = '/Users/isabeldiaz/Dev/agent-swarm/test_results/swarm'
os.makedirs(OUTPUT_DIR, exist_ok=True)

REQUIREMENT = """Crea report_tool.py: herramienta CLI que procesa un JSON de transacciones [{id,fecha,tipo,categoria,monto,descripcion}]. Filtra registros inválidos (monto<=0, fecha mal formada, campos faltantes). Calcula totales por categoria y tipo, transaccion mas grande, transacciones por mes. Exporta CSV a reporte.csv. Incluye tests pytest. Maneja errores de archivo."""

async def main():
    state = {
        'user_requirement': REQUIREMENT,
        'business_rules': [],
        'retrieved_memory': '',
        'architecture_blueprint': {},
        'source_code': {},
        'test_report': {},
        'scratchpad': [],
        'iteration_count': 0,
        'audit_trail': [],
        'messages': [],
    }

    graph = get_graph()
    print('Running swarm...')
    final_state = await graph.ainvoke(state)

    source_code = final_state.get('source_code', {})
    test_report = final_state.get('test_report', {})
    scratchpad = final_state.get('scratchpad', [])
    audit = final_state.get('audit_trail', [])
    blueprint = final_state.get('architecture_blueprint', {})

    # Save architecture blueprint
    with open(f'{OUTPUT_DIR}/architecture.json', 'w') as f:
        json.dump(blueprint, f, indent=2, ensure_ascii=False)

    # Save test report
    with open(f'{OUTPUT_DIR}/test_report.json', 'w') as f:
        json.dump(test_report, f, indent=2, ensure_ascii=False)

    # Save scratchpad
    with open(f'{OUTPUT_DIR}/scratchpad.json', 'w') as f:
        json.dump(scratchpad, f, indent=2, ensure_ascii=False)

    # Save audit trail
    with open(f'{OUTPUT_DIR}/audit_trail.json', 'w') as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)

    # Save source code files
    for filename, code in source_code.items():
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, 'w') as f:
            f.write(code)
        print(f'  Saved: {filename} ({len(code)} chars)')

    print(f'\nSaved {len(source_code)} files to {OUTPUT_DIR}')
    print(f'Test report: {test_report.get("status", "N/A")}')

asyncio.run(main())
