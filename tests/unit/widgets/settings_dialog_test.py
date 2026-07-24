from __future__ import annotations

import pytest
from PySide6 import QtCore
from PySide6 import QtGui
from PySide6 import QtWidgets
from pytestqt.qtbot import QtBot

from labelme._config import _schema as schema
from labelme._config import load_config
from labelme._widgets.settings_dialog import SettingsDialog
from labelme._widgets.settings_dialog import _ColorSwatchButton
from labelme._widgets.settings_dialog import _PlainTextEdit

Applied = list[tuple[tuple[str, ...], object]]

_INT_SETTING = schema.Setting(
    key_path=("shape", "point_size"),
    section="General",
    label="Vertex size",
    kind="int",
    min_value=1,
    max_value=32,
)

_COLOR_SETTING = schema.Setting(
    key_path=("default_shape_color",),
    section="General",
    label="Default shape color",
    kind="color",
)

_CROSSHAIR_SETTING = schema.Setting(
    key_path=("canvas", "crosshair"),
    section="Annotation",
    label="Show crosshair while drawing",
    kind="bool",
)


@pytest.fixture
def applied() -> Applied:
    return []


def _make_dialog(
    qtbot: QtBot,
    applied: Applied,
    overrides: dict,
    succeed: bool = True,
    settings: tuple[schema.Setting, ...] | None = None,
) -> SettingsDialog:
    config = load_config(config_file=None, config_overrides=overrides)

    def apply_setting(key_path: tuple[str, ...], value: object) -> bool:
        applied.append((key_path, value))
        return succeed

    dialog = SettingsDialog(
        config=config,
        apply_setting=apply_setting,
        open_as_text=lambda: None,
        settings=settings,
    )
    qtbot.addWidget(dialog)
    return dialog


@pytest.fixture
def dialog(qtbot: QtBot, applied: Applied) -> SettingsDialog:
    return _make_dialog(qtbot=qtbot, applied=applied, overrides={})


def test_no_apply_on_construction(dialog: SettingsDialog, applied: Applied) -> None:
    assert applied == []


def test_beta_settings_render_a_badge(dialog: SettingsDialog) -> None:
    expected = {dialog.tr(setting.label) for setting in schema.SETTINGS if setting.beta}
    assert expected, "no beta settings to verify"

    badge_text = dialog.tr("BETA")
    beta_labels: set[str] = set()
    for badge in dialog.findChildren(QtWidgets.QLabel):
        if badge.text() != badge_text:
            continue
        cell = badge.parentWidget()
        assert cell is not None
        beta_labels.update(
            sibling.text()
            for sibling in cell.findChildren(QtWidgets.QLabel)
            if sibling is not badge
        )
    assert beta_labels == expected


def test_accept_does_not_reapply_unchanged_str_list(
    dialog: SettingsDialog, applied: Applied
) -> None:
    dialog.accept()
    assert applied == []


def test_str_list_none_initial_is_blank(dialog: SettingsDialog) -> None:
    edit = dialog._editors[("labels",)]
    assert isinstance(edit, QtWidgets.QPlainTextEdit)
    assert edit.toPlainText() == ""


def test_language_default_selects_system(dialog: SettingsDialog) -> None:
    combo = dialog._editors[("language",)]
    assert isinstance(combo, QtWidgets.QComboBox)
    assert combo.currentData() is None


def test_language_lists_bundled_locales(dialog: SettingsDialog) -> None:
    combo = dialog._editors[("language",)]
    assert isinstance(combo, QtWidgets.QComboBox)
    assert combo.findData("ja_JP") >= 0


def test_language_applies_locale_code(dialog: SettingsDialog, applied: Applied) -> None:
    combo = dialog._editors[("language",)]
    assert isinstance(combo, QtWidgets.QComboBox)
    combo.setCurrentIndex(combo.findData("en_US"))
    assert (("language",), "en_US") in applied


def test_language_applies_discovered_locale(
    dialog: SettingsDialog, applied: Applied
) -> None:
    combo = dialog._editors[("language",)]
    assert isinstance(combo, QtWidgets.QComboBox)
    index = combo.findData("ja_JP")
    assert index >= 0
    combo.setCurrentIndex(index)
    assert (("language",), "ja_JP") in applied


def test_language_unknown_code_falls_back_to_system(
    qtbot: QtBot, applied: Applied
) -> None:
    dialog = _make_dialog(qtbot=qtbot, applied=applied, overrides={"language": "xx_ZZ"})
    combo = dialog._editors[("language",)]
    assert isinstance(combo, QtWidgets.QComboBox)
    assert combo.currentData() is None
    assert applied == []


