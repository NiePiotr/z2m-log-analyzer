import logging
import uvicorn
from app.config import load_config


def main():
    cfg = load_config()
    logging.basicConfig(
        level=cfg.log_level.upper(),
        format="%(asctime)s %(levelname)s:%(name)s: %(message)s",
    )
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8099,
        log_level=cfg.log_level.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()
