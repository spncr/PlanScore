import os
import boto3
import json

from . import data, util, constants, observe, preread_followup, postread_calculate

FUNCTION_NAME = os.environ.get('FUNC_NAME_POSTREAD_INTERMEDIATE') or 'PlanScore-PostreadIntermediate'

def lambda_handler(event, context):
    '''
    '''
    s3 = boto3.client('s3')
    lam = boto3.client('lambda')
    storage = data.Storage(s3, event['bucket'], None)
    upload1 = data.Upload.from_dict(event)

    try:
        body = json.loads(event['callback_body'])
    except:
        print(f"Could not read description and incumbents from {event['callback_body']}.")
        description = None
        incumbents = None
        library_metadata = None
    else:
        print(f"Read description and incumbents from {event['callback_body']}...")
        description = body.get('description', None)
        incumbents = body.get('incumbents', None)
        library_metadata = body.get('library_metadata', None)

    upload2 = upload1.clone(
        message = 'Scoring: Starting analysis.',
        description = description,
        incumbents = incumbents,
        library_metadata = library_metadata,
    )

    observe.put_upload_index(storage, upload2)
    upload3 = preread_followup.commence_upload_parsing(s3, lam, event['bucket'], upload2)
    
    next_event = dict(bucket=event['bucket'])
    next_event.update(upload3.to_dict())

    lam.invoke(
        FunctionName=postread_calculate.FUNCTION_NAME,
        InvocationType='Event',
        Payload=json.dumps(next_event).encode('utf8'),
    )
