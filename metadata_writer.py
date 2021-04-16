from __future__ import (unicode_literals, division, absolute_import, print_function)

import re
import sys

from calibre.customize import MetadataWriterPlugin

__license__ = "GPL v3"
__copyright__ = "2021, John Howell <jhowell@acm.org>"


ASIN_RE = r"^B[0-9A-Z]{9}$"
AUTO_PAGES = "(auto)"           # fake name for automatic page number generation, instead of a lookup name

if sys.version_info[0] == 2:
    str = type("")


class KFXMetadataWriter(MetadataWriterPlugin):
    name = "Set KFX metadata (from KFX Output)"
    file_types = {"kfx"}   # accept only monolithic KFX since that will be the format produced
    description = "Set metadata in KFX files"
    author = "jhowell"

    def set_metadata(self, stream, mi, type_):
        from calibre_plugins.kfx_output.kfxlib import (set_logger, YJ_Book, YJ_Metadata)
        from calibre.ebooks import normalize as normalize_unicode
        from calibre.ebooks.metadata import author_to_author_sort
        from calibre.utils.config_base import tweaks
        from calibre.utils.date import (is_date_undefined, isoformat)
        from calibre.utils.logging import Log
        from calibre.utils.localization import (canonicalize_lang, lang_as_iso639_1)

        def mapped_author_to_author_sort(author):
            if hasattr(mi, "author_sort_map"):
                author_sort = mi.author_sort_map.get(author)    # use mapping if provided
                if author_sort:
                    return author_sort

            return author_to_author_sort(author)

        def normalize(s):
            if not isinstance(s, type("")):
                s = s.decode("utf8", "ignore")

            return normalize_unicode(s)

        log = set_logger(Log())

        filename = stream.name if hasattr(stream, "name") else "stream"
        log.info("KFX metadata writer activated for %s" % filename)

        try:
            from calibre.ebooks.conversion.config import load_defaults
            prefs = load_defaults('kfx_output')
        except Exception:
            prefs = {}
            log.info("Failed to read default KFX Output preferences")

        md = YJ_Metadata(author_sort_fn=mapped_author_to_author_sort)

        md.title = normalize(mi.title)

        md.authors = [normalize(author) for author in mi.authors]

        if mi.publisher:
            md.publisher = normalize(mi.publisher)

        if mi.pubdate and not is_date_undefined(mi.pubdate):
            md.issue_date = str(isoformat(mi.pubdate)[:10])

        if mi.comments:
            # Strip user annotations
            a_offset = mi.comments.find('<div class="user_annotations">')
            ad_offset = mi.comments.find('<hr class="annotations_divider" />')

            if a_offset >= 0:
                mi.comments = mi.comments[:a_offset]
            if ad_offset >= 0:
                mi.comments = mi.comments[:ad_offset]

            md.description = normalize(mi.comments)

        if not mi.is_null('language'):
            lang = canonicalize_lang(mi.language)
            lang = lang_as_iso639_1(lang) or lang
            if lang:
                md.language = normalize(lang)

        if mi.cover_data[1]:
            md.cover_image_data = mi.cover_data
        elif mi.cover:
            md.cover_image_data = ("jpg", open(mi.cover, 'rb').read())

        if not tweaks.get("kfx_output_ignore_asin_metadata", False):
            value = mi.identifiers.get("mobi-asin")
            if value is not None and re.match(ASIN_RE, value):
                md.asin = value
            else:
                for ident, value in mi.identifiers.items():
                    if ident.startswith("amazon") and re.match(ASIN_RE, value):
                        md.asin = value
                        break
                else:
                    value = mi.identifiers.get("asin")
                    if value is not None and re.match(ASIN_RE, value):
                        md.asin = value

        if md.asin:
            md.cde_content_type = "EBOK"

        if prefs.get("approximate_pages", False):
            page_count = 0
            number_of_pages_field = prefs.get("number_of_pages_field", AUTO_PAGES)
            if number_of_pages_field and number_of_pages_field != AUTO_PAGES:
                number_of_pages = mi.get(number_of_pages_field, "")
                try:
                    page_count = int(number_of_pages)
                except Exception:
                    pass
        else:
            page_count = -1

        book = YJ_Book(stream, log)
        book.decode_book(set_metadata=md, set_approximate_pages=page_count)
        new_data = book.convert_to_single_kfx()
        set_logger()

        stream.seek(0)
        stream.truncate()
        stream.write(new_data)
        stream.seek(0)
