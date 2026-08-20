# Plan de 90 Días — MutaLambda: de proyecto personal a activo comercializable

**Inicio:** lunes 24 de agosto de 2026 · **Fin:** domingo 22 de noviembre de 2026
**Operador:** 1 fundador técnico (supuesto: 15–20 h/semana; si es tiempo completo, comprime ~40%)
**Presupuesto estimado:** $150–400 USD total (APIs LLM ~$100–300, dominio ~$15, resto $0 usando tiers gratuitos)

## Objetivo único del plan

> Convertir "código sin señales externas" en "activo con evidencia de terceros y usuarios reales", que es el delta entre valer $5–50K y valer $250K–1.5M (ver ESTUDIO_MERCADO_Y_VALORACION.md §7).

Tres workstreams en paralelo: **E** (Evidencia externa), **D** (Distribución), **M** (Monetización). Regla de prioridad ante conflicto: E > D > M. Sin evidencia, la distribución no convierte y la monetización no cierra.

---

## FASE 1 — Empaquetado y credibilidad mínima (Días 1–14 · 24 ago – 6 sep)

*Meta: que un desarrollador desconocido pueda instalar, correr y creer en 10 minutos.*

### Semana 1 (24–30 ago)
| # | Tarea | WS | Esfuerzo | Done cuando… |
|---|---|---|---|---|
| 1.1 | Publicar en PyPI: `pip install mutalambda` (revisar classifiers para BUSL-1.1, `extras_require` ya definidos) | D | 3 h | `pip install mutalambda && mutalambda --help` funciona en máquina limpia |
| 1.2 | Release v4.0.0 en GitHub con changelog (incluye: fix lambdas, perfil self, 2 optimizaciones auto-evolucionadas, BSL) | D | 2 h | Release publicado, tag firmado |
| 1.3 | CI públicamente verde: revisar los 2 workflows existentes, añadir badge de tests (483 passing) y de licencia al README | D | 3 h | Badges reales, no decorativos |
| 1.4 | Quickstart de 5 minutos en README: un ejemplo copy-paste con Ollama local (sin API key) y uno con OpenAI | D | 4 h | Un tercero lo reproduce sin ayuda |
| 1.5 | Grabar demo de 3 min: MutaLambda optimizando una función real + el oráculo rechazando un mutante incorrecto (el momento diferenciador) | D | 4 h | Video subido (YouTube/asciinema), enlazado en README |

### Semana 2 (31 ago – 6 sep)
| # | Tarea | WS | Esfuerzo | Done cuando… |
|---|---|---|---|---|
| 1.6 | Landing de 1 página (mutalambda.dev o similar): propuesta de valor, tabla vs-OpenEvolve, video, waitlist por email (Formspree/Tally, $0) | M | 6 h | Página viva con captura de emails |
| 1.7 | Preparar harness de benchmark externo reproducible: `benchmarks/external/` con runner + README de metodología (misma disciplina que `experiments/`: semillas, medianas, no-regresión) | E | 6 h | `python benchmarks/external/run.py` produce JSON + tabla |
| 1.8 | Definir presupuesto LLM y backend por defecto para benchmarks (p. ej. modelo open-weight vía OpenRouter para reproducibilidad barata) | E | 2 h | Costo por corrida documentado |

**KPIs Fase 1:** paquete en PyPI ✓ · release ✓ · demo ✓ · landing ✓ · 0→10 stars (red personal).

---

## FASE 2 — Evidencia externa (Días 15–56 · 7 sep – 18 oct)

*Meta: 3 fuentes de evidencia que NO dependan de tu palabra. Es la fase que multiplica la valoración.*

### 2A. Benchmark head-to-head vs OpenEvolve (7–20 sep)
El experimento que convierte tu tesis en dato:

