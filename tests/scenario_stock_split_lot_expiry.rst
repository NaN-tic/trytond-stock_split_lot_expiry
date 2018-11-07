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
    >>> from trytond.tests.tools import activate_modules
    >>> from trytond.modules.company.tests.tools import create_company, \
    ...     get_company
    >>> today = datetime.date.today()

Install stock_split_lot_expiry::

    >>> config = activate_modules('stock_split_lot_expiry')

Create company::

    >>> _ = create_company()
    >>> company = get_company()
    >>> currency = company.currency

Create customer::

    >>> Party = Model.get('party.party')
    >>> customer = Party(name='Customer')
    >>> customer.save()

Get stock locations and set Allow Expired to Storage Location::

    >>> Location = Model.get('stock.location')
    >>> customer_loc, = Location.find([('code', '=', 'CUS')])
    >>> output_loc, = Location.find([('code', '=', 'OUT')])
    >>> storage_loc, = Location.find([('code', '=', 'STO')])

Get Stock Lot Type::

    >>> LotType = Model.get('stock.lot.type')
    >>> lot_types = LotType.find()

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
    >>> for lot_type in lot_types:
    ...     template.lot_required.append(lot_type)
    >>> template.save()
    >>> product.template = template
    >>> product.save()

Create four lots with different expiry dates (the first one is expired)::

    >>> Lot = Model.get('stock.lot')
    >>> lots = []
    >>> for i in range(1, 5):
    ...     lot = Lot(number='%05i' % i, product=product)
    ...     lot.expiration_date = today + relativedelta(days=((i - 1) * 10))
    ...     lot.save()
    ...     lots.append(lot)


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

    >>> ok = ShipmentOut.assign_try([shipment_out.id], config.context)
    >>> lot_moves = [m for m in shipment_out.inventory_moves
    ...     if m.lot]
    >>> len(lot_moves)
    3
    >>> all(m.quantity == 4 for m in lot_moves)
    True
    >>> without_lot, = [m for m in shipment_out.inventory_moves
    ...     if not m.lot]
    >>> without_lot.quantity == 3
    True

Execute the Split Moves by Expiry Date button and check all inventory moves are
assigned and sum the 11 units of shipment line::

    >>> without_lot.click('cancel')
    >>> StockMove.delete([without_lot])
    >>> shipment_out.reload()
    >>> len(shipment_out.inventory_moves)
    3
    >>> all(bool(m.lot) for m in shipment_out.inventory_moves)
    True
    >>> sum(m.quantity for m in shipment_out.inventory_moves)
    12.0

Check that lots are used priorizing what have the nearest Expiry Date, without
using the expired lots::

    >>> unused = config.set_context({'locations': [storage.id]})
    >>> lots = Lot.find([], order=[('expiration_date', 'ASC')])
    >>> [(l.number, l.quantity) for l in lots]
    [(u'00001', 4.0), (u'00002', 0.0), (u'00003', 0.0), (u'00004', 0.0)]
