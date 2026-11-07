"""Open the Inky display (auto-detect, or a forced type)."""

# Driver modules for the types you're most likely to need to force when the
# EEPROM can't be read. Anything else goes through inky.auto.
FORCED_TYPES = {
    "spectra73": ("inky.inky_e673", {}),                 # Impression 7.3" 2025 / Spectra 6
    "impressions73": ("inky.inky_ac073tc1a", {}),        # Impression 7.3" older 7-colour
    "spectra13": ("inky.inky_el133uf1", {}),             # Impression 13.3" Spectra 6
}


def open_inky(display_type=""):
    """Return an Inky instance. Raises RuntimeError with a helpful message."""
    try:
        import inky  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "The 'inky' Python library is not installed in this Python. "
            "Use venv/bin/python, or run scripts/install.sh."
        ) from e

    if display_type:
        if display_type not in FORCED_TYPES:
            raise RuntimeError(
                f"Unknown display type '{display_type}'. "
                f"Use one of: {', '.join(FORCED_TYPES)} (or leave empty to auto-detect)."
            )
        import importlib

        module_name, kwargs = FORCED_TYPES[display_type]
        return importlib.import_module(module_name).Inky(**kwargs)

    from inky.auto import auto

    try:
        return auto(ask_user=False, verbose=True)
    except RuntimeError as e:
        raise RuntimeError(
            f"{e}\nCould not auto-detect the Inky board. Check that I2C is enabled "
            "(sudo raspi-config nonint do_i2c 0) and run scripts/doctor.sh. "
            "You can also force the type, e.g. set display.type = \"spectra73\" "
            "in config.toml or pass --type spectra73."
        ) from e
