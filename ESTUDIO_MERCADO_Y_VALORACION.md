# MutaLambda — Estudio de Mercado y Valoración

**Fecha:** 19 de agosto de 2026
**Preparado para:** Adlgr87 (único autor del proyecto)
**Alcance:** Análisis del producto, due diligence técnica verificada en este repositorio, dimensionamiento de mercado, panorama competitivo y valoración por tres métodos, con escenarios.

---

## 1. Resumen ejecutivo

MutaLambda es un **sistema de optimización evolutiva de código** que combina LLMs con algoritmos genéticos multi-objetivo (NSGA-II, modelo de islas, HFC) para mejorar automáticamente el rendimiento de código manteniendo la correctitud, con soporte multi-lenguaje (Python, Rust, C++, Go) vía una capa de AST universal (UAST).

**Veredicto en una frase:** el producto es técnicamente serio y está en una categoría de mercado caliente y en crecimiento (~24–27% CAGR), pero **hoy su valor de venta es bajo porque no tiene tracción, ni usuarios, ni ingresos, y el código ya es público bajo MIT**. El valor real está en lo que se puede construir encima en los próximos 3–12 meses, no en el código tal cual está.

| Escenario | Rango de valor estimado (USD) |
|---|---|
| Venta hoy, tal cual, como activo de código (marketplace) | $5.000 – $50.000 |
| Coste de reposición (lo que costaría reconstruirlo) | $60.000 – $250.000 |
| Como startup pre-seed con validación inicial (6–12 meses de trabajo) | $250.000 – $1,5 M |
| Adquisición estratégica de tecnología (con benchmarks de terceros + usuarios) | $1 M – $5 M |

---

## 2. Qué es MutaLambda (evaluación del producto)

### Propuesta de valor
"Dame tu código y te devuelvo una versión más rápida, verificada como correcta" — optimización automática de rendimiento como servicio/herramienta, no como asistente de autocompletado.

### Activos técnicos reales del repositorio
- **~38.000 líneas de Python** en una arquitectura modular razonable (orquestador, motor de evolución, islas, sandbox, checkpoints, backends LLM intercambiables: Ollama, OpenAI, Anthropic, OpenRouter, Mistral).
- **Fitness multi-objetivo real** (correctitud como gate duro + latencia P50/P99 + memoria + parsimonia) con selección NSGA-II — esto es más sofisticado que la mayoría de proyectos open source equivalentes.
- **Capa UAST multi-lenguaje** (tree-sitter): Python, Rust, C++, Go. Diferenciador frente a competidores centrados solo en Python.
- **Seguridad y anti-alucinación**: sandbox con límites duros, filtros de mutación, verificación algebraica con SymPy, invariantes de dominio ("modo científico").
- **Ingeniería honesta**: el documento `EMPIRICAL_EVIDENCE.md` reporta experimentos fallidos y revertidos, no solo éxitos. Esto es raro y es un activo de credibilidad ante un comprador técnico.
- **Extras**: CLI con Click/Rich, dashboard Streamlit, cache semántica FAISS, checkpoints MsgPack, evolución de prompts, servidor LSP, integración CI.

### Debilidades del producto (relevantes para valoración)
1. **Las validaciones de rendimiento son internas.** Los speedups de 1,5×–3,6× se midieron contra MASSIVE, un framework del propio autor. Un comprador o inversor descontará esto casi a cero hasta ver benchmarks de terceros (p. ej. la suite de AlphaEvolve, SWE-Perf, o PRs de optimización aceptados en repos open source conocidos).
2. **Dependencia de LLMs externos** para la generación de variantes: el coste por optimización y la calidad dependen del modelo elegido.
3. **Sin distribución**: no está en PyPI, no tiene GitHub Action publicada, no tiene web ni demo online.

---

## 3. Due diligence técnica (verificada hoy en este repositorio)

Ejecuté la suite completa en un entorno limpio:

