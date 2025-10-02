import argparse
import types

from src.cli.commands import versioning


def test_handle_create_version_command(monkeypatch, capsys):
    fake_version = types.SimpleNamespace(id="version-1", version_tag="v1")

    def fake_create(dataset_name, version_tag, description=None):
        assert dataset_name == "candidate_links"
        assert version_tag == "v1"
        assert description is None
        return fake_version

    monkeypatch.setattr(versioning, "create_dataset_version", fake_create)

    args = argparse.Namespace(
        dataset="candidate_links",
        tag="v1",
        description=None,
    )

    result = versioning.handle_create_version_command(args)
    output = capsys.readouterr().out

    assert result == 0
    assert "Created dataset version" in output
    assert "version-1" in output
    assert "v1" in output


def test_handle_list_versions_command(monkeypatch, capsys):
    versions = [
        types.SimpleNamespace(
            id="ver-1",
            dataset_name="candidate_links",
            version_tag="tag-1",
            created_at="2025-09-24",
            snapshot_path="snap-1.parquet",
        ),
        types.SimpleNamespace(
            id="ver-2",
            dataset_name="candidate_links",
            version_tag="tag-2",
            created_at="2025-09-25",
            snapshot_path="snap-2.parquet",
        ),
    ]

    captured = {}

    def fake_list(dataset=None):
        captured["dataset"] = dataset
        return versions

    monkeypatch.setattr(versioning, "list_dataset_versions", fake_list)

    args = argparse.Namespace(dataset="candidate_links")

    result = versioning.handle_list_versions_command(args)
    output = capsys.readouterr().out

    assert result == 0
    assert captured["dataset"] == "candidate_links"
    for version in versions:
        assert version.id in output
        assert version.version_tag in output


def test_handle_list_versions_no_results(monkeypatch, capsys):
    monkeypatch.setattr(
        versioning,
        "list_dataset_versions",
        lambda dataset=None: [],
    )

    result = versioning.handle_list_versions_command(
        argparse.Namespace(dataset=None)
    )
    output = capsys.readouterr().out

    assert result == 0
    assert "No dataset versions found" in output


def test_handle_list_versions_error(monkeypatch, capsys):
    def fake_list(dataset=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(versioning, "list_dataset_versions", fake_list)

    result = versioning.handle_list_versions_command(
        argparse.Namespace(dataset=None)
    )
    output = capsys.readouterr().out

    assert result == 1
    assert "Failed to list dataset versions" in output


def test_handle_export_version_command(monkeypatch, capsys):
    def fake_export(version_id, output_path):
        assert version_id == "v1"
        assert output_path == "out.parquet"
        return "out.parquet"

    monkeypatch.setattr(versioning, "export_dataset_version", fake_export)

    args = argparse.Namespace(version_id="v1", output="out.parquet")

    result = versioning.handle_export_version_command(args)
    output = capsys.readouterr().out

    assert result == 0
    assert "Exported version" in output


def test_handle_export_version_error(monkeypatch, capsys):
    def fake_export(version_id, output_path):
        raise RuntimeError("boom")

    monkeypatch.setattr(versioning, "export_dataset_version", fake_export)

    result = versioning.handle_export_version_command(
        argparse.Namespace(version_id="v1", output="out"),
    )
    output = capsys.readouterr().out

    assert result == 1
    assert "Failed to export version" in output


def test_handle_export_snapshot_command(monkeypatch, capsys):
    fake_version = types.SimpleNamespace(
        id="version-1",
        snapshot_path="snap.parquet",
    )

    def fake_export(version_id, table, output_path, **kwargs):
        assert version_id == "v1"
        assert table == "candidate_links"
        assert output_path == "snap.parquet"
        assert kwargs["chunksize"] == 10_000
        assert kwargs["compression"] is None
        return fake_version

    monkeypatch.setattr(versioning, "export_snapshot_for_version", fake_export)

    args = argparse.Namespace(
        version_id="v1",
        table="candidate_links",
        output="snap.parquet",
        snapshot_chunksize=10_000,
        snapshot_compression=None,
    )

    result = versioning.handle_export_snapshot_command(args)
    output = capsys.readouterr().out

    assert result == 0
    assert "Snapshot created" in output


def test_handle_export_snapshot_error(monkeypatch, capsys):
    def fake_export(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(versioning, "export_snapshot_for_version", fake_export)

    args = argparse.Namespace(
        version_id="v1",
        table="candidate_links",
        output="snap.parquet",
        snapshot_chunksize=10_000,
        snapshot_compression=None,
    )

    result = versioning.handle_export_snapshot_command(args)
    output = capsys.readouterr().out

    assert result == 1
    assert "Failed to export snapshot" in output
