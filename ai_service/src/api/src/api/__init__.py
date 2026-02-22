__all__ = ["app", "create_app", "main"]


def __getattr__(name: str):
    if name in {"app", "create_app"}:
        from api.app import app, create_app

        return app if name == "app" else create_app
    if name == "main":
        from api.server import main

        return main
    raise AttributeError(name)
