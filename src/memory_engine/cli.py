"""
🎛️ CLI — Interfaz de línea de comandos para el Memory Engine.

Permite gestionar la memoria del enjambre desde terminal.

Uso:
    python -m src.memory_engine.cli save <file> [--project P] [--topic T]
    python -m src.memory_engine.cli get <chat_id>
    python -m src.memory_engine.cli index <chat_id>
    python -m src.memory_engine.cli search <query> [--project P] [--tag T]
    python -m src.memory_engine.cli list [--project P]
    python -m src.memory_engine.cli projects
    python -m src.memory_engine.cli diary <project>
    python -m src.memory_engine.cli diary-add <project> [--chat C] [--logros L]
    python -m src.memory_engine.cli merge <proj1> <proj2> [--strategy group|fuse] [--name N]
    python -m src.memory_engine.cli split <project> --splits '[{"name":"A","tags":["x"]}]'
    python -m src.memory_engine.cli rebuild
    python -m src.memory_engine.cli maintenance
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="🧠 Memory Engine — Sistema de Memoria Multi-Capa del Enjambre",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python -m src.memory_engine.cli list --project enjambre-engine
  python -m src.memory_engine.cli search "websocket dashboard" --tag mejora
  python -m src.memory_engine.cli diary enjambre-engine
  python -m src.memory_engine.cli merge proyecto-a proyecto-b --strategy fuse --name fusion-ab
  python -m src.memory_engine.cli rebuild
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Comando a ejecutar")

    # save
    save_p = subparsers.add_parser("save", help="Guarda un chat en la memoria")
    save_p.add_argument("file", help="Archivo markdown con el contenido del chat")
    save_p.add_argument("--project", "-p", default="general", help="Nombre del proyecto")
    save_p.add_argument("--topic", "-t", default="sesion", help="Tema del chat")
    save_p.add_argument("--tags", nargs="*", default=[], help="Tags")
    save_p.add_argument("--decisions", nargs="*", default=[], help="Decisiones tomadas")
    save_p.add_argument("--dir", choices=["chats", "episodic", "sueltas"], default=None)

    # get
    get_p = subparsers.add_parser("get", help="Recupera un chat completo")
    get_p.add_argument("chat_id", help="ID del chat (CHAT-20260713-proyecto-tema-v1.md)")

    # index (get just the index)
    index_p = subparsers.add_parser("index", help="Muestra el índice de un chat")
    index_p.add_argument("chat_id", help="ID del chat")

    # search
    search_p = subparsers.add_parser("search", help="Búsqueda híbrida en la memoria")
    search_p.add_argument("query", help="Texto a buscar")
    search_p.add_argument("--project", help="Filtrar por proyecto")
    search_p.add_argument("--type", choices=["chat", "diary", "note"], help="Filtrar por tipo")
    search_p.add_argument("--tag", help="Filtrar por tag")
    search_p.add_argument("--limit", type=int, default=10, help="Máximo resultados")

    # list
    list_p = subparsers.add_parser("list", help="Lista chats")
    list_p.add_argument("--project", help="Filtrar por proyecto")

    # projects
    subparsers.add_parser("projects", help="Lista todos los proyectos")

    # diary
    diary_p = subparsers.add_parser("diary", help="Muestra el diario de un proyecto")
    diary_p.add_argument("project", help="Nombre del proyecto")

    # diary-add
    diary_add_p = subparsers.add_parser("diary-add", help="Añade entrada al diario")
    diary_add_p.add_argument("project", help="Nombre del proyecto")
    diary_add_p.add_argument("--chat", help="ID del chat relacionado")
    diary_add_p.add_argument("--logros", nargs="*", default=[], help="Logros")
    diary_add_p.add_argument("--decisiones", nargs="*", default=[], help="Decisiones")
    diary_add_p.add_argument("--lecciones", nargs="*", default=[], help="Lecciones")
    diary_add_p.add_argument("--pendientes", nargs="*", default=[], help="Pendientes")

    # merge
    merge_p = subparsers.add_parser("merge", help="Une dos o más proyectos")
    merge_p.add_argument("projects", nargs="+", help="Nombres de proyectos")
    merge_p.add_argument("--strategy", choices=["group", "fuse"], default="group",
                         help="group=carpeta macro, fuse=fusión real")
    merge_p.add_argument("--name", help="Nombre del proyecto resultante")

    # split
    split_p = subparsers.add_parser("split", help="Divide un proyecto")
    split_p.add_argument("project", help="Nombre del proyecto")
    split_p.add_argument("--splits", required=True,
                         help='JSON: [{"name":"A","tags":["x"]}, {"name":"B","tags":["y"]}]')

    # rebuild
    subparsers.add_parser("rebuild", help="Reconstruye el índice general")

    # maintenance
    subparsers.add_parser("maintenance", help="Ejecuta mantenimiento (L5)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Importar engine (lazy)
    from src.memory_engine import MemoryEngine
    engine = MemoryEngine()

    # Ejecutar comando
    try:
        if args.command == "save":
            with open(args.file, "r", encoding="utf-8") as f:
                content = f.read()
            from src.memory_engine.naming import generate_chat_id
            chat_id = generate_chat_id(args.project, args.topic)
            metadata = {
                "tags": args.tags,
                "decisions": args.decisions,
                "project": args.project,
                "topic": args.topic,
            }
            result = engine.save_chat(chat_id, content, metadata)
            print(json.dumps(result, indent=2, ensure_ascii=False))

        elif args.command == "get":
            result = engine.get_chat(args.chat_id)
            if result:
                print(f"--- Metadatos ---")
                print(json.dumps(result.get("metadata", {}), indent=2, ensure_ascii=False))
                print(f"\n--- Contenido ({len(result.get('content', ''))} chars) ---")
                print(result.get("content", "")[:2000] + "...")
            else:
                print(f"❌ Chat no encontrado: {args.chat_id}")

        elif args.command == "index":
            result = engine.get_chat_index(args.chat_id)
            if result:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print(f"❌ Chat no encontrado: {args.chat_id}")

        elif args.command == "search":
            result = engine.search(
                args.query,
                project=args.project,
                entry_type=args.type,
                tag=args.tag,
                limit=args.limit,
            )
            print(f"\n🔍 Query: '{result.query}'")
            print(f"📊 {result.total_results} resultados en {result.timing_ms}ms")
            print(f"🔧 Métodos: {', '.join(result.methods_used)}")
            if result.filters_applied:
                print(f"📋 Filtros: {result.filters_applied}")
            print()
            for entry in result.entries:
                score_str = f"[{entry.search_score:.3f}]" if entry.search_score else ""
                print(f"  {score_str} {entry.id}")
                print(f"     📝 {entry.title}")
                print(f"     📁 {entry.project} | {entry.date} | {entry.type}")
                if entry.tags:
                    print(f"     🏷️  {', '.join(entry.tags[:5])}")
                print()

        elif args.command == "list":
            chats = engine.list_chats(project=args.project)
            print(f"\n📋 {len(chats)} chats encontrados")
            print(f"{'ID':<55} {'Proyecto':<20} {'Fecha':<12} {'Estado':<10}")
            print("-" * 100)
            for c in chats:
                print(f"{c['chat_id']:<55} {c['project']:<20} {c['date']:<12} {c['status']:<10}")

        elif args.command == "projects":
            projects = engine.list_projects()
            print(f"\n📁 {len(projects)} proyectos")
            print(f"{'Proyecto':<25} {'Estado':<12} {'Prioridad':<12} {'Entradas':<10} {'Última':<12}")
            print("-" * 75)
            for p in projects:
                print(f"{p['project']:<25} {p['status']:<12} {p['priority']:<12} "
                      f"{p['entry_count']:<10} {p.get('last_entry', ''):<12}")

        elif args.command == "diary":
            diary = engine.get_diary(args.project)
            if diary:
                print(f"\n📓 Diario: {args.project}")
                print(f"   Estado: {diary.get('metadata', {}).get('status', '?')}")
                print(f"   Tags: {diary.get('metadata', {}).get('tags', [])}")
                print(f"   {len(diary.get('entries', []))} entradas\n")
                for entry in diary.get("entries", []):
                    print(f"  ### {entry.get('date', '?')}")
                    if entry.get("chat_id"):
                        print(f"    Chat: {entry['chat_id']}")
                    for a in entry.get("achievements", []):
                        print(f"    ✅ {a}")
                    for d in entry.get("decisions", []):
                        if isinstance(d, dict):
                            print(f"    📌 {d.get('tema', '')}: {d.get('decision', '')}")
                        else:
                            print(f"    📌 {d}")
                    for l in entry.get("lessons", []):
                        print(f"    💡 {l}")
                    for p in entry.get("pending", []):
                        print(f"    ⏳ {p}")
                    print()
            else:
                print(f"❌ Proyecto no encontrado: {args.project}")

        elif args.command == "diary-add":
            entry = {
                "chat_id": args.chat or "",
                "achievements": args.logros,
                "decisions": [{"tema": d.split(":")[0] if ":" in d else d,
                               "decision": d.split(":", 1)[1].strip() if ":" in d else ""}
                              for d in args.decisiones],
                "lessons": args.lecciones,
                "pending": args.pendientes,
            }
            result = engine.update_diary(args.project, entry)
            print(json.dumps(result, indent=2, ensure_ascii=False))

        elif args.command == "merge":
            result = engine.merge_projects(args.projects, strategy=args.strategy)
            if args.name:
                result["name"] = args.name
            print(json.dumps(result, indent=2, ensure_ascii=False))

        elif args.command == "split":
            splits = json.loads(args.splits)
            result = engine.split_project(args.project, splits)
            print(json.dumps(result, indent=2, ensure_ascii=False))

        elif args.command == "rebuild":
            result = engine.rebuild_index()
            print(json.dumps(result, indent=2, ensure_ascii=False))

        elif args.command == "maintenance":
            result = engine.run_maintenance()
            print(json.dumps(result, indent=2, ensure_ascii=False))

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
