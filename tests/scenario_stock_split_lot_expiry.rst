===============================
Stock Split Lot Expiry Scenario
===============================

=============
General Setup
=============

Imports::

    >>> import datetime
    >>> from dateutil.relativedelta import relativedelta
    >>> from decimal import Decimal
    >>> from proteus import config, Model, Wizard
    >>> today = datetime.date.today()

Create database::

    >>> config = config.set_trytond()
    >>> config.pool.test = True

Install purchase_lot_cost::

    >>> Module = Model.get('ir.module.module')
    >>> modules = Module.find([
    ...         ('name', '=', 'stock_split_lot_expiry'),
    ...         ])
    >>> Module.install([x.id for x in modules], config.context)
    >>> Wizard('ir.module.module.install_upgrade').execute('upgrade')

Create company::

    >>> Currency = Model.get('currency.currency')
    >>> CurrencyRate = Model.get('currency.currency.rate')
    >>> Company = Model.get('company.company')
    >>> Party = Model.get('party.party')
    >>> company_config = Wizard('company.company.config')
    >>> company_config.execute('company')
    >>> company = company_config.form
    >>> party = Party(name='B2CK')
    >>> party.save()
    >>> company.party = party
    >>> currencies = Currency.find([('code', '=', 'EUR')])
    >>> if not currencies:
    ...     currency = Currency(name='Euro', symbol=u'€', code='EUR',
    ...         rounding=Decimal('0.01'), mon_grouping='[3, 3, 0]',
    ...         mon_decimal_point=',')
    ...     currency.save()
    ...     CurrencyRate(date=today + relativedelta(month=1, day=1),
    ...         rate=Decimal('1.0'), currency=currency).save()
    ... else:
    ...     currency, = currencies
    >>> company.currency = currency
    >>> company_config.execute('add')
    >>> company, = Company.find()

Reload the context::

    >>> User = Model.get('res.user')
    >>> config._context = User.get_preferences(True, config.context)

Create customer::

    >>> Party = Model.get('party.party')
    >>> customer = Party(name='Customer')
    >>> customer.save()

Create products::

    >>> ProductUom = Model.get('product.uom')
    >>> ProductTemplate = Model.get('product.template')
    >>> Product = Model.get('product.product')
    >>> unit, = ProductUom.find([('name', '=', 'Unit')])
    >>> product = Product()
    >>> template = ProductTemplate()
    >>> template.name = 'Product'
    >>> template.default_uom = unit
    >>> template.type = 'goods'
    >>> template.list_price = Decimal('20')
    >>> template.cost_price = Decimal('8')
    >>> template.save()
    >>> product.template = template
    >>> product.save()

Get stock locations and set Allow Expired to Storage Location::

    >>> Location = Model.get('stock.location')
    >>> customer_loc, = Location.find([('code', '=', 'CUS')])
    >>> output_loc, = Location.find([('code', '=', 'OUT')])
    >>> storage_loc, = Location.find([('code', '=', 'STO')])
    >>> storage_loc.allow_expired = True
    >>> storage_loc.save()

Create four lots with different expiry dates (one is expired)::

    >>> Lot = Model.get('stock.lot')
    >>> lots = []
    >>> for i in range(1, 5):
    ...     lot = Lot(number='%05i' % i,
    ...         product=product,
    ...         expiry_date=today + relativedelta(days=((i - 1) * 10)),
    ...         )
    ...     lot.save()
    ...     lots.append(lot)
    >>> not any(l.expired for l in lots[1:])
    True
    >>> lots[0].expired
    True

Create an Inventory to add 4 units of each lot in Storage Location::

    >>> Inventory = Model.get('stock.inventory')
    >>> InventoryLine = Model.get('stock.inventory.line')
    >>> storage, = Location.find([
    ...         ('code', '=', 'STO'),
    ...         ])
    >>> inventory = Inventory()
    >>> inventory.location = storage
    >>> for lot in lots:
    ...     inventory_line = InventoryLine()
    ...     inventory.lines.append(inventory_line)
    ...     inventory_line.product = product
    ...     inventory_line.lot = lot
    ...     inventory_line.quantity = 4
    >>> inventory.save()
    >>> Inventory.confirm([inventory.id], config.context)
    >>> inventory.state
    u'done'