def test_clearing_labels_is_rejected_when_validate_label_is_exact(
    qtbot: QtBot, applied: Applied, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog = _make_dialog(
        qtbot=qtbot,
        applied=applied,
        overrides={"labels": ["cat"], "validate_label": "exact"},
    )
    warned: list[str] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: warned.append(args[2]),
    )

    validate_combo = dialog._editors[("validate_label",)]
    assert isinstance(validate_combo, QtWidgets.QComboBox)
    model = validate_combo.model()
    assert isinstance(model, QtGui.QStandardItemModel)
    exact_index = validate_combo.findData("exact")
    assert model.item(exact_index).isEnabled()
    assert validate_combo.currentData() == "exact"

    labels_editor = dialog._editors[("labels",)]
    assert isinstance(labels_editor, _PlainTextEdit)
    labels_editor.setPlainText("")
    labels_editor.editing_finished.emit()

    assert warned == [
        (
            "Predefined labels cannot be empty while Label validation is set to "
            "exact. Disable exact validation first."
        )
    ]
    assert applied == []
    assert model.item(exact_index).isEnabled()
    assert validate_combo.currentData() == "exact"
    assert labels_editor.toPlainText() == "cat"


def test_refresh_setting_updates_editor_from_config(
    qtbot: QtBot, applied: Applied
) -> None:
    dialog = _make_dialog(
        qtbot=qtbot, applied=applied, overrides={"display_label_popup": True}
    )
    checkbox = dialog._editors[("display_label_popup",)]
    assert isinstance(checkbox, QtWidgets.QCheckBox)
    assert checkbox.isChecked()

    # Simulate an external change (e.g. a menu toggle) landing in config without
    # going through the dialog's own apply path.
    dialog._config["display_label_popup"] = False
    dialog.refresh_setting(("display_label_popup",))

    assert not checkbox.isChecked()
    assert applied == []  # a refresh must not re-trigger apply_setting


def test_refresh_setting_ignores_unknown_key(qtbot: QtBot, applied: Applied) -> None:
    dialog = _make_dialog(qtbot=qtbot, applied=applied, overrides={})
    # a key without a dialog row must be a no-op, not raise
    dialog.refresh_setting(("does_not_exist",))
    assert applied == []


def test_failed_apply_reverts_checkbox(qtbot: QtBot, applied: Applied) -> None:
    dialog = _make_dialog(
        qtbot=qtbot,
        applied=applied,
        overrides={"display_label_popup": True},
        succeed=False,
    )
    checkbox = dialog._editors[("display_label_popup",)]
    assert isinstance(checkbox, QtWidgets.QCheckBox)
    assert checkbox.isChecked()

    checkbox.setChecked(False)

    assert checkbox.isChecked()  # reverted to the last-saved value


def test_failed_apply_reverts_labels_editor(qtbot: QtBot, applied: Applied) -> None:
    dialog = _make_dialog(
        qtbot=qtbot, applied=applied, overrides={"labels": ["cat"]}, succeed=False
    )
    edit = dialog._editors[("labels",)]
    assert isinstance(edit, _PlainTextEdit)
    assert edit.toPlainText() == "cat"

    edit.setPlainText("cat\ndog")
    edit.commit()

    assert edit.toPlainText() == "cat"  # reverted, not left in a phantom state
    applied.clear()
    edit.commit()  # nothing pending: the revert reset the committed text
    assert applied == []


def test_int_editor_initial_value(qtbot: QtBot, applied: Applied) -> None:
    dialog = _make_dialog(
        qtbot=qtbot, applied=applied, overrides={}, settings=(_INT_SETTING,)
    )
    spin = dialog._editors[("shape", "point_size")]
    assert isinstance(spin, QtWidgets.QSpinBox)
    assert spin.value() == 8
    assert spin.minimum() == 1
    assert spin.maximum() == 32


def test_int_editor_applies_on_change(qtbot: QtBot, applied: Applied) -> None:
    dialog = _make_dialog(
        qtbot=qtbot, applied=applied, overrides={}, settings=(_INT_SETTING,)
    )
    spin = dialog._editors[("shape", "point_size")]
    assert isinstance(spin, QtWidgets.QSpinBox)
    spin.setValue(16)
    assert applied == [(("shape", "point_size"), 16)]


