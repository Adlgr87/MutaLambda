"""Tests for THC Engine - cross-language transfer blocking and integration."""
import pytest
from unittest.mock import Mock, MagicMock

from models import Individual
from muta_ext.thc_engine import HorizontalTransferEngine, FragmentRecord, THCConfig


class TestTHCCrossLanguageBlocking:
    """Verify that cross-language transfers are blocked."""

    def test_thc_blocks_cross_language_transfers(self):
        """Fragments from a different language should be skipped."""
        config = THCConfig(
            enabled=True,
            max_transfers_per_generation=5,
            validate_in_sandbox=False,
        )

        rng = Mock()
        engine = HorizontalTransferEngine(config=config, rng=rng)

        # A python individual
        receiver = Individual(
            id="py-1",
            code="def f(x): return x + 1",
            score=1.0,
            language="python",
        )
        population = [receiver]

        # A fragment from rust language - should be blocked
        rust_fragment = FragmentRecord(
            name="rust-frag",
            donor_id="rust-donor-1",
            donor_score=1.2,
            donor_language="rust",
            code="fn f(x: i32) -> i32 { x + 1 }",
        )
        engine.fragments = {"rust-frag": rust_fragment}

        # Mock rng.choice to return the rust fragment
        rng.choice = Mock(return_value=rust_fragment)

        # Run transfer_population
        evaluator = Mock()
        evaluator.evaluate_batch = Mock(return_value=[Mock(score=2.0, fitness=Mock(correctness=1.0), passed=True)])

        result = engine.apply(population, evaluator, generation=0)

        # Receiver should still be present (transfer blocked, no new hybrid added)
        # The rust fragment should be skipped
        assert len(result) == 1  # only the original receiver
        assert result[0] is receiver

    def test_thc_allows_same_language_transfers(self):
        """Fragments from the same language should be accepted."""
        config = THCConfig(
            enabled=True,
            max_transfers_per_generation=5,
            validate_in_sandbox=False,
        )

        rng = Mock()
        engine = HorizontalTransferEngine(config=config, rng=rng)

        receiver = Individual(
            id="py-2",
            code="def f(x): return x + 1",
            score=1.0,
            language="python",
        )
        population = [receiver]

        # A python fragment - same language, should pass
        py_fragment = FragmentRecord(
            name="py-frag",
            donor_id="py-donor-1",
            donor_score=1.2,
            donor_language="python",
            code="def helper(x): return x * 2",
        )
        engine.fragments = {"py-frag": py_fragment}

        rng.choice = Mock(return_value=py_fragment)

        evaluator = Mock()
        result = engine.apply(population, evaluator, generation=0)

        # With same language, transfer should proceed (may add hybrid)
        # At minimum, the receiver should be preserved
        assert receiver in result


class TestTHCEngineIntegration:
    """Integration tests for THC Engine."""

    def test_fragment_record_has_donor_language(self):
        """FragmentRecord should have donor_language field with default 'python'."""
        record = FragmentRecord(
            name="test-frag",
            donor_id="donor-1",
            donor_score=1.0,
            code="print('hello')",
        )
        assert record.donor_language == "python"

        # Should be settable
        record2 = FragmentRecord(
            name="rust-frag",
            donor_id="donor-2",
            donor_score=1.0,
            code="println!(\"hello\")",
            donor_language="rust",
        )
        assert record2.donor_language == "rust"

    def test_individual_has_language_field(self):
        """Individual should have language field with default 'python'."""
        ind = Individual(
            id="test-1",
            code="def f(): pass",
            score=0.5,
        )
        assert ind.language == "python"

        ind2 = Individual(
            id="test-2",
            code="fn main() {}",
            score=0.5,
            language="rust",
        )
        assert ind2.language == "rust"