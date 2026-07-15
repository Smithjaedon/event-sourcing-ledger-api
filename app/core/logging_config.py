import logging

from rich.console import Console
from rich.logging import RichHandler


def setup_logging(level=logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            RichHandler(
                console=Console(stderr=False, force_terminal=True),
                markup=True,
                rich_tracebacks=True,
                show_path=False,
            )
        ],
        force=True,
    )

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True