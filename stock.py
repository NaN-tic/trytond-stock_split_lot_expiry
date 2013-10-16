# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from datetime import date

from trytond.model import ModelView
from trytond.pyson import Equal, Eval, Not
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction

__all__ = ['Move', 'ShipmentOut']
__metaclass__ = PoolMeta


class Move:
    __name__ = 'stock.move'

    @classmethod
    def __setup__(cls):
        super(Move, cls).__setup__()
        cls._error_messages.update({
            'invalid_split_by_expiry_date': 'You are trying to split the '
                'Stock Move "%s" by Expiry Dates but it is in a invalid state '
                '(Assigned, Done or Cancelled) or it already has a Lot.',
            })
        cls._buttons.update({
                'split_by_expiry_date': {
                    'invisible': Eval('state').in_(
                        ['cancel', 'assigned' 'done']),
                    },
                })

    @classmethod
    @ModelView.button
    def split_by_expiry_date(cls, moves):
        for move in moves:
            move._split_by_expiry_date()

    def _split_by_expiry_date(self):
        pool = Pool()
        Lot = pool.get('stock.lot')
        Uom = pool.get('product.uom')

        if self.state in ('done', 'cancel', 'assigned') or self.lot:
            self.raise_user_error('invalid_split_by_expiry_date',
                (self.rec_name,))

        date_end = self.effective_date or self.planned_date or date.today()
        search_context = {
            'locations': [self.from_location.id],
            'stock_date_end': date_end,
            'forecast': False,
            }
        lots_and_qty = []
        with Transaction().set_context(search_context):
            lots = Lot.search([
                    ('product', '=', self.product.id),
                    ('expiry_date', '>', date_end),
                    ('quantity', '>', 0.0),
                    ], order=[('expiry_date', 'ASC')])
            for lot in lots:
                lots_and_qty.append((lot, lot.quantity))

        moves = [self]
        if not lots_and_qty:
            return moves

        state = self.state
        self.write([self], {
                'state': 'draft',
                })

        remainder = self.internal_quantity
        current_lot, current_lot_qty = lots_and_qty.pop(0)
        if current_lot_qty >= remainder:
            quantity = Uom.compute_qty(self.product.default_uom, remainder,
                self.uom)
            self.write(moves, {
                    'lot': current_lot.id,
                    'quantity': quantity,
                    'state': state,
                    })
            return moves

        quantity = Uom.compute_qty(self.product.default_uom,
            current_lot_qty, self.uom)
        self.write(moves, {
                'lot': current_lot.id,
                'quantity': quantity,
                })
        remainder -= current_lot_qty

        while remainder > 0.0 and lots_and_qty:
            current_lot, current_lot_qty = lots_and_qty.pop(0)
            quantity = min(current_lot_qty, remainder)
            moves.extend(self.copy([self], {
                        'lot': current_lot.id,
                        'quantity': Uom.compute_qty(self.product.default_uom,
                            quantity, self.uom),
                        }))
            remainder -= quantity
        if remainder > 0.0:
            moves.extend(self.copy([self], {
                        'lot': current_lot.id,
                        'quantity': Uom.compute_qty(self.product.default_uom,
                            remainder, self.uom),
                        }))

        self.write(moves, {
                'state': state,
                })
        self.assign_try(moves, grouping=('product', 'lot'))
        return moves


class ShipmentOut:
    __name__ = 'stock.shipment.out'

    @classmethod
    def __setup__(cls):
        super(ShipmentOut, cls).__setup__()
        cls._buttons.update({
                'split_moves_by_expiry_date': {
                    'invisible': Not(Equal(Eval('state', ''), 'waiting')),
                    },
                })

    @classmethod
    @ModelView.button
    def split_moves_by_expiry_date(cls, shipments):
        for shipment in shipments:
            for move in shipment.inventory_moves:
                if (not move.lot and
                        move.state not in ('cancel', 'assigned', 'done')):
                    move._split_by_expiry_date()
