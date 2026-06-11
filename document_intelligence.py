"""
document_intelligence.py — Inteligencia Documental para MASSIVE
===============================================================

Extrae parámetros de simulación MASSIVE desde archivos heterogéneos:
PDF, JSON, CSV, XLSX e imágenes con gráficas (via LLM visión).

Diseño:
    - Sin dependencias obligatorias: cada parser se activa solo si la
      librería correspondiente está instalada. Fallback a texto plano.
    - Salidas validadas con Pydantic v2 antes de llegar al simulador.
    - Totalmente agnóstico al proveedor LLM: usa llm_credentials.py.

Uso rápido::

    from document_intelligence import DocumentIntelligence
    di = DocumentIntelligence(llm_client=client)

    ctx = di.parse_file("informe_polarizacion.pdf")
    params = di.extract_massive_params(ctx)
    # params.config_dict  → listo para simular()

Autor: MASSIVE Research
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

log = logging.getLogger("massive.document_intelligence")

# ── Detección de dependencias opcionales ─────────────────────────────────────

def _try_import(module: str):
    try:
        import importlib
        return importlib.import_module(module)
    except ImportError:
        return None

_pdfplumber  = _try_import("pdfplumber")
_pandas      = _try_import("pandas")
_PIL         = _try_import("PIL.Image")
_openpyxl    = _try_import("openpyxl")   # backend de pandas para xlsx


# ── Modelos Pydantic de salida ────────────────────────────────────────────────

class ExtractedTimeSeries(BaseModel):
    """Serie temporal de opinión / actitud extraída del documento."""
    label: str = ""
    values: list[float] = Field(default_factory=list)
    timestamps: list[str] = Field(default_factory=list)
    unit: str = "opinion"            # "opinion", "porcentaje", "likert"
    source_column: str = ""


class ExtractedNetworkInfo(BaseModel):
    """Información de red/comunidades detectada en el documento."""
    n_nodes_approx: int | None = None
    n_communities: int | None = None
    density_approx: float | None = None
    topology_hint: str = ""          # "scale-free", "small-world", "random"


class ExtractedDemographics(BaseModel):
    """Distribución sociodemográfica detectada."""
    religion_pct: float | None = Field(None, ge=0.0, le=1.0)
    education_high_pct: float | None = Field(None, ge=0.0, le=1.0)
    age_young_pct: float | None = Field(None, ge=0.0, le=1.0)
    age_middle_pct: float | None = Field(None, ge=0.0, le=1.0)
    age_senior_pct: float | None = Field(None, ge=0.0, le=1.0)


class MASSIVEExtractedConfig(BaseModel):
    """
    Parámetros MASSIVE extraídos/inferidos desde un documento.

    Solo se populan los campos con evidencia explícita o fuerte inferencia.
    Los campos None deben mantenerse en sus defaults del simulador.
    """
    # Estado inicial
    opinion_inicial: float | None = Field(None, ge=-1.0, le=1.0)
    confianza_institucional: float | None = Field(None, ge=0.0, le=1.0)
    propaganda: float | None = Field(None, ge=-1.0, le=1.0)

    # Grupos
    opinion_grupo_a: float | None = Field(None, ge=-1.0, le=1.0)
    opinion_grupo_b: float | None = Field(None, ge=-1.0, le=1.0)
    identidad_grupo: float | None = Field(None, ge=0.0, le=1.0)

    # Mecanismos
    sesgo_confirmacion: float | None = Field(None, ge=0.0, le=1.0)
    homofilia: float | None = Field(None, ge=0.0, le=1.0)
    pasos: int | None = Field(None, ge=10, le=500)

    # Pesos de capas (multilayer)
    w_social: float | None = Field(None, ge=0.0, le=1.0)
    w_digital: float | None = Field(None, ge=0.0, le=1.0)
    w_economico: float | None = Field(None, ge=0.0, le=1.0)

    # Demografía para multilayer
    demographics: ExtractedDemographics = Field(
        default_factory=ExtractedDemographics
    )

    # Regla sugerida
    regla_sugerida: str | None = None    # nombre de la regla del simulador
    archetype_sugerido: str | None = None  # archetype del Programmatic Architect

    # Metadatos de extracción
    confianza_extraccion: float = Field(0.5, ge=0.0, le=1.0)
    campos_inferidos: list[str] = Field(default_factory=list)
    campos_faltantes: list[str] = Field(default_factory=list)
    notas: str = ""

    @field_validator("opinion_inicial", "propaganda",
                     "opinion_grupo_a", "opinion_grupo_b", mode="before")
    @classmethod
    def _clip_bipolar(cls, v):
        if v is not None:
            return max(-1.0, min(1.0, float(v)))
        return v

    def to_simular_kwargs(self) -> dict[str, Any]:
        """
        Convierte los campos extraídos al formato de kwargs de simular().
        Solo incluye campos con valor (no None).
        """
        mapping = {
            "opinion_inicial": "opinion",
            "confianza_institucional": "confianza",
            "propaganda": "propaganda",
            "opinion_grupo_a": "opinion_grupo_a",
            "opinion_grupo_b": "opinion_grupo_b",
            "identidad_grupo": "identidad_grupo",
            "sesgo_confirmacion": "sesgo_confirmacion",
            "homofilia": "homofilia_rate",
            "pasos": "pasos",
        }
        out: dict[str, Any] = {}
        for src, dst in mapping.items():
            val = getattr(self, src)
            if val is not None:
                out[dst] = val
        return out


class DocumentContext(BaseModel):
    """Contexto completo extraído de uno o varios archivos."""
    filename: str = ""
    file_type: str = ""              # "pdf", "json", "csv", "xlsx", "image", "text"
    raw_text: str = ""               # texto plano extraído
    structured_data: dict = Field(default_factory=dict)  # datos tabulares/JSON
    image_b64: str | None = None     # imagen (portada, gráfica) en base64
    charts_description: str = ""     # descripción de gráficas detectadas
    time_series: list[ExtractedTimeSeries] = Field(default_factory=list)
    network_info: ExtractedNetworkInfo = Field(
        default_factory=ExtractedNetworkInfo
    )
    parse_warnings: list[str] = Field(default_factory=list)

    @property
    def summary_for_llm(self) -> str:
        """
        Texto compacto para incluir en el prompt del LLM.
        Combina texto, datos estructurados y descripciones de gráficas.
        """
        parts: list[str] = []
        if self.raw_text.strip():
            # Truncar a 6000 chars para no saturar el contexto
            parts.append(f"[TEXTO DEL DOCUMENTO]\n{self.raw_text[:6000]}")
        if self.structured_data:
            parts.append(
                f"[DATOS ESTRUCTURADOS]\n"
                + json.dumps(self.structured_data, ensure_ascii=False, indent=2)[:3000]
            )
        if self.charts_description:
            parts.append(f"[DESCRIPCIÓN DE GRÁFICAS]\n{self.charts_description}")
        if self.time_series:
            ts_summary = "\n".join(
                f"  · {ts.label}: {len(ts.values)} puntos, "
                f"rango [{min(ts.values, default=0):.2f}, {max(ts.values, default=0):.2f}]"
                for ts in self.time_series
            )
            parts.append(f"[SERIES TEMPORALES DETECTADAS]\n{ts_summary}")
        if self.network_info.n_nodes_approx:
            parts.append(
                f"[RED SOCIAL]\n"
                f"Nodos ≈ {self.network_info.n_nodes_approx}, "
                f"Comunidades ≈ {self.network_info.n_communities}, "
                f"Topología: {self.network_info.topology_hint}"
            )
        return "\n\n".join(parts) or "[Documento vacío o no parseable]"


# ── Parsers por tipo de archivo ───────────────────────────────────────────────

class _PDFParser:
    @staticmethod
    def parse(path: Path) -> DocumentContext:
        ctx = DocumentContext(filename=path.name, file_type="pdf")
        if _pdfplumber is None:
            ctx.parse_warnings.append(
                "pdfplumber no instalado. Instala con: pip install pdfplumber"
            )
            return ctx
        try:
            with _pdfplumber.open(str(path)) as pdf:
                texts: list[str] = []
                for page in pdf.pages:
                    t = page.extract_text() or ""
                    texts.append(t)
                    # Detectar tablas
                    for table in page.extract_tables():
                        if table:
                            ctx.structured_data.setdefault("tables", []).append(table)
                ctx.raw_text = "\n".join(texts)
                # Primera página como imagen para visión LLM
                if pdf.pages:
                    img = pdf.pages[0].to_image(resolution=96).original
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    ctx.image_b64 = base64.b64encode(buf.getvalue()).decode()
        except Exception as exc:
            ctx.parse_warnings.append(f"Error parseando PDF: {exc}")
        return ctx


class _JSONParser:
    @staticmethod
    def parse(path: Path) -> DocumentContext:
        ctx = DocumentContext(filename=path.name, file_type="json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            ctx.structured_data = data if isinstance(data, dict) else {"data": data}
            ctx.raw_text = json.dumps(data, ensure_ascii=False, indent=2)[:8000]
            # Detectar series temporales automáticamente
            _detect_time_series_from_dict(data, ctx)
        except Exception as exc:
            ctx.parse_warnings.append(f"Error parseando JSON: {exc}")
        return ctx


class _CSVParser:
    @staticmethod
    def parse(path: Path) -> DocumentContext:
        ctx = DocumentContext(filename=path.name, file_type="csv")
        if _pandas is None:
            ctx.parse_warnings.append(
                "pandas no instalado. Instala con: pip install pandas"
            )
            return ctx
        try:
            df = _pandas.read_csv(str(path))
            ctx.raw_text = df.describe(include="all").to_string()
            ctx.structured_data = {
                "columns": list(df.columns),
                "shape": list(df.shape),
                "dtypes": {c: str(t) for c, t in df.dtypes.items()},
                "sample": df.head(5).to_dict(orient="records"),
                "stats": json.loads(df.describe().to_json()),
            }
            _detect_time_series_from_df(df, ctx)
        except Exception as exc:
            ctx.parse_warnings.append(f"Error parseando CSV: {exc}")
        return ctx


class _XLSXParser:
    @staticmethod
    def parse(path: Path) -> DocumentContext:
        ctx = DocumentContext(filename=path.name, file_type="xlsx")
        if _pandas is None or _openpyxl is None:
            ctx.parse_warnings.append(
                "pandas/openpyxl no instalados: pip install pandas openpyxl"
            )
            return ctx
        try:
            sheets: dict[str, Any] = {}
            xls = _pandas.ExcelFile(str(path))
            for sheet in xls.sheet_names:
                df = xls.parse(sheet)
                sheets[sheet] = {
                    "columns": list(df.columns),
                    "shape": list(df.shape),
                    "sample": df.head(5).to_dict(orient="records"),
                }
                _detect_time_series_from_df(df, ctx)
            ctx.structured_data = {"sheets": sheets}
            ctx.raw_text = json.dumps(sheets, ensure_ascii=False, indent=2)[:6000]
        except Exception as exc:
            ctx.parse_warnings.append(f"Error parseando XLSX: {exc}")
        return ctx


class _ImageParser:
    @staticmethod
    def parse(path: Path) -> DocumentContext:
        ctx = DocumentContext(filename=path.name, file_type="image")
        try:
            with open(path, "rb") as f:
                ctx.image_b64 = base64.b64encode(f.read()).decode()
            ctx.raw_text = f"[Imagen: {path.name}]"
        except Exception as exc:
            ctx.parse_warnings.append(f"Error leyendo imagen: {exc}")
        return ctx


class _TextParser:
    @staticmethod
    def parse(path: Path) -> DocumentContext:
        ctx = DocumentContext(filename=path.name, file_type="text")
        try:
            ctx.raw_text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            ctx.parse_warnings.append(f"Error leyendo texto: {exc}")
        return ctx


# ── Detección automática de series temporales ─────────────────────────────────

_OPINION_KEYWORDS = {
    "opinion", "actitud", "attitude", "approval", "aprobacion", "apoyo",
    "rechazo", "polarizacion", "polarization", "sentiment", "sentimiento",
    "likert", "score", "indice", "index",
}

def _detect_time_series_from_df(df: Any, ctx: DocumentContext) -> None:
    if _pandas is None:
        return
    for col in df.select_dtypes(include=["number"]).columns:
        col_lower = str(col).lower()
        if any(kw in col_lower for kw in _OPINION_KEYWORDS):
            vals = df[col].dropna().tolist()
            if len(vals) >= 3:
                ctx.time_series.append(ExtractedTimeSeries(
                    label=str(col),
                    values=[float(v) for v in vals],
                    source_column=str(col),
                ))


def _detect_time_series_from_dict(data: Any, ctx: DocumentContext) -> None:
    if not isinstance(data, (dict, list)):
        return
    items = data.items() if isinstance(data, dict) else enumerate(data)
    for key, val in items:
        key_lower = str(key).lower()
        if any(kw in key_lower for kw in _OPINION_KEYWORDS):
            if isinstance(val, list) and all(
                isinstance(v, (int, float)) for v in val
            ):
                ctx.time_series.append(ExtractedTimeSeries(
                    label=str(key),
                    values=[float(v) for v in val],
                    source_column=str(key),
                ))


# ── Clase principal ───────────────────────────────────────────────────────────

_EXT_MAP: dict[str, type] = {
    ".pdf":  _PDFParser,
    ".json": _JSONParser,
    ".csv":  _CSVParser,
    ".xlsx": _XLSXParser,
    ".xls":  _XLSXParser,
    ".png":  _ImageParser,
    ".jpg":  _ImageParser,
    ".jpeg": _ImageParser,
    ".webp": _ImageParser,
    ".txt":  _TextParser,
    ".md":   _TextParser,
}

# System prompt compartido para todas las llamadas de extracción
_EXTRACTION_SYSTEM_PROMPT = """Eres un experto en dinámica social y ciencias de la conducta.
Se te proporciona contenido de un documento (informe, estudio, encuesta, dataset, etc.).
Tu tarea: extraer parámetros numéricos para el simulador MASSIVE y devolver SOLO JSON válido.

