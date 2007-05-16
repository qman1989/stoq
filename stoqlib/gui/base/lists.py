# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2005-2007 Async Open Source
##
## This program is free software; you can redistribute it and/or
## modify it under the terms of the GNU Lesser General Public License
## as published by the Free Software Foundation; either version 2
## of the License, or (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU Lesser General Public License for more details.
##
## You should have received a copy of the GNU Lesser General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., or visit: http://www.gnu.org/.
##
##
##  Author(s): Evandro Vale Miquelito   <evandro@async.com.br>
##             Johan Dahlin             <jdahlin@async.com.br>
##
""" List management for common dialogs.  """

import gtk
from kiwi.ui.delegates import GladeSlaveDelegate
from kiwi.ui.objectlist import ObjectList
from kiwi.ui.listdialog import ListDialog
from kiwi.utils import gsignal

from stoqlib.database.runtime import new_transaction, finish_transaction
from stoqlib.domain.interfaces import IDescribable
from stoqlib.exceptions import SelectionError, StoqlibError
from stoqlib.gui.base.dialogs import (run_dialog, BasicPluggableDialog,
                                      BasicDialog)
from stoqlib.gui.base.wizards import BaseWizard
from stoqlib.gui.editors.baseeditor import BaseEditor
from stoqlib.lib.translation import stoqlib_gettext
from stoqlib.lib.message import yesno

_ = stoqlib_gettext

class ModelListDialog(ListDialog):
    """
    A dialog which displays all items in a table and allows you to
    add and remove items from it

    @cvar model_type: an SQLObject for the table we want to modify, must
      implement the IDescribable interface.
    @cvar columns: a list of L{kiwi.ui.objectlist.Columns}
    @cvar editor_class: class used to edit the model, must take the
      constructor arguments (conn, model)
    @cvar size: a two sized tuple;  (width, height) or None
    @cvar title: window title
    """
    model_type = None
    columns = None
    editor_class = None
    size = None
    title = None

    def __init__(self, conn):
        """
        @param conn: A database connection
        """
        self.conn = conn
        if self.model_type is None:
            raise TypeError("%s must define a model_type class attribute" %
                            type(self).__name__)
        if not IDescribable.implementedBy(self.model_type):
            raise TypeError("%s must provide the IDescribable interface" %
                            self.model_type.__name__)

        ListDialog.__init__(self)
        if self.size:
            self.set_size_request(*self.size)
        if self.title:
            self.set_title(self.title)

    def _delete_model(self, model):
        trans = new_transaction()
        self.model_type.delete(model.id, connection=trans)
        trans.commit(close=True)

    def _prepare_run_editor(self, item):
        # 1) Create a new transaction
        # 2) Fetch the model from that transactions POW
        # 3) Sent it to the editor and run the editor
        # 4) If the return value is not None fetch it in the
        #    original connection (eg, self.conn)
        # 5) Return the value, so it can be populated by the list
        trans = new_transaction()
        if item is not None:
            model = trans.get(item)
        else:
            model = None
        retval = self.run_editor(trans, model)
        finish_transaction(trans, retval)
        if retval:
            retval = self.model_type.get(retval.id, connection=self.conn)
        trans.close()
        return retval

    #
    # ListDialog
    #

    def populate(self):
        return self.model_type.select(connection=self.conn)

    def add_item(self):
        return self._prepare_run_editor(None)

    def remove_item(self, constant):
        retval = self.default_remove(IDescribable(constant).get_description())
        if retval:
            # Remove the list before deleting it because it'll be late
            # afterwards, the object is invalid and SQLObject will complain
            self.remove_list_item(constant)
            self._delete_model(constant)
        return False

    def edit_item(self, item):
        return bool(self._prepare_run_editor(item))

    #
    # Hooks
    #

    def run_editor(self, trans, model):
        """
        This can be override by a subclass who wants to send in
        custom arguments to the editor.
        """
        if self.editor_class is None:
            raise ValueError("editor_class cannot be None in %s" % (
                type(self).__name__))

        return run_dialog(
            self.editor_class, parent=self,
            conn=trans, model=model)

