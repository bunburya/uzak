import logging

logging.basicConfig(level=logging.INFO)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.propagate = False
    # Logger to handle "normal" output, ie, information provided to the user in the usual way.
    normal_output = logging.StreamHandler()
    normal_output.setFormatter(logging.Formatter("%(message)s"))
    normal_output.setLevel(logging.INFO)
    normal_output.filter = lambda r: r.levelno < logging.WARN

    # Logger to handle "bad" output (warnings or errors), which also communicates the log level.
    bad_output = logging.StreamHandler()
    bad_output.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    bad_output.setLevel(logging.WARN)

    logger.addHandler(normal_output)
    logger.addHandler(bad_output)
    return logger