def test_int_editor_does_not_apply_per_keystroke(
    qtbot: QtBot, applied: Applied
) -> None:
    dialog = _make_dialog(
        qtbot=qtbot, applied=applied, overrides={}, settings=(_INT_SETTING,)
    )
    spin = dialog._editors[("shape", "point_size")]
    assert isinstance(spin, QtWidgets.QSpinBox)

    spin.clear()
    qtbot.keyClicks(spin, "12")
    # a half-typed value must not be applied (or persisted) mid-edit
    assert applied == []

    qtbot.keyClick(spin, QtCore.Qt.Key.Key_Return)
    assert applied == [(("shape", "point_size"), 12)]


def test_failed_int_apply_reverts_spinbox(qtbot: QtBot, applied: Applied) -> None:
    dialog = _make_dialog(
        qtbot=qtbot,
        applied=applied,
        overrides={},
        settings=(_INT_SETTING,),
        succeed=False,
    )
    spin = dialog._editors[("shape", "point_size")]
    assert isinstance(spin, QtWidgets.QSpinBox)
    spin.setValue(16)
    assert spin.value() == 8  # reverted to the last-saved value


def test_int_refresh_setting_updates_spinbox(qtbot: QtBot, applied: Applied) -> None:
    dialog = _make_dialog(
        qtbot=qtbot, applied=applied, overrides={}, settings=(_INT_SETTING,)
    )
    spin = dialog._editors[("shape", "point_size")]
    assert isinstance(spin, QtWidgets.QSpinBox)

    dialog._config["shape"]["point_size"] = 20
    dialog.refresh_setting(("shape", "point_size"))

    assert spin.value() == 20
    assert applied == []


def test_color_editor_initial_swatch(qtbot: QtBot, applied: Applied) -> None:
    dialog = _make_dialog(
        qtbot=qtbot, applied=applied, overrides={}, settings=(_COLOR_SETTING,)
    )
    swatch = dialog._editors[("default_shape_color",)]
    assert isinstance(swatch, _ColorSwatchButton)
    assert swatch.rgb() == (0, 255, 0)


def test_color_editor_exposes_value_as_tooltip_and_accessible_name(
    qtbot: QtBot, applied: Applied
) -> None:
    dialog = _make_dialog(
        qtbot=qtbot, applied=applied, overrides={}, settings=(_COLOR_SETTING,)
    )
    swatch = dialog._editors[("default_shape_color",)]
    assert isinstance(swatch, _ColorSwatchButton)
    assert swatch.toolTip() == "rgb(0, 255, 0)"
    assert swatch.accessibleName() == "rgb(0, 255, 0)"

    swatch.set_rgb((10, 20, 30))

    assert swatch.toolTip() == "rgb(10, 20, 30)"
    assert swatch.accessibleName() == "rgb(10, 20, 30)"


