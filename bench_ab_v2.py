#!/usr/bin/env python3
"""A/B Test v2: Enjambre Mejorado vs Pro Build"""
import asyncio, time, sys, re
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from src.config import get_pro_llm, safe_invoke, reset_fallback, precheck_free_model, detect_complexity, set_complexity
from src.state import TeamState
from src.graph import get_graph
from src.model_router import reset_router, get_router
from langchain_core.messages import HumanMessage, SystemMessage

SEP = "=" * 72
DASH = "-" * 60

TESTS = [
    ('A', 'filter_logs', 'Crea una funcion filter_logs(logs, level, since) que filtre logs por nivel y timestamp. Incluye tests pytest. Un solo archivo .py.'),
    ('B', 'CLI CSV', 'Crea un script CLI en Python que procese un archivo CSV de ventas con columnas: fecha,producto,cantidad,precio. Calcula totales por producto y exporta a Excel. Usa argparse y pandas. Archivos: main.py + processor.py + tests/test_processor.py.'),
    ('C', 'API REST', 'Crea API REST Flask para catalogo de productos con GET/POST/PUT/DELETE /products. Validar nombre no vacio, precio>0. Tests pytest con fixture. Archivos: app.py, tests/test_api.py.'),
]

PROMPT_PRO = 'Eres ingeniero Python senior. Genera codigo completo con tests pytest. Separa archivos con # --- filename.py ---. Incluye type hints, docstrings, manejo de errores.'

async def run_pro(req):
    t0 = time.time()
    llm = get_pro_llm(max_tokens=8192)
    resp = await safe_invoke(llm, [SystemMessage(content=PROMPT_PRO), HumanMessage(content=req)])
    c = resp.content if hasattr(resp,'content') else str(resp)
    files = {}; cur = None; code = []
    for line in c.split('\n'):
        m = re.match(r'^# ---+\s*(.+\.py)\s*---+$', line)
        if m:
            if cur: files[cur] = '\n'.join(code)
            cur = m.group(1).strip(); code = []
        elif cur: code.append(line)
    if cur: files[cur] = '\n'.join(code)
    if not files and c.strip(): files['main.py'] = c
    return {'files': files, 'time': time.time()-t0}

async def run_enjambre(req):
    reset_fallback()
    c = detect_complexity(req); set_complexity(c); reset_router(c)
    s = TeamState(user_requirement=req, business_rules=[], retrieved_memory='',
        injected_skills={'matched':[],'rules':[],'blueprint':'','code':'','checks':''},
        architecture_blueprint={}, source_code={}, test_report={},
        scratchpad=[], iteration_count=0, audit_trail=[], messages=[],
        debug_history=[], loop_detected=False, code_fingerprint='', router_stats={},
        error_history=[], last_error_set='')
    t0 = time.time()
    r = await get_graph().ainvoke(s)
    sc = r.get('source_code',{}); tr = r.get('test_report',{}); au = r.get('audit_trail',[])
    nodes = {'Orquestador','Arquitecto','Programador','Tester','Auditor Gate 1','Auditor Gate 2','Auditor Gate 3','Extractor','Tester (paralelo)','Investigador','Skill Resolver'}
    return {'files': sc, 'time': time.time()-t0, 'iteration': r.get('iteration_count',0),
            'status': tr.get('status','FAIL'), 'calls': sum(1 for s in au if s.get('nodo','') in nodes)}

def eval_q(files):
    if not files: return 0
    code = ' '.join(files.values())
    s = 0.15
    if 'def test_' in code: s += 0.20
    if ': str' in code or ': int' in code: s += 0.10
    if '"""' in code: s += 0.10
    if 'try:' in code or 'except' in code: s += 0.10
    if 'pytest' in code: s += 0.10
    if len(files) >= 2: s += 0.10
    if 'test_' in ' '.join(files.keys()): s += 0.10
    if 'requirements' in ' '.join(files.keys()).lower(): s += 0.05
    return round(s, 3)

async def main():
    print(SEP)
    print('  A/B TEST: ENJAMBRE (MEJORADO) vs PRO BUILD')
    print(SEP)
    print(f'  Fecha: {__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print()
    
    results_e, results_p = [], []
    
    for tid, tname, req in TESTS:
        print(f'  Test {tid}: {tname}')
        
        # Enjambre
        print(f'    Enjambre...', end=' ')
        sys.stdout.flush()
        re = await run_enjambre(req)
        qe = eval_q(re['files'])
        ra = get_router()
        pro_used = ra.pro_calls_used if ra else 0
        icon = chr(9989) if re['status'] == 'PASS' else chr(10060)
        print(f'{icon} {re["status"]} | {len(re["files"])} arch | {re["calls"]} calls | {pro_used} pro | {re["time"]:.0f}s | calidad {qe:.3f}')
        results_e.append(re)
        
        # Pro
        print(f'    Pro......', end=' ')
        sys.stdout.flush()
        rp = await run_pro(req)
        qp = eval_q(rp['files'])
        print(f'{chr(9989) if rp["files"] else chr(10060)} OK | {len(rp["files"])} arch | 1 call | {rp["time"]:.0f}s | calidad {qp:.3f}')
        results_p.append(rp)
    
    # Reporte
    print(f'\n{SEP}')
    print('  REPORTE COMPARATIVO')
    print(SEP)
    print(f'\n  {"Test":<6} {"Sistema":<12} {"Status":<8} {"Arch":<6} {"Calls":<7} {"Pro":<5} {"Tiempo":<8} {"Calidad":<8}')
    print(f'  {DASH}')
    
    avg_qe = avg_qp = 0.0
    total_te = total_tp = 0.0
    total_pro = 0
    
    for i, (tid, tname, req) in enumerate(TESTS):
        re = results_e[i]; rp = results_p[i]
        qe = eval_q(re['files']); qp = eval_q(rp['files'])
        ra = get_router()
        pro_used = ra.pro_calls_used if ra else 0
        avg_qe += qe; avg_qp += qp
        total_te += re['time']; total_tp += rp['time']
        total_pro += pro_used
        
        print(f'  {tid:<6} {"Enjambre":<12} {re["status"]:<8} {len(re["files"]):<6} {re["calls"]:<7} {pro_used:<5} {re["time"]:<8.0f} {qe:<8.3f}')
        print(f'  {"":6} {"Pro":<12} {"OK":<8} {len(rp["files"]):<6} {1:<7} {"-":<5} {rp["time"]:<8.0f} {qp:<8.3f}')
        print(f'  {DASH}')
    
    avg_qe /= 3; avg_qp /= 3
    
    print(f'\n  {"":20} {"Enjambre":>12} {"Pro":>12}')
    print(f'  {"-"*44}')
    print(f'  {"Calidad promedio":22} {avg_qe:>10.3f} {avg_qp:>10.3f}')
    print(f'  {"Tiempo total":22} {total_te:>10.0f}s {total_tp:>10.0f}s')
    print(f'  {"Archivos totales":22} {sum(len(r["files"]) for r in results_e):>10} {sum(len(r["files"]) for r in results_p):>10}')
    print(f'  {"Calls Pro totales":22} {total_pro:>10} {"N/A":>10}')
    
    print(f'\n  Costo: Enjambre ~$0.002/task ({total_pro} calls pro) vs Pro ~$0.015/task')
    
    print(f'\n{SEP}')
    if avg_qe >= avg_qp:
        print(f'  EL ENJAMBRE MEJORADO SUPERA AL PRO EN CALIDAD')
    else:
        print(f'  EL PRO AUN SUPERA AL ENJAMBRE EN CALIDAD')
    print(SEP)

asyncio.run(main())
