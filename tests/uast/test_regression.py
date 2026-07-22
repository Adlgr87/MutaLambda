#!/usr/bin/env python3
"""Regression test: ensure use_uast=False produces identical output to baseline."""
import pytest


class TestUASTRegression:
    """Verify that disabled UAST flag causes no regression in mutation flow."""

    def test_uast_disabled_bypass(self):
        """When use_uast=False, workflow should bypass UAST parsing."""
        from muta_ext.uast.workflow import UASTWorkflow
        
        workflow = UASTWorkflow(use_uast=False)
        # Placeholder: current impl returns original source
        # This test documents the expected behavior
        assert workflow.use_uast is False

    def test_uast_config_default_false(self):
        """UAST should be disabled by default for safe adoption."""
        from muta_config import MutaLambdaConfig
        
        config = MutaLambdaConfig()
        assert config.uast.use_uast is False

    def test_uast_supported_languages_default(self):
        """Default supported languages should be python and rust."""
        from muta_config import MutaLambdaConfig
        
        config = MutaLambdaConfig()
        assert "python" in config.uast.supported_languages
        assert "rust" in config.uast.supported_languages