class AdditionListSlave(GladeSlaveDelegate):
    """
    A slave that offers a simple list and its management.
    """

    toplevel_name = gladefile = 'AdditionListSlave'
    widgets = ('add_button',
               'delete_button',
               'klist',
               'list_vbox',
               'edit_button')
    gsignal('on-edit-item', object)
    gsignal('on-add-item', object)
    gsignal('before-delete-items', object)
    gsignal('after-delete-items')

    def __init__(self, conn, columns=None, editor_class=None,
                 klist_objects=None, visual_mode=False):
        """
        @param conn:          a connection
        @param columns:       column definitions
        @type columns:        sequence of L{kiwi.ui.widgets.list.Columns}
        @param editor_class:  the window that is going to be open when user
                              clicks on add_button or edit_button.
        @type: editor_class:  a L{stoqlib.gui.editors.BaseEditor} subclass
        @param klist_objects: initial objects to insert into the list
        """
        GladeSlaveDelegate.__init__(self, gladefile=self.gladefile)
        self._columns = columns or self.get_columns()
        if not self._columns:
            raise StoqlibError("columns must be specified")
        self.visual_mode = visual_mode
        self.conn = conn
        self.set_editor(editor_class)
        self._editor_kwargs = dict()
        self._can_edit = True
        if self.visual_mode:
            self.hide_add_button()
            self.hide_edit_button()
            self.hide_del_button()
        items = klist_objects or self.get_items()
        self._setup_klist(items)
        self._update_sensitivity()

    def _setup_klist(self, klist_objects):
        self.klist.set_columns(self._columns)
        self.klist.set_selection_mode(gtk.SELECTION_MULTIPLE)
        self.klist.add_list(klist_objects)

    def _update_sensitivity(self, *args):
        if self.visual_mode:
            return
        can_delete = _can_edit = True
        objs = self.get_selection()
        if not objs:
            _can_edit = can_delete = False
        elif len(objs) > 1:
            _can_edit = False

        self.add_button.set_sensitive(True)
        self.edit_button.set_sensitive(_can_edit)
        self.delete_button.set_sensitive(can_delete)

    def _edit_model(self, model=None):
        # Here we need manage objects persistence by our own
        # hands using clone.
        edit_mode = model
        if model:
            # XXX: get_clone() doesn't works with objects that inherits
            # from InheritableModelAdapter or InheritableModel.
            # Bug #2633 will fix that.
            clone = model.clone()
        else:
            clone = None

        result = self.run_editor(clone)

        if result:
            if edit_mode:
                # XXX self.klist.replace()?
                item_idx = self.klist.index(model)
                self.klist[item_idx] = clone
                self.delete_model(model)
                return
        else:
            if edit_mode:
                self.delete_model(clone)
            return

        if edit_mode and model in self.klist:
            self.emit('on-edit-item', result)
            self.klist.update(result)
        else:
            self.klist.append(result)
            # Emit the signal after we added the item to the list to be able to
            # check the length of the list in our validation callbacks.
            self.emit('on-add-item', result)

        # As we have a selection extended mode for kiwi list, we
        # need to unselect everything before select the new instance.
        self.klist.unselect_all()
        self.klist.select(result)
        self._update_sensitivity()

    def _edit(self):
        if not self._can_edit:
            return
        objs = self.get_selection()
        qty = len(objs)
        if qty != 1:
            raise SelectionError(
                ("Please select only one item before choosing Edit."
                   "\nThere are currently %d items selected") % qty)
        self._edit_model(objs[0])

    def _clear(self):
        objs = self.get_selection()
        qty = len(objs)
        if qty < 1:
            raise SelectionError('There are no objects selected')

        if qty > 1:
            msg = _(u'Delete these %d items?') % qty
        else:
            msg = _(u'Delete this item?')
        if yesno(msg, gtk.RESPONSE_NO, _(u"Cancel"), _(u"Delete items")):
            return
        self.emit('before-delete-items', objs)
        if qty == len(self.klist):
            self.klist.clear()
        else:
            for obj in objs:
                self.klist.remove(obj)
        self.klist.unselect_all()
        self._update_sensitivity()
        self.emit('after-delete-items')

    #
    # Hooks
    #

    def get_items(self):
        return []

    def get_columns(self):
        raise NotImplementedError("get_columns must be implemented in "
                                  "subclasses")

    def run_editor(self, model):
        """
        This can be overriden to provide a custom run_dialog line,
        or a conversion function for the model
        """
        if self._editor_class is None:
            raise TypeError(
                "%s cannot create or edit items without the editor_class "
                "argument set" % (self.__class__.__name__))

        return run_dialog(self._editor_class, None, conn=self.conn,
                          model=model, **self._editor_kwargs)

    def delete_model(self, model):
        """
        Deletes a model, can be overridden in subclass
        @param model: model to delete
        """
        model.__class__.delete(model.id, connection=self.conn)

    #
    # Public API
    #

    def register_editor_kwargs(self, **kwargs):
        self._editor_kwargs = kwargs

    def get_selection(self):
        # XXX: add get_selected_rows and raise exceptions if not in the
        #      right mode
        if self.klist.get_selection_mode() == gtk.SELECTION_MULTIPLE:
            return self.klist.get_selected_rows()
        selection = self.klist.get_selected()
        if not selection:
            return []
        return [selection]

    def hide_add_button(self):
        self.add_button.hide()

    def hide_edit_button(self):
        self._can_edit = False
        self.edit_button.hide()

    def hide_del_button(self):
        self.delete_button.hide()

    def set_editor(self, editor_class):
        if editor_class and not issubclass(editor_class,
                                           (BaseEditor, BaseWizard)):
            raise TypeError("editor_class must be a BaseEditor subclass")
        self._editor_class = editor_class

    #
    # Signal handlers
    #

    def on_klist__double_click(self, *args):
        self._edit()

    def on_klist__selection_changed(self, *args):
        self._update_sensitivity()

    def on_add_button__clicked(self, button):
        self._edit_model()

    def on_edit_button__clicked(self, button):
        self._edit()

    def on_delete_button__clicked(self, button):
        self._clear()


