# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2013 Async Open Source <http://www.async.com.br>
## All rights reserved
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU Lesser General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
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
## Author(s): Stoq Team <stoq-devel@async.com.br>
##

import decimal

import gtk
from kiwi.datatypes import ValidationError
from kiwi.ui.objectlist import Column
from storm.expr import Join

from stoqlib.api import api
from stoqlib.domain.inventory import Inventory, InventoryItem
from stoqlib.domain.product import Product, Storable, StorableBatch
from stoqlib.domain.sellable import Sellable
from stoqlib.gui.base.dialogs import run_dialog
from stoqlib.gui.base.wizards import BaseWizard, BaseWizardStep
from stoqlib.gui.dialogs.batchselectiondialog import (BatchSelectionDialog,
                                                      BatchItem)
from stoqlib.gui.wizards.abstractwizard import SellableItemStep
from stoqlib.lib.defaults import MAX_INT
from stoqlib.lib.formatters import format_quantity
from stoqlib.lib.translation import stoqlib_gettext as _


class _TemporaryInventoryItem(object):
    def __init__(self, sellable, storable, quantity, batch_number=None):
        self.sellable = sellable
        self.code = sellable.code
        self.description = sellable.description
        self.category_description = sellable.get_category_description()
        self.storable = storable
        self.is_batch = self.storable.is_batch
        self.batches = []
        self.changed = False
        if batch_number is not None:
            self.add_or_update_batch(batch_number, quantity)
        elif not self.is_batch:
            self.quantity = quantity

    def _get_quantity(self):
        if self.is_batch:
            return sum(item.quantity for item in self.batches)
        return self._quantity

    def _set_quantity(self, quantity):
        assert not self.is_batch
        self._quantity = quantity

    quantity = property(_get_quantity, _set_quantity)

    #
    #  Public API
    #

    def add_or_update_batch(self, batch_number, quantity):
        assert self.is_batch
        for item in self.batches:
            if item.batch == batch_number:
                # FIXME: namedtuple doesn't accept data to be changed, so we
                # will remove the item and add another one at the same position
                # This would't be necessary if we could use OrderedDict here
                # (or ideally, if BatchItem was an OrderedDict) but for
                # that we need to raise our python requirement to 2.7
                index = self.batches.index(item)
                self.batches.remove(item)
                # And sum the quantity to mimic the update
                quantity += item.quantity
                break
        else:
            index = len(self.batches)

        self.batches.insert(
            index, BatchItem(batch=batch_number, quantity=quantity))


class _InventoryBatchSelectionDialog(BatchSelectionDialog):
    show_existing_batches_list = False
    confirm_dialog_on_entry_activate = True
    allow_no_quantity = True

    #
    #  BatchSelectionDialog
    #

    def validate_entry(self, entry):
        # FIXME: For now we are not allowing not registered batches to be
        # counted. That makes sense though, but we should find a way to
        # validate the batch properly (since storable/batch_number should
        # be unique)
        batch_number = unicode(entry.get_text())
        if not batch_number:
            return

        if self.store.find(StorableBatch, batch_number=batch_number).is_empty():
            return ValidationError(
                _("The batch '%s' does not exist") % (batch_number,))


class InventoryCountTypeStep(BaseWizardStep):
    """Step responsible for defining the type of the count

    A simple step that will present 2 radiobutton options for
    the user to choose between an assisted count and a manual count.

    """

    gladefile = 'InventoryCountTypeStep'

    #
    #  WizardEditorStep
    #

    def next_step(self):
        self.wizard.temporary_items.clear()
        return InventoryCountItemStep(self.wizard, self,
                                      self.store, self.wizard.model)

    #
    #  Callbacks
    #

    def on_manual_count__toggled(self, radio):
        self.wizard.manual_count = radio.get_active()


