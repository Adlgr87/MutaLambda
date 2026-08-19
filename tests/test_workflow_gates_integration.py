import pytest
import json
import time
from workflow_protocol import (
    PASS,
    FAIL,
    RETRYABLE_FAIL,
    StageResult,
    ProtocolTrace,
    ProtocolStage,
    ProtocolWorkflow,
    make_stage_result,
    security_findings,
    artifact_ref,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pass_stage(name: str, message: str = "") -> StageResult:
    return make_stage_result(name, PASS, message)


def _fail_stage(name: str, message: str = "") -> StageResult:
    return make_stage_result(name, FAIL, message)


def _retry_stage(name: str, message: str = "") -> StageResult:
    return make_stage_result(name, RETRYABLE_FAIL, message)


def _stages_runner(*stage_results: StageResult):
    """Factory que produce un runner que devuelve los resultados en orden."""
    idx = [0]

    def runner(ctx: dict) -> StageResult:
        if idx[0] < len(stage_results):
            result = stage_results[idx[0]]
            idx[0] += 1
            return result
        return make_stage_result("default", PASS, "no more stages")

    return runner


# ── Tests de gates secuenciales ─────────────────────────────────────────────

@pytest.mark.e2e
class TestSequentialGates:
    """Validar que los gates se ejecutan en orden y detienen el flujo."""

    def test_all_pass_promotes(self):
        """Todos los stages PASS → decisión promote."""
        stages = [
            ProtocolStage("scan", _stages_runner(_pass_stage("scan"))),
            ProtocolStage("lint", _stages_runner(_pass_stage("lint"))),
            ProtocolStage("security", _stages_runner(_pass_stage("security"))),
        ]
        workflow = ProtocolWorkflow(stages)
        trace = ProtocolTrace(run_id="run-1", subject_id="subj-1")

        result = workflow.execute({}, trace)

        assert result is True
        assert trace.decision == "promote"
        assert len(trace.stages) == 3
        assert trace.stage_names() == ["scan", "lint", "security"]

    def test_first_gate_fail_rejects(self):
        """Primer stage FAIL → decisión reject, sin ejecutar siguientes."""
        stages = [
            ProtocolStage("scan", _stages_runner(_fail_stage("scan", "syntax error"))),
            ProtocolStage("lint", _stages_runner(_pass_stage("lint"))),
            ProtocolStage("security", _stages_runner(_pass_stage("security"))),
        ]
        workflow = ProtocolWorkflow(stages)
        trace = ProtocolTrace(run_id="run-2", subject_id="subj-2")

        result = workflow.execute({}, trace)

        assert result is False
        assert trace.decision == "reject"
        assert len(trace.stages) == 1
        assert trace.stages[0].status == FAIL
        assert "syntax error" in trace.stages[0].message

    def test_middle_gate_fail_rejects(self):
        """Stage intermedio FAIL → decide reject pero registra los anteriores."""
        stages = [
            ProtocolStage("scan", _stages_runner(_pass_stage("scan"))),
            ProtocolStage("lint", _stages_runner(_fail_stage("lint", "style violation"))),
            ProtocolStage("security", _stages_runner(_pass_stage("security"))),
        ]
        workflow = ProtocolWorkflow(stages)
        trace = ProtocolTrace(run_id="run-3", subject_id="subj-3")

        result = workflow.execute({}, trace)

        assert result is False
        assert trace.decision == "reject"
        assert len(trace.stages) == 2
        assert trace.stages[0].status == PASS
        assert trace.stages[1].status == FAIL

    def test_retryable_fail_returns_retry(self):
        """Stage RETRYABLE_FAIL → decisión retry, detiene ejecución."""
        stages = [
            ProtocolStage("eval", _stages_runner(_pass_stage("eval"))),
            ProtocolStage("sandbox", _stages_runner(_retry_stage("sandbox", "timeout"))),
        ]
        workflow = ProtocolWorkflow(stages)
        trace = ProtocolTrace(run_id="run-4", subject_id="subj-4")

        result = workflow.execute({}, trace)

        assert result is False
        assert trace.decision == "retry"
        assert len(trace.stages) == 2

    def test_empty_workflow_promotes(self):
        """Workflow sin stages → promote."""
        workflow = ProtocolWorkflow([])
        trace = ProtocolTrace(run_id="run-5", subject_id="subj-5")

        result = workflow.execute({}, trace)

        assert result is True
        assert trace.decision == "promote"
        assert len(trace.stages) == 0

    def test_stage_order_preserved(self):
        """El orden de las etapas en el trace refleja el orden de ejecución."""
        order = ["auth", "schema", "sanitize", "validate"]
        stages = [
            ProtocolStage(name, _stages_runner(_pass_stage(name)))
            for name in order
        ]
        workflow = ProtocolWorkflow(stages)
        trace = ProtocolTrace(run_id="run-6", subject_id="subj-6")

        workflow.execute({}, trace)

        assert trace.stage_names() == order


# ── Tests de serialización de traces ─────────────────────────────────────────

@pytest.mark.e2e
class TestTraceSerialization:
    """Validar que ProtocolTrace serializa y deserializa correctamente."""

    def test_to_dict_basic(self):
        """to_dict() incluye todos los campos requeridos."""
        trace = ProtocolTrace(
            run_id="run-100",
            subject_id="subj-100",
            decision="pending",
            attempts=3,
            metadata={"key": "value"},
        )
        trace.add_stage(_pass_stage("stage-a", "ok"))
        trace.add_stage(_fail_stage("stage-b", "error"))

        data = trace.to_dict()

        assert data["run_id"] == "run-100"
        assert data["subject_id"] == "subj-100"
        assert data["decision"] == "pending"
        assert data["attempts"] == 3
        assert data["metadata"] == {"key": "value"}
        assert len(data["stages"]) == 2
        assert data["stages"][0]["name"] == "stage-a"
        assert data["stages"][0]["status"] == PASS
        assert data["stages"][1]["name"] == "stage-b"
        assert data["stages"][1]["status"] == FAIL

    def test_to_dict_json_roundtrip(self):
        """Serialización JSON → deserialización preserva datos."""
        trace = ProtocolTrace(
            run_id="run-200",
            subject_id="subj-200",
            decision="promote",
            attempts=1,
            metadata={"score": 0.95},
        )
        stage = make_stage_result("check", PASS, "passed", metadata={"n": 42})
        trace.add_stage(stage)

        json_str = json.dumps(trace.to_dict())
        restored = ProtocolTrace(
            run_id="restored",
            subject_id="restored",
        )
        restored_data = json.loads(json_str)
        # Verificar que la estructura es correcta
        assert restored_data["run_id"] == "run-200"
        assert restored_data["decision"] == "promote"
        assert len(restored_data["stages"]) == 1
        assert restored_data["stages"][0]["metadata"]["n"] == 42

    def test_duration_computed(self):
        """La duración de cada stage se computa correctamente."""
        started = time.perf_counter()
        stage = make_stage_result(
            "timing", PASS, "duration test", started_at=started
        )
        trace = ProtocolTrace(run_id="run-300", subject_id="subj-300")
        trace.add_stage(stage)

        data = trace.to_dict()
        assert "duration_sec" in data["stages"][0]
        assert isinstance(data["stages"][0]["duration_sec"], float)
        assert data["stages"][0]["duration_sec"] >= 0.0


# ── Tests de detección de seguridad ──────────────────────────────────────────

@pytest.mark.e2e
class TestSecurityFindings:
    """Validar que security_findings detecta calls peligrosas."""

    def test_no_findings_safe_code(self):
        """Código sin llamadas peligrosas → lista vacía."""
        code = """
def f(x):
    return x + 1

def g():
    return [i for i in range(10)]
"""
        findings = security_findings(code)
        assert findings == []

    def test_detects_eval(self):
        """Eval debe ser detectado."""
        code = "user_input = input(); result = eval(user_input)"
        findings = security_findings(code)
        assert any("dynamic_call:eval" in f for f in findings)

    def test_detects_exec(self):
        """Exec debe ser detectado."""
        code = "code = 'print(1)'; exec(code)"
        findings = security_findings(code)
        assert any("dynamic_call:exec" in f for f in findings)

    def test_detects_compile(self):
        """Compile debe ser detectado."""
        code = "compiled = compile('x=1', '<string>', 'exec')"
        findings = security_findings(code)
        assert any("dynamic_call:compile" in f for f in findings)

    def test_detects_import(self):
        """__import__ debe ser detectado."""
        code = "mod = __import__('os')"
        findings = security_findings(code)
        assert any("dynamic_call:__import__" in f for f in findings)

    def test_detects_os_system(self):
        """os.system debe ser detectado."""
        code = "import os; os.system('ls')"
        findings = security_findings(code)
        assert any("risky_call:os.system" in f for f in findings)

    def test_detects_os_popen(self):
        """os.popen debe ser detectado."""
        code = "import os; os.popen('cat file')"
        findings = security_findings(code)
        assert any("risky_call:os.popen" in f for f in findings)

    def test_detects_subprocess_run(self):
        """subprocess.run debe ser detectado."""
        code = "import subprocess; subprocess.run(['ls'])"
        findings = security_findings(code)
        assert any("risky_call:subprocess.run" in f for f in findings)

    def test_detects_subprocess_popen(self):
        """subprocess.Popen debe ser detectado."""
        code = "import subprocess; subprocess.Popen(['cat'])"
        findings = security_findings(code)
        assert any("risky_call:subprocess.Popen" in f for f in findings)

    def test_detects_subprocess_call(self):
        """subprocess.call debe ser detectado."""
        code = "import subprocess; subprocess.call(['echo'])"
        findings = security_findings(code)
        assert any("risky_call:subprocess.call" in f for f in findings)

    def test_detects_subprocess_check_output(self):
        """subprocess.check_output debe ser detectado."""
        code = "import subprocess; subprocess.check_output(['pwd'])"
        findings = security_findings(code)
        assert any("risky_call:subprocess.check_output" in f for f in findings)

    def test_multiple_findings(self):
        """Múltiples llamadas peligrosas deben reportarse todas."""
        code = """
import os
import subprocess
x = eval("1+1")
exec("print(1)")
os.system("ls")
subprocess.run(["echo"])
"""
        findings = security_findings(code)
        assert len(findings) >= 4
        assert any("dynamic_call:eval" in f for f in findings)
        assert any("dynamic_call:exec" in f for f in findings)
        assert any("risky_call:os.system" in f for f in findings)
        assert any("risky_call:subprocess.run" in f for f in findings)

    def test_syntax_error_returns_empty(self):
        """Código con error de sintaxis → lista vacía."""
        findings = security_findings("def broken(:")
        assert findings == []

    def test_empty_code_returns_empty(self):
        """Código vacío → lista vacía."""
        findings = security_findings("")
        assert findings == []

    def test_safe_stdlib_calls_not_flagged(self):
        """Llamadas seguras de stdlib no deben ser detectadas."""
        code = """
import os
import json
path = os.path.join("a", "b")
data = json.loads('{"x": 1}')
"""
        findings = security_findings(code)
        assert findings == []


# ── Tests de artifact_ref ────────────────────────────────────────────────────

@pytest.mark.e2e
class TestArtifactRef:
    """Validar referencia estable de artefactos."""

    def test_deterministic(self):
        """Mismo código → mismo artifact_ref."""
        code = "def f(x): return x + 1"
        assert artifact_ref(code) == artifact_ref(code)

    def test_different_code_different_ref(self):
        """Código diferente → artifact_ref diferente."""
        ref1 = artifact_ref("def f(): pass")
        ref2 = artifact_ref("def g(): pass")
        assert ref1 != ref2

    def test_returns_hex_string(self):
        """Debe retornar un string hexadecimal de 12 caracteres."""
        ref = artifact_ref("x")
        assert len(ref) == 12
        int(ref, 16)  # debe ser un hex válido


# ── Tests de integración de workflow completo ────────────────────────────────

@pytest.mark.e2e
class TestFullWorkflowIntegration:
    """Integración completa: workflow → trace → serialización."""

    def test_promote_pipeline(self):
        """Pipeline completo que termina en promote."""
        def ctx_scanner(ctx):
            return make_stage_result("scanner", PASS, "clean")

        def ctx_linter(ctx):
            return make_stage_result("linter", PASS, "no issues")

        def ctx_security(ctx):
            return make_stage_result("security", PASS, "no findings")

        workflow = ProtocolWorkflow([
            ProtocolStage("scanner", ctx_scanner),
            ProtocolStage("linter", ctx_linter),
            ProtocolStage("security", ctx_security),
        ])

        trace = ProtocolTrace(run_id="full-1", subject_id="subject-A")
        success = workflow.execute({"code": "def f(): pass"}, trace)

        assert success is True
        assert trace.decision == "promote"
        assert len(trace.stages) == 3
        data = trace.to_dict()
        assert data["decision"] == "promote"
        assert len(data["stages"]) == 3

    def test_reject_pipeline(self):
        """Pipeline completo que termina en reject por security."""
        def safe_scanner(ctx):
            return make_stage_result("scanner", PASS, "clean")

        def failing_security(ctx):
            code = ctx.get("code", "")
            findings = security_findings(code)
            if findings:
                return make_stage_result(
                    "security", FAIL, f"findings: {', '.join(findings)}"
                )
            return make_stage_result("security", PASS, "clean")

        workflow = ProtocolWorkflow([
            ProtocolStage("scanner", safe_scanner),
            ProtocolStage("security", failing_security),
        ])

        trace = ProtocolTrace(run_id="full-2", subject_id="subject-B")
        success = workflow.execute(
            {"code": "x = eval(user_input)"}, trace
        )

        assert success is False
        assert trace.decision == "reject"
        assert len(trace.stages) == 2
        assert trace.stages[1].status == FAIL

    def test_workflow_with_metadata_propagation(self):
        """Los stages pueden passing metadata que persiste en el trace."""
        def metadata_stage(ctx):
            return make_stage_result(
                "process", PASS, "done",
                metadata={"score": 0.9, "tags": ["a", "b"]},
                artifacts={"hash": "abc123"},
            )

        workflow = ProtocolWorkflow([
            ProtocolStage("process", metadata_stage),
        ])

        trace = ProtocolTrace(run_id="full-3", subject_id="subject-C")
        workflow.execute({}, trace)

        assert trace.stages[0].metadata["score"] == 0.9
        assert trace.stages[0].artifacts["hash"] == "abc123"
        data = trace.to_dict()
        assert data["stages"][0]["metadata"]["score"] == 0.9
        assert data["stages"][0]["artifacts"]["hash"] == "abc123"


# ── Tests de AST-only fast-path ───────────────────────────────────────────────

@pytest.mark.e2e
class TestASTOnlyFastPath:
    """Validar que los mutations AST-only omiten build_gate y security_gate."""

    def test_ast_only_skips_build_and_security_gates(self):
        """Cuando strategy='ast', el workflow debe excluir build_gate y security_gate."""
        executed_stages = []

        def make_recording_stage(name):
            def stage(ctx):
                executed_stages.append(name)
                return make_stage_result(name, PASS, f"{name} ok")
            return stage

        # Simular el comportamiento de _build_child_candidate con is_ast_only=True
        stages = [ProtocolStage("generate_candidate", make_recording_stage("generate_candidate"))]
        is_ast_only = True
        if not is_ast_only:
            stages.append(ProtocolStage("build_gate", make_recording_stage("build_gate")))
        if not is_ast_only:
            stages.append(ProtocolStage("security_gate", make_recording_stage("security_gate")))
        stages.append(ProtocolStage("api_gate", make_recording_stage("api_gate")))
        stages.append(ProtocolStage("evaluate_candidate", make_recording_stage("evaluate_candidate")))
        stages.append(ProtocolStage("tests_gate", make_recording_stage("tests_gate")))
        stages.append(ProtocolStage("differential_gate", make_recording_stage("differential_gate")))
        stages.append(ProtocolStage("performance_gate", make_recording_stage("performance_gate")))
        stages.append(ProtocolStage("decision_gate", make_recording_stage("decision_gate")))

        workflow = ProtocolWorkflow(stages)
        trace = ProtocolTrace(run_id="ast-1", subject_id="ast-subject")
        workflow.execute({}, trace)

        assert "generate_candidate" in executed_stages
        assert "build_gate" not in executed_stages
        assert "security_gate" not in executed_stages
        assert "api_gate" in executed_stages
        assert "evaluate_candidate" in executed_stages
        assert "tests_gate" in executed_stages
        assert "differential_gate" in executed_stages
        assert "performance_gate" in executed_stages
        assert "decision_gate" in executed_stages
        assert trace.decision == "promote"

    def test_non_ast_includes_build_and_security_gates(self):
        """Cuando strategy no es 'ast', el workflow debe incluir build_gate y security_gate."""
        executed_stages = []

        def make_recording_stage(name):
            def stage(ctx):
                executed_stages.append(name)
                return make_stage_result(name, PASS, f"{name} ok")
            return stage

        stages = [ProtocolStage("generate_candidate", make_recording_stage("generate_candidate"))]
        is_ast_only = False
        if not is_ast_only:
            stages.append(ProtocolStage("build_gate", make_recording_stage("build_gate")))
        if not is_ast_only:
            stages.append(ProtocolStage("security_gate", make_recording_stage("security_gate")))
        stages.append(ProtocolStage("api_gate", make_recording_stage("api_gate")))
        stages.append(ProtocolStage("evaluate_candidate", make_recording_stage("evaluate_candidate")))

        workflow = ProtocolWorkflow(stages)
        trace = ProtocolTrace(run_id="ast-2", subject_id="ast-subject-2")
        workflow.execute({}, trace)

        assert "build_gate" in executed_stages
        assert "security_gate" in executed_stages
        assert trace.decision == "promote"

    def test_ast_only_fast_path_skips_2_stages(self):
        """El fast-path AST-only debe ahorrar exactamente 2 stages: build_gate y security_gate."""
        def pass_stage(ctx):
            return make_stage_result("any", PASS, "ok")

        # Full workflow (non-AST)
        full_stages = [
            ProtocolStage("generate_candidate", pass_stage),
            ProtocolStage("build_gate", pass_stage),
            ProtocolStage("security_gate", pass_stage),
            ProtocolStage("api_gate", pass_stage),
            ProtocolStage("evaluate_candidate", pass_stage),
            ProtocolStage("tests_gate", pass_stage),
            ProtocolStage("differential_gate", pass_stage),
            ProtocolStage("performance_gate", pass_stage),
            ProtocolStage("decision_gate", pass_stage),
        ]
        # AST-only workflow (skipped 2 stages)
        ast_stages = [
            ProtocolStage("generate_candidate", pass_stage),
            ProtocolStage("api_gate", pass_stage),
            ProtocolStage("evaluate_candidate", pass_stage),
            ProtocolStage("tests_gate", pass_stage),
            ProtocolStage("differential_gate", pass_stage),
            ProtocolStage("performance_gate", pass_stage),
            ProtocolStage("decision_gate", pass_stage),
        ]

        assert len(full_stages) == 9
        assert len(ast_stages) == 7
        stage_name_diff = {s.name for s in full_stages} - {s.name for s in ast_stages}
        assert stage_name_diff == {"build_gate", "security_gate"}
