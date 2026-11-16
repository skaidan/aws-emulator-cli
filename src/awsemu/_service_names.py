"""boto3 client names whose score-file (Smithy namespace) name differs by more than hyphens.

Generated from manifest.jsonl + scores.json.gz of the evaluation suite v1.0.0 and
AWS Emulator v1.0.x; anything else maps by dropping hyphens ("cognito-identity" ->
"cognitoidentity").
"""

BOTO_TO_SCORE = {
    "ce": "costexplorer", "cognito-idp": "cognitoidentityprovider", "config": "configservice",
    "cur": "costandusagereportservice", "dms": "databasemigrationservice",
    "ds": "directoryservice", "ds-data": "directoryservicedata", "elb": "elasticloadbalancing",
    "elbv2": "elasticloadbalancingv2", "es": "elasticsearchservice", "events": "eventbridge",
    "iot-data": "iotdataplane", "iot-jobs-data": "iotjobsdataplane", "lexv2-models": "lexmodelsv2",
    "lexv2-runtime": "lexruntimev2", "logs": "cloudwatchlogs",
    "serverlessrepo": "serverlessapplicationrepository", "stepfunctions": "sfn",
}
