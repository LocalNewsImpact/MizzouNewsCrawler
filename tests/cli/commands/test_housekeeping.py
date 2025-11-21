"""Test housekeeping command."""

import argparse


class TestHousekeepingCommand:
    """Test housekeeping command registration and dry-run."""

    def test_add_housekeeping_parser_registers_command(self):
        """Verify housekeeping parser adds the command to argparse."""
        from src.cli.commands.housekeeping import add_housekeeping_parser

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        add_housekeeping_parser(subparsers)

        # Should parse housekeeping command with expected parameters
        args = parser.parse_args(["housekeeping", "--dry-run"])
        assert hasattr(args, "candidate_expiration_days")
        assert hasattr(args, "dry_run")
        assert args.dry_run is True

    def test_housekeeping_command_dry_run_mode(self, mocker):
        """Verify housekeeping command respects --dry-run flag."""
        from src.cli.commands.housekeeping import handle_housekeeping_command

        # Mock DatabaseManager to avoid real DB calls
        mock_db = mocker.MagicMock()
        mock_session = mocker.MagicMock()
        mock_db.get_session.return_value.__enter__ = mocker.MagicMock(
            return_value=mock_session
        )
        mock_db.get_session.return_value.__exit__ = mocker.MagicMock(return_value=False)

        # Mock the session.execute to return empty results
        mock_session.execute.return_value.scalar.return_value = 0

        mocker.patch(
            "src.cli.commands.housekeeping.DatabaseManager", return_value=mock_db
        )

        # Create args object
        args = argparse.Namespace(
            candidate_expiration_days=7,
            extraction_stall_hours=24,
            cleaning_stall_hours=24,
            verification_stall_hours=24,
            dry_run=True,
            verbose=False,
        )

        # Run with dry-run
        result = handle_housekeeping_command(args)

        assert result == 0

    def test_housekeeping_command_verbose_output(self, mocker):
        """Verify housekeeping command supports --verbose flag."""
        from src.cli.commands.housekeeping import handle_housekeeping_command

        # Mock DatabaseManager
        mock_db = mocker.MagicMock()
        mock_session = mocker.MagicMock()
        mock_db.get_session.return_value.__enter__ = mocker.MagicMock(
            return_value=mock_session
        )
        mock_db.get_session.return_value.__exit__ = mocker.MagicMock(return_value=False)

        # Mock results from queries
        mock_session.execute.return_value.scalar.return_value = 0
        mock_session.execute.return_value.fetchall.return_value = []

        mocker.patch(
            "src.cli.commands.housekeeping.DatabaseManager", return_value=mock_db
        )

        # Create args object
        args = argparse.Namespace(
            candidate_expiration_days=7,
            extraction_stall_hours=24,
            cleaning_stall_hours=24,
            verification_stall_hours=24,
            dry_run=True,
            verbose=True,
        )

        # Run with verbose
        result = handle_housekeeping_command(args)

        assert result == 0

    def test_housekeeping_command_configurable_thresholds(self, mocker):
        """Verify housekeeping command accepts custom thresholds."""
        from src.cli.commands.housekeeping import handle_housekeeping_command

        # Mock DatabaseManager
        mock_db = mocker.MagicMock()
        mock_session = mocker.MagicMock()
        mock_db.get_session.return_value.__enter__ = mocker.MagicMock(
            return_value=mock_session
        )
        mock_db.get_session.return_value.__exit__ = mocker.MagicMock(return_value=False)

        mock_session.execute.return_value.scalar.return_value = 0
        mock_session.execute.return_value.fetchall.return_value = []

        mocker.patch(
            "src.cli.commands.housekeeping.DatabaseManager", return_value=mock_db
        )

        # Create args object with custom thresholds
        args = argparse.Namespace(
            candidate_expiration_days=14,
            extraction_stall_hours=48,
            cleaning_stall_hours=48,
            verification_stall_hours=48,
            dry_run=True,
            verbose=False,
        )

        # Run with custom thresholds
        result = handle_housekeeping_command(args)

        assert result == 0
