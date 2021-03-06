# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2005-2007 Async Open Source <http://www.async.com.br>
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
## GNU General Public License for more details.
##
## You should have received a copy of the GNU Lesser General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., or visit: http://www.gnu.org/.
##
## Author(s): Stoq Team <stoq-devel@async.com.br>
##
""" Test for lib/parameters module.  """

from decimal import Decimal

from stoqlib.lib.parameters import sysparam
from stoqlib.domain.address import CityLocation
from stoqlib.domain.person import (Branch, Client, Company, Employee,
                                   EmployeeRole, Individual, LoginUser,
                                   Person, SalesPerson, Supplier)
from stoqlib.domain.service import Service
from stoqlib.domain.profile import UserProfile
from stoqlib.domain.receiving import ReceivingOrder
from stoqlib.domain.sale import Sale
from stoqlib.domain.test.domaintest import DomainTest


class TestParameter(DomainTest):

    def _create_examples(self):
        person = Person(name=u'Jonas', store=self.store)
        Individual(person=person, store=self.store)
        role = EmployeeRole(store=self.store, name=u'desenvolvedor')
        Employee(person=person, store=self.store,
                 role=role)
        self.salesperson = SalesPerson(person=person,
                                       store=self.store)
        Company(person=person, store=self.store)
        client = Client(person=person, store=self.store)
        self.branch = Branch(person=person, store=self.store)

        group = self.create_payment_group()
        self.sale = Sale(coupon_id=123, client=client,
                         cfop=self.sparam.DEFAULT_SALES_CFOP,
                         group=group, branch=self.branch,
                         salesperson=self.salesperson,
                         store=self.store)

        self.storable = self.create_storable()

    def setUp(self):
        DomainTest.setUp(self)
        self.sparam = sysparam(self.store)

    # System instances based on stoq.lib.parameters

    def test_main_company(self):
        company = self.sparam.MAIN_COMPANY
        branchTable = Branch
        assert isinstance(company, branchTable)
        assert isinstance(company.person, Person)

    def test_default_employee_role(self):
        employee_role = self.sparam.DEFAULT_SALESPERSON_ROLE
        assert isinstance(employee_role, EmployeeRole)

    def test_suggested_supplier(self):
        supplier = self.sparam.SUGGESTED_SUPPLIER
        assert isinstance(supplier, Supplier)

    def test_delivery_service(self):
        service = self.sparam.DELIVERY_SERVICE
        assert isinstance(service, Service)

    # System constants based on stoq.lib.parameters

    def test_pos_full_screen(self):
        param = self.sparam.POS_FULL_SCREEN
        assert isinstance(param, bool)

    def test_pos_separate_cashier(self):
        param = self.sparam.POS_SEPARATE_CASHIER
        assert isinstance(param, bool)

    def test_location_suggested(self):
        location = CityLocation.get_default(self.store)
        self.assertEqual(location.city, self.sparam.CITY_SUGGESTED)
        self.assertEqual(location.state, self.sparam.STATE_SUGGESTED)
        self.assertEqual(location.country, self.sparam.COUNTRY_SUGGESTED)

    def test_has_delivery_mode(self):
        param = self.sparam.HAS_DELIVERY_MODE
        assert isinstance(param, int)

    def test_max_search_results(self):
        param = self.sparam.MAX_SEARCH_RESULTS
        assert isinstance(param, int)

    def test_confirm_sales_on_till(self):
        param = self.sparam.CONFIRM_SALES_ON_TILL
        assert isinstance(param, int)

    def test_accept_change_salesperson(self):
        param = self.sparam.ACCEPT_CHANGE_SALESPERSON
        assert isinstance(param, bool)

    def test_return_policy_on_sales(self):
        param = self.sparam.RETURN_POLICY_ON_SALES
        self.assertTrue(isinstance(param, int))
        self.assertEquals(param, 0)

    def test_ask_sale_c_f_o_p(self):
        param = self.sparam.ASK_SALES_CFOP
        assert isinstance(param, bool)

    def test_default_sales_c_f_o_p(self):
        self._create_examples()
        group = self.create_payment_group()
        sale = Sale(coupon_id=123, salesperson=self.salesperson,
                    branch=self.branch, group=group, store=self.store)
        self.assertEqual(sale.cfop, self.sparam.DEFAULT_SALES_CFOP)
        param = self.sparam.DEFAULT_RECEIVING_CFOP
        group = self.create_payment_group()
        sale = Sale(coupon_id=432, salesperson=self.salesperson,
                    branch=self.branch, group=group, cfop=param,
                    store=self.store)
        self.assertEquals(sale.cfop, param)

    def test_default_return_sales_c_f_o_p(self):
        from stoqlib.domain.fiscal import FiscalBookEntry
        self._create_examples()
        wrong_param = self.sparam.DEFAULT_SALES_CFOP
        drawee = Person(name=u'Antonione', store=self.store)
        group = self.create_payment_group()
        book_entry = FiscalBookEntry(
            entry_type=FiscalBookEntry.TYPE_SERVICE,
            invoice_number=123,
            cfop=wrong_param,
            branch=self.branch,
            drawee=drawee,
            payment_group=group,
            iss_value=1,
            icms_value=0,
            ipi_value=0,
            store=self.store)
        reversal = book_entry.reverse_entry(invoice_number=124)
        self.failIfEqual(wrong_param, reversal.cfop)
        self.assertEqual(self.sparam.DEFAULT_RETURN_SALES_CFOP,
                         reversal.cfop)

    def test_default_receiving_c_f_o_p(self):
        branch = self.create_branch()
        param = self.sparam.DEFAULT_RECEIVING_CFOP
        person = Person(name=u'Craudinho', store=self.store)
        Individual(person=person, store=self.store)
        profile = UserProfile(name=u'profile', store=self.store)
        responsible = LoginUser(person=person, store=self.store,
                                password=u'asdfgh', profile=profile,
                                username=u'craudio')
        purchase = self.create_purchase_order()
        receiving_order = ReceivingOrder(responsible=responsible,
                                         branch=branch,
                                         store=self.store,
                                         invoice_number=876,
                                         supplier=None,
                                         purchase=purchase)
        param2 = self.sparam.DEFAULT_SALES_CFOP
        receiving_order2 = ReceivingOrder(responsible=responsible,
                                          cfop=param2, branch=branch,
                                          store=self.store,
                                          invoice_number=1231,
                                          supplier=None,
                                          purchase=purchase)
        self.assertEqual(param, receiving_order.cfop)
        self.failIfEqual(param, receiving_order2.cfop)

    def test_icms_tax(self):
        param = self.sparam.ICMS_TAX
        assert isinstance(param, Decimal)

    def test_iss_tax(self):
        param = self.sparam.ISS_TAX
        assert isinstance(param, Decimal)

    def test_substitution_tax(self):
        param = self.sparam.SUBSTITUTION_TAX
        assert isinstance(param, Decimal)

    def test_default_area_code(self):
        param = self.sparam.DEFAULT_AREA_CODE
        self.failUnless(isinstance(param, int), type(param))
