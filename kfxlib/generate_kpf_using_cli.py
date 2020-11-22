#!/usr/bin/python
# -*- coding: utf8 -*-

from __future__ import (unicode_literals, division, absolute_import, print_function)

import csv
import io
import os

from .generate_kpf_common import (ConversionProcess, ConversionResult, ConversionSequence, KindlePreviewer)
from .message_logging import log
from .utilities import (file_read_binary, file_read_utf8, join_search_path, natural_sort_key, truncate_list)

from .python_transition import IS_PYTHON2
if IS_PYTHON2:
    from .python_transition import (repr)


__license__ = "GPL v3"
__copyright__ = "2020, John Howell <jhowell@acm.org>"


MAX_CONVERSION_RETRIES = 5

MAX_GUIDANCE = 100


class KPR_CLI(ConversionSequence):

    SEQUENCE_NAME = "KPR_CLI"

    def init_application(self):
        self.application = KindlePreviewer()

    def perform_conversion_sequence(self):
        retry_count = 0
        result, is_specific_error = self.perform_conversion_sequence_once()

        while result.kpf_data is None and retry_count < MAX_CONVERSION_RETRIES and not is_specific_error:
            log.info("Unknown conversion error occurred -- Retrying")
            retry_count += 1
            result, is_specific_error = self.perform_conversion_sequence_once()

        return result

    def perform_conversion_sequence_once(self):
        self.out_dir = self.create_unique_dir()
        cli = KPR_CLI_Process(self)
        cli.run(self.in_file_name, self.out_dir)

        error_msg = cli.error_msg
        log_data = cli.logs
        guidance_entries = []
        kpf_data = None
        is_specific_error = cli.process_failure

        summary_log_name = "Summary_Log.csv"
        summary_log_csv_file = os.path.join(self.out_dir, summary_log_name)

        conversion_log_file = quality_report_file = None

        if os.path.isfile(summary_log_csv_file):
            log_data[summary_log_name] = lg = file_read_utf8(summary_log_csv_file, "utf-8-sig")

            try:
                with io.BytesIO(lg.encode("utf-8")) if IS_PYTHON2 else io.StringIO(lg) as csvfile:
                    for row in csv.DictReader(csvfile):
                        if ustr(row["Conversion Status"]) == "Success":
                            if ustr(row["Enhanced Typesetting Status"]) == "Supported":
                                kpf_filename = self.fix_output_filename(ustr(row["Output File Path"]))

                                if os.path.isfile(kpf_filename):
                                    kpf_data = file_read_binary(kpf_filename)
                                else:
                                    error_msg = "KPF file is missing: \"%s\"" % kpf_filename
                                    break
                            else:
                                error_msg = "Enhanced Typesetting not supported for this %s" % (self.full_book_type or "book")
                        else:
                            error_msg = "Conversion failed"

                        conversion_log_file = self.fix_output_filename(ustr(row["Log File Path"]))
                        quality_report_file = ustr(row.get("Quality Report Path"))
                        break

            except Exception as e:
                error_msg = "Exception occurred processing %s: %s" % (summary_log_name, repr(e))
        else:
            error_msg = error_msg or "%s is missing: %s" % (summary_log_name, summary_log_csv_file)

        if os.path.isfile(conversion_log_file):
            try:
                log_data[os.path.basename(conversion_log_file)] = lg = file_read_utf8(conversion_log_file, "utf-8-sig")

                while "\n" in lg and not lg.startswith("\"Type\""):
                    lg = lg.partition("\n")[2]

                have_error_msg = False
                with io.BytesIO(lg.encode("utf-8")) if IS_PYTHON2 else io.StringIO(lg) as logfile:
                    for row in csv.DictReader(logfile):
                        field = dict(row)
                        msg_type = ustr(field.pop("Type", ""))
                        description = ustr(field.pop("Description", "")).strip()
                        msg = "%s %s" % (msg_type, description)

                        if msg_type in {"Error", "ET Error"} and not have_error_msg:
                            error_msg = description
                            have_error_msg = True
                            is_specific_error = True

                        guidance_lines = [msg]

                        source_file = ustr(field.pop("Source File", ""))
                        if source_file:
                            msg = "    Source File: %s" % source_file

                            line_number = ustr(field.pop("Line Number", ""))
                            if line_number:
                                msg += " (Line %s)" % line_number

                            guidance_lines.append(msg)

                        for k, v in sorted(field.items()):
                            if k is not None and v:
                                guidance_lines.append("    %s: %s" % (ustr(k), ustr(v)))

                        guidance_entries.append("\n".join(guidance_lines) + "\n")

            except Exception as e:
                error_msg = "Exception occurred processing log: %s" % repr(e)
                is_specific_error = True
        else:
            error_msg = "Log file is missing: %s" % conversion_log_file
            is_specific_error = True

        if quality_report_file:
            quality_report_file = self.fix_output_filename(quality_report_file)

            if os.path.isfile(quality_report_file):
                try:
                    log_data[os.path.basename(quality_report_file)] = lg = file_read_utf8(quality_report_file, "utf-8-sig")

                    while "\n" in lg and not lg.startswith("\"Type\""):
                        lg = lg.partition("\n")[2]

                    with io.BytesIO(lg.encode("utf-8")) if IS_PYTHON2 else io.StringIO(lg) as reportfile:
                        for row in csv.DictReader(reportfile):
                            field = dict(row)
                            msg_type = ustr(field.pop("Type", ""))
                            category = ustr(field.pop("Category", "")).strip()
                            description = ustr(field.pop("Description", "")).strip()
                            msg = (
                                ("%s Quality (%s): %s" % (msg_type, category, description)) if category else
                                ("%s Quality: %s" % (msg_type, description)))
                            guidance_lines = [msg]

                            for k, v in sorted(field.items()):
                                if k is not None and v:
                                    guidance_lines.append("    %s: %s" % (ustr(k), ustr(v)))

                            guidance_entries.append("%s\n" % ("\n".join(guidance_lines)))

                except Exception as e:
                    guidance_entries.append("Exception occurred processing quality report: %s\n" % repr(e))
            else:
                guidance_entries.append("Quality report file is missing: %s\n" % quality_report_file)

        return ConversionResult(
                kpf_data=kpf_data, error_msg=error_msg, logs=self.combine_logs(log_data, error_msg),
                guidance="\n".join(truncate_list(guidance_entries, MAX_GUIDANCE))), is_specific_error

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

        if "QC" in self.sequence.flags and self.application.program_version_sort >= natural_sort_key("3.37.0"):
            self.argv.append("-qualitychecks")

        self.working_dir = out_dir
        self.out_file_name = os.path.join(out_dir, "log_KPR_CLI.txt")

        self.get_clean_environment()
        self.env[self.PATH_VAR_NAME] = join_search_path(
                self.application.program_path, self.env.get(self.PATH_VAR_NAME, ""))

        ConversionProcess.run(self)


def ustr(s):
    return s.decode("utf-8") if isinstance(s, bytes) else s