| Verificación | Resultado |
|---|---|
| Instalación de dependencias core + UAST | ✅ Sin fricción |
| `import muta_lambda` | ✅ OK |
| Suite de tests (excl. 1 archivo con bug y el flaky documentado) | ✅ **468 passed, 5 skipped en ~5 s** |
| Bug encontrado | ❌ `tests/uast/test_cli_generate_mutator.py` no colecta: `NameError: name 'List' is not defined` en el mutador generado (falta import de `typing.List`) |
| Archivo LICENSE | ❌ No existe (la licencia MIT solo se declara en README/pyproject) — **imprescindible para cualquier venta** |
| Higiene del repo | ⚠️ Dos archivos basura en la raíz que son volcados accidentales de páginas man (`s-file hotspot detection`, `upport, LSP server, ...`) |
| Historial git | ⚠️ 1 solo commit (squash). Un comprador no puede auditar la evolución del desarrollo |
| Señales públicas | ⚠️ 0 stars, 0 forks, sin releases, sin PyPI |

**Interpretación:** el core es sólido y estable (468 tests verdes es una señal fuerte para un proyecto de un solo autor), pero la presentación pública actual transmite "proyecto personal", no "producto". Arreglar esto cuesta días, no meses, y cambia materialmente la percepción de valor.

---

## 4. El mercado

