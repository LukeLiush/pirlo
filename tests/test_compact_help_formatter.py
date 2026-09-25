# tests/test_compact_help_formatter.py
from __future__ import annotations

import argparse

from pirlo.infrastructure.adapters.cli.argument_parser_builder import (
    ArgumentParserBuilder,
)
from pirlo.infrastructure.adapters.cli.compact_help_formatter import (
    CompactHelpFormatter,
)
from pirlo.playbooks.demo.report_dag import SendAlertPlay


def test_short_and_long_options_share_one_metavar():
    """Pins '-r, --routine CRON' — argparse on 3.12 would repeat the metavar."""
    help_text = (
        ArgumentParserBuilder(SendAlertPlay)
        .build_parser("demo_report_dag")
        .format_help()
    )

    assert "-r, --routine CRON" in help_text
    assert "-r CRON, --routine CRON" not in help_text
    assert "--orchestrator LINK" in help_text


def test_store_true_flags_render_without_a_metavar():
    """nargs=0 actions consume no value, so they must stay placeholder-free."""
    help_text = (
        ArgumentParserBuilder(SendAlertPlay)
        .build_parser("demo_report_dag")
        .format_help()
    )

    assert "-l, --log" in help_text
    assert "-l LOG" not in help_text
    assert "-f, --force, --no-cache" in help_text


def test_play_parameter_metavars_stay_derived_from_the_signature():
    """--channel/--quarter carry no explicit metavar; argparse derives dest.upper()."""
    help_text = (
        ArgumentParserBuilder(SendAlertPlay)
        .build_parser("demo_report_dag")
        .format_help()
    )

    assert "--channel CHANNEL" in help_text
    assert "--quarter QUARTER" in help_text


def test_formatter_preserves_raw_description():
    """The rendered DAG must survive verbatim, not be reflowed as a paragraph."""
    parser = argparse.ArgumentParser(
        prog="demo",
        description="Line one\n\nWorkflow DAG:\n  +----+\n  | ab |\n  +----+",
        formatter_class=CompactHelpFormatter,
    )
    help_text = parser.format_help()

    assert "Workflow DAG:\n  +----+\n  | ab |\n  +----+" in help_text
