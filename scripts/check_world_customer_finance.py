"""Fresh-database acceptance: delivered knowledge -> intent -> settle -> return."""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utilsim.world import World  # noqa: E402
from utilsim.world import customer_finance as finance  # noqa: E402
from utilsim.world.store import stable  # noqa: E402


def main():
    with TemporaryDirectory(prefix='world-customer-finance-') as temporary:
        world = World(Path(temporary)/'world.sqlite')
        world.initialize({'schemaVersion': 'utility-town/2.0', 'id': 'finance-acceptance', 'seed': '42',
                          'premises': [{'id': 'P1', 'occupants': 2, 'occupied': True, 'floorAreaM2': 100,
                                        'heatingFuel': 'gas', 'dailyKWh': 20, 'dailyGasM3': .6, 'dailyWaterM3': .4}],
                          'meters': [{'id': 'electric', 'installedAt': '2015-01-01'}],
                          'servicePoints': [{'premiseId': 'P1', 'commodity': 'electric', 'meterId': 'electric',
                                             'installationId': 'I-electric'}]}, 'FINANCE-ACCEPTANCE')
        with world.db() as db:
            meta = world.metadata(db)
        identity = {'environmentId': meta['environment'], 'runId': meta['environment'], 'worldFingerprint': meta['fingerprint']}
        finance.command(world, {'schemaVersion': finance.VERSION, 'commandId': 'configure', **identity,
                                'actorId': 'world-admin', 'expectedRevision': 0, 'effectiveDate': meta['through'],
                                'action': 'configure', 'premiseId': 'P1', 'reason': 'Illustrative acceptance fixture',
                                'causalReference': 'acceptance', 'active': True, 'customerKind': 'household',
                                'recipientRef': 'SIM-P1', 'cashCents': 10000, 'essentialReserveCents': 3000,
                                'maxPaymentCents': 4000, 'paymentProbability': 1})
        assert finance.ready(world)['items'] == []
        # Explicit synthetic fixture of the trusted delivery boundary. This is
        # not an enterprise invoice generator and is never connected to live data.
        delivered = {'schemaVersion': finance.DELIVERY_VERSION, 'deliveryId': 'delivered-fixture', **identity,
                     'premiseId': 'P1', 'recipientRef': 'SIM-P1', 'invoiceId': 'INV-fixture', 'currency': 'USD',
                     'amountCents': 9000, 'dueDate': '2026-01-01', 'deliveredAt': '2026-01-01T00:00:00Z',
                     'kind': 'invoice', 'status': 'delivered'}
        finance.receive_delivery(world, delivered)
        world.advance('2026-01-02')
        intent = finance.ready(world)['items'][0]['intent']
        before = finance.inspect(world, 'P1')
        assert (before['cashCents'], before['reservedCashCents'], before['knownOutstandingCents']) == (10000, 4000, 9000)
        settlement = {'schemaVersion': finance.RECEIPT_VERSION, 'receiptId': 'settled-fixture', **identity,
                      'intentId': intent['id'], 'intentFingerprint': stable(intent), 'status': 'settled',
                      'amountCents': 4000, 'currency': 'USD', 'occurredAt': '2026-01-02T00:00:00Z',
                      'settlementReceiptId': None}
        finance.provider_receipt(world, settlement)
        world = World(world.path)
        finance.provider_receipt(world, settlement)
        settled = finance.inspect(world, 'P1')
        assert (settled['cashCents'], settled['reservedCashCents'], settled['knownOutstandingCents']) == (6000, 0, 5000)
        returned = {**settlement, 'receiptId': 'returned-fixture', 'status': 'returned', 'settlementReceiptId': 'settled-fixture'}
        finance.provider_receipt(world, returned)
        finance.provider_receipt(world, returned)
        final = finance.inspect(world, 'P1')
        assert (final['cashCents'], final['reservedCashCents'], final['knownOutstandingCents']) == (10000, 0, 9000)
        print(json.dumps({'result': 'passed', 'intentCents': intent['amountCents'],
                          'endingCashCents': final['cashCents'], 'knownOutstandingCents': final['knownOutstandingCents'],
                          'enterprisePosting': 'not performed', 'database': 'temporary fixture only'}))


if __name__ == '__main__':
    main()