class AdditionListDialog(BasicPluggableDialog):
    size = (500, 500)

    def __init__(self, conn, editor_class=None, columns=None,
                 klist_objects=None, title='', visual_mode=False):
        self.title = title
        BasicPluggableDialog.__init__(self)
        self.addition_list = None
        self.conn = conn
        self.visual_mode = visual_mode
        self._initialize(editor_class, columns, klist_objects)

    def get_slave(self, editor_class, columns, klist_objects):
        return AdditionListSlave(self.conn, columns,
                                 editor_class, klist_objects,
                                 visual_mode=self.visual_mode)

    def _initialize(self, editor_class, columns, klist_objects):
        self.addition_list = self.get_slave(editor_class, columns,
                                            klist_objects)
        self.addition_list.on_confirm = self.on_confirm
        self.addition_list.on_cancel = self.on_cancel
        self.addition_list.validate_confirm = self.validate_confirm
        hide_footer = self.visual_mode
        BasicPluggableDialog._initialize(self, self.addition_list,
                                         size=self.size, title=self.title,
                                         hide_footer=hide_footer)

    def register_editor_kwargs(self, **kwargs):
        self.addition_list.register_editor_kwargs(**kwargs)

    def set_before_delete_items(self, callback):
        self.addition_list.connect('before-delete-items', callback)

    def set_on_add_item(self, callback):
        self.addition_list.connect('on-add-item', callback)

    def set_on_edit_item(self, callback):
        self.addition_list.connect('on-edit-item', callback)

    #
    # BasicPluggableDialog callbacks
    #

    def on_cancel(self):
        return

    def on_confirm(self):
        return self.addition_list.klist

    def validate_confirm(self):
        return True


class SimpleListDialog(BasicDialog):
    size = (500, 400)

    def __init__(self, columns, objects, hide_cancel_btn=True,
                 title='', multiple=True):
        """
        @param columns:
        @param objects:
        @param hide_cancel_btn:
        @param title:
        @param multiple: if we're allowed to select multiple items
        @type multiple: boolean
        """

        BasicDialog.__init__(self)
        BasicDialog._initialize(self, size=self.size, title=title)
        if hide_cancel_btn:
            self.cancel_button.hide()

        if multiple:
            selection_mode = gtk.SELECTION_MULTIPLE
        else:
            selection_mode = gtk.SELECTION_BROWSE
        self.setup_slave(columns, objects, selection_mode)

    def setup_slave(self, columns, objects, selection_mode):
        self.main.remove(self.main_label)
        self._klist = ObjectList(columns, objects, selection_mode)
        self.main.add(self._klist)
        self._klist.show()

    def get_selection(self):
        mode = self._klist.get_selection_mode()
        if mode == gtk.SELECTION_MULTIPLE:
            return self._klist.get_selected_rows()
        selection = self._klist.get_selected()
        if not selection:
            return []
        return [selection]

    # BasicDialog 'confirm' method override
    def confirm(self):
        self.retval = self.get_selection()
        self.close()
