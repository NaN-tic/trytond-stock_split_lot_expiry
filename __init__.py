# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import stock


def register():
    Pool.register(
        stock.Move,
        stock.ShipmentOut,
        module='stock_split_lot_expiry', type_='model')
