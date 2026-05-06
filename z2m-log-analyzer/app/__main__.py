import uvicorn
from app.config import load_config


def main():
    cfg = load_config()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8099,
        log_level=cfg.log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()
