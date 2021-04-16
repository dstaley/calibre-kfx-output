from __future__ import (unicode_literals, division, absolute_import, print_function)

import logging
import threading

__license__ = "GPL v3"
__copyright__ = "2021, John Howell <jhowell@acm.org>"


thread_local_cfg = threading.local()


def set_logger(logger=None):
    global thread_local_cfg

    if log is not None:
        thread_local_cfg.logger = logger
    else:
        del thread_local_cfg.logger

    return logger


def get_current_logger():
    return getattr(thread_local_cfg, "logger", logging)


class LogCurrent(object):

    def __getattr__(self, method_name):
        return getattr(get_current_logger(), method_name)


log = LogCurrent()
