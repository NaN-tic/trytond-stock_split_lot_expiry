# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import ModelView, fields
from trytond.pyson import Eval, Not
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction

__all__ = ['Move', 'ShipmentOut']


class Move:
    __metaclass__ = PoolMeta
    __name__ = 'stock.move'

    allow_split_lot_expiry = fields.Function(fields.Boolean('Allow Split'),
        'get_allow_split_lot_expiry')

    @classmethod
    def __setup__(cls):
        super(Move, cls).__setup__()
        cls._error_messages.update({
            'invalid_split_by_lot_expiry': ('You are trying to split the '
                'Stock Move "%s" by Expiry Dates but it is in a invalid state '
                '(Assigned, Done or Cancelled) or it already has a Lot.'),
            })
        cls._buttons.update({
                'split_by_lot_expiry': {
                    'invisible': Not(Eval('allow_split_lot_expiry', False)),
                    },
                })

    def get_allow_split_lot_expiry(self, name):
        return (self.state not in ('cancel', 'assigned', 'done') and
            not self.lot
            and (not self.shipment
                or self.shipment.__name__ != 'stock.shipment.in'))

    @classmethod
    @ModelView.button
    def split_by_lot_expiry(cls, moves):
        for move in moves:
            move._split_by_lot_expiry()

    def _split_by_lot_expiry(self, assign=False):
        pool = Pool()
        Date = pool.get('ir.date')
        Lot = pool.get('stock.lot')
        Uom = pool.get('product.uom')

        if self.state != 'draft':
            return

        if not self.allow_split_lot_expiry:
            self.raise_user_error('invalid_split_by_lot_expiry',
                (self.rec_name,))

        if self.effective_date:
            shipment_date = self.effective_date
        elif self.planned_date and self.planned_date >= Date.today():
            shipment_date = self.planned_date
        else:
            shipment_date = Date.today()
        search_context = {
            'locations': [self.from_location.id],
            'stock_date_end': Date.today(),
            'stock_assign': True,
            'forecast': False,
            }
        lots_and_qty = []
        with Transaction().set_context(search_context):
            lots = Lot.search([
                    ('product', '=', self.product.id),
                    ('expiry_date', '>', shipment_date),
                    ('quantity', '>', 0.0),
                    ],
                order=[
                    ('expiry_date', 'ASC'),
                    ('number', 'ASC'),
                    ])
            for lot in lots:
                lots_and_qty.append((lot, lot.quantity))

        if lots_and_qty:

            remainder = self.internal_quantity
            current_lot, current_lot_qty = lots_and_qty.pop(0)
            if ((current_lot_qty - remainder) >=
                    -self.product.default_uom.rounding):
                # current_lot_qty >= remainder
                self.write([self], {
                        'lot': current_lot.id,
                        'quantity': Uom.compute_qty(self.product.default_uom,
                            remainder, self.uom),
                        })
                if assign:
                    self.assign_try([self], grouping=('product', 'lot'))
            elif current_lot_qty >= self.product.default_uom.rounding:
                self.write([self], {
                        'lot': current_lot.id,
                        'quantity': Uom.compute_qty(self.product.default_uom,
                            current_lot_qty, self.uom),
                        })
                remainder -= current_lot_qty

                to_assign = [self]
                while (remainder > self.product.default_uom.rounding
                        and lots_and_qty):
                    current_lot, current_lot_qty = lots_and_qty.pop(0)
                    quantity = min(current_lot_qty, remainder)
                    to_assign.extend(self.copy([self], {
                                'lot': current_lot.id,
                                'quantity': Uom.compute_qty(
                                    self.product.default_uom,
                                    quantity, self.uom),
                                }))
                    remainder -= quantity
                if remainder > self.product.default_uom.rounding:
                    self.copy([self], {
                            'lot': None,
                            'quantity': Uom.compute_qty(
                                self.product.default_uom, remainder, self.uom),
                            })
                if assign:
                    self.assign_try(to_assign, grouping=('product', 'lot'))


class ShipmentOut:
    __metaclass__ = PoolMeta
    __name__ = 'stock.shipment.out'

    @classmethod
    @ModelView.button
    def assign_try(cls, shipments):
        for shipment in shipments:
            for move in shipment.inventory_moves:
                lot_required = ('customer'
                        in [t.code for t in move.product.lot_required]
                    or move.product.lot_is_required(move.from_location,
                        move.to_location))
                if move.allow_split_lot_expiry and lot_required:
                    # Moves must to be assigned here to avoid select the same
                    # lot twice
                    move._split_by_lot_expiry(assign=True)
        return super(ShipmentOut, cls).assign_try(shipments)
