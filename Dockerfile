# syntax=docker/dockerfile:1

# --- Etapa 1: builder -------------------------------------------------------
# Instala MutaLambda con extras de produccion en un venv aislado que luego se
# copia integro a la imagen final. Sin toolchain de compilacion: todas las
# dependencias de los extras cli/uast/scientific publican ruedas cp312 linux.
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /build
COPY . .

# Extras: CLI (click/rich), UAST (tree-sitter + gramaticas Go/Rust/C++) y
# cientifico (z3, pdfplumber, pandas, openpyxl, Pillow).
# El extra 'archive' (faiss + sentence-transformers -> torch) queda fuera por
# defecto para mantener la imagen ligera; extendelo asi si lo necesitas:
#   pip install ".[cli,uast,scientific,archive]"
RUN pip install --upgrade pip && \
    pip install ".[cli,uast,scientific]"

# --- Etapa 2: runtime ------------------------------------------------------
FROM python:3.12-slim AS runtime

ARG MUTALAMBDA_VERSION=4.0.0

LABEL org.opencontainers.image.title="MutaLambda" \
      org.opencontainers.image.description="Evolutionary multi-island code optimization framework" \
      org.opencontainers.image.version="${MUTALAMBDA_VERSION}" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/Adlgr87/MutaLambda"

# Usuario sin privilegios (uid/gid fijos para legibilidad de politicas).
RUN groupadd --gid 10001 mutalambda && \
    useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin mutalambda

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Compatible con rootfs read-only (el home real vive en capa imagen).
    HOME=/tmp

WORKDIR /workspace
RUN mkdir -p /workspace && chown mutalambda:mutalambda /workspace

# Ejemplos listos para usar con `mutalambda examples` y los presets.
COPY --chown=mutalambda:mutalambda examples/ ./examples/

USER mutalambda:mutalambda

ENTRYPOINT ["mutalambda"]
CMD ["--help"]
