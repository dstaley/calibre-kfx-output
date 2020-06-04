#!/usr/bin/python
# -*- coding: utf8 -*-

from __future__ import (unicode_literals, division, absolute_import, print_function)

import csv
import io
import os

from .generate_kpf_common import (ConversionProcess, ConversionResult, ConversionSequence, KindlePreviewer)
from .utilities import (file_read_binary, file_read_utf8, file_write_utf8, join_search_path, natural_sort_key, truncate_list)

from .python_transition import IS_PYTHON2
if IS_PYTHON2:
    from .python_transition import (repr)


__license__ = "GPL v3"
__copyright__ = "2020, John Howell <jhowell@acm.org>"


MAX_GUIDANCE = 100


class KPR_CLI(ConversionSequence):

    SEQUENCE_NAME = "KPR_CLI"

    def init_application(self):
        self.application = KindlePreviewer(self.log)

    def perform_conversion_sequence(self):
        self.out_dir = self.create_unique_dir()
        cli = KPR_CLI_Process(self)
        cli.run(self.in_file_name, self.out_dir)

        error_msg = cli.error_msg
        log_data = cli.logs()
        guidance_entries = []
        kpf_data = None

        summary_log_name = "Summary_Log.csv"
        summary_log_csv_file = os.path.join(self.out_dir, summary_log_name)

        if os.path.isfile(summary_log_csv_file):
            log_data[summary_log_name] = lg = file_read_utf8(summary_log_csv_file, "utf-8-sig")
            file_write_utf8(summary_log_csv_file, lg)

            try:
                with (io.open(summary_log_csv_file, "rb") if IS_PYTHON2 else
                        io.open(summary_log_csv_file, "r", encoding="utf-8-sig", errors="ignore")) as csvfile:
                    for row in csv.DictReader(csvfile):
                        if row["Conversion Status"] == "Success":
                            if row["Enhanced Typesetting Status"] == "Supported":
                                kpf_filename = self.fix_output_filename(row["Output File Path"])

                                if os.path.isfile(kpf_filename):
                                    kpf_data = file_read_binary(kpf_filename)
                                else:
                                    error_msg = "KPF file is missing: \"%s\"" % kpf_filename
                                    break
                            else:
                                error_msg = "Enhanced Typesetting not supported for this %s" % (self.full_book_type or "book")
                        else:
                            error_msg = "Conversion failed"

                        conversion_log_file = self.fix_output_filename(row["Log File Path"])

                        if os.path.isfile(conversion_log_file):
                            log_data[os.path.basename(conversion_log_file)] = lg = file_read_utf8(conversion_log_file, "utf-8-sig")

                            while "\n" in lg and not lg.startswith("\"Type\""):
                                lg = lg.partition("\n")[2]

                            file_write_utf8(conversion_log_file, lg)

                            try:
                                have_error_msg = False
                                with (io.open(conversion_log_file, "rb") if IS_PYTHON2 else
                                        io.open(conversion_log_file, "r", encoding="utf-8-sig", errors="ignore")) as logfile:

                                    for row in csv.DictReader(logfile):
                                        field = dict(row)
                                        msg_type = field.pop("Type", "")
                                        description = field.pop("Description", "").strip()
                                        msg = "%s: %s" % (msg_type, description)

                                        if msg_type in {"Error", "ET Error"} and not have_error_msg:
                                            error_msg = description
                                            have_error_msg = True

                                        guidance_lines = []
                                        guidance_lines.append(msg)

                                        source_file = field.pop("Source File", "")

                                        if source_file:
                                            msg = "    Source File: %s" % source_file

                                            line_number = field.pop("Line Number", "")
                                            if line_number:
                                                msg += " (Line %s)" % line_number

                                            guidance_lines.append(msg)

                                        for k, v in sorted(field.items()):
                                            if k is not None and v:
                                                guidance_lines.append("    %s: %s" % (k, v))

                                        guidance_entries.append("\n".join(guidance_lines) + "\n")

                            except Exception as e:
                                error_msg = "Exception occurred processing log: %s" % repr(e)

                        else:
                            error_msg = "Log file is missing: %s" % conversion_log_file

                        break

            except Exception as e:
                error_msg = "Exception occurred processing %s: %s" % (summary_log_name, repr(e))

        else:
            error_msg = error_msg or "%s is missing: %s" % (summary_log_name, summary_log_csv_file)

        return ConversionResult(
                kpf_data=kpf_data, error_msg=error_msg, logs=self.combine_logs(log_data, error_msg),
                guidance="\n".join(truncate_list(guidance_entries, MAX_GUIDANCE)))

    def fix_output_filename(self, filename):

        if not os.path.isfile(filename):
            dirname, basename = os.path.split(filename)
            root, ext = os.path.splitext(basename)
            alt_filename = os.path.join(dirname, root.partition(".")[0] + ext)

            if os.path.isfile(alt_filename):
                return alt_filename

        return filename


class KPR_CLI_Process(ConversionProcess):
    function_name = "CLI"
    use_wincon = True

    def run(self, in_file_name, out_dir):
        if self.application.program_version_sort < natural_sort_key("3.32.0"):
            raise Exception("CLI not available in Kindle Previewer version %s" % self.program_version)

        self.argv = [
            self.application.main_program_path,
            in_file_name,
            "-convert",
            "-locale", "en",
            "-output", out_dir,
            ]

        self.working_dir = out_dir
        self.out_file_name = os.path.join(out_dir, "log_KPR_CLI.txt")

        self.get_clean_environment()
        self.env[self.PATH_VAR_NAME] = join_search_path(
                self.application.program_path, self.env.get(self.PATH_VAR_NAME, ""))

        ConversionProcess.run(self)
