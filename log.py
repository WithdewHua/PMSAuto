#!/usr/bin/env python3
#

import logging


# 日志格式
logging_datefmt = "%m/%d/%Y %H:%M:%S"
logging_format = "[%(asctime)s][%(levelname)s]<%(funcName)s>: %(message)s"


# 日志相关
logFormatter = logging.Formatter(fmt=logging_format, datefmt=logging_datefmt)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
while logger.handlers:  # Remove un-format logging in Stream, or all of messages are appearing more than once.
    logger.handlers.pop()

consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logFormatter)
logger.addHandler(consoleHandler)


