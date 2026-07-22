import pytest

from muta_ext.uast.mutators.llm_generator import (
    MutatorSafetyError,
    build_system_prompt,
    generate_mutator_code,
    validate_generated_mutator,
)


def test_prompt_construction_contract():
    prompt = build_system_prompt("python")
    assert "def mutate(node, **kwargs):" in prompt
    assert "Return ONLY valid Python code" in prompt
    assert "Target language: python" in prompt


def test_safety_filter_blocks_dangerous_code():
    code = "import os\n\ndef mutate(node, **kwargs):\n    os.system('echo x')\n    return node\n"
    with pytest.raises(MutatorSafetyError):
        validate_generated_mutator(code, "python")


def test_valid_generated_mutator_passes_validation_and_codegen():
    llm_output = """```python
def mutate(node, **kwargs):
    if isinstance(node, dict):
        node = dict(node)
        node["tag"] = "ok"
    return node
```"""

    code = generate_mutator_code(
        "add a marker field",
        "python",
        completion_fn=lambda **_: llm_output,
    )
    assert "def mutate" in code
    validate_generated_mutator(code, "python")

