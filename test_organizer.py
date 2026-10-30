import json

import pytest
from organizer import ConfigError, FileOrganizer, load_categories, main


def make_files(directory, *names):
    """Creates empty files inside `directory` (tmp_path is a real, temporary folder)."""
    for name in names:
        (directory / name).write_text("content", encoding="utf-8")


# ---------------------------------------------------------------- organize
def test_files_go_to_the_right_folders(tmp_path):
    make_files(tmp_path, "photo.jpg", "report.pdf", "script.py", "song.mp3", "backup.zip")

    FileOrganizer(tmp_path).organize()

    assert (tmp_path / "Images" / "photo.jpg").exists()
    assert (tmp_path / "Documents" / "report.pdf").exists()
    assert (tmp_path / "Code" / "script.py").exists()
    assert (tmp_path / "Audio" / "song.mp3").exists()
    assert (tmp_path / "Archives" / "backup.zip").exists()
    assert not (tmp_path / "photo.jpg").exists()  # really moved, not copied


def test_extension_matching_is_case_insensitive(tmp_path):
    make_files(tmp_path, "PHOTO.JPG")

    FileOrganizer(tmp_path).organize()

    assert (tmp_path / "Images" / "PHOTO.JPG").exists()


def test_unknown_extension_goes_to_others(tmp_path):
    make_files(tmp_path, "weird.xyz")

    FileOrganizer(tmp_path).organize()

    assert (tmp_path / "Others" / "weird.xyz").exists()


def test_directories_hidden_and_extensionless_files_are_ignored(tmp_path):
    (tmp_path / "some_folder").mkdir()
    make_files(tmp_path, "README", ".hidden.txt")

    moves = FileOrganizer(tmp_path).organize()

    assert moves == []
    assert (tmp_path / "some_folder").is_dir()
    assert (tmp_path / "README").exists()
    assert (tmp_path / ".hidden.txt").exists()


def test_name_collision_adds_numeric_suffix(tmp_path):
    (tmp_path / "Documents").mkdir()
    (tmp_path / "Documents" / "notes.txt").write_text("old", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("new", encoding="utf-8")

    FileOrganizer(tmp_path).organize()

    assert (tmp_path / "Documents" / "notes.txt").read_text(encoding="utf-8") == "old"
    assert (tmp_path / "Documents" / "notes_1.txt").read_text(encoding="utf-8") == "new"


def test_invalid_directory_raises(tmp_path):
    with pytest.raises(ValueError):
        FileOrganizer(tmp_path / "does_not_exist")


def test_dry_run_does_not_touch_anything(tmp_path):
    make_files(tmp_path, "photo.jpg")

    moves = FileOrganizer(tmp_path, dry_run=True).organize()

    assert len(moves) == 1
    assert (tmp_path / "photo.jpg").exists()
    assert not (tmp_path / "Images").exists()
    assert not (tmp_path / ".organizer_history.json").exists()


# ------------------------------------------------------------------ config
def test_custom_categories_are_used(tmp_path):
    make_files(tmp_path, "book.epub", "photo.jpg")
    rules = {"Books": ["epub"]}  # no leading dot on purpose: should be normalized

    FileOrganizer(tmp_path, categories=rules).organize()

    assert (tmp_path / "Books" / "book.epub").exists()
    assert (tmp_path / "Others" / "photo.jpg").exists()  # not in custom rules


def test_load_categories_reads_valid_json(tmp_path):
    config = tmp_path / "rules.json"
    config.write_text(json.dumps({"Books": [".epub"]}), encoding="utf-8")

    assert load_categories(config) == {"Books": [".epub"]}


def test_load_categories_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        load_categories(tmp_path / "nope.json")


def test_load_categories_invalid_json(tmp_path):
    config = tmp_path / "rules.json"
    config.write_text("{not json", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_categories(config)


@pytest.mark.parametrize(
    "bad_rules",
    [
        ["not", "a", "dict"],
        {"Images": ".jpg"},        # value must be a list
        {"../escape": [".jpg"]},   # path traversal
    ],
)
def test_load_categories_rejects_bad_structure(tmp_path, bad_rules):
    config = tmp_path / "rules.json"
    config.write_text(json.dumps(bad_rules), encoding="utf-8")

    with pytest.raises(ConfigError):
        load_categories(config)


# -------------------------------------------------------------------- undo
def test_undo_restores_files_and_removes_empty_folders(tmp_path):
    make_files(tmp_path, "photo.jpg", "report.pdf")
    organizer = FileOrganizer(tmp_path)
    organizer.organize()

    restored = organizer.undo()

    assert restored == 2
    assert (tmp_path / "photo.jpg").exists()
    assert (tmp_path / "report.pdf").exists()
    assert not (tmp_path / "Images").exists()
    assert not (tmp_path / "Documents").exists()
    assert not organizer.history_path.exists()


def test_undo_only_reverts_the_last_run(tmp_path):
    make_files(tmp_path, "a.jpg")
    organizer = FileOrganizer(tmp_path)
    organizer.organize()
    make_files(tmp_path, "b.jpg")
    organizer.organize()

    organizer.undo()

    assert (tmp_path / "b.jpg").exists()           # reverted
    assert (tmp_path / "Images" / "a.jpg").exists()  # first run untouched


def test_undo_without_history_returns_zero(tmp_path):
    assert FileOrganizer(tmp_path).undo() == 0


def test_undo_skips_files_that_were_deleted(tmp_path):
    make_files(tmp_path, "photo.jpg", "report.pdf")
    organizer = FileOrganizer(tmp_path)
    organizer.organize()
    (tmp_path / "Images" / "photo.jpg").unlink()  # user deleted it after organizing

    assert organizer.undo() == 1
    assert (tmp_path / "report.pdf").exists()


def test_history_file_is_never_moved(tmp_path):
    make_files(tmp_path, "photo.jpg")
    organizer = FileOrganizer(tmp_path)
    organizer.organize()
    make_files(tmp_path, "other.jpg")
    organizer.organize()  # second run must not treat the .json history as a file to move

    assert organizer.history_path.exists()


# --------------------------------------------------------------------- CLI
def test_cli_organizes_and_undoes(tmp_path):
    make_files(tmp_path, "photo.jpg")

    assert main(["--path", str(tmp_path)]) == 0
    assert (tmp_path / "Images" / "photo.jpg").exists()

    assert main(["--path", str(tmp_path), "--undo"]) == 0
    assert (tmp_path / "photo.jpg").exists()


def test_cli_uses_config_file(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    make_files(target, "book.epub")
    config = tmp_path / "rules.json"
    config.write_text(json.dumps({"Books": [".epub"]}), encoding="utf-8")

    assert main(["--path", str(target), "--config", str(config)]) == 0
    assert (target / "Books" / "book.epub").exists()


def test_cli_returns_error_code_for_bad_path(tmp_path):
    assert main(["--path", str(tmp_path / "nope")]) == 1


def test_cli_returns_error_code_for_bad_config(tmp_path):
    assert main(["--path", str(tmp_path), "--config", str(tmp_path / "nope.json")]) == 1


def test_cli_rejects_undo_with_dry_run(tmp_path):
    with pytest.raises(SystemExit):
        main(["--path", str(tmp_path), "--undo", "--dry-run"])
