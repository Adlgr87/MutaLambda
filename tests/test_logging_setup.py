"""Tests for logging_setup (logger hierarchy + handler configuration)."""

import logging

import pytest

from logging_setup import ROOT_LOGGER_NAME, get_logger, setup_logging


@pytest.fixture
def clean_root_logger():
    """Isolate the MutaLambda root logger for handler/level assertions."""
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    saved_handlers = list(logger.handlers)
    saved_level = logger.level
    logger.handlers = []
    try:
        yield logger
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers = saved_handlers
        logger.setLevel(saved_level)


@pytest.mark.root
class TestGetLogger:
    @pytest.mark.parametrize("name", [None, "", ROOT_LOGGER_NAME])
    def test_root_names_return_root_logger(self, name):
        assert get_logger(name).name == ROOT_LOGGER_NAME

    def test_short_name_becomes_child(self):
        assert get_logger("sandbox").name == f"{ROOT_LOGGER_NAME}.sandbox"

    def test_already_qualified_name_is_kept(self):
        qualified = f"{ROOT_LOGGER_NAME}.island"
        assert get_logger(qualified).name == qualified

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("muta_lambda", "muta_lambda"),
            ("muta_lambda.py", "muta_lambda"),
            ("pkg/sub/module.py", "module"),
            ("evolution_engine.py", "evolution_engine"),
            ("pkg\\sub\\module.py", "module"),
        ],
    )
    def test_module_paths_use_last_segment(self, name, expected):
        assert get_logger(name).name == f"{ROOT_LOGGER_NAME}.{expected}"

    def test_same_name_returns_same_instance(self):
        assert get_logger("archive") is get_logger("archive")

    def test_child_propagates_to_root(self, clean_root_logger):
        setup_logging(level="DEBUG")
        child = get_logger("nsga2")
        assert child.propagate is True
        assert child.getEffectiveLevel() == logging.DEBUG


@pytest.mark.root
class TestSetupLogging:
    def test_adds_single_console_handler(self, clean_root_logger):
        setup_logging()
        assert len(clean_root_logger.handlers) == 1
        assert isinstance(clean_root_logger.handlers[0], logging.StreamHandler)
        assert clean_root_logger.level == logging.INFO

    def test_is_idempotent(self, clean_root_logger):
        setup_logging()
        setup_logging(level="ERROR")
        # Re-entry updates the level but never duplicates handlers.
        assert len(clean_root_logger.handlers) == 1
        assert clean_root_logger.level == logging.ERROR

    @pytest.mark.parametrize(
        "level,expected",
        [("debug", logging.DEBUG), ("WARNING", logging.WARNING), ("bogus", logging.INFO)],
    )
    def test_level_parsing(self, clean_root_logger, level, expected):
        setup_logging(level=level)
        assert clean_root_logger.level == expected

    def test_log_file_handler_created_with_parent_dirs(self, clean_root_logger, tmp_path):
        log_path = tmp_path / "nested" / "run.log"
        setup_logging(level="INFO", log_file=log_path)

        assert log_path.parent.is_dir()
        assert any(isinstance(h, logging.FileHandler) for h in clean_root_logger.handlers)

        get_logger("sandbox").info("hello from sandbox")
        for handler in clean_root_logger.handlers:
            handler.flush()
        assert "hello from sandbox" in log_path.read_text(encoding="utf-8")

    def test_env_override_wins_over_argument(self, clean_root_logger, monkeypatch):
        monkeypatch.setenv("MUTALAMBDA_LOG_LEVEL", "DEBUG")
        setup_logging(level="ERROR")
        assert clean_root_logger.level == logging.DEBUG

    def test_invalid_env_override_falls_back_to_info(self, clean_root_logger, monkeypatch):
        monkeypatch.setenv("MUTALAMBDA_LOG_LEVEL", "not-a-level")
        setup_logging(level="ERROR")
        assert clean_root_logger.level == logging.INFO
