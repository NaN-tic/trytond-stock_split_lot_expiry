# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import ModelView, fields
from trytond.pyson import Eval, Not
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction
from trytond.i18n import gettext
from trytond.exceptions import UserError

__all__ = ['Move', 'ShipmentOut']


class Move(metaclass=PoolMeta):
    __name__ = 'stock.move'

    allow_split_lot_expiry = fields.Function(fields.Boolean('Allow Split'),
        'get_allow_split_lot_expiry')

    @classmethod
    def __setup__(cls):
        super(Move, cls).__setup__()
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
        cls._split_by_lot_expiry(moves)

    @classmethod
    def _split_by_lot_expiry(cls, moves, assign=False):
        pool = Pool()
        Date = pool.get('ir.date')
        Lot = pool.get('stock.lot')
        Uom = pool.get('product.uom')

        split_moves = [x for x in moves if x.state == 'draft']
        if not split_moves:
            return

        moves_grouped = {}
        for move in split_moves:
            if not move.allow_split_lot_expiry:
                raise UserError(gettext(
                    'stock_split_lot_expiry.invalid_split_by_lot_expiry',
                    move=move.rec_name))

            if move.effective_date:
                shipment_date = move.effective_date
            elif move.planned_date and move.planned_date >= Date.today():
                shipment_date = move.planned_date
            else:
                shipment_date = Date.today()
            key = (move.from_location.id, shipment_date)
            if key not in moves_grouped:
                moves_grouped[key] = []

            moves_grouped[key].append(move)

        if cls.lock_stock_move():
            Transaction().database.lock(Transaction().connection, cls._table)

        for key, moves in moves_grouped.items():
            moves = cls.browse(moves)
            location, shipment_date = key
            search_context = {
                'locations': [location],
                'stock_date_end': Date.today(),
                'stock_assign': True,
                'forecast': False,
                }

            to_assign = []
            to_write = []

            lots_and_qty = {}
            with Transaction().set_context(search_context):
                products = set(x.product.id for x in moves)
                lots = Lot.search([
                        ('product', 'in', list(products)),
                        ('expiration_date', '>', shipment_date),
                        ('quantity', '>', 0.0),
                        ],
                    order=[
                        ('product', 'ASC'),
                        ('expiration_date', 'ASC'),
                        ('number', 'ASC'),
                        ])
                for lot in lots:
                    if lot.product not in lots_and_qty:
                        lots_and_qty[lot.product] = []
                    lots_and_qty[lot.product].append((lot, lot.quantity))

            for move in moves:
                if move.product not in lots_and_qty:
                    continue
                if getattr(move, 'production_input', False):
                    for production_input in move.production_input.inputs:
                        if (production_input.product == move.product
                                and production_input.state == 'draft'
                                and production_input.lot):
                            new_lots_and_qty = []
                            for lot, quantity in lots_and_qty[move.product]:
                                if lot == production_input.lot:
                                    quantity -= production_input.quantity
                                    if quantity <= 0:
                                        continue
                                new_lots_and_qty.append((lot, quantity))
                            lots_and_qty[move.product] = new_lots_and_qty
                remainder = move.internal_quantity
                lots_and_qty_product = lots_and_qty[move.product]
                # can't split a move by lot-qty that is empty list
                if not lots_and_qty_product:
                    continue
                current_lot, current_lot_qty = lots_and_qty_product.pop(0)
                if ((current_lot_qty - remainder) >=
                        -move.product.default_uom.rounding):
                    # current_lot_qty >= remainder
                    move.lot = current_lot.id
                    move.quantity = Uom.compute_qty(move.product.default_uom,
                        remainder, move.uom)
                    to_write.append(move)
                    if assign:
                        to_assign.append(move)
                elif current_lot_qty >= move.product.default_uom.rounding:
                    move.lot = current_lot.id
                    move.quantity = Uom.compute_qty(move.product.default_uom,
                        current_lot_qty, move.uom)
                    remainder -= current_lot_qty
                    to_assign.append(move)
                    to_write.append(move)
                    while (remainder > move.product.default_uom.rounding
                            and lots_and_qty[move.product]):
                        current_lot, current_lot_qty = \
                            lots_and_qty[move.product].pop(0)
                        quantity = min(current_lot_qty, remainder)
                        to_assign.extend(cls.copy([move], {
                                    'lot': current_lot.id,
                                    'quantity': Uom.compute_qty(
                                        move.product.default_uom,
                                        quantity, move.uom),
                                    }))
                        remainder -= quantity
                    if remainder > move.product.default_uom.rounding:
                        cls.copy([move], {
                                'lot': None,
                                'quantity': Uom.compute_qty(
                                    move.product.default_uom, remainder,
                                    move.uom),
                                })
            if to_write:
                cls.save(to_write)
            if assign:
                cls.assign_try(to_assign, grouping=('product', 'lot'))


class ShipmentOut(metaclass=PoolMeta):
    __name__ = 'stock.shipment.out'

    @classmethod
    @ModelView.button
    def assign_try(cls, shipments):
        Move = Pool().get('stock.move')
        for shipment in shipments:
            to_split = []
            for move in shipment.inventory_moves:
                lot_required = ('customer'
                        in [t.code for t in move.product.lot_required]
                    or move.product.lot_is_required(move.from_location,
                        move.to_location))
                if move.allow_split_lot_expiry and lot_required:
                    # Moves must to be assigned here to avoid select the same
                    # lot twice
                    to_split.append(move)

            Move._split_by_lot_expiry(to_split, assign=True)
        return super(ShipmentOut, cls).assign_try(shipments)
