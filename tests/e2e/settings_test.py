from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6 import QtGui
from PySide6 import QtWidgets
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from labelme import _config
from labelme._app import MainWindow
from labelme._widgets import SettingsDialog
from labelme._widgets.settings_dialog import _ColorSwatchButton
from labelme._widgets.settings_dialog import _PlainTextEdit
from labelme._yaml import safe_load

from ..conftest import close_or_pause
from .conftest import MainWinFactory


def _set_flag_checked(win: MainWindow, name: str) -> None:
    flag_list = win._docks.flag_list
    flag_list.blockSignals(True)  # avoid mark_dirty; we test only the flag refresh
    try:
        for i in range(flag_list.count()):
            item = flag_list.item(i)
            assert item is not None
            if item.text() == name:
                item.setCheckState(Qt.CheckState.Checked)
                return
        raise AssertionError(f"flag {name!r} not found in the dock")
    finally:
        flag_list.blockSignals(False)


@pytest.fixture
def editable_config_file(tmp_path: Path) -> Path:
    config_file = tmp_path / "labelmerc.yaml"
    config_file.write_text("auto_save: true\n")
    return config_file


@pytest.mark.gui
def test_settings_dialog_opens_when_editable(
    main_win: MainWinFactory, qtbot: QtBot, editable_config_file: Path, pause: bool
) -> None:
    win = main_win(config_file=editable_config_file)

    assert win._settings_dialog is None
    win._open_settings()
    assert isinstance(win._settings_dialog, SettingsDialog)
    assert win._settings_dialog.isVisible()

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_setting_change_persists_and_applies(
    main_win: MainWinFactory, qtbot: QtBot, editable_config_file: Path, pause: bool
) -> None:
    win = main_win(config_file=editable_config_file)

    label_dialog_before = win._label_dialog
    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None

    checkbox = dialog._editors[("display_label_popup",)]
    assert isinstance(checkbox, QtWidgets.QCheckBox)
    checkbox.setChecked(False)  # toggling applies immediately

    labels_editor = dialog._editors[("labels",)]
    assert isinstance(labels_editor, QtWidgets.QPlainTextEdit)
    labels_editor.setPlainText("cat\ndog\n\ncat\n")
    dialog.accept()  # flushes the pending label edit on close

    assert win._config["display_label_popup"] is False
    assert win._config["labels"] == ["cat", "dog"]
    assert win._label_dialog is label_dialog_before  # updated in place, not rebuilt
    unique_label_list = win._docks.unique_label_list
    assert unique_label_list.find_label_item("cat") is not None
    assert unique_label_list.find_label_item("dog") is not None

    persisted = safe_load(editable_config_file.read_text())
    assert persisted["display_label_popup"] is False
    assert persisted["labels"] == ["cat", "dog"]

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_show_labels_toggle_applies_to_canvas(
    main_win: MainWinFactory, qtbot: QtBot, editable_config_file: Path, pause: bool
) -> None:
    win = main_win(config_file=editable_config_file)
    canvas = win._canvas_widgets.canvas
    assert canvas._show_labels is False

    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None
    checkbox = dialog._editors[("shape", "show_labels")]
    assert isinstance(checkbox, QtWidgets.QCheckBox)
    checkbox.setChecked(True)  # toggling applies immediately, without restart
    dialog.accept()

    assert win._config["shape"]["show_labels"] is True
    assert canvas._show_labels is True
    assert safe_load(editable_config_file.read_text())["shape"]["show_labels"] is True

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_label_edit_preserves_label_history(
    main_win: MainWinFactory, qtbot: QtBot, editable_config_file: Path, pause: bool
) -> None:
    win = main_win(config_file=editable_config_file)
    win._label_dialog.add_label_history("bird")  # learned from a loaded/created shape

    old_label_dialog = win._label_dialog

    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None
    labels_editor = dialog._editors[("labels",)]
    assert isinstance(labels_editor, QtWidgets.QPlainTextEdit)
    labels_editor.setPlainText("cat\ndog")
    dialog.accept()

    assert win._label_dialog is old_label_dialog  # updated in place, not rebuilt
    label_list = win._label_dialog.label_list
    labels = {label_list.item(i).text() for i in range(label_list.count())}
    assert labels == {"bird", "cat", "dog"}  # history kept, new labels added

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_flags_setting_refreshes_flag_dock_live(
    main_win: MainWinFactory, qtbot: QtBot, editable_config_file: Path, pause: bool
) -> None:
    win = main_win(config_file=editable_config_file)

    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None
    flags_editor = dialog._editors[("flags",)]
    assert isinstance(flags_editor, _PlainTextEdit)

    flags_editor.setPlainText("occluded\ntruncated")
    flags_editor.commit()

    # The flag dock reflects the edit immediately, without navigating images.
    assert win._config["flags"] == ["occluded", "truncated"]
    assert win._read_flag_dock_states() == {"occluded": False, "truncated": False}
    assert not win._is_changed  # a settings-driven refresh must not dirty the image

    _set_flag_checked(win, "occluded")
    flags_editor.setPlainText("occluded\ntruncated\nblurry")
    flags_editor.commit()

    states = win._read_flag_dock_states()
    # The new "blurry" flag appears unchecked while "occluded" stays checked.
    assert states == {"occluded": True, "truncated": False, "blurry": False}

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_clearing_labels_is_rejected_when_validate_label_is_exact(
    main_win: MainWinFactory,
    qtbot: QtBot,
    editable_config_file: Path,
    pause: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    editable_config_file.write_text("labels: [cat]\nvalidate_label: exact\n")
    win = main_win(config_file=editable_config_file)

    warned: list[str] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: warned.append(args[2]),
    )

    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None

    labels_editor = dialog._editors[("labels",)]
    assert isinstance(labels_editor, QtWidgets.QPlainTextEdit)
    labels_editor.setPlainText("")
    dialog.accept()

    validate_combo = dialog._editors[("validate_label",)]
    assert isinstance(validate_combo, QtWidgets.QComboBox)
    assert warned == [
        (
            "Predefined labels cannot be empty while Label validation is set to "
            "exact. Disable exact validation first."
        )
    ]
    assert labels_editor.toPlainText() == "cat"
    assert validate_combo.currentData() == "exact"
    assert win._config["labels"] == ["cat"]
    assert win._config["validate_label"] == "exact"

    persisted = safe_load(editable_config_file.read_text())
    assert persisted["labels"] == ["cat"]
    assert persisted["validate_label"] == "exact"

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_setting_reverts_when_write_fails(
    main_win: MainWinFactory,
    qtbot: QtBot,
    tmp_path: Path,
    pause: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("a read-only directory is not enforced for root")

    config_dir = tmp_path / "ro"
    config_dir.mkdir()
    config_file = config_dir / "labelmerc.yaml"
    config_file.write_text("display_label_popup: true\n")
    win = main_win(config_file=config_file)

    warned: list[object] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: warned.append(args[2]),
    )

    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None
    checkbox = dialog._editors[("display_label_popup",)]
    assert isinstance(checkbox, QtWidgets.QCheckBox)
    assert checkbox.isChecked()

    # The atomic save writes a temp file in the config directory, so a read-only
    # directory makes set_override raise.
    config_dir.chmod(0o500)
    try:
        checkbox.setChecked(False)
    finally:
        config_dir.chmod(0o700)

    assert warned  # the user was told the write failed
    assert checkbox.isChecked()  # editor reverted to the last-saved value
    assert win._config["display_label_popup"] is True  # in-memory config unchanged
    assert safe_load(config_file.read_text())["display_label_popup"] is True

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_settings_dialog_is_deleted_when_opening_text_editor(
    main_win: MainWinFactory,
    qtbot: QtBot,
    editable_config_file: Path,
    pause: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    win = main_win(config_file=editable_config_file)
    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None

    deleted: list[bool] = []
    dialog.destroyed.connect(lambda: deleted.append(True))
    monkeypatch.setattr("labelme._app.subprocess.Popen", lambda *args, **kwargs: None)

    win._open_config_file()

    assert win._settings_dialog is None
    qtbot.waitUntil(lambda: bool(deleted))

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_settings_disabled_with_cli_overrides(
    main_win: MainWinFactory, qtbot: QtBot, editable_config_file: Path, pause: bool
) -> None:
    win = main_win(
        config_file=editable_config_file, config_overrides={"labels": ["bird"]}
    )

    assert win._config_overrides
    win._open_settings()
    assert win._settings_dialog is None

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_save_with_image_data_toggle_persists_and_survives_restart(
    main_win: MainWinFactory, qtbot: QtBot, tmp_path: Path, pause: bool
) -> None:
    # with_image_data defaults to false, so toggling on writes an explicit
    # override (unlike auto_save, whose default is already true).
    config_file = tmp_path / "labelmerc.yaml"
    config_file.write_text("")
    win = main_win(config_file=config_file)
    assert not win._actions.save_with_image_data.isChecked()

    win._actions.save_with_image_data.trigger()

    assert win._actions.save_with_image_data.isChecked()
    assert win._config["with_image_data"] is True
    assert safe_load(config_file.read_text())["with_image_data"] is True

    # Restart-equivalent: a fresh MainWindow over the same config file picks up
    # the persisted value.
    restarted = main_win(config_file=config_file)
    assert restarted._actions.save_with_image_data.isChecked()
    assert restarted._config["with_image_data"] is True

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_save_automatically_toggle_persists_and_survives_restart(
    main_win: MainWinFactory, qtbot: QtBot, tmp_path: Path, pause: bool
) -> None:
    # auto_save defaults to true, so this exercises toggling off (and the file
    # gaining an explicit override that differs from the default).
    config_file = tmp_path / "labelmerc.yaml"
    config_file.write_text("")
    win = main_win(config_file=config_file)
    assert win._actions.save_auto.isChecked()

    win._actions.save_auto.trigger()

    assert not win._actions.save_auto.isChecked()
    assert win._config["auto_save"] is False
    assert safe_load(config_file.read_text())["auto_save"] is False

    restarted = main_win(config_file=config_file)
    assert not restarted._actions.save_auto.isChecked()
    assert restarted._config["auto_save"] is False

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_fill_drawing_toggle_persists_nested_key(
    main_win: MainWinFactory, qtbot: QtBot, tmp_path: Path, pause: bool
) -> None:
    config_file = tmp_path / "labelmerc.yaml"
    config_file.write_text("")
    win = main_win(config_file=config_file)
    assert win._actions.fill_drawing.isChecked()  # canvas.fill_drawing defaults true

    win._actions.fill_drawing.trigger()

    assert not win._actions.fill_drawing.isChecked()
    assert win._config["canvas"]["fill_drawing"] is False
    persisted = safe_load(config_file.read_text())
    assert persisted["canvas"]["fill_drawing"] is False

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_fill_drawing_startup_sync_does_not_write_config(
    main_win: MainWinFactory, qtbot: QtBot, tmp_path: Path, pause: bool
) -> None:
    config_file = tmp_path / "labelmerc.yaml"
    config_file.write_text("canvas:\n  fill_drawing: true\n")

    win = main_win(config_file=config_file)

    assert win._actions.fill_drawing.isChecked()
    assert win._canvas_widgets.canvas._fill_drawing
    # The startup trigger() that syncs the canvas to the loaded config must not
    # itself rewrite the file (it did not originate from a user edit).
    assert config_file.read_text() == "canvas:\n  fill_drawing: true\n"

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_keep_prev_dialog_toggle_checks_menu_action(
    main_win: MainWinFactory, qtbot: QtBot, editable_config_file: Path, pause: bool
) -> None:
    win = main_win(config_file=editable_config_file)
    assert not win._actions.toggle_keep_prev_mode.isChecked()

    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None
    checkbox = dialog._editors[("keep_prev",)]
    assert isinstance(checkbox, QtWidgets.QCheckBox)
    checkbox.setChecked(True)

    assert win._actions.toggle_keep_prev_mode.isChecked()
    assert win._config["keep_prev"] is True
    assert safe_load(editable_config_file.read_text())["keep_prev"] is True

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_fill_drawing_dialog_toggle_applies_to_canvas(
    main_win: MainWinFactory, qtbot: QtBot, editable_config_file: Path, pause: bool
) -> None:
    win = main_win(config_file=editable_config_file)
    canvas = win._canvas_widgets.canvas
    assert canvas._fill_drawing  # canvas.fill_drawing defaults true

    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None
    checkbox = dialog._editors[("canvas", "fill_drawing")]
    assert isinstance(checkbox, QtWidgets.QCheckBox)
    checkbox.setChecked(False)

    assert not canvas._fill_drawing
    assert not win._actions.fill_drawing.isChecked()
    assert (
        safe_load(editable_config_file.read_text())["canvas"]["fill_drawing"] is False
    )

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_crosshair_dialog_toggle_writes_all_nine_modes_and_applies_to_canvas(
    main_win: MainWinFactory, qtbot: QtBot, editable_config_file: Path, pause: bool
) -> None:
    win = main_win(config_file=editable_config_file)
    canvas = win._canvas_widgets.canvas
    # Defaults: rectangle and ai_box_to_shape true, every other mode false.
    assert any(canvas._crosshair.values())

    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None
    checkbox = dialog._editors[("canvas", "crosshair")]
    assert isinstance(checkbox, QtWidgets.QCheckBox)
    assert checkbox.isChecked()
    checkbox.setChecked(False)

    all_disabled = {mode: False for mode in win._config["canvas"]["crosshair"]}
    assert win._config["canvas"]["crosshair"] == all_disabled
    assert canvas._crosshair == all_disabled

    persisted = safe_load(editable_config_file.read_text())
    # Modes already false at default are pruned; only the two true defaults
    # become explicit overrides.
    assert persisted["canvas"]["crosshair"] == {
        "rectangle": False,
        "ai_box_to_shape": False,
    }

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_menu_toggle_failed_write_reverts_action_and_config(
    main_win: MainWinFactory,
    qtbot: QtBot,
    editable_config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    pause: bool,
) -> None:
    # A menu toggle whose config write fails must not leave the session
    # diverged from disk: the action and in-memory config both revert, like
    # the dialog reverting its editor on a failed apply.
    win = main_win(config_file=editable_config_file)
    action = win._actions.save_auto
    assert action.isChecked()  # editable_config_file sets auto_save: true

    warned: list[str] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: warned.append(args[2]),
    )

    def failing_set_overrides(
        config_file: Path, overrides: list[tuple[tuple[str, ...], object]]
    ) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(_config, "set_overrides", failing_set_overrides)

    action.trigger()

    assert warned == ["disk full"]
    assert win._config["auto_save"] is True
    assert action.isChecked()
    assert safe_load(editable_config_file.read_text())["auto_save"] is True

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_menu_toggle_does_not_write_config_with_cli_overrides(
    main_win: MainWinFactory, qtbot: QtBot, tmp_path: Path, pause: bool
) -> None:
    config_file = tmp_path / "labelmerc.yaml"
    config_file.write_text("")
    win = main_win(config_file=config_file, config_overrides={"labels": ["bird"]})
    before = config_file.read_text()
    assert win._actions.save_auto.isChecked()

    win._actions.save_auto.trigger()

    assert not win._actions.save_auto.isChecked()
    assert win._config["auto_save"] is False  # in-memory still updates
    assert config_file.read_text() == before  # but nothing is persisted

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_point_size_dialog_change_applies_to_canvas(
    main_win: MainWinFactory, qtbot: QtBot, editable_config_file: Path, pause: bool
) -> None:
    win = main_win(config_file=editable_config_file)
    canvas = win._canvas_widgets.canvas
    assert canvas._point_size == 8  # shape.point_size default

    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None
    spin = dialog._editors[("shape", "point_size")]
    assert isinstance(spin, QtWidgets.QSpinBox)
    spin.setValue(16)

    assert win._config["shape"]["point_size"] == 16
    assert canvas._point_size == 16
    assert safe_load(editable_config_file.read_text())["shape"]["point_size"] == 16

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_default_shape_color_dialog_change_recolors_docks(
    main_win: MainWinFactory,
    qtbot: QtBot,
    editable_config_file: Path,
    pause: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # shape_color: null ("Fixed") routes _get_rgb_by_label straight to
    # default_shape_color, so a color-dialog pick has an observable effect.
    editable_config_file.write_text(
        "shape_color: null\ndefault_shape_color: [10, 20, 30]\n"
    )
    win = main_win(config_file=editable_config_file)
    win._docks.unique_label_list.add_label_item(label="cat", color=(10, 20, 30))
    item = win._docks.unique_label_list.find_label_item("cat")
    assert item is not None
    assert "#0a141e" in item.text()

    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None
    swatch = dialog._editors[("default_shape_color",)]
    assert isinstance(swatch, _ColorSwatchButton)
    monkeypatch.setattr(
        QtWidgets.QColorDialog,
        "getColor",
        lambda *args, **kwargs: QtGui.QColor(40, 50, 60),
    )

    swatch.clicked.emit()

    assert win._config["default_shape_color"] == [40, 50, 60]
    assert "#28323c" in item.text()  # unique-label dock swatch recolored live
    persisted = safe_load(editable_config_file.read_text())
    assert persisted["default_shape_color"] == [40, 50, 60]

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_shape_color_dialog_change_persists_fixed_as_null(
    main_win: MainWinFactory, qtbot: QtBot, editable_config_file: Path, pause: bool
) -> None:
    win = main_win(config_file=editable_config_file)
    assert win._config["shape_color"] == "auto"

    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None
    combo = dialog._editors[("shape_color",)]
    assert isinstance(combo, QtWidgets.QComboBox)
    combo.setCurrentIndex(combo.findData(None))  # "Fixed"

    assert win._config["shape_color"] is None
    assert safe_load(editable_config_file.read_text())["shape_color"] is None

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_sort_labels_dialog_toggle_rebuilds_label_dialog(
    main_win: MainWinFactory, qtbot: QtBot, editable_config_file: Path, pause: bool
) -> None:
    win = main_win(config_file=editable_config_file)
    assert win._config["sort_labels"] is True
    old_label_dialog = win._label_dialog

    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None
    checkbox = dialog._editors[("sort_labels",)]
    assert isinstance(checkbox, QtWidgets.QCheckBox)
    assert checkbox.isChecked()
    checkbox.setChecked(False)

    assert win._config["sort_labels"] is False
    # sort_labels is only read at LabelDialog construction, so the live-apply
    # rebuilds the dialog instead of updating it in place.
    assert win._label_dialog is not old_label_dialog
    assert win._label_dialog._sort_labels is False
    assert safe_load(editable_config_file.read_text())["sort_labels"] is False

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_show_label_text_field_dialog_toggle_rebuilds_label_dialog(
    main_win: MainWinFactory, qtbot: QtBot, editable_config_file: Path, pause: bool
) -> None:
    win = main_win(config_file=editable_config_file)
    assert win._label_dialog.edit.parent() is not None

    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None
    checkbox = dialog._editors[("show_label_text_field",)]
    assert isinstance(checkbox, QtWidgets.QCheckBox)
    assert checkbox.isChecked()
    checkbox.setChecked(False)

    assert win._config["show_label_text_field"] is False
    assert win._label_dialog.edit.parent() is None
    assert safe_load(editable_config_file.read_text())["show_label_text_field"] is False

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_label_completion_dialog_change_rebuilds_label_dialog(
    main_win: MainWinFactory, qtbot: QtBot, editable_config_file: Path, pause: bool
) -> None:
    win = main_win(config_file=editable_config_file)
    assert win._config["label_completion"] == "startswith"

    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None
    combo = dialog._editors[("label_completion",)]
    assert isinstance(combo, QtWidgets.QComboBox)
    combo.setCurrentIndex(combo.findData("contains"))

    assert win._config["label_completion"] == "contains"
    completer = win._label_dialog.edit.completer()
    assert completer is not None
    assert completer.filterMode() == Qt.MatchFlag.MatchContains
    assert (
        completer.completionMode()
        == QtWidgets.QCompleter.CompletionMode.PopupCompletion
    )
    assert safe_load(editable_config_file.read_text())["label_completion"] == "contains"

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_ai_default_dialog_change_syncs_dock_combo(
    main_win: MainWinFactory, qtbot: QtBot, editable_config_file: Path, pause: bool
) -> None:
    win = main_win(config_file=editable_config_file)
    assert win._config["ai"]["default"] == "Sam2 (balanced)"
    dock_combo = win._ai_annotation._model_combo
    assert dock_combo.currentText() == "Sam2 (balanced)"

    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None
    combo = dialog._editors[("ai", "default")]
    assert isinstance(combo, QtWidgets.QComboBox)
    combo.setCurrentIndex(combo.findData("EfficientSam (speed)"))

    assert win._config["ai"]["default"] == "EfficientSam (speed)"
    # settings-dialog change -> dock combobox follows
    assert dock_combo.currentText() == "EfficientSam (speed)"
    assert win._canvas_widgets.canvas.get_ai_model_name() == "efficientsam:10m"
    assert (
        safe_load(editable_config_file.read_text())["ai"]["default"]
        == "EfficientSam (speed)"
    )

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_ai_dock_combo_change_persists_as_default(
    main_win: MainWinFactory, qtbot: QtBot, editable_config_file: Path, pause: bool
) -> None:
    win = main_win(config_file=editable_config_file)
    dock_combo = win._ai_annotation._model_combo

    # dock combobox change -> persists as the new default
    dock_combo.setCurrentIndex(dock_combo.findData("sam:100m"))

    assert win._config["ai"]["default"] == "Sam (speed)"
    assert safe_load(editable_config_file.read_text())["ai"]["default"] == "Sam (speed)"

    win._open_settings()
    dialog = win._settings_dialog
    assert dialog is not None
    combo = dialog._editors[("ai", "default")]
    assert isinstance(combo, QtWidgets.QComboBox)
    assert combo.currentData() == "Sam (speed)"

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)


@pytest.mark.gui
def test_ai_annotation_construction_does_not_write_config(
    main_win: MainWinFactory, qtbot: QtBot, editable_config_file: Path, pause: bool
) -> None:
    # The dock combobox's startup sync (index set from ai.default, which is not
    # the combo's first entry) must not round-trip back into a config write; the
    # model_changed -> _set_config_value wiring is connected only after
    # construction to avoid exactly that.
    before = editable_config_file.read_text()
    win = main_win(config_file=editable_config_file)

    assert editable_config_file.read_text() == before

    close_or_pause(qtbot=qtbot, widget=win, pause=pause)
