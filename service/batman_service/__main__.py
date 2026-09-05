import argparse

import uvicorn

from . import config


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the batman service.")
    parser.add_argument("--config", default=None, help="Path to config.toml")
    parser.add_argument("--host", default=None, help="Override server host")
    parser.add_argument("--port", type=int, default=None, help="Override server port")
    args = parser.parse_args(argv)

    cfg = config.load(args.config)
    if args.host is not None:
        cfg.server.host = args.host
    if args.port is not None:
        cfg.server.port = args.port

    config.CFG = cfg
    uvicorn.run("batman_service.main:app", host=cfg.server.host, port=cfg.server.port, log_level="info")


if __name__ == "__main__":
    main()
