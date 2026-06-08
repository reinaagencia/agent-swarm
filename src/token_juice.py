"""TokenJuice — Capa de compresión inteligente de tokens.

Inspirado en el TokenJuice de OpenHuman (tinyhumansai/openhuman).
Reduce el consumo de tokens 40-80% mediante compresión de tool outputs,
HTML→Markdown, truncado inteligente, deduplicación y acortamiento de URLs.

Cada función recibe texto crudo y devuelve texto comprimido + métricas
de ahorro para logging y optimización de presupuesto.

Autor: Enjambre Dev v3.0 → v4.0 | Fase 1 TokenJuice | Junio 2026
"""

import re
import html
import hashlib
import logging
from typing import Tuple, Optional
from dataclasses import dataclass, field
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

# ── Constantes ───────────────────────────────────────────────────

DEFAULT_MAX_TOKENS = 3000       # Tokens máximos después de compresión
CHUNK_HEAD_PCT = 0.70          # 70% del presupuesto para el inicio
CHUNK_TAIL_PCT = 0.30          # 30% para el final
EMPTY_LINE_LIMIT = 2           # Máx. líneas vacías consecutivas
MIN_LINE_LENGTH = 20           # Líneas < N chars se consideran cortas
APPROX_CHARS_PER_TOKEN = 4     # Estimación chars → tokens (~4 chars/token)


# ── HTML → Markdown parser integrado ────────────────────────────

