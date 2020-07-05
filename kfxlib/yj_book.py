from __future__ import (unicode_literals, division, absolute_import, print_function)

import os
import posixpath
import traceback

from .ion_symbol_table import (LocalSymbolTable, SymbolTableCatalog, report_local_symbol_tables)
from .ion_text import IonText
from .kfx_container import (KfxContainer, MAX_KFX_CONTAINER_SIZE)
from .kpf_book import KpfBook
from .kpf_container import KpfContainer
from .unpack_container import (IonTextContainer, ZipUnpackContainer)
from .utilities import (
        DataFile, file_read_utf8, flush_unicode_cache, bytes_to_separated_hex, KFXDRMError,
        temp_file_cleanup, ZIP_SIGNATURE)
from .yj_container import YJFragmentList
from .yj_metadata import (BookMetadata, YJ_Metadata)
from .yj_position_location import BookPosLoc
from .yj_structure import BookStructure
from .yj_symbol_catalog import YJ_SYMBOLS
from .yj_symbol_catalog import IonSharedSymbolTable


from .python_transition import (IS_PYTHON2)
if IS_PYTHON2:
    from .python_transition import repr


__license__ = "GPL v3"
__copyright__ = "2020, John Howell <jhowell@acm.org>"


class YJ_Book(BookStructure, BookPosLoc, BookMetadata, KpfBook):
    def __init__(self, file, log, credentials=[], pure=False, metadata=None, approximate_pages=None, is_netfs=False,
                 retain_yj_locals=False):
        self.datafile = DataFile(file)
        self.log = log
        self.credentials = credentials
        self.pure = pure
        self.desired_metadata = metadata
        self.desired_approximate_pages = approximate_pages
        self.is_netfs = is_netfs
        self.retain_yj_locals = retain_yj_locals

        self.reported_errors = set()
        self.symtab = LocalSymbolTable(self.log, YJ_SYMBOLS.name)
        self.fragments = YJFragmentList()
        self.reported_missing_fids = set()
        self.is_kpf_prepub = self.is_dictionary = False
        self.yj_containers = []
        self.kpf_container = None

        self.load_symbol_catalog()

    def load_symbol_catalog(self):
        from calibre.constants import config_dir

        translation_catalog_filename = os.path.join(config_dir, "plugins", "kfx_symbol_catalog.ion")

        if os.path.isfile(translation_catalog_filename):
            translation_catalog = SymbolTableCatalog()

            try:
                IonText(self.log, LocalSymbolTable(self.log, catalog=translation_catalog)).deserialize_multiple_values(
                        file_read_utf8(translation_catalog_filename), import_symbols=True)
            except Exception:
                self.log.error("Failed to parse symbol catalog %s" % translation_catalog_filename)
                raise

            translation_symtab = translation_catalog.get_shared_symbol_table(YJ_SYMBOLS.name)
            if translation_symtab is None:
                raise Exception("Symbol catalog %s does not contain a definition for YJ_symbols" % translation_catalog_filename)

            self.log.info("Symbol catalog defines %d symbols in YJ_symbols" % len(translation_symtab.symbols))

        else:
            translation_symtab = IonSharedSymbolTable(YJ_SYMBOLS.name)

        self.symtab.set_translation(translation_symtab)

    def final_actions(self):
        report_local_symbol_tables()
        flush_unicode_cache()
        temp_file_cleanup()

    def convert_to_single_kfx(self):
        self.decode_book()

        if self.is_dictionary:
            raise Exception("Cannot serialize dictionary as KFX container")

        if self.is_kpf_prepub:
            raise Exception("Cannot serialize KPF as KFX container without fix-up")

        result = KfxContainer(self.log, self.symtab, fragments=self.fragments).serialize()

        if len(result) > MAX_KFX_CONTAINER_SIZE:
            self.log.warning("KFX container created may be too large for some devices (%d bytes)" % len(result))
            pass

        self.final_actions()
        return result

    def convert_to_epub(self, epub2_desired=False):
        from .yj_to_epub import KFX_EPUB
        self.decode_book()
        result = KFX_EPUB(self, self.log, epub2_desired).epub_data
        self.final_actions()
        return result

    def get_metadata(self):

        self.locate_book_datafiles()

        for datafile in self.container_datafiles:
            try:
                container = self.get_container(datafile, ignore_drm=True)
                if container is None:
                    continue

                container.deserialize(ignore_drm=True)
                self.fragments.extend(container.get_fragments())

            except Exception as e:
                self.log.warning("Failed to extract content from %s: %s" % (datafile.name, repr(e)))
                continue

            if self.has_metadata() and self.has_cover_data():
                break

        if not self.has_metadata():
            raise Exception("Failed to locate a KFX container with metadata")

        return YJ_Metadata().get_from_book(self)

    def convert_to_kpf(self, conversion=None, flags=None, timeout_sec=None, cleaned_filename=None):
        from .generate_kpf_common import ConversionResult
        from .generate_kpf_using_cli import KPR_CLI

        if not self.datafile.is_real_file:
            raise Exception("Cannot create KPF from stream")

        infile = self.datafile.name
        intype = os.path.splitext(infile)[1]

        if not conversion:
            conversion = "KPR_CLI"

        flags = set() if flags is None else set(flags)

        options = conversion.split("/")
        conversion_name = options[0]
        flags |= set(options[1:])

        ALL_TYPES = [".doc", ".docx", ".epub", ".mobi", ".opf"]

        if conversion_name == "KPR_CLI" and intype in ALL_TYPES:
            conversion_sequence = KPR_CLI()
        else:
            return ConversionResult(error_msg="Cannot generate KPF from %s file using %s" % (intype, conversion_name))

        try:
            result = conversion_sequence.convert(self.log, infile, flags, timeout_sec, cleaned_filename)
        except Exception as e:
            traceback.print_exc()
            result = ConversionResult(error_msg=repr(e))

        return result

    def convert_to_zip_unpack(self):
        self.decode_book()
        result = ZipUnpackContainer(self.log, self.symtab, fragments=self.fragments).serialize()
        self.final_actions()
        return result

    def decode_book(self):
        if self.fragments:
            return

        self.locate_book_datafiles()

        for datafile in self.container_datafiles:
            self.log.info("Processing container: %s" % datafile.name)
            container = self.get_container(datafile)
            container.deserialize()
            self.yj_containers.append(container)

        for container in self.yj_containers:
            self.fragments.extend(container.get_fragments())

        if self.is_kpf_prepub:
            self.fix_kpf_prepub_book(self.retain_yj_locals)

        if True:
            self.check_consistency()

        if not self.pure:
            if self.desired_metadata is not None:
                self.desired_metadata.set_to_book(self)

            if self.desired_approximate_pages is not None and self.desired_approximate_pages >= 0:
                try:
                    self.create_approximate_page_list(self.desired_approximate_pages)
                except Exception as e:
                    traceback.print_exc()
                    self.log.error("Exception creating approximate page numbers: %s" % repr(e))

        try:
            self.report_features_and_metadata(unknown_only=False)
        except Exception as e:
            traceback.print_exc()
            self.log.error("Exception checking book features and metadata: %s" % repr(e))

        self.check_fragment_usage(rebuild=not self.pure, ignore_extra=False)
        self.check_symbol_table(rebuild=not self.pure)

        self.final_actions()

    def locate_book_datafiles(self):
        self.container_datafiles = []

        if self.datafile.is_real_file and os.path.isdir(self.datafile.name):
            self.locate_files_from_dir(self.datafile.name)

        elif self.datafile.ext in [".azw8", ".ion", ".kfx", ".kpf"]:

            self.container_datafiles.append(self.datafile)

            if self.datafile.ext == ".kfx" and self.datafile.is_real_file:
                sdr_dirname = os.path.splitext(self.datafile.name)[0] + ".sdr"
                if os.path.isdir(sdr_dirname):
                    self.locate_files_from_dir(sdr_dirname)

        elif self.datafile.ext in [".kfx-zip", ".zip"]:
            with self.datafile.as_ZipFile() as zf:
                for info in zf.infolist():
                    if posixpath.basename(info.filename) in ["book.ion", "book.kdf"]:
                        self.container_datafiles.append(self.datafile)
                        break
                else:
                    for info in zf.infolist():
                        self.check_located_file(info.filename, zf.read(info), self.datafile)

        else:
            raise Exception("Unknown main file type. Must be azw8, ion, kfx, kfx-zip, kpf, or zip.")

        if not self.container_datafiles:
            raise Exception("No KFX containers found. This book is not in KFX format.")

        self.container_datafiles = sorted(self.container_datafiles)

    def locate_files_from_dir(self, directory, match=None):
        for dirpath, dirnames, filenames in os.walk(directory):
            for fn in filenames:
                if (not match) or match == fn:
                    self.check_located_file(os.path.join(dirpath, fn))

    def check_located_file(self, name, data=None, parent=None):
        basename = posixpath.basename(name.replace("\\", "/"))
        ext = os.path.splitext(basename)[1]

        if ext in [".azw", ".azw8", ".azw9", ".kfx", ".md", ".res", ".yj"]:
            self.container_datafiles.append(DataFile(name, data, parent))

    def get_container(self, datafile, ignore_drm=False):
        if datafile.ext == ".ion":
            return IonTextContainer(self.log, self.symtab, datafile)

        data = datafile.get_data()

        if data.startswith(ZIP_SIGNATURE):
            with datafile.as_ZipFile() as zf:
                for info in zf.infolist():
                    if posixpath.basename(info.filename) in ["book.ion", "book.kdf"]:
                        if info.filename.endswith(".kdf"):
                            return KpfContainer(self.log, self.symtab, datafile, book=self)
                        else:
                            return ZipUnpackContainer(self.log, self.symtab, datafile)

        if data.startswith(KpfContainer.KDF_SIGNATURE):
            return KpfContainer(self.log, self.symtab, datafile, book=self)

        if data.startswith(KfxContainer.SIGNATURE):
            return KfxContainer(self.log, self.symtab, datafile)

        if data.startswith(KfxContainer.DRM_SIGNATURE):

            if ignore_drm:
                return None

            raise KFXDRMError("Book container %s has DRM and cannot be converted" % datafile.name)

        if data[0x3c:0x3c+8] == b"BOOKMOBI":
            raise Exception("File format is MOBI (not KFX) for %s" % datafile.name)

        raise Exception("Unable to determine KFX container type of %s (%s)" % (datafile.name, bytes_to_separated_hex(data[:8])))