1. Elegir 5–8 tareas: 2–3 de la suite pública de AlphaEvolve/OpenEvolve (p. ej. circle packing) + 3–5 kernels científicos con oráculo de correctitud estricto (integración numérica, álgebra con invariantes, simulación con conservación de energía — tu "modo científico" brilla aquí).
2. Correr ambos frameworks con el MISMO modelo LLM y presupuesto de iteraciones.
3. Medir tres cosas: (a) speedup logrado, (b) **tasa de candidatos incorrectos aceptados por cada sistema** — tu métrica estrella, ya probada internamente con 28 rechazos, (c) costo en tokens.
4. Publicar TODO: código, semillas, JSONs, y las derrotas si las hay (el ledger es tu marca).

**Entregable:** `BENCHMARK_VS_OPENEVOLVE.md` + datos. **Gate de decisión:** si MutaLambda no muestra ventaja clara en correctitud, NO lanzar marketing todavía — iterar los gates primero (el resultado negativo también se documenta).

### 2B. PRs de optimización a librerías open source (14 sep – 18 oct, solapado)
Cada PR aceptado = prueba de valor imposible de falsear + backlink + caso de estudio.

| Tier | Objetivos sugeridos | Por qué | Meta |
|---|---|---|---|
| Realista | networkx, sympy, statsmodels, scikit-image (código Python puro, hot paths conocidos, mantenedores activos) | Alta probabilidad de aceptación | 4–6 PRs enviados, **2–3 aceptados** |
| Aspiracional | scipy, pandas | Marca de prestigio; proceso lento | 1–2 PRs enviados |
| Nicho científico | librerías de simulación/HPC medianas (p. ej. del ecosistema astropy o pysal) | Alineado al posicionamiento "optimización verificada para código científico" | 2 PRs |

Método por PR (≈4–6 h c/u): perfilar la librería → MutaLambda propone → validar con la suite de la librería + benchmark honesto multi-talla (lección D4: incluir tallas pequeñas) → PR con metodología transparente y mención "found & verified with MutaLambda".

**Regla de oro:** ningún PR sin benchmark reproducible incluido. Un PR rechazado por calidad daña; uno rechazado por "no priority" no.

### 2C. Caso de estudio profundo (5–18 oct)
Reescribir la evidencia MASSIVE como caso de estudio con metodología replicable, o mejor: conseguir **1 usuario externo piloto** (grupo de investigación universitario — tu ubicación ayuda: Tec de Monterrey/UANL tienen grupos de cómputo científico) y documentar su resultado con su nombre.

**KPIs Fase 2:** benchmark publicado ✓ · ≥2 PRs aceptados · 1 caso externo · 30–100 stars orgánicos.

---

## FASE 3 — Distribución y lanzamiento (Días 57–76 · 19 oct – 7 nov)

*Meta: que el mundo se entere, con la evidencia ya en la mano.*

| # | Tarea | Detalle |
|---|---|---|
| 3.1 | **GitHub Action** `mutalambda-optimize` | El formato que Codeflash validó comercialmente: corre en CI, comenta el PR con optimizaciones verificadas. MVP: modo análisis + sugerencia. 12–16 h |
| 3.2 | **Show HN** | Titular con el dato, no el adjetivo: *"Show HN: MutaLambda – evolutionary code optimizer that rejected 28 of its own false speedups"*. Enlazar el ledger de derrotas — a HN le encanta la honestidad técnica. Martes–jueves, 8–10 am ET |
| 3.3 | Reddit r/Python, r/MachineLearning, r/rust | Un post por semana, ángulos distintos (self-evolution / benchmark vs OpenEvolve / PRs aceptados). No spamear |
| 3.4 | Hilo técnico X/Twitter + LinkedIn | El hilo del "6.87× que era mentira" (D7) es contenido viral técnico legítimo |
| 3.5 | Newsletter/podcasts Python | Python Weekly, Real Python, Talk Python (pitch corto con los números) |
| 3.6 | Comunidad | Responder issues < 24 h durante ventana de lanzamiento; CONTRIBUTING.md ya existe — añadir "good first issues" |