def test_color_editor_applies_picked_color(
    qtbot: QtBot, applied: Applied, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog = _make_dialog(
        qtbot=qtbot, applied=applied, overrides={}, settings=(_COLOR_SETTING,)
    )
    swatch = dialog._editors[("default_shape_color",)]
    assert isinstance(swatch, _ColorSwatchButton)
    monkeypatch.setattr(
        QtWidgets.QColorDialog,
        "getColor",
        lambda *args, **kwargs: QtGui.QColor(10, 20, 30),
    )

    swatch.clicked.emit()

    assert applied == [(("default_shape_color",), [10, 20, 30])]
    assert swatch.rgb() == (10, 20, 30)


def test_color_editor_cancelled_picker_does_not_apply(
    qtbot: QtBot, applied: Applied, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog = _make_dialog(
        qtbot=qtbot, applied=applied, overrides={}, settings=(_COLOR_SETTING,)
    )
    swatch = dialog._editors[("default_shape_color",)]
    assert isinstance(swatch, _ColorSwatchButton)
    monkeypatch.setattr(
        QtWidgets.QColorDialog,
        "getColor",
        lambda *args, **kwargs: QtGui.QColor(),  # invalid color == cancelled
    )

    swatch.clicked.emit()

    assert applied == []
    assert swatch.rgb() == (0, 255, 0)


def test_failed_color_apply_reverts_swatch(
    qtbot: QtBot, applied: Applied, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog = _make_dialog(
        qtbot=qtbot,
        applied=applied,
        overrides={},
        settings=(_COLOR_SETTING,),
        succeed=False,
    )
    swatch = dialog._editors[("default_shape_color",)]
    assert isinstance(swatch, _ColorSwatchButton)
    monkeypatch.setattr(
        QtWidgets.QColorDialog,
        "getColor",
        lambda *args, **kwargs: QtGui.QColor(10, 20, 30),
    )

    swatch.clicked.emit()

    assert swatch.rgb() == (0, 255, 0)  # reverted to the last-saved value


def test_color_refresh_setting_updates_swatch(qtbot: QtBot, applied: Applied) -> None:
    dialog = _make_dialog(
        qtbot=qtbot, applied=applied, overrides={}, settings=(_COLOR_SETTING,)
    )
    swatch = dialog._editors[("default_shape_color",)]
    assert isinstance(swatch, _ColorSwatchButton)

    dialog._config["default_shape_color"] = [1, 2, 3]
    dialog.refresh_setting(("default_shape_color",))

    assert swatch.rgb() == (1, 2, 3)
    assert applied == []


def test_tabs_include_annotation_section(dialog: SettingsDialog) -> None:
    titles = [dialog._tabs.tabText(i) for i in range(dialog._tabs.count())]
    assert titles == ["General", "Annotation", "Display", "Labels", "AI"]


def test_crosshair_editor_shows_partial_when_modes_disagree(
    qtbot: QtBot, applied: Applied
) -> None:
    dialog = _make_dialog(
        qtbot=qtbot, applied=applied, overrides={}, settings=(_CROSSHAIR_SETTING,)
    )
    checkbox = dialog._editors[("canvas", "crosshair")]
    assert isinstance(checkbox, QtWidgets.QCheckBox)
    # default enables canvas.crosshair.rectangle but not e.g. polygon, and a
    # solid checkmark would misrepresent that mixed state
    assert checkbox.checkState() == QtCore.Qt.CheckState.PartiallyChecked


def test_crosshair_editor_click_from_partial_enables_all(
    qtbot: QtBot, applied: Applied
) -> None:
    dialog = _make_dialog(
        qtbot=qtbot, applied=applied, overrides={}, settings=(_CROSSHAIR_SETTING,)
    )
    checkbox = dialog._editors[("canvas", "crosshair")]
    assert isinstance(checkbox, QtWidgets.QCheckBox)
    assert checkbox.checkState() == QtCore.Qt.CheckState.PartiallyChecked

    checkbox.click()

    assert checkbox.checkState() == QtCore.Qt.CheckState.Checked
    assert applied == [(("canvas", "crosshair"), True)]


def test_crosshair_editor_unchecked_when_every_mode_is_disabled(
    qtbot: QtBot, applied: Applied
) -> None:
    dialog = _make_dialog(
        qtbot=qtbot,
        applied=applied,
        overrides={
            "canvas": {
                "crosshair": {"rectangle": False, "ai_box_to_shape": False},
            }
        },
        settings=(_CROSSHAIR_SETTING,),
    )
    checkbox = dialog._editors[("canvas", "crosshair")]
    assert isinstance(checkbox, QtWidgets.QCheckBox)
    assert not checkbox.isChecked()


def test_crosshair_editor_applies_a_single_bool_on_toggle(
    qtbot: QtBot, applied: Applied
) -> None:
    dialog = _make_dialog(
        qtbot=qtbot, applied=applied, overrides={}, settings=(_CROSSHAIR_SETTING,)
    )
    checkbox = dialog._editors[("canvas", "crosshair")]
    assert isinstance(checkbox, QtWidgets.QCheckBox)

    checkbox.setChecked(False)

    # The dialog treats this like any other bool row; MainWindow is the one that
    # fans this single value out to the nine canvas.crosshair.<mode> keys.
    assert applied == [(("canvas", "crosshair"), False)]


def test_crosshair_refresh_setting_updates_from_config(
    qtbot: QtBot, applied: Applied
) -> None:
    dialog = _make_dialog(
        qtbot=qtbot, applied=applied, overrides={}, settings=(_CROSSHAIR_SETTING,)
    )
    checkbox = dialog._editors[("canvas", "crosshair")]
    assert isinstance(checkbox, QtWidgets.QCheckBox)
    assert checkbox.checkState() == QtCore.Qt.CheckState.PartiallyChecked

    dialog._config["canvas"]["crosshair"]["rectangle"] = False
    dialog._config["canvas"]["crosshair"]["ai_box_to_shape"] = False
    dialog.refresh_setting(("canvas", "crosshair"))

    assert checkbox.checkState() == QtCore.Qt.CheckState.Unchecked
    assert applied == []