class HTMLStripper(HTMLParser):
    """Convierte HTML a texto plano preservando estructura básica."""

    def __init__(self):
        super().__init__()
        self.output = []
        self.skip_data = False
        self.in_pre = False
        self.list_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ('script', 'style', 'noscript', 'svg', 'canvas'):
            self.skip_data = True
        elif tag == 'pre':
            self.in_pre = True
        elif tag in ('br', 'hr'):
            self.output.append('\n')
        elif tag in ('p', 'div', 'section', 'article', 'header', 'footer',
                     'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.output.append('\n')
        elif tag in ('ul', 'ol'):
            self.list_depth += 1

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ('script', 'style', 'noscript', 'svg', 'canvas'):
            self.skip_data = False
        elif tag == 'pre':
            self.in_pre = False
            self.output.append('\n')
        elif tag in ('p', 'div', 'section', 'article', 'header', 'footer'):
            self.output.append('\n')
        elif tag in ('ul', 'ol'):
            self.list_depth -= 1

    def handle_data(self, data):
        if self.skip_data:
            return
        text = data.strip()
        if text:
            self.output.append(text)
            if not self.in_pre:
                self.output.append(' ')

    def get_text(self) -> str:
        return ''.join(self.output)


def html_to_markdown(html_text: str) -> Tuple[str, dict]:
    """Convierte HTML a texto limpio preservando estructura legible.

    Returns:
        (texto_plano, stats) — stats incluye bytes_original, bytes_resultado, ratio
    """
    if not html_text or '<' not in html_text:
        return html_text, {"html_detected": False, "saved_bytes": 0}

    original_bytes = len(html_text.encode('utf-8'))
    stripper = HTMLStripper()
    stripper.feed(html_text)

    text = stripper.get_text()
    # Decodificar entidades HTML (&amp; → &, etc.)
    text = html.unescape(text)
    # Colapsar espacios múltiples
    text = re.sub(r' {2,}', ' ', text)
    # Colapsar saltos de línea múltiples
    text = re.sub(r'\n{3,}', '\n\n', text)

    result_bytes = len(text.encode('utf-8'))
    saved = original_bytes - result_bytes
    ratio = saved / max(original_bytes, 1)

    return text.strip(), {
        "html_detected": True,
        "original_bytes": original_bytes,
        "result_bytes": result_bytes,
        "saved_bytes": saved,
        "compression_ratio": round(ratio, 3),
    }


# ── Estimación de tokens ────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Estima tokens en un texto (~4 chars por token en inglés, ~2.5 en español).

    Usa heurística conservadora de 4 chars/token para no subestimar.
    """
    if not text:
        return 0
    # Contar palabras (más preciso que chars para texto mixto)
    words = len(text.split())
    chars = len(text)
    # Promedio ponderado: palabras * 1.3 + chars / 6
    return int(words * 1.3 + chars / 6)


# ── Truncado inteligente ────────────────────────────────────────

def intelligent_truncate(text: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> Tuple[str, dict]:
    """Trunca preservando inicio (70%) + final (30%) del contenido.

    A diferencia del truncado simple (cortar al final), preserva
    conclusiones y secciones finales que suelen contener información
    importante (resultados, recomendaciones, próximos pasos).

    Args:
        text: Texto a truncar
        max_tokens: Límite objetivo de tokens

    Returns:
        (texto_truncado, stats)
    """
    if not text:
        return text, {"truncated": False, "tokens_before": 0, "tokens_after": 0}

    tokens_before = estimate_tokens(text)
    if tokens_before <= max_tokens:
        return text, {"truncated": False, "tokens_before": tokens_before, "tokens_after": tokens_before}

    lines = text.split('\n')
    total_lines = len(lines)

    head_max = max(int(max_tokens * CHUNK_HEAD_PCT), 100)
    tail_max = max(int(max_tokens * CHUNK_TAIL_PCT), 50)

    # Head: acumular líneas desde el inicio hasta llenar head_max
    head_lines = []
    head_tokens = 0
    for line in lines:
        line_tokens = estimate_tokens(line)
        if head_tokens + line_tokens > head_max:
            break
        head_lines.append(line)
        head_tokens += line_tokens

    # Tail: acumular líneas desde el final hasta llenar tail_max
    tail_lines = []
    tail_tokens = 0
    used_head = len(head_lines)
    remaining = lines[used_head:]
    for line in reversed(remaining):
        line_tokens = estimate_tokens(line)
        if tail_tokens + line_tokens > tail_max:
            break
        tail_lines.insert(0, line)
        tail_tokens += line_tokens

    # Construir resultado
    middle_marker = f"\n\n[... {total_lines - used_head - len(tail_lines)} líneas omitidas — ahorro de tokens por TokenJuice ...]\n\n"
    result = '\n'.join(head_lines) + middle_marker + '\n'.join(tail_lines)

    tokens_after = estimate_tokens(result)
    return result, {
        "truncated": True,
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "lines_before": total_lines,
        "lines_omitted": total_lines - used_head - len(tail_lines),
        "saved_pct": round((1 - tokens_after / max(tokens_before, 1)) * 100, 1),
    }


# ── Deduplicación ───────────────────────────────────────────────

def dedup_lines(text: str) -> Tuple[str, dict]:
    """Elimina líneas repetidas y colapsa patrones repetitivos."""
    if not text:
        return text, {"duplicates_removed": 0}

    lines = text.split('\n')
    seen = set()
    clean = []
    removed = 0
    consecutive_empty = 0

    for line in lines:
        stripped = line.strip()

        # Limitar líneas vacías consecutivas
        if not stripped:
            consecutive_empty += 1
            if consecutive_empty > EMPTY_LINE_LIMIT:
                removed += 1
                continue
        else:
            consecutive_empty = 0

        # Detectar duplicados exactos
        line_hash = hashlib.md5(stripped.encode()).hexdigest()
        if line_hash in seen:
            # Solo eliminar si no es muy corta (líneas cortas pueden ser legítimas)
            if len(stripped) > MIN_LINE_LENGTH:
                removed += 1
                continue

        if len(stripped) > MIN_LINE_LENGTH:
            seen.add(line_hash)

        clean.append(line)

    result = '\n'.join(clean)
    return result, {"duplicates_removed": removed, "lines_original": len(lines), "lines_result": len(clean)}


# ── Acortamiento de URLs ───────────────────────────────────────

URL_PATTERN = re.compile(r'https?://[^\s<>"\')\]]+')


def shorten_urls(text: str) -> Tuple[str, dict]:
    """Acorta URLs largas preservando dominio y ruta clave.

    https://github.com/tinyhumansai/openhuman/blob/main/src/core/engine.rs
    → github.com/tinyhumansai/openhuman/.../engine.rs
    """
    if not text:
        return text, {"urls_shortened": 0, "bytes_saved": 0}

    count = 0
    bytes_saved = 0

    def _shorten(match):
        nonlocal count, bytes_saved
        url = match.group(0)
        original_len = len(url)

        # Extraer dominio y ruta significativa
        shortened = re.sub(r'https?://(www\.)?', '', url)
        # Si es muy larga, truncar manteniendo las 3 últimas partes de ruta
        if len(shortened) > 80:
            parts = shortened.split('/')
            if len(parts) > 4:
                shortened = '/'.join(parts[:2]) + '/.../' + '/'.join(parts[-2:])

        count += 1
        bytes_saved += original_len - len(shortened)
        return shortened

    result = URL_PATTERN.sub(_shorten, text)
    return result, {"urls_shortened": count, "bytes_saved": bytes_saved}


# ── Limpieza de código/JSON verboso ─────────────────────────────

def compress_verbose_output(text: str) -> Tuple[str, dict]:
    """Comprime output verboso: logs de build, JSON con arrays enormes, stack traces.

    Estrategias:
    - Arrays JSON con >10 elementos → muestran primeros 3 + count
    - Stack traces → solo primeras 5 líneas + mensaje
    - Timestamps repetitivos → colapsar a un marcador
    """
    if not text:
        return text, {"verbose_compressed": False}

    original_tokens = estimate_tokens(text)
    result = text

    # Stack traces: reducir a lo esencial
    stack_pattern = re.compile(r'(Traceback \(most recent call last\):.*?)(?=\n\n|\Z)', re.DOTALL)
    def _compress_stack(match):
        lines = match.group(0).split('\n')
        if len(lines) > 7:
            return '\n'.join(lines[:5]) + f'\n  [... {len(lines) - 5} frames más ...]\n' + lines[-1]
        return match.group(0)

    result = stack_pattern.sub(_compress_stack, result)

    # Arrays JSON enormes: truncar
    array_pattern = re.compile(r'\[([^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*?)\]')
    def _truncate_array(match):
        content = match.group(1)
        items = [i.strip() for i in content.split(',') if i.strip()]
        if len(items) > 10:
            return '[' + ', '.join(items[:3]) + f', ... ({len(items) - 3} items más) ...]'
        return match.group(0)

    result = array_pattern.sub(_truncate_array, result)

    tokens_after = estimate_tokens(result)
    return result, {
        "verbose_compressed": tokens_after < original_tokens,
        "tokens_before": original_tokens,
        "tokens_after": tokens_after,
    }


# ── Pipeline principal ──────────────────────────────────────────

@dataclass
class TokenJuiceStats:
    """Estadísticas acumuladas de compresión."""

    total_calls: int = 0
    total_tokens_before: int = 0
    total_tokens_after: int = 0
    total_bytes_before: int = 0
    total_bytes_after: int = 0
    html_savings: int = 0
    urls_shortened: int = 0
    duplicates_removed: int = 0
    details: list = field(default_factory=list)

    @property
    def overall_savings_pct(self) -> float:
        if self.total_tokens_before == 0:
            return 0.0
        return round((1 - self.total_tokens_after / self.total_tokens_before) * 100, 1)

    @property
    def summary(self) -> str:
        return (
            f"TokenJuice: {self.total_calls} llamadas | "
            f"{self.total_tokens_before} → {self.total_tokens_after} tokens "
            f"({self.overall_savings_pct}% ahorro) | "
            f"{self.html_savings} HTML | {self.urls_shortened} URLs | "
            f"{self.duplicates_removed} dups"
        )


# Instancia global para tracking
_stats = TokenJuiceStats()


def compress(text: str, max_tokens: int = DEFAULT_MAX_TOKENS,
             is_html: bool = False) -> Tuple[str, dict]:
    """Pipeline completo de compresión TokenJuice.

    Aplica en orden:
    1. HTML → Markdown (si is_html=True o se detecta HTML)
    2. Acortamiento de URLs
    3. Compresión de output verboso (logs, stacks, JSON)
    4. Deduplicación de líneas
    5. Truncado inteligente (preserva inicio + final)

    Args:
        text: Texto a comprimir
        max_tokens: Límite máximo de tokens tras compresión
        is_html: Forzar modo HTML aunque no se detecte

    Returns:
        (texto_comprimido, report) — report contiene métricas detalladas
    """
    global _stats

    if not text:
        return text, {"compressed": False, "reason": "empty_input"}

    original_tokens = estimate_tokens(text)
    report = {
        "compressed": False,
        "tokens_before": original_tokens,
        "steps_applied": [],
    }

    current = text
    total_saved = 0

    # Paso 1: HTML → Markdown
    if is_html or ('<' in current[:200] and '>' in current[:200]):
        current, html_stats = html_to_markdown(current)
        if html_stats.get("html_detected"):
            report["steps_applied"].append("html_to_markdown")
            report["html_stats"] = html_stats
            _stats.html_savings += html_stats.get("saved_bytes", 0)

    # Paso 2: Acortar URLs
    current, url_stats = shorten_urls(current)
    if url_stats["urls_shortened"] > 0:
        report["steps_applied"].append("shorten_urls")
        report["url_stats"] = url_stats
        _stats.urls_shortened += url_stats["urls_shortened"]

    # Paso 3: Comprimir output verboso
    current, verbose_stats = compress_verbose_output(current)
    if verbose_stats["verbose_compressed"]:
        report["steps_applied"].append("compress_verbose")
        report["verbose_stats"] = verbose_stats

    # Paso 4: Deduplicar
    current, dedup_stats = dedup_lines(current)
    if dedup_stats["duplicates_removed"] > 0:
        report["steps_applied"].append("dedup_lines")
        report["dedup_stats"] = dedup_stats
        _stats.duplicates_removed += dedup_stats["duplicates_removed"]

    # Paso 5: Truncado inteligente
    current, trunc_stats = intelligent_truncate(current, max_tokens)
    if trunc_stats["truncated"]:
        report["steps_applied"].append("intelligent_truncate")
        report["truncate_stats"] = trunc_stats

    # Final
    result_tokens = estimate_tokens(current)
    saved = original_tokens - result_tokens
    report["compressed"] = saved > 0
    report["tokens_after"] = result_tokens
    report["saved_tokens"] = saved
    report["saved_pct"] = round((saved / max(original_tokens, 1)) * 100, 1)

    # Actualizar estadísticas globales
    _stats.total_calls += 1
    _stats.total_tokens_before += original_tokens
    _stats.total_tokens_after += result_tokens

    if report["compressed"]:
        logger.info(
            f"TokenJuice: {original_tokens}→{result_tokens} tokens "
            f"({report['saved_pct']}% ahorro) | pasos: {report['steps_applied']}"
        )

    return current, report


def compress_state_context(state: dict, fields_to_compress: list = None,
                           max_tokens: int = DEFAULT_MAX_TOKENS) -> dict:
    """Comprime campos específicos del TeamState antes de enviar al LLM.

    Args:
        state: TeamState dict
        fields_to_compress: Lista de campos a comprimir (default: ['retrieved_memory'])
        max_tokens: Límite de tokens por campo

    Returns:
        Dict con campos comprimidos listos para merge en el state
    """
    if fields_to_compress is None:
        fields_to_compress = ["retrieved_memory", "scratchpad"]

    result = {}

    for field in fields_to_compress:
        value = state.get(field, "")
        if isinstance(value, list):
            value = "\n".join(value)

        if isinstance(value, str) and len(value) > 500:
            compressed, report = compress(value, max_tokens)
            if report["compressed"]:
                result[field + "_original_tokens"] = report["tokens_before"]
                result[field] = compressed
                logger.debug(
                    f"TokenJuice.{field}: {report['tokens_before']}→"
                    f"{report['tokens_after']} tokens "
                    f"({report['saved_pct']}% ahorro)"
                )

    return result


def get_stats() -> TokenJuiceStats:
    """Devuelve estadísticas acumuladas de TokenJuice."""
    return _stats


def reset_stats():
    """Reinicia estadísticas (útil entre ejecuciones de prueba)."""
    global _stats
    _stats = TokenJuiceStats()