class InventoryCountItemStep(SellableItemStep):
    """Step responsible for the real products counting

    This step will behave different, depending on the
    :class:`InventoryCountTypeStep`'s choice. For example:

        * If we choose to do a manual counting, all items will be populated
          and the user will be able to inform the quantity of each one

        * If we choose to do an assisted counting, no items will be populated
          (with the exception of the ones already counted before) and the user
          will be able to add items as it scans the barcode.

    Note that on the assisted count, pressing enter on the barcode will
    add the item on the list and not focus the quantity entry. That's
    done to make it easier for counting items using a barcode scanner.

    """

    model_type = Inventory
    item_table = _TemporaryInventoryItem
    summary_label_text = "<b>%s</b>" % api.escape(_('Total quantity:'))
    summary_label_column = 'quantity'
    sellable_editable = False
    stock_labels_visible = False
    batch_selection_dialog = _InventoryBatchSelectionDialog
    add_sellable_on_barcode_activate = True

    #
    #  SellableItemStep
    #

    def post_init(self):
        super(InventoryCountItemStep, self).post_init()

        # We use this to check if the sellable the user is trying to add
        # really is on the inventory
        #self._inventory_sellables = set(i.product.sellable for i in
        #                                self.model.get_items())
        store = self.model.store
        tables = [InventoryItem,
                  Join(Product, Product.id == InventoryItem.product_id),
                  Join(Sellable, Sellable.id == Product.sellable_id),
                  ]
        data = store.using(*tables).find(Sellable, InventoryItem.inventory_id == self.model.id)
        self._inventory_sellables = set(data)

        self.proxy.remove_widget('cost')
        self.cost.hide()
        self.cost_label.hide()
        self.hide_add_button()
        self.hide_edit_button()
        self.hide_del_button()
        if self.wizard.manual_count:
            self.hide_item_addition_toolbar()

        self.slave.klist.set_selection_mode(gtk.SELECTION_SINGLE)
        self.slave.klist.connect('cell-edited', self._on_klist__cell_edited)
        self.slave.klist.connect('row-activated', self._on_klist__row_activated)
        self.slave.klist.set_cell_data_func(self._on_klist__cell_data_func)

        self.force_validation()

    def get_order_item(self, sellable, cost, quantity, batch=None):
        if sellable not in self._inventory_sellables:
            return

        item = self.wizard.temporary_items.get(sellable, None)
        # We populated all items on get_saved_items, so this should not be None
        assert item is not None

        if batch is not None:
            assert isinstance(batch, basestring)
            item.add_or_update_batch(batch, quantity)
        else:
            item.quantity += quantity

        item.changed = True
        return item

    def get_saved_items(self):
        store = self.model.store
        tables = [InventoryItem,
                  Join(Product, Product.id == InventoryItem.product_id),
                  Join(Storable, Product.id == Storable.product_id),
                  Join(Sellable, Sellable.id == Product.sellable_id),
                  ]
        data = store.using(*tables).find((InventoryItem, Sellable, Product, Storable),
                                   InventoryItem.inventory_id == self.model.id)
        for item, sellable, product, storable in data:
            if (sellable in self.wizard.temporary_items and
                item.batch and item.counted_quantity is not None):
                tmp_item = self.wizard.temporary_items[sellable]
                tmp_item.add_or_update_batch(item.batch.batch_number,
                                             item.counted_quantity or 0)
                tmp_item.changed = (tmp_item.changed and
                                    item.counted_quantity is not None)
            elif sellable in self.wizard.temporary_items:
                continue
            else:
                tmp_item = _TemporaryInventoryItem(sellable, storable,
                                                   item.counted_quantity or 0)
                tmp_item.changed = item.counted_quantity is not None
                self.wizard.temporary_items[sellable] = tmp_item

            yield tmp_item

    def get_batch_items(self):
        return []

    def get_batch_order_items(self, sellable, value, quantity):
        if sellable not in self._inventory_sellables:
            return []

        storable = sellable.product.storable
        available_batches = list(
            storable.get_available_batches(self.model.branch))
        # The trivial case, where there's just one batch, we count it directly
        if len(available_batches) == 1:
            batch = available_batches[0]
            # Pass the batch number since it's what what this step is expecting
            return [self.get_order_item(sellable, value,
                                        quantity=quantity,
                                        batch=batch.batch_number)]

        return super(InventoryCountItemStep, self).get_batch_order_items(
            sellable, value, quantity)

    def get_columns(self):
        adjustment = gtk.Adjustment(lower=0, upper=MAX_INT,
                                    step_incr=1, page_incr=10)
        return [
            Column('code', title=_('Code'), data_type=str, sorted=True),
            Column('description', title=_('Description'),
                   data_type=str, expand=True),
            Column('category_description', title=_('Category'), data_type=str),
            Column('quantity', title=_('Quantity'), data_type=decimal.Decimal,
                   editable=True, spin_adjustment=adjustment,
                   format_func=self._format_quantity, format_func_data=True),
        ]

    def has_next_step(self):
        return False

    def validate(self, value):
        super(InventoryCountItemStep, self).validate(value)

        # FIXME: Maybe we should not require all to be changed if
        # we are doing an assisted count
        #self.wizard.refresh_next(value and
        #                         all(i.changed for i in self.slave.klist))

    #
    #  Private
    #

    def _update_view(self):
        self.summary.update_total()
        self.force_validation()

    def _format_quantity(self, item, data):
        # FIXME: Why is this item sometimes None? It shouldn't ever be!
        if item is None:
            return ''
        if not item.changed:
            return ''
        return format_quantity(item.quantity)

    #
    #  Callbacks
    #

    def _on_klist__cell_data_func(self, column, renderer, item, text):
        if column.attribute == 'quantity':
            renderer.set_property('editable-set', not item.is_batch)
            renderer.set_property('editable', not item.is_batch)

        return text

    def _on_klist__row_activated(self, storables, item):
        if item.is_batch:
            retval = run_dialog(_InventoryBatchSelectionDialog, self.wizard,
                                store=self.store, model=item.storable,
                                quantity=0, original_batches=item.batches)
            item.batches = retval or item.batches
            item.changed = item.changed or bool(retval)
            self.slave.klist.update(item)
            self._update_view()

    def _on_klist__cell_edited(self, klist, item, attr):
        if attr == 'quantity':
            item.changed = True

        self._update_view()

        # FIXME: This event is being emitted twice making it to jump
        # 2 rows below the current one. Remove this workaround when solving it
        if item != klist.get_selected():
            return

        treeview = klist.get_treeview()
        rows, column = treeview.get_cursor()
        next_row = rows[0] + 1
        if next_row < len(klist):
            treeview.set_cursor(next_row, column)
        else:
            self.wizard.next_button.grab_focus()


