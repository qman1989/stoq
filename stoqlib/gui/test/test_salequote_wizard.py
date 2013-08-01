# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2012 Async Open Source <http://www.async.com.br>
## All rights reserved
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., or visit: http://www.gnu.org/.
##
## Author(s): Stoq Team <stoq-devel@async.com.br>
##

import decimal

import mock
import gtk

from stoqlib.api import api
from stoqlib.domain.sale import Sale
from stoqlib.gui.dialogs.clientdetails import ClientDetailsDialog
from stoqlib.domain.payment.method import PaymentMethod
from stoqlib.domain.payment.payment import Payment
from stoqlib.gui.editors.noteeditor import NoteEditor
from stoqlib.gui.editors.personeditor import ClientEditor
from stoqlib.gui.test.uitestutils import GUITest
from stoqlib.gui.wizards.salequotewizard import SaleQuoteWizard, DiscountEditor
from stoqlib.lib.parameters import sysparam
from stoqlib.lib.translation import stoqlib_gettext

_ = stoqlib_gettext


class TestSaleQuoteWizard(GUITest):
    @mock.patch('stoqlib.gui.wizards.salequotewizard.yesno')
    @mock.patch('stoqlib.gui.wizards.salequotewizard.run_dialog')
    @mock.patch('stoqlib.gui.wizards.salequotewizard.run_person_role_dialog')
    def test_confirm(self, run_person_role_dialog, run_dialog, yesno):
        client = self.create_client()
        self.create_address(person=client.person)

        run_person_role_dialog.return_value = client
        yesno.return_value = False

        sellable = self.create_sellable()
        sellable.barcode = u'12345678'

        wizard = SaleQuoteWizard(self.store)

        step = wizard.get_current_step()

        self.click(step.create_client)
        self.assertEquals(run_person_role_dialog.call_count, 1)
        args, kwargs = run_person_role_dialog.call_args
        editor, parent, store, model = args
        self.assertEquals(editor, ClientEditor)
        self.assertEquals(parent, wizard)
        self.assertTrue(store is not None)
        self.assertTrue(model is None)

        self.click(step.client_details)
        self.assertEquals(run_dialog.call_count, 1)
        args, kwargs = run_dialog.call_args
        dialog, parent, store, model = args
        self.assertEquals(dialog, ClientDetailsDialog)
        self.assertEquals(parent, wizard)
        self.assertTrue(store is not None)
        self.assertEquals(model, client)
        self.click(step.notes_button)
        self.assertEquals(run_dialog.call_count, 2)
        args, kwargs = run_dialog.call_args
        editor, parent, store, model, notes = args
        self.assertEquals(editor, NoteEditor)
        self.assertEquals(parent, wizard)
        self.assertTrue(store is not None)
        self.assertEquals(set(wizard.model.comments), set([model]))
        self.assertEquals(notes, 'comment')
        self.assertEquals(kwargs['title'], _("Sale observations"))

        self.check_wizard(wizard, 'wizard-sale-quote-start-sale-quote-step')
        self.click(wizard.next_button)

        step = wizard.get_current_step()
        self.assertNotSensitive(wizard, ['next_button'])
        step.barcode.set_text(sellable.barcode)
        step.sellable_selected(sellable)
        step.quantity.update(2)

        # Make sure that we cannot add an item with a value greater than the allowed.
        sysparam(self.store).update_parameter(u'ALLOW_HIGHER_SALE_PRICE', False)
        step.cost.update(11)
        self.assertNotSensitive(step, ['add_sellable_button'])
        step.cost.update(10)
        self.assertSensitive(step, ['add_sellable_button'])

        self.click(step.add_sellable_button)
        self.assertSensitive(wizard, ['next_button'])
        sale = wizard.model
        self.check_wizard(wizard, 'wizard-sale-quote-sale-quote-item-step',
                          [sale, client] + list(sale.get_items()) + [sellable])

        module = 'stoqlib.gui.events.SaleQuoteWizardFinishEvent.emit'
        with mock.patch(module) as emit:
            self.click(wizard.next_button)
            self.assertEquals(emit.call_count, 1)
            args, kwargs = emit.call_args
            self.assertTrue(isinstance(args[0], Sale))

        self.assertEqual(wizard.model.payments.count(), 0)
        yesno.assert_called_once_with(_('Would you like to print the quote '
                                        'details now?'), gtk.RESPONSE_YES,
                                      _("Print quote details"), _("Don't print"))

    @mock.patch('stoqlib.gui.wizards.salequotewizard.run_dialog')
    def test_missing_items(self, run_dialog):
        from stoqlib.gui.base.lists import SimpleListDialog

        sellable = self.create_sellable(price=499, product=True)
        sellable.barcode = u'123'

        supplier = self.create_supplier()
        info = self.create_product_supplier_info(supplier, sellable.product)
        info.lead_time = 3  # days

        wizard = SaleQuoteWizard(self.store)

        # SaleQuoteItemStep
        self.click(wizard.next_button)
        step = wizard.get_current_step()
        step.barcode.set_text(u'123')
        step.quantity.update(1000)
        self.activate(step.barcode)
        self.click(step.add_sellable_button)

        self.check_wizard(wizard, 'wizard-sale-quote-missing-items')
        self.click(step.slave.message_details_button)
        self.assertEquals(run_dialog.call_count, 1)
        args, kwargs = run_dialog.call_args
        self.assertTrue(issubclass(args[0], SimpleListDialog))
        self.assertTrue(isinstance(args[1], gtk.Dialog))
        self.assertTrue(isinstance(args[2], list))
        self.assertTrue(isinstance(args[3], list))
        self.assertEquals(kwargs['title'], 'Missing products')

    @mock.patch('stoqlib.gui.wizards.salequotewizard.run_dialog')
    def test_apply_discount(self, run_dialog):
        sellable = self.create_sellable(price=100, product=True)
        sellable.barcode = u'123'

        wizard = SaleQuoteWizard(self.store)

        self.click(wizard.next_button)
        step = wizard.get_current_step()
        step.barcode.set_text(u'123')
        self.activate(step.barcode)
        self.click(step.add_sellable_button)

        label = step.summary.get_value_widget()
        self.assertEqual(label.get_text(), '$100.00')

        # 10% of discount
        step.model.set_items_discount(decimal.Decimal(10))
        run_dialog.return_value = True
        self.click(step.discount_btn)
        run_dialog.assert_called_once_with(
            DiscountEditor, step.parent, step.store, step.model,
            user=api.get_current_user(step.store))
        self.assertEqual(label.get_text(), '$90.00')

        # Cancelling the dialog this time
        run_dialog.reset_mock()
        run_dialog.return_value = None
        self.click(step.discount_btn)
        run_dialog.assert_called_once_with(
            DiscountEditor, step.parent, step.store, step.model,
            user=api.get_current_user(step.store))
        self.assertEqual(label.get_text(), '$90.00')

    def test_client_with_credit(self):
        method = PaymentMethod.get_by_name(self.store, u'credit')

        client_without_credit = self.create_client()

        client_with_credit = self.create_client()
        # Create a client and add some credit for it
        group = self.create_payment_group(payer=client_with_credit.person)
        payment = self.create_payment(payment_type=Payment.TYPE_OUT, value=10,
                                      method=method, group=group)
        payment.set_pending()
        payment.pay()

        wizard = SaleQuoteWizard(self.store)
        step = wizard.get_current_step()

        step.client.update(client_without_credit)
        self.check_wizard(wizard, 'wizard-salequote-client-without-credit')

        step.client.update(client_with_credit)
        self.check_wizard(wizard, 'wizard-salequote-client-with-credit')
