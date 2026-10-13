"""Read-only comparison of baseline physical outcomes in distinct saved worlds.

Companion HTTP-run receipts establish batch sizes and restarts. This comparator
does not certify customer, field, sewer, enterprise or delivery-owner replay.
"""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from utilsim.world.store import canonical, stable

QUERIES = {
    'weather': 'SELECT day,temperature FROM days ORDER BY day',
    'assets': 'SELECT * FROM assets ORDER BY id',
    'physicalDemand': 'SELECT asset,day,quantity FROM truth ORDER BY asset,day',
    'observations': 'SELECT asset,day,device,quantity,status FROM observations ORDER BY asset,day',
    'physicalEvents': 'SELECT day,type,subject,cause,payload FROM events ORDER BY sequence',
    'registerState': 'SELECT device,value FROM observed_register_state ORDER BY device',
    'registerValues': 'SELECT o.asset,o.day,r.value FROM observed_register_values r '
                      'JOIN observations o ON o.id=r.observation ORDER BY o.asset,o.day',
    'registerCache': 'SELECT version,through FROM observed_register_cache ORDER BY singleton',
}


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inspect(path):
    """No World constructor, migration, write connection or full-table materialization."""
    path = Path(path).resolve(strict=True)
    before = file_hash(path)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        meta = {key: json.loads(value) for key, value in db.execute('SELECT key,value FROM meta')}
        if meta['fingerprint'] != stable(meta['snapshot'], meta['environment'], meta['start'],
                                         meta['settings'], meta['modelVersion']):
            raise ValueError('World fingerprint does not match its actual source/settings.')
        if db.execute('SELECT COUNT(*) FROM commands').fetchone()[0]:
            raise ValueError('This baseline comparator excludes worlds with injected commands.')
        for identity, asset, day in db.execute('SELECT id,asset,day FROM observations'):
            if identity != stable(meta['environment'], asset, day, 'observation'):
                raise ValueError('Observation lineage does not belong to its world.')
        for identity, day, kind, subject, payload in db.execute('SELECT id,day,type,subject,payload FROM events'):
            if identity != stable(meta['environment'], day, kind, subject, json.loads(payload)):
                raise ValueError('Event lineage does not belong to its world.')
        projections = {}
        for label, sql in QUERIES.items():
            checksum, count = hashlib.sha256(), 0
            for row in db.execute(sql):
                checksum.update((canonical(row) + '\n').encode())
                count += 1
            projections[label] = {'rows': count, 'sha256': checksum.hexdigest()}
        register_count = db.execute('SELECT COUNT(*) FROM observed_register_values').fetchone()[0]
        if register_count != projections['registerValues']['rows'] or register_count != projections['observations']['rows']:
            raise ValueError('Register records are missing or have no matching observation.')
        summary = {
            'assetConditions': dict(db.execute('SELECT condition,COUNT(*) FROM assets GROUP BY condition')),
            'observationStatuses': dict(db.execute('SELECT status,COUNT(*) FROM observations GROUP BY status')),
            'eventTypes': dict(db.execute('SELECT type,COUNT(*) FROM events GROUP BY type')),
        }
    if file_hash(path) != before:
        raise ValueError('Input database changed during inspection; stop its writer first.')
    return {'path': str(path), 'fileSha256': before, 'environmentId': meta['environment'],
            'worldFingerprint': meta['fingerprint'], 'metadata': {
                key: value for key, value in meta.items() if key not in ('environment', 'fingerprint', 'snapshot')},
            'snapshotSha256': hashlib.sha256(canonical(meta['snapshot']).encode()).hexdigest(),
            'projections': projections, 'summary': summary}


def compare(left, right):
    if Path(left).resolve() == Path(right).resolve():
        raise ValueError('Choose two separate stopped world databases.')
    a, b = inspect(left), inspect(right)
    if a['environmentId'] == b['environmentId']:
        raise ValueError('This acceptance requires independently created world identities.')
    for key in ('metadata', 'snapshotSha256', 'projections', 'summary'):
        if a[key] != b[key]:
            raise ValueError(f'Physical replay differs: {key}.')
    return {'schemaVersion': 'physical-horizon-replay/1', 'status': 'passed',
            'scope': 'baseline weather, metered demand, faults, observations and registers only',
            'distinctWorldLineageVerified': True, 'inputsUnchanged': True, 'left': a, 'right': b}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--left-db', type=Path, required=True)
    parser.add_argument('--right-db', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new result path; existing evidence is preserved.')
    result = compare(args.left_db, args.right_db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(canonical({'status': result['status'], 'inputsUnchanged': True,
                     'projections': result['left']['projections'], 'summary': result['left']['summary']}))


if __name__ == '__main__':
    main()