GLOSARIO DE PARÁMETROS (rango permitido):
  opinion_inicial        [-1.0, 1.0]  opinión media inicial de la población
  confianza_institucional [0.0, 1.0]  confianza en instituciones
  propaganda             [-1.0, 1.0]  narrativa dominante / media principal
  opinion_grupo_a        [-1.0, 1.0]  opinión del grupo afín/dominante
  opinion_grupo_b        [-1.0, 1.0]  opinión del grupo opuesto/minoritario
  identidad_grupo        [0.0, 1.0]   intensidad de identidad grupal
  sesgo_confirmacion     [0.0, 1.0]   sesgo de confirmación observado
  homofilia              [0.0, 1.0]   tendencia a interactuar con similares
  pasos                  [10, 500]    duración estimada de la simulación
  w_social               [0.0, 1.0]   peso de la capa social
  w_digital              [0.0, 1.0]   peso de la capa digital
  w_economico            [0.0, 1.0]   peso de la capa económica
  regla_sugerida         string       uno de: hegselmann_krause, degroot,
                                      competitive_contagion, threshold,
                                      replicator_dynamics, confirmation_bias,
                                      axelrod_homophily, nash_equilibrium,
                                      bayesian_network, sir_contagion
  archetype_sugerido     string       uno de: polarizacion_extrema,
                                      polarizacion_moderada, consenso_moderado,
                                      consenso_forzado, fragmentacion_3_grupos,
                                      fragmentacion_4_grupos, caos_social,
                                      radicalizacion_progresiva

