# Workflow del Equipo de Agent Frameworks

## Vision
El Equipo (OpenCode, OpenHands, ClaudeCode, Prime Agent) ejecuta auditorias de seguridad
mediante delegacion coordinada de subagents. Garantiza cobertura completa, cero regresiones.

## Arquitectura
[Coordinador Principal] -> [Subagent Security] + [Subagent Secrets] + [Subagent Injection]

## Fases
1. Discovery: clonar repo, baseline tests, identificar audit dir
2. Hallazgo: SecurityVisitor AST scan, categorizar findings (D1..D15)
3. Asignacion: delegar cada finding a subagent especializado
4. Remediation: fix quirurgico (1 file), tests de verificacion, reporte
5. Regresiones: git stash compare, 0 regresiones garantizadas
6. Entregables: REPORTE_AUDITORIA_MUTALAMBDA.md + WORKFLOW + YAML
7. PR: branch maintenance/security-oleada-1 -> main, merge, CI green

## Prioridades
1. Security Priority #1 (RCE verified antes de cualquier otro trabajo)
2. Zero Regressions (git stash verification)
3. Surgical Changes (1 file per fix, minimal diff)
4. Test Coverage (each fix must pass existing tests)

## Herramientas
- OpenCode: AST analysis, SecurityVisitor, test infrastructure
- OpenHands: Secret redaction, regex patterns
- ClaudeCode: Prompt injection, lazy init, orchestration
- Prime Agent: Fail-closed, isolation guards, sandbox

## Referencias
- AD-0038: Fail-closed isolation policy
- ML-002: Sandbox hardening spec
- ML-014: Secret redaction spec