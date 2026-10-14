"""
Imposta search_bucket = "ALL" sui profili che non lo hanno.

Gli indici di ricerca utenti (nome, cognome, username) sono sparsi: un profilo
senza search_bucket non compare nella ricerca per prefisso. Succede ai profili
creati prima che l'attributo esistesse.

Idempotente: tocca solo i profili dove l'attributo manca. Senza --apply stampa
soltanto cosa farebbe.

Usage:
    python3 scripts/backfill-search-bucket.py <table_name> <region> [--apply]
    python3 scripts/backfill-search-bucket.py dev-aurabattle-UserProfiles eu-south-1 --apply
"""
import sys
import boto3
from boto3.dynamodb.conditions import Attr


def main():
    args = [a for a in sys.argv[1:] if a != '--apply']
    apply = '--apply' in sys.argv
    if len(args) != 2:
        print(__doc__)
        sys.exit(1)

    table = boto3.resource('dynamodb', region_name=args[1]).Table(args[0])
    scan_kwargs = {
        'FilterExpression': Attr('search_bucket').not_exists(),
        'ProjectionExpression': 'user_id',
    }

    updated = 0
    while True:
        page = table.scan(**scan_kwargs)
        for item in page.get('Items', []):
            print(f"{'UPDATE' if apply else 'would update'} {item['user_id']}")
            if apply:
                table.update_item(
                    Key={'user_id': item['user_id']},
                    UpdateExpression='SET search_bucket = :all',
                    ConditionExpression='attribute_exists(user_id) AND attribute_not_exists(search_bucket)',
                    ExpressionAttributeValues={':all': 'ALL'},
                )
            updated += 1
        if 'LastEvaluatedKey' not in page:
            break
        scan_kwargs['ExclusiveStartKey'] = page['LastEvaluatedKey']

    print(f"{updated} profili {'aggiornati' if apply else 'da aggiornare (usa --apply)'}")


if __name__ == '__main__':
    main()
