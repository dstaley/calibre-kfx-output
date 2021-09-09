#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import, print_function)

import argparse
import imp
import os
import platform
import re
import shutil
import sys
import traceback

from calibre.constants import (config_dir, get_version)
from calibre.customize.conversion import (OutputFormatPlugin, OptionRecommendation)
from calibre.ebooks.conversion import ConversionUserFeedBack
from calibre.ebooks.conversion.plugins.epub_output import EPUBOutput
from calibre.ebooks.oeb.base import OPF as OPFNS
from calibre.ebooks.metadata.opf2 import OPF
from calibre.utils.config_base import tweaks
from calibre.utils.logging import Log

__license__ = "GPL v3"
__copyright__ = "2021, John Howell <jhowell@acm.org>"


PREPARED_FILE_SAVE_DIR = None
ASIN_RE = r"^B[0-9A-Z]{9}$"
AUTO_PAGES = "(auto)"           # fake name for automatic page number generation, instead of a lookup name
TIMEOUT = 15 * 60               # in seconds

if sys.version_info[0] == 2:
    str = type("")


class KFXOutput(OutputFormatPlugin):
    name = "KFX Output"
    author = "jhowell"
    file_type = "kfx"
    version = (1, 55, 0)
    minimum_calibre_version = (2, 0, 0)                 # required for apsw with sqlite >= 3.8.2
    supported_platforms = ["windows", "osx", "linux"]

    options = {
        OptionRecommendation(
            name="cde_type_pdoc", recommended_value=False,
            help="Mark this book as a personal document (PDOC) instead of an Amazon purchased book (EBOK). "
            "This results in different handling by Kindle apps and devices. The default setting will enable the most features, "
            "such as cover thumbnail images, but because the book was not actually purchased from Amazon unexpected behavior "
            "may sometimes result. Setting this option disables some features, but reduces the chance of odd problems occurring."),

        OptionRecommendation(
            name="show_kpr_logs", recommended_value=False,
            help="Show the Kindle Previewer conversion logs in the job log. This shows all of the output produced "
            "by Kindle Previewer during conversion and may possibly help in debugging a conversion failure in cases where "
            "the error message produced does not provide enough information."),

        OptionRecommendation(
            name="approximate_pages", recommended_value=False,
            help="Create approximate page numbers if real page numbers are not present in the source file of the book. "
            "(The default value for this option will also be used by the KFX Metadata Writer.)"),

        OptionRecommendation(
            name="number_of_pages_field", recommended_value=AUTO_PAGES,
            help=("Lookup name of the custom column holding the desired number of pages to produce when creating approximate "
                  "page numbers for books. (A non-numeric or zero column value will cause the number of pages to be determined "
                  "automatically based on the content of each book.) Leave this as '%s' to always determine page numbers "
                  "automatically. (The default value for this option will also be used the KFX Metadata Writer.)") % AUTO_PAGES),

        OptionRecommendation(
            name="enable_timeout", recommended_value=False,
            help="Stop conversions lasting over 15 minutes. This can help to debug cases where the Kindle Previewer becomes "
            "hung up during conversion."),

        OptionRecommendation(
            name="quality_report", recommended_value=False,
            help="Include Kindle Previewer quality report messages in the conversion log."),
    }

    recommendations = EPUBOutput.recommendations

    def __init__(self, *args, **kwargs):
        self.cli = False
        OutputFormatPlugin.__init__(self, *args, **kwargs)

        self.epub_output_plugin = EPUBOutput(*args, **kwargs)

        self.resources = self.load_resources(["kfx.png", "plugin_widget.py"])
        self.load_kfx_icon()
        self.load_configuration_widget()
        self.init_embedded_plugins()

    def load_kfx_icon(self):
        # calibre does not include an icon for KFX format

        filename = os.path.join(config_dir, "resources", "images", "mimetypes", "kfx.png")
        if not os.path.isfile(filename):
            try:
                os.makedirs(os.path.dirname(filename))
            except Exception:
                pass

            try:
                with open(filename, "wb") as f:
                    f.write(self.resources["kfx.png"])
            except Exception:
                traceback.print_exc()
                print("Failed to create KFX icon file")

    def load_configuration_widget(self):
        # hack to work around OutputOptions.load_conversion_widgets() in calibre.gui2.preferences.conversion
        # not using gui_configuration_widget() to find configuration widgets for conversion plugins
        # it instead looks for a module named "calibre.gui2.convert.kfx_output" containing a PluginWidget

        try:
            from calibre_plugins.kfx_output.plugin_widget import PluginWidget
            self.PluginWidget = PluginWidget
        except Exception:
            return      # not running GUI so no need to install this

        mod_name = "calibre.gui2.convert.kfx_output"        # expected name of module containing PluginWidget
        mod_src = self.resources["plugin_widget.py"]

        try:
            mod = imp.new_module(mod_name)
            exec(mod_src, mod.__dict__)         # compile source
            sys.modules[mod_name] = mod         # prevent any future import attempt

        except Exception:
            traceback.print_exc()
            print("Failed to create module %s" % mod_name)

    def gui_configuration_widget(self, parent, get_option_by_name, get_option_help, db, book_id=None):
        from calibre_plugins.kfx_output.plugin_widget import PluginWidget
        return PluginWidget(parent, get_option_by_name, get_option_help, db, book_id)

    def convert(self, oeb_book, output, input_plugin, opts, log):
        self.report_version(log)

        #for mivals in oeb_book.metadata.items.values():
        #    for mival in mivals:
        #        log.info("metadata: %s" % repr(mival))

        try:
            book_name = str(oeb_book.metadata.title[0])
        except Exception:
            book_name = ""

        asin = None

        if not tweaks.get("kfx_output_ignore_asin_metadata", False):
            for idre in ["^mobi-asin$", "^amazon.*$", "^asin$"]:
                for ident in oeb_book.metadata["identifier"]:
                    idtype = ident.get(OPFNS("scheme"), "").lower()
                    if re.match(idre, idtype) and re.match(ASIN_RE, ident.value):
                        asin = ident.value
                        log.info("Found ASIN metadata %s: %s" % (idtype, asin))
                        break

                if asin:
                    break

        #with open(opts.read_metadata_from_opf, "rb") as opff:
        #    log.info("opf: %s" % opff.read())

        if opts.approximate_pages:
            page_count = 0
            if opts.number_of_pages_field and opts.number_of_pages_field != AUTO_PAGES and opts.read_metadata_from_opf:
                # This OPF contains custom column metadata not present in the oeb_book OPF
                opf = OPF(opts.read_metadata_from_opf, populate_spine=False, try_to_guess_cover=False, read_toc=False)
                mi = opf.to_book_metadata()
                page_count_str = mi.get(opts.number_of_pages_field, None)

                if page_count_str is not None:
                    try:
                        page_count = int(page_count_str)
                    except Exception:
                        pass

                    log.info("Page count value from field %s: %d ('%s')" % (opts.number_of_pages_field, page_count, page_count_str))
                else:
                    log.warning("Book has no page count field %s" % opts.number_of_pages_field)
        else:
            page_count = -1

        #log.info("oeb_book contains %d pages" % len(oeb_book.pages.pages))
        #log.info("options: %s" % str(opts.__dict__))

        # set default values for options expected by the EPUB Output plugin
        for optrec in EPUBOutput.options:
            setattr(opts, optrec.option.name, optrec.recommended_value)

        # override currently known EPUB Output plugin options
        opts.extract_to = None
        opts.dont_split_on_page_breaks = False
        opts.flow_size = 0
        opts.no_default_epub_cover = False
        opts.no_svg_cover = False
        opts.preserve_cover_aspect_ratio = True
        opts.epub_flatten = False
        opts.epub_inline_toc = False
        opts.epub_toc_at_end = False
        opts.toc_title = None

        epub_filename = self.temporary_file(".epub").name
        self.epub_output_plugin.convert(oeb_book, epub_filename, input_plugin, opts, log)  # convert input format to EPUB
        log.info("Successfully converted input format to EPUB")

        if PREPARED_FILE_SAVE_DIR:
            if not os.path.exists(PREPARED_FILE_SAVE_DIR):
                os.makedirs(PREPARED_FILE_SAVE_DIR)

            prepared_file_path = os.path.join(PREPARED_FILE_SAVE_DIR, os.path.basename(epub_filename))
            shutil.copyfile(epub_filename, prepared_file_path)
            log.warning("Saved conversion input file: %s" % prepared_file_path)

        self.convert_using_previewer(
                JobLog(log), book_name, epub_filename, asin, opts.cde_type_pdoc, page_count,
                opts.show_kpr_logs, False, opts.enable_timeout, opts.quality_report, output)

    def cli_main(self, argv):
        self.cli = True
        log = JobLog(Log())
        self.report_version(log)
        log.info("")

        allowed_exts = [".epub", ".opf", ".mobi", ".doc", ".docx", ".kpf", ".kfx-zip"]
        ext_choices = ", ".join(allowed_exts[:-1] + ["or " + allowed_exts[-1]])

        parser = argparse.ArgumentParser(prog='calibre-debug -r "KFX Output" --', description="Convert e-book to KFX format")
        parser.add_argument("-a", "--asin", action="store", help="Optional ASIN to assign to the book")
        parser.add_argument("-c", "--clean", action="store_true", help="Save the input file cleaned for conversion to KFX")
        parser.add_argument("-d", "--doc", action="store_true", help="Create personal document (PDOC) instead of book (EBOK)")
        parser.add_argument("-p", "--pages", action="store", type=int, default=-1,
                            help="Create n approximate page numbers if missing from input file (0 for auto)")
        parser.add_argument("-q", "--quality", action="store_true", help="Include Kindle Previewer quality report in log")
        parser.add_argument("-t", "--timeout", action="store_true", help="Stop conversions lasting over 15 minutes")
        parser.add_argument("-l", "--logs", action="store_true", help="Show log files produced during conversion")
        parser.add_argument("infile", help="Pathname of the %s file to be converted" % ext_choices)
        parser.add_argument("outfile", nargs="?", help="Optional pathname of the resulting .kfx file")
        args = parser.parse_args(argv[1:])

        input = book_name = args.infile
        intype = os.path.splitext(input)[1]

        if not os.path.isfile(input):
            raise Exception("Input file does not exist: %s" % input)

        if args.outfile:
            output = args.outfile
        else:
            output = os.path.join(os.path.dirname(input), os.path.splitext(os.path.basename(input))[0] + ".kfx")

        if not output.endswith(".kfx"):
            raise Exception("Output file must have .kfx extension")

        if intype in [".kpf", ".kfx-zip"]:
            self.convert_from_kpf_or_zip(log, book_name, input, args.asin, args.doc, args.pages, intype == ".kpf", output)
        elif intype in allowed_exts:
            self.convert_using_previewer(
                    log, book_name, input, args.asin, args.doc, args.pages, args.logs,
                    args.clean, args.timeout, args.quality, output)
        else:
            raise Exception("Input file must be %s" % ext_choices)

    def report_version(self, log):
        try:
            platform_info = platform.platform()
        except Exception:
            platform_info = sys.platform     # handle failure to retrieve platform seen on linux

        log.info("Software versions: %s %s, calibre %s, %s" % (self.name, ".".join([str(v) for v in self.version]),
                 get_version(), platform_info))
        log.info("KFX Output plugin help is available at http://www.mobileread.com/forums/showthread.php?t=272407")

    def convert_using_previewer(self, log, book_name, input_filename, asin, cde_type_pdoc, approximate_pages,
                                include_logs, save_cleaned, enable_timeout, quality_report, output):
        from calibre_plugins.kfx_output.kfxlib import (file_write_binary, set_logger, YJ_Book)

        set_logger(log)
        log.info("Converting %s" % input_filename)

        result = YJ_Book(input_filename, log).convert_to_kpf(
                timeout_sec=TIMEOUT if enable_timeout else None,
                flags={"QC"} if quality_report else None,
                cleaned_filename=os.path.splitext(output)[0] + "_cleaned.epub" if save_cleaned else None)
        set_logger()

        if not result.kpf_data:
            log.info("\n****************** Conversion Failure Reason *****************")
            log.info(result.error_msg)
            log.info("**************************************************************")

        if result.guidance:
            log.info("\n************ Kindle Previewer Conversion Guidance ************")
            print(result.guidance)
            log.info("**************************************************************")

        if result.logs and include_logs:
            log.info("\n************** Kindle Previewer Conversion Logs **************")
            print(result.logs)
            log.info("*************************************************************")

        if not result.kpf_data:
            self.report_failure("Conversion error", result.error_msg, book_name)

        kpf_filename = self.temporary_file(".kpf").name
        file_write_binary(kpf_filename, result.kpf_data)

        input_format = os.path.splitext(input_filename)[1][1:].upper()
        log.info("Successfully converted %s to KPF" % input_format)

        self.convert_from_kpf_or_zip(log, book_name, kpf_filename, asin, cde_type_pdoc, approximate_pages, True, output)

    def convert_from_kpf_or_zip(self, log, book_name, input, asin, cde_type_pdoc, approximate_pages, from_kpf, output):
        from calibre.ebooks.metadata import author_to_author_sort
        from calibre_plugins.kfx_output.kfxlib import (file_write_binary, set_logger, YJ_Book, YJ_Metadata)

        # would be better to use db.author_sort_from_authors instead of author_to_author_sort since that uses the author table
        # controlled by user, but the db is not available when conversion is performed.

        set_logger(log)
        log.info("Converting %s" % input)

        if from_kpf:
            md = YJ_Metadata(author_sort_fn=author_to_author_sort, replace_existing_authors_with_sort=True)

            if cde_type_pdoc:
                md.asin = True
                md.cde_content_type = "PDOC"
            else:
                md.asin = asin or True      # generate random if none set
                md.cde_content_type = "EBOK"
        else:
            md = None       # keep existing metadata

        book = YJ_Book(input, log)
        book.decode_book(set_metadata=md, set_approximate_pages=approximate_pages)
        kfx_data = book.convert_to_single_kfx()    # repackage KPF as KFX
        set_logger()

        if log.errors and not self.cli:
            self.report_failure("KFX creation error", "\n".join(log.errors), book_name)

        file_write_binary(output, kfx_data)
        log.info("Successfully converted to KFX")

    def report_failure(self, cat, msg, book_name):
        if self.cli:
            raise Exception(cat + ": " + msg)
        else:
            from calibre_plugins.kfx_output.kfxlib import clean_message
            bn = "<b>Cannot convert " + clean_message(book_name) + "</b><br><br>" if book_name else ""
            raise ConversionUserFeedBack("KFX conversion failed", bn + "<b>" + cat + ":</b> " + clean_message(msg), level="error")

    def init_embedded_plugins(self):
        from calibre.customize.ui import _initialized_plugins
        from calibre_plugins.kfx_output.metadata_writer import KFXMetadataWriter

        def init_pi(pi_type):
            for plugin in _initialized_plugins:
                if isinstance(plugin, pi_type):
                    return plugin

            pi_type.version = self.version
            plugin = pi_type(self.plugin_path)
            _initialized_plugins.append(plugin)
            plugin.initialize()
            return plugin

        init_pi(KFXMetadataWriter)


class JobLog(object):
    '''
    Logger that also collects errors and warnings for presentation in a job summary.
    '''

    def __init__(self, logger):
        self.logger = logger
        self.errors = []
        self.warnings = []

    def debug(self, msg):
        self.logger.debug(msg)

    def info(self, msg):
        self.logger.info(msg)

    def warn(self, msg):
        self.warnings.append(msg)
        self.logger.warn("WARNING: %s" % msg)

    def warning(self, desc):
        self.warn(desc)

    def error(self, msg):
        self.errors.append(msg)
        self.logger.error("ERROR: %s" % msg)

    def exception(self, msg):
        self.errors.append("EXCEPTION: %s" % msg)
        self.logger.exception("EXCEPTION: %s" % msg)

    def __call__(self, *args):
        self.info(" ".join([str(arg) for arg in args]))
