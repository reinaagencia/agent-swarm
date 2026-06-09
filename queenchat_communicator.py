#!/usr/bin/env python3
"""
QueenChat Communicator — Puente Agent-Swarm ↔ QueenChat (WhatsApp)

Este módulo permite al enjambre de agentes comunicarse bidireccionalmente
con Rodrigo a través de QueenChat vía WhatsApp.

¿Cómo funciona?
1. El enjambre detecta que fue invocado por QueenChat (variable ENJAMBRE_MODE=true)
2. Cuando necesita input de Rodrigo, llama a send_ask() que genera un marcador
   <!--QUEENCHAT:ask(...)--> en el output
3. El daemon detecta el marcador y envía la pregunta a Rodrigo vía WhatsApp
4. Cuando Rodrigo responde, QueenChat reenvía la respuesta al enjambre

Variables de entorno:
- ENJAMBRE_MODE: "true" si el enjambre fue invocado por QueenChat
- ENJAMBRE_SESSION_ID: ID de sesión único
- QUEENCHAT_API_BASE: URL base de QueenChat (default: http://localhost:3000)
- ORCHESTRATOR_API_TOKEN: Token de autenticación
- REPLY_PHONE: Número de WhatsApp de Rodrigo
"""

import os
import json
import urllib.request
import urllib.error
import sys
from typing import Optional

# ── Configuración ────────────────────────────────────────────────────

ENJAMBRE_MODE = os.environ.get("ENJAMBRE_MODE", "").lower() == "true"
SESSION_ID = os.environ.get("ENJAMBRE_SESSION_ID", "")
QUEENCHAT_API_BASE = os.environ.get("QUEENCHAT_API_BASE", "http://localhost:3000")
API_TOKEN = os.environ.get("ORCHESTRATOR_API_TOKEN", "queenchat-bridge-secret-2026")
REPLY_PHONE = os.environ.get("REPLY_PHONE", "573006806468")  # Rodrigo por defecto

# ── API de comunicación ──────────────────────────────────────────────


def is_queenchat_mode() -> bool:
    """Retorna True si el enjambre fue invocado por QueenChat."""
    return ENJAMBRE_MODE


def build_ask_marker(message: str, phone: Optional[str] = None) -> str:
    """
    Genera un marcador <!--QUEENCHAT:ask(...)--> que el daemon detectará
    para enviar un mensaje a Rodrigo vía WhatsApp.

    Args:
        message: Mensaje que el enjambre quiere enviar a Rodrigo
        phone: Número de teléfono (default: Rodrigo)

    Returns:
        String con el marcador para incluir en el output
    """
    target_phone = phone or REPLY_PHONE
    # Escapar comillas en el mensaje
    safe_message = message.replace('"', '\\"').replace("'", "\\'")
    return f'<!--QUEENCHAT:ask(phone="{target_phone}",message="{safe_message}")-->'


def send_to_rodrigo(message: str, phone: Optional[str] = None) -> bool:
    """
    Envía un mensaje directo a Rodrigo vía QueenChat API.

    Este método hace una llamada HTTP directa a QueenChat para que
    envíe el mensaje por WhatsApp. Úsalo cuando necesites comunicación
    inmediata sin pausar el pipeline.

    Args:
        message: Mensaje a enviar
        phone: Número de teléfono (default: Rodrigo)

    Returns:
        True si se envió exitosamente
    """
    if not is_queenchat_mode():
        # Si no estamos en modo QueenChat, solo imprimir en consola
        print(f"\n[QueenChat] 📤 Mensaje para Rodrigo ({phone or REPLY_PHONE}):")
        print(f"[QueenChat] {message}")
        return True

    try:
        url = f"{QUEENCHAT_API_BASE}/agent-suite/enjambre/callback"
        payload = json.dumps({
            "type": "enjambre_notify",
            "sessionId": SESSION_ID,
            "phone": phone or REPLY_PHONE,
            "message": message,
            "context": "",
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-token": API_TOKEN,
            },
            method="POST",
        )

        response = urllib.request.urlopen(req, timeout=30)
        status = response.getcode()
        print(f"\n[QueenChat] ✅ Mensaje enviado a Rodrigo (HTTP {status})")
        return status == 200

    except urllib.error.HTTPError as e:
        print(f"\n[QueenChat] ⚠️ Error HTTP {e.code} enviando mensaje: {e.read().decode()[:200]}")
        return False
    except urllib.error.URLError as e:
        print(f"\n[QueenChat] ⚠️ Error de conexión: {e.reason}")
        return False
    except Exception as e:
        print(f"\n[QueenChat] ⚠️ Error inesperado: {e}")
        return False