### Tamaño y crecimiento
- El mercado de **AI code tools** se estima en **$7,4–9,4 mil millones USD en 2025–2026**, con proyecciones de **$22–30 mil millones hacia 2030–2031** (CAGR ~24–27%). Fuentes: [Mordor Intelligence](https://www.mordorintelligence.com/industry-reports/artificial-intelligence-code-tools-market), [The Business Research Company](https://www.thebusinessresearchcompany.com/report/artificial-intelligence-ai-code-tools-global-market-report), [Grand View Research](https://www.grandviewresearch.com/press-release/global-ai-code-tools-market).
- MutaLambda compite en el sub-segmento de **optimización de código / performance engineering automatizado**, un nicho pequeño dentro de ese mercado pero con un viento de cola potente: la explosión de código generado por IA ("vibe coding") produce código funcional pero ineficiente, y el coste de infraestructura cloud/GPU hace que el rendimiento vuelva a ser un problema de negocio, no solo técnico.

### Por qué el timing es bueno
- Google DeepMind legitimó la categoría "evolución de código con LLMs" con **AlphaEvolve** (2025), que es cerrado. Esto creó demanda de alternativas abiertas/comerciales.
- Los compradores enterprise ya pagan por esto: TurinTech levantó **$20M** para su plataforma Artemis de optimización de código ([TechCrunch, marzo 2025](https://www.thesaasnews.com/news/turintech-raises-20-million-in-funding)); Codeflash vende optimización de Python a **$20/usuario/mes** con tier enterprise on-premises ([codeflash.ai/pricing](https://www.codeflash.ai/pricing)).

---

## 5. Panorama competitivo

| Competidor | Qué es | Estado / dinero | Frente a MutaLambda |
|---|---|---|---|
| **[Codeflash](https://www.codeflash.ai/)** (SF, 2023) | Optimización automática de Python con verificación; integración GitHub/Cursor/Claude Code | Seed, ~8–11 empleados; pricing $0 / $20 user/mes / enterprise | El comparable comercial más directo. Solo Python; MutaLambda es multi-lenguaje pero Codeflash tiene producto, distribución y clientes |
| **[TurinTech Artemis](https://www.turintech.ai/)** (Londres, 2017) | Plataforma enterprise GenAI de optimización y validación de código | **$20M levantados** (Series A 2025) | Valida que hay dinero enterprise en la categoría. Juega en liga enterprise con ventas consultivas |
| **AlphaEvolve** (Google DeepMind) | Agente evolutivo de descubrimiento algorítmico | Cerrado, interno | Define el estado del arte y da credibilidad narrativa a la categoría |
| **[OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve)** | Implementación open source de AlphaEvolve | **~6.900 stars**, comunidad activa | **La amenaza principal.** Gratis, popular, mismo enfoque conceptual. MutaLambda debe diferenciarse (fitness multi-objetivo con gates de correctitud, sandbox, UAST multi-lenguaje, modo científico) o quedará invisible |
| **ShinkaEvolve, CodeEvolve, EvoControl, etc.** | Frameworks académicos/open source 2025–2026 | 100–150 stars c/u | El espacio open source se está poblando rápido; la ventana para destacar se estrecha |
| **Qodo, Sonar, etc.** (adyacentes) | Calidad/testing de código con IA | Qodo levantó $70M (mar 2026) | Compradores estratégicos potenciales que podrían querer añadir "optimización" a su suite |

**Lectura honesta:** MutaLambda no tiene hoy ninguna ventaja de distribución y llega tarde a la carrera de stars en GitHub. Sus diferenciadores defendibles son (a) el rigor de correctitud (gates duros, verificación algebraica, modo científico con invariantes de dominio) y (b) el soporte multi-lenguaje vía UAST. El posicionamiento con más probabilidad de éxito no es "otro AlphaEvolve open source" sino **"optimización verificada para código científico/numérico"** — un nicho donde la correctitud es innegociable y donde OpenEvolve no compite en serio.

---

## 6. FODA

**Fortalezas:** arquitectura completa y probada (468 tests), multi-objetivo real (NSGA-II + Pareto), multi-lenguaje, seguridad/sandboxing, backends LLM agnósticos, documentación de evidencia empírica honesta, un solo dueño del IP (venta limpia).

**Debilidades:** cero tracción (0 stars, 0 usuarios conocidos, 0 ingresos), benchmarks solo internos, sin empaquetado de distribución (PyPI/Action/web), sin archivo LICENSE, historial git de 1 commit, bus factor = 1.

**Oportunidades:** ola de código IA ineficiente que necesita optimización; nicho científico/HPC desatendido; costes cloud/GPU crecientes; categoría legitimada por AlphaEvolve y financiada (TurinTech $20M, Codeflash); posible open-core + servicio cloud.

**Amenazas:** OpenEvolve (gratis, 6.9k stars) comoditiza el enfoque; los IDE/agentes generalistas (Cursor, Copilot, Claude Code) podrían absorber la función "optimiza esto"; dependencia del coste/calidad de LLMs de terceros.

---

## 7. Valoración

Un proyecto **pre-revenue, pre-usuarios y con código ya público bajo MIT** no se valora con múltiplos de ingresos. Aplico tres métodos y los triangulo.

### Método 1 — Coste de reposición (suelo de valor)
- COCOMO clásico sobre 38 KLOC daría ~109 persona-mes (>$1M nominal), pero es irreal en la era de desarrollo asistido por IA.
- Estimación realista: un ingeniero senior con herramientas de IA reconstruiría un sistema equivalente (con esta madurez de tests y este nivel de detalle en NSGA-II/HFC/UAST/sandbox) en **6–12 meses** de trabajo enfocado → a $120–250K/año de coste total, el rango es **$60.000 – $250.000**.
- Matiz importante: al ser MIT y público, nadie *necesita* reconstruirlo — puede hacer fork gratis. El coste de reposición es un ancla de negociación, no un precio de mercado.

### Método 2 — Comparables de mercado (lo que pagan compradores reales)
- En marketplaces tipo Acquire.com, los SaaS **con ingresos** venden a mediana de **3,9× beneficio** ([Acquire.com, reporte 2026](https://movemrr.com/blog/saas-valuation-multiples/)); sin ingresos, no aplica múltiplo.
- Para activos pre-revenue, las referencias de mercado son: **adquisición de tecnología $1M–$5M** *solo cuando* hay un comprador estratégico al que le resuelve algo único y con evidencia de que funciona ([guía de múltiplos 2025](https://wildfront.co/saas-acquisition-multiples)); ventas de "código + concepto" sin tracción en marketplaces cierran típicamente en **cuatro o cinco cifras bajas**.
- **Hoy, tal cual: $5.000 – $50.000** si aparece comprador (lo más probable: otro desarrollador o una consultora de performance que quiera acelerar 6 meses de I+D). El extremo alto requiere arreglar la higiene del repo y demostrar una optimización real end-to-end reproducible.

### Método 3 — Berkus/Scorecard (si se sigue el camino startup)
Método Berkus para pre-revenue (máx. ~$500K por factor):

| Factor | Evaluación | Valor asignado |
|---|---|---|
| Idea / tamaño de oportunidad | Mercado grande y creciente, nicho claro | $300K |
| Prototipo funcional (reduce riesgo tecnológico) | Sistema completo con 468 tests | $400K |
| Equipo | 1 fundador técnico, sin equipo comercial | $100K |
| Relaciones estratégicas / distribución | Ninguna | $0 |
| Tracción / ventas | Ninguna | $0 |
| **Total indicativo** | | **~$800K** |

Es decir: como **vehículo para levantar una pre-seed o buscar cofundador**, el proyecto soporta una narrativa de valoración de **$0,5M–$1,5M** — pero solo tras conseguir las primeras señales externas (usuarios, benchmarks de terceros, stars). Sin eso, un inversor lo tratará como "proyecto personal prometedor" sin precio.

### Triangulación
> **Valor de venta hoy: $5K–$50K. Valor construible en 6–12 meses: $250K–$1,5M como startup, o $1M–$5M en una adquisición estratégica si se logran benchmarks de terceros + adopción real.** El delta entre "hoy" y "construible" no está en el código — está en la evidencia y la distribución.

---

## 8. Qué haría subir la valoración (plan de 90 días, en orden de ROI)

1. **Semana 1 — Higiene (coste: horas, impacto: alto en percepción):**
   - Añadir archivo `LICENSE` (decisión estratégica: ver punto 9 antes de reafirmar MIT).
   - Borrar los 2 archivos basura de la raíz; arreglar el `NameError` de `test_cli_generate_mutator.py`.
   - Publicar en PyPI (`pip install mutalambda`), crear release v4.0 con changelog.
2. **Semanas 2–6 — Evidencia externa (el multiplicador de valor n.º 1):**
   - Correr MutaLambda contra un benchmark público reconocido (suite de AlphaEvolve, SWE-Perf, o los benchmarks de OpenEvolve) y publicar resultados reproducibles.
   - Abrir 5–10 PRs de optimización (con benchmarks) en librerías científicas open source conocidas (scipy, scikit-image, astropy...). Cada PR aceptado es una prueba de valor imposible de falsear y marketing gratuito.
3. **Semanas 4–12 — Distribución:**
   - GitHub Action: "MutaLambda optimize" en CI (el formato que Codeflash validó comercialmente).
   - Página web de una sola página con demo en video + los resultados de benchmarks.
   - Posts en HN/Reddit r/Python/r/MachineLearning apalancando el ángulo "AlphaEvolve open source pero con gates de correctitud y multi-lenguaje".
4. **Mes 3+ — Monetización (elegir una):**
   - **Open-core:** core MIT + capa cloud de pago (paralelización de islas gestionada, dashboards, historial). Precio ancla del mercado: $20/usuario/mes (Codeflash).
   - **Servicio/consultoría de performance:** usar MutaLambda como herramienta interna y vender "optimización con garantía de correctitud" a equipos de computación científica/HPC — ingresos inmediatos, valida el nicho.
   - **Venta del activo:** listar en Acquire.com/Flippa solo después de los pasos 1–3; cada señal de tracción mueve el precio un orden de magnitud.

## 9. Nota estratégica sobre la licencia

> **Actualización 19-ago-2026:** ejecutado. El proyecto ahora usa **BSL 1.1** (gratis para uso personal/académico/investigación y evaluación de 90 días; uso comercial en producción requiere licencia; cada versión convierte a Apache 2.0 en 2030). El código publicado anteriormente bajo MIT conserva esos términos.

El código ya está publicado bajo MIT en un repo público: **eso no se puede deshacer** para el código ya publicado. Opciones a futuro:
- Mantener MIT y monetizar servicio/cloud/soporte (modelo Codeflash/OpenEvolve).
- Cambiar la licencia de versiones *futuras* (BSL, AGPL, dual licensing) — legalmente posible siendo el único autor, pero con coste reputacional si ya hubiera comunidad (hoy no la hay, así que la ventana está abierta).
- Para una venta del IP: al ser único autor sin contribuciones externas, puedes transferir el copyright limpiamente — este es de los pocos puntos donde el proyecto está en situación *ideal* para una venta.

---

## 10. Conclusión

MutaLambda no es un proyecto de juguete: es un sistema de ingeniería serio en una categoría de mercado real, financiada y en crecimiento. Pero el mercado no paga por código — paga por **evidencia, usuarios y distribución**, y hoy el proyecto tiene cero de las tres. La buena noticia es que el trabajo duro (el sistema) ya está hecho, y lo que falta (benchmarks externos, empaquetado, primeros usuarios) cuesta semanas, no años.

**Recomendación:** no vender ahora. Invertir 90 días en evidencia externa y distribución; con 2–3 PRs de optimización aceptados en proyectos conocidos y unos cientos de usuarios, el mismo activo se negocia en un rango 10–50× superior al actual.

---

*Descargo: este documento es un análisis informativo basado en datos públicos y en la inspección del repositorio; no constituye asesoramiento financiero, legal ni una tasación formal. Los rangos de valoración pre-revenue tienen incertidumbre inherente muy alta.*