INSTRUCCIONES:
1. Solo popula campos con evidencia explícita o inferencia fuerte.
2. Usa null para campos sin evidencia.
3. Escala correctamente (ej: 75% de aprobación = opinion_inicial ≈ 0.5).
4. Incluye campo "confianza_extraccion" [0.0-1.0] indicando tu certeza.
5. Lista "campos_inferidos" (sin dato directo) y "campos_faltantes" (no mencionados).
6. Campo "notas" con observaciones relevantes en español.

Devuelve SOLO el JSON sin markdown ni explicaciones."""


class DocumentIntelligence:
    """
    Motor de inteligencia documental para MASSIVE.

    Parsea archivos de cualquier formato, extrae contexto estructurado y
    usa un LLM para mapear ese contexto a parámetros MASSIVE validados.

    Args:
        llm_client: Cliente LLM compatible (openai.OpenAI, groq.Groq, etc.)
            con interfaz ``client.chat.completions.create()``.
            Si es None, el parseo funciona pero la extracción LLM no.
        model: Nombre del modelo a usar para la extracción.
        vision_model: Modelo con capacidad de visión para imágenes/gráficas.
            Si es None, se usa ``model`` como fallback.
    """

    def __init__(
        self,
        llm_client: Any = None,
        model: str = "llama-3.3-70b-versatile",
        vision_model: str | None = None,
    ) -> None:
        self._client = llm_client
        self._model = model
        self._vision_model = vision_model or model

    # ── Parseo ───────────────────────────────────────────────────────────────

    def parse_file(self, path: str | Path) -> DocumentContext:
        """
        Parsea un archivo y devuelve su DocumentContext.

        Detecta el tipo por extensión y usa el parser apropiado.
        No requiere LLM — funciona en modo offline.
        """
        p = Path(path)
        ext = p.suffix.lower()
        parser_cls = _EXT_MAP.get(ext, _TextParser)
        log.info(f"[DI] Parseando {p.name} con {parser_cls.__name__}")
        ctx = parser_cls.parse(p)
        if ctx.parse_warnings:
            for w in ctx.parse_warnings:
                log.warning(f"[DI] {w}")
        return ctx

    def parse_bytes(
        self,
        data: bytes,
        filename: str,
    ) -> DocumentContext:
        """
        Parsea contenido en memoria (útil para uploads de Streamlit).

        Escribe a un archivo temporal, parsea y limpia.
        """
        import tempfile
        ext = Path(filename).suffix.lower()
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            ctx = self.parse_file(tmp_path)
            ctx.filename = filename
        finally:
            tmp_path.unlink(missing_ok=True)
        return ctx

    def parse_multiple(self, paths: list[str | Path]) -> DocumentContext:
        """
        Combina múltiples archivos en un único DocumentContext fusionado.

        Útil cuando el usuario sube informe PDF + dataset CSV + config JSON.
        """
        ctxs = [self.parse_file(p) for p in paths]
        merged = DocumentContext(
            filename=" + ".join(c.filename for c in ctxs),
            file_type="mixed",
        )
        texts: list[str] = []
        for ctx in ctxs:
            if ctx.raw_text:
                texts.append(f"[{ctx.filename}]\n{ctx.raw_text}")
            merged.structured_data.update(ctx.structured_data)
            merged.time_series.extend(ctx.time_series)
            merged.parse_warnings.extend(ctx.parse_warnings)
            if not merged.image_b64 and ctx.image_b64:
                merged.image_b64 = ctx.image_b64
        merged.raw_text = "\n\n---\n\n".join(texts)
        return merged

    # ── Extracción LLM ───────────────────────────────────────────────────────

    def extract_massive_params(
        self,
        ctx: DocumentContext,
        extra_instructions: str = "",
    ) -> MASSIVEExtractedConfig:
        """
        Usa el LLM para extraer parámetros MASSIVE desde el DocumentContext.

        Args:
            ctx: Contexto ya parseado del documento.
            extra_instructions: Instrucciones adicionales para el LLM
                (ej: "Enfócate en la capa digital, el contexto es latinoamericano").

        Returns:
            MASSIVEExtractedConfig validado por Pydantic.
        """
        if self._client is None:
            log.warning("[DI] No hay cliente LLM configurado. Retornando config vacía.")
            return MASSIVEExtractedConfig(
                notas="Sin cliente LLM configurado.",
                campos_faltantes=["todos"],
            )

        user_prompt = ctx.summary_for_llm
        if extra_instructions:
            user_prompt += f"\n\n[INSTRUCCIONES ADICIONALES]\n{extra_instructions}"

        messages = [
            {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ]

        # Si hay imagen, usar modelo de visión
        model = self._model
        if ctx.image_b64 and ctx.file_type == "image":
            model = self._vision_model
            messages[-1]["content"] = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{ctx.image_b64}"
                    },
                },
                {"type": "text", "text": user_prompt},
            ]

        try:
            resp = self._client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
                max_tokens=1024,
            )
            raw_json = resp.choices[0].message.content.strip()
            # Limpiar posibles bloques markdown
            if raw_json.startswith("```"):
                raw_json = raw_json.split("```")[1]
                if raw_json.startswith("json"):
                    raw_json = raw_json[4:]
            parsed = json.loads(raw_json)
            config = MASSIVEExtractedConfig(**parsed)
            log.info(
                f"[DI] Extracción OK — confianza={config.confianza_extraccion:.2f}, "
                f"campos={len([f for f in parsed if parsed[f] is not None])}"
            )
            return config
        except json.JSONDecodeError as exc:
            log.error(f"[DI] JSON inválido del LLM: {exc}")
            return MASSIVEExtractedConfig(
                notas=f"Error de parseo JSON: {exc}",
                confianza_extraccion=0.0,
            )
        except Exception as exc:
            log.error(f"[DI] Error en extracción LLM: {exc}")
            return MASSIVEExtractedConfig(
                notas=f"Error LLM: {exc}",
                confianza_extraccion=0.0,
            )

    def describe_charts(self, ctx: DocumentContext) -> str:
        """
        Usa el modelo de visión para describir gráficas de una imagen.

        Devuelve descripción en texto que se añade a DocumentContext.charts_description.
        """
        if self._client is None or not ctx.image_b64:
            return ""
        try:
            resp = self._client.chat.completions.create(
                model=self._vision_model,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{ctx.image_b64}"
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "Describe detalladamente las gráficas, tablas y "
                                "visualizaciones que aparecen en esta imagen. "
                                "Extrae todos los valores numéricos visibles. "
                                "Responde en español."
                            ),
                        },
                    ],
                }],
                max_tokens=800,
            )
            description = resp.choices[0].message.content
            ctx.charts_description = description
            return description
        except Exception as exc:
            log.warning(f"[DI] describe_charts falló: {exc}")
            return ""