**KPIs Fase 3:** 300–1,000 stars acumuladas · 50–200 emails en waitlist · 3–10 conversaciones entrantes (usuarios serios, empresas o inversores).

---

## FASE 4 — Monetización y decisión (Días 77–90 · 8–22 nov)

*Meta: elegir ruta con datos, no con esperanza.*

### Preparación (8–15 nov)
- Pricing page: **Free** (personal/académico/eval 90 días, ya cubierto por BSL) · **Pro $25–40/usuario/mes** (uso comercial, CLI+Action ilimitados) · **Enterprise** (on-prem, SLA, modo científico con invariantes custom). Ancla de mercado: Codeflash $20.
- 10 entrevistas con los leads más calientes de la waitlist: ¿pagarían? ¿cuánto? ¿por qué no?
- Actualizar ESTUDIO_MERCADO_Y_VALORACION.md con las métricas reales de los 90 días.

### Gate de decisión final (16–22 nov) — elegir según lo observado:

| Señal observada al día 90 | Ruta recomendada |
|---|---|
| ≥2 empresas dispuestas a pagar o piloto enterprise activo | **Open-core SaaS**: cobrar ya, considerar pre-seed con tracción |
| Interés académico/HPC fuerte pero sin presupuesto de software | **Servicio**: "optimización verificada" como consultoría ($3–8K/proyecto), el producto como herramienta interna |
| Tracción de stars/usuarios pero sin señal de pago | Seguir open-core 90 días más, buscar cofundador comercial o acquihire |
| Interés de adquisición entrante (Codeflash/Qodo/TurinTech compran capacidades) | Negociar con el dossier: evidencia + tracción + IP limpio de autor único. Piso de conversación: $250K+ |
| Nada de lo anterior | Vender como activo en Acquire.com con todo el dossier (aun así, 10× el valor de agosto) o mantener como side project rentable vía servicio |

---

## Cadencia y disciplina

- **Viernes (30 min):** revisar KPIs contra plan; si una tarea lleva 2 semanas estancada, se corta o se re-alcanza (scope-down, no perfección).
- **Registro continuo:** cada victoria Y derrota va al ledger de SELF_EVOLUTION_REPORT.md o al log del plan — es tu diferenciador de marca, no solo higiene.
- **Regla anti-scope-creep:** cero features nuevas del motor durante los 90 días salvo que un PR/benchmark lo exija. El motor ya es suficiente; lo que falta es el mundo exterior.

## Riesgos principales

| Riesgo | Prob. | Mitigación |
|---|---|---|
| Benchmark vs OpenEvolve no favorece claramente | Media | La métrica de correctitud es donde casi seguro ganas; publicar honesto refuerza marca aunque el speedup empate (lección del ledger) |
| PRs ignorados por mantenedores | Alta (parcial) | Enviar 2× los necesarios; elegir repos con historial de merges rápidos; issues antes que PRs |
| Lanzamiento HN pasa desapercibido | Media | Se puede repostear una vez semanas después con ángulo distinto; Reddit y newsletters son canales independientes |
| Burnout de fundador único | Media | El plan cabe en 15–20 h/sem; los viernes se recorta alcance, nunca se extiende |
| Un competidor open source copia el enfoque de gates | Baja–media | BSL protege el código nuevo; la ventaja real es la evidencia acumulada y la marca de honestidad, que no se forkean |

## Tablero de KPIs (llenar cada viernes)

| Métrica | D14 | D30 | D56 | D76 | D90 (meta) |
|---|---|---|---|---|---|
| Stars GitHub | | | | | 300–1,000 |
| Descargas PyPI/sem | | | | | 200+ |
| PRs aceptados en libs externas | | | | | 2–3 |
| Benchmark externo publicado | | | ✓ | | ✓ |
| Waitlist emails | | | | | 50–200 |
| Conversaciones de pago/pilotos | | | | | 3–10 |
| Casos de estudio con nombre de tercero | | | | | 1–2 |
