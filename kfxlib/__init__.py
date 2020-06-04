#! /usr/bin/python3

from __future__ import (unicode_literals, division, absolute_import, print_function)

from . import utilities
from . import yj_book


__license__ = "GPL v3"
__copyright__ = "2020, John Howell <jhowell@acm.org>"


YJ_Book = yj_book.YJ_Book
YJ_Metadata = yj_book.YJ_Metadata
KFXDRMError = utilities.KFXDRMError


clean_message = utilities.clean_message
file_read_binary = utilities.file_read_binary
file_write_binary = utilities.file_write_binary
file_read_utf8 = utilities.file_read_utf8
file_write_utf8 = utilities.file_write_utf8
json_deserialize = utilities.json_deserialize
json_serialize = utilities.json_serialize
unicode_argv = utilities.unicode_argv
windows_long_path_fix = utilities.windows_long_path_fix

IS_MACOS = utilities.IS_MACOS
IS_WINDOWS = utilities.IS_WINDOWS

user_home_dir = utilities.user_home_dir
windows_user_dir = utilities.windows_user_dir

locale_encode = utilities.locale_encode
locale_decode = utilities.locale_decode
os_environ_get = utilities.os_environ_get
