import boto3

client = boto3.client(
    "dynamodb",
    endpoint_url="http://localhost:8000",
    region_name="us-east-1",
    aws_access_key_id="fake",
    aws_secret_access_key="fake",
)

client.create_table(
    TableName="NyanwatchFailures",
    AttributeDefinitions=[{"AttributeName": "service", "AttributeType": "S"}],
    KeySchema=[{"AttributeName": "service", "KeyType": "HASH"}],
    BillingMode="PAY_PER_REQUEST",
)
