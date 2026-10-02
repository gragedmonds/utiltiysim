from utilsim.config.model import SimConfig, config_schema

__all__ = ["SimConfig", "config_schema", "load_preset", "list_presets", "SCENARIOS"]


def __getattr__(name: str):
    # Presets need PyYAML; loading them lazily keeps the hosted engine (no YAML) importing SimConfig.
    if name in ("SCENARIOS", "list_presets", "load_preset"):
        from utilsim.config import presets

        return getattr(presets, name)
    raise AttributeError(name)