Create Shipment Out of 15 units of Product and set to waiting::

    >>> ShipmentOut = Model.get('stock.shipment.out')
    >>> StockMove = Model.get('stock.move')
    >>> shipment_out = ShipmentOut()
    >>> shipment_out.planned_date = today
    >>> shipment_out.customer = customer
    >>> shipment_out.warehouse = storage_loc.parent
    >>> shipment_out.company = company
    >>> move = StockMove()
    >>> shipment_out.outgoing_moves.append(move)
    >>> move.product = product
    >>> move.uom = unit
    >>> move.quantity = 15
    >>> move.from_location = output_loc
    >>> move.to_location = customer_loc
    >>> move.company = company
    >>> move.unit_price = Decimal('1')
    >>> move.currency = currency
    >>> shipment_out.save()
    >>> ShipmentOut.wait([shipment_out.id], config.context)
    >>> shipment_out.reload()
    >>> shipment_out.state == 'waiting'
    True

Execute the Split Moves by Expiry Date button and check there is 3 Inventory
Moves assigned with lot and 4 units and another Inventory Move of 3 units
in Draft state::

    >>> ShipmentOut.split_moves_by_expiry_date([shipment_out.id],
    ...     config.context)
    >>> shipment_out.reload()
    >>> assigned_moves = [m for m in shipment_out.inventory_moves
    ...     if m.state == 'assigned']
    >>> len(assigned_moves)
    3
    >>> all(bool(m.lot) and m.quantity == 4 for m in assigned_moves)
    True
    >>> draft_moves = [m for m in shipment_out.inventory_moves
    ...     if m.state == 'draft']
    >>> len(draft_moves)
    1
    >>> draft_moves[0].quantity == 3
    True
    >>> ShipmentOut.assign_try([shipment_out.id], config.context)
    False

Cancel Shipment and set to Draft

    >>> ShipmentOut.cancel([shipment_out.id], config.context)
    >>> ShipmentOut.draft([shipment_out.id], config.context)
    >>> shipment_out.reload()
    >>> shipment_out.state == 'draft'
    True

Add a new shipment line of 11 units of product and set shipment to waiting::

    >>> move = StockMove()
    >>> shipment_out.outgoing_moves.append(move)
    >>> move.product = product
    >>> move.uom = unit
    >>> move.quantity = 11
    >>> move.from_location = output_loc
    >>> move.to_location = customer_loc
    >>> move.company = company
    >>> move.unit_price = Decimal('1')
    >>> move.currency = currency
    >>> shipment_out.save()
    >>> ShipmentOut.wait([shipment_out.id], config.context)
    >>> shipment_out.reload()
    >>> shipment_out.state == 'waiting'
    True

Execute the Split Moves by Expiry Date button and check all inventory moves are
assigned and sum the 11 units of shipment line::

    >>> ShipmentOut.split_moves_by_expiry_date([shipment_out.id],
    ...     config.context)
    >>> shipment_out.reload()
    >>> len(shipment_out.inventory_moves)
    3
    >>> all(bool(m.lot) for m in shipment_out.inventory_moves)
    True
    >>> sum(m.quantity for m in shipment_out.inventory_moves)
    11.0

Assign, pack and set done the shipment::

    >>> ShipmentOut.assign_try([shipment_out.id], config.context)
    True
    >>> ShipmentOut.pack([shipment_out.id], config.context)
    >>> ShipmentOut.done([shipment_out.id], config.context)
    >>> shipment_out.reload()
    >>> shipment_out.state == 'done'
    True

Check that lots are used priorizing what have the nearest Expiry Date, without
using the expired lots::

    >>> unused = config.set_context({'locations': [storage.id]})
    >>> lots = Lot.find([], order=[('expiry_date', 'ASC')])
    >>> [(l.number, l.expired, l.quantity) for l in lots]
    [(u'00001', True, 4.0), (u'00002', False, 0.0), (u'00003', False, 0.0), (u'00004', False, 1.0)]
