#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import, print_function)

from PyQt5 import (QtCore, QtWidgets)
from calibre.gui2.convert import Widget


__license__ = "GPL v3"
__copyright__ = "2020, John Howell <jhowell@acm.org>"

AUTO_PAGES = "(auto)"           # fake name for automatic page number generation, instead of a lookup name

# the class name PluginWidget is required for calibre to access this properly


class PluginWidget(Widget):
    TITLE = "KFX Output"
    HELP = "Options specific to KFX output"
    ICON = I("mimetypes/kfx.png")
    COMMIT_NAME = "kfx_output"          # where option values are saved

    def __init__(self, parent, get_option, get_help, db=None, book_id=None):
        self.db = db                # db is set for conversion, but not default preferences
        self.book_id = book_id      # book_id is set for individual conversion, but not bulk

        Widget.__init__(self, parent, [
            "cde_type_pdoc", "show_kpr_logs", "approximate_pages", "number_of_pages_field",
            "enable_timeout"])

        self.initialize_options(get_option, get_help, db, book_id)

    def setupUi(self, Form):
        Form.setObjectName("Form")
        Form.setWindowTitle("Form")
        Form.resize(588, 481)

        self.formLayout = QtWidgets.QFormLayout(Form)
        self.formLayout.setObjectName("formLayout")

        self.opt_cde_type_pdoc = QtWidgets.QCheckBox(Form)
        self.opt_cde_type_pdoc.setObjectName("opt_cde_type_pdoc")
        self.opt_cde_type_pdoc.setText("Create personal document instead of book")
        self.formLayout.addRow(self.opt_cde_type_pdoc)

        self.opt_show_kpr_logs = QtWidgets.QCheckBox(Form)
        self.opt_show_kpr_logs.setObjectName("opt_show_kpr_logs")
        self.opt_show_kpr_logs.setText("Show full Kindle Previewer conversion logs")
        self.formLayout.addRow(self.opt_show_kpr_logs)

        self.opt_approximate_pages = QtWidgets.QCheckBox(Form)
        self.opt_approximate_pages.setObjectName("opt_approximate_pages")
        self.opt_approximate_pages.setText("Create approximate page numbers")
        self.opt_approximate_pages.stateChanged.connect(self.opt_approximate_pages_changed)
        self.formLayout.addRow(self.opt_approximate_pages)

        self.opt_number_of_pages_field = QtWidgets.QComboBox(Form)
        self.opt_number_of_pages_field.setObjectName("opt_number_of_pages_field")
        self.opt_number_of_pages_field.setEditable(True)

        labels = set()
        db = self.db

        if db is None:
            from calibre.gui2.ui import get_gui
            db = get_gui().current_db

        if db is not None:
            for l in db.custom_column_label_map:
                labels.add("#" + l)

        for cc in [AUTO_PAGES] + sorted(list(labels)):
            self.opt_number_of_pages_field.addItem(cc)

        self.opt_number_of_pages_field.setCurrentIndex(0)
        self.formLayout.addRow("               Lookup name of custom column with desired number of pages:", self.opt_number_of_pages_field)

        self.opt_enable_timeout = QtWidgets.QCheckBox(Form)
        self.opt_enable_timeout.setObjectName("opt_enable_timeout")
        self.opt_enable_timeout.setText("Enable conversion timeout")
        self.formLayout.addRow(self.opt_enable_timeout)

        self.formLayout.addItem(QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding))

        self.help_label = QtWidgets.QLabel(Form)
        self.help_label.setWordWrap(True)
        self.help_label.setOpenExternalLinks(True)
        self.help_label.setObjectName("help_label")
        self.help_label.setText(
            '<p>KFX Output plugin help is available at '
            '<a href="http://www.mobileread.com/forums/showthread.php?t=272407">'
            'http://www.mobileread.com/forums/showthread.php?t=272407</a>.</p>')
        self.formLayout.addRow(self.help_label)

        self.opt_approximate_pages_changed()
        QtCore.QMetaObject.connectSlotsByName(Form)

    def opt_approximate_pages_changed(self):
        self.opt_number_of_pages_field.setEnabled(self.opt_approximate_pages.isChecked())