def wait_for_input(question: str, phone: Optional[str] = None) -> Optional[str]:
    """
    Envía una pregunta a Rodrigo y espera su respuesta.

    NOTA: En modo pipeline (no interactivo), este método genera el marcador
    <!--QUEENCHAT:ask--> que el daemon detectará. El pipeline se pausa
    hasta que Rodrigo responda.

    En modo interactivo (standalone), pregunta por terminal.

    Args:
        question: Pregunta para Rodrigo
        phone: Número de teléfono

    Returns:
        La respuesta de Rodrigo o None si no se pudo obtener
    """
    if not is_queenchat_mode():
        # Modo interactivo local: preguntar por terminal
        print(f"\n🤔 [{SESSION_ID or 'enjambre'}] Pregunta para Rodrigo:")
        print(f"   {question}")
        try:
            response = input("   > ").strip()
            return response if response else None
        except (EOFError, KeyboardInterrupt):
            return None

    # Modo QueenChat: generar marcador en output
    # El daemon detectará esto y enviará la pregunta a WhatsApp
    marker = build_ask_marker(question, phone)
    print(f"\n[QueenChat] ⏸️  Enjambre necesita input de Rodrigo...")
    print(f"[QueenChat] Pregunta: {question}")
    print(f"[QueenChat] Marcador: {marker}")
    print(f"[QueenChat] El daemon pausará el pipeline y esperará respuesta.")

    # En modo pipeline, debemos retornar None porque no podemos esperar
    # sincrónicamente. El daemon se encarga de re-ejecutar con la respuesta.
    return None


def notify_completion(summary: str, files: list = None, phone: Optional[str] = None):
    """
    Notifica a Rodrigo que el enjambre completó una tarea.

    Args:
        summary: Resumen de lo que se completó
        files: Lista de archivos generados
        phone: Número de teléfono
    """
    message_parts = [f"✅ Enjambre completó la tarea:\n{summary}"]

    if files:
        message_parts.append(f"\n📁 Archivos generados ({len(files)}):")
        for f in files[:5]:
            message_parts.append(f"  • {f}")
        if len(files) > 5:
            message_parts.append(f"  ... y {len(files) - 5} más")

    message = "\n".join(message_parts)
    send_to_rodrigo(message, phone)


def notify_error(error: str, phone: Optional[str] = None):
    """
    Notifica a Rodrigo que hubo un error en el enjambre.

    Args:
        error: Descripción del error
        phone: Número de teléfono
    """
    message = f"❌ El Enjambre encontró un error:\n{error[:500]}"
    send_to_rodrigo(message, phone)


# ── Integración con el pipeline ──────────────────────────────────────


class QueenChatContext:
    """
    Contexto de comunicación QueenChat que se inyecta en el pipeline.
    """

    def __init__(self):
        self.mode = is_queenchat_mode()
        self.session_id = SESSION_ID
        self.reply_phone = REPLY_PHONE
        self.needs_input = False
        self.pending_question = None

    def ask(self, question: str) -> Optional[str]:
        """
        Pregunta a Rodrigo y espera respuesta.
        En modo QueenChat, genera marcador y retorna None.
        """
        self.needs_input = True
        self.pending_question = question
        return wait_for_input(question, self.reply_phone)

    def send_message(self, message: str):
        """Envía un mensaje a Rodrigo."""
        return send_to_rodrigo(message, self.reply_phone)

    def get_system_prompt(self) -> str:
        """
        Genera el prompt de sistema para inyectar en el pipeline,
        informando al enjambre que está siendo orquestado por QueenChat.
        """
        if not self.mode:
            return ""

        return f"""
[MODO QUEENCHAT - ACTIVADO]
Estás siendo ejecutado a través de QueenChat. Rodrigo te ha enviado una instrucción desde WhatsApp.

CANAL DE COMUNICACIÓN:
- Tus respuestas serán enviadas a Rodrigo por WhatsApp
- Para preguntarle algo a Rodrigo, usa: <!--QUEENCHAT:ask(phone="{self.reply_phone}",message="tu pregunta")-->
- Cuando necesites su autorización o más datos, genera ese marcador y el sistema se pausará
- Al completar la tarea, los resultados se enviarán automáticamente

REGLAS:
1. Trabaja normalmente, el scratchpad y memoria funcionan igual
2. Si necesitas algo de Rodrigo, genera el marcador QUEENCHAT:ask
3. No te preocupes por formatear output para WhatsApp — el bridge lo hace por ti
4. Sesión ID: {self.session_id}
"""

    def __str__(self) -> str:
        return f"QueenChatContext(session={self.session_id}, mode={'active' if self.mode else 'local'})"


# ── Singleton para uso fácil ─────────────────────────────────────────

queenchat = QueenChatContext()


# ── Test rápido ──────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  QueenChat Communicator — Test")
    print("=" * 60)
    print(f"  Mode: {'QueenChat' if is_queenchat_mode() else 'Local'}")
    print(f"  Session: {SESSION_ID or 'N/A'}")
    print(f"  API: {QUEENCHAT_API_BASE}")
    print(f"  Reply phone: {REPLY_PHONE}")
    print()

    ctx = QueenChatContext()
    print(ctx.get_system_prompt() or "  ☐ Modo QueenChat INACTIVO")

    print()
    print("  Ejemplo de marcador:")
    print(f'  {build_ask_marker("¿Qué diseño prefieres para el botón de login?")}')
    print()

    # En modo local, probar envío
    if not is_queenchat_mode():
        print("  Enviando mensaje de prueba...")
        send_to_rodrigo("🧪 Mensaje de prueba desde el enjambre")
        print("  Hecho.")
    else:
        print("  ☑ En modo QueenChat — el daemon maneja la comunicación.")