class InventoryCountWizard(BaseWizard):
    """A wizard for counting items on an |inventory|"""

    size = (800, 450)
    title = _('Inventory product counting')
    help_section = 'inventory-count'

    def __init__(self, store, model):
        self.temporary_items = {}
        self.manual_count = True

        first_step = InventoryCountTypeStep(store, self, previous=None)
        BaseWizard.__init__(self, store, first_step, model)

    #
    #  BaseWizard
    #

    def finish(self):
        self._update_items()

        self.retval = self.model
        self.close()

    #
    #  Private
    #

    def _update_items(self):
        model_items = {}
        store = self.model.store
        tables = [InventoryItem,
                  Join(Product, Product.id == InventoryItem.product_id),
                  Join(Sellable, Sellable.id == Product.sellable_id),
                  ]
        data = store.using(*tables).find((InventoryItem, Sellable),
                                   InventoryItem.inventory_id == self.model.id)
        for item, sellable in data:
            batch_number = item.batch and item.batch.batch_number
            model_items[(sellable, batch_number)] = item

        for sellable, tmp_item in self.temporary_items.items():
            if tmp_item.is_batch:
                for batch_number, quantity in tmp_item.batches:
                    try:
                        # We will try to get the InventoryItem and update it
                        item = model_items.pop((sellable, batch_number))
                    except KeyError:
                        # If a KeyError happens, it means that we counted some
                        # quantity for a batch that wasn't registered on stoq
                        # yet, so add a new InventoryItem for it
                        item = self.model.add_sellable(
                            sellable, batch_number=batch_number)

                    item.counted_quantity = quantity
            else:
                item = model_items.pop((sellable, None))
                item.counted_quantity = tmp_item.quantity

        # Since we popped the items in here, those items not on the list are
        # considered to have 0 stock
        for sellable, item in model_items.items():
            # None means it wasn't counted
            item.counted_quantity = 0
