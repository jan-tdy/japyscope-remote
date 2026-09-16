def create_app(*args, **kwargs):
    """Import the Flask factory lazily so ``python -m webui.app`` is clean."""
    from .app import create_app as factory

    return factory(*args, **kwargs)


__all__ = ["create_app"]
