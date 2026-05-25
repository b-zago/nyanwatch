import httpx
import asyncio
import json
import sys
import boto3
import hashlib
import hmac
import os

from pydantic import BaseModel
from datetime import datetime, timezone
from dataclasses import dataclass


class Subject(BaseModel):
    service: str
    endpoint: str


class Payload(BaseModel):
    receiver_id: int
    message: str


TIMEOUT = int(os.environ["TIMEOUT"])  # get from env/config or hardcode
HMAC_KEY = os.environ["HMAC_KEY"]

WEBHOOK_URL = "https://nyanify.zagoapps.com/webhook"
SIG_HEADER = "x-nyanify-signature"
RECEIVER_ID = os.environ["RECEIVER_ID"]

dynamodb = boto3.resource("dynamodb")
ssm = boto3.client("ssm")

table = dynamodb.Table(os.environ["NYANWATCH_TABLE"])

failures = table.scan()["Items"]

failed_services = [service["service"] for service in failures]

now = datetime.now(timezone.utc)

print(failed_services)


async def main():
    parameter = ssm.get_parameter(Name="/nyanwatch/endpoints")
    raw_value = parameter.get("Parameter").get("Value")

    if not raw_value:
        sys.exit("Could not get the SSM Parameter!")

    new_failures = []
    new_healthy = []

    value: list[Subject] = [Subject(**s) for s in json.loads(raw_value)]

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        sem = asyncio.Semaphore(100)

        async def fetch(subject: Subject):
            async with sem:
                wasHealthy = subject.service not in failed_services
                try:
                    r = await client.get(subject.endpoint)
                except httpx.TimeoutException as e:
                    if wasHealthy:
                        new_failures.append(
                            await new_failure(subject, "TIMEOUT", client, svc_err=e)
                        )
                    return
                except httpx.HTTPError as e:
                    if wasHealthy:
                        new_failures.append(
                            await new_failure(subject, "DEAD", client, svc_err=e)
                        )
                    return

                if (r.status_code != 200) and wasHealthy:
                    new_failures.append(
                        await new_failure(
                            subject, "NOT_OK", client, r.status_code, r.text
                        )
                    )
                    return

                if r.status_code == 200 and not wasHealthy:
                    svc_data = next(
                        (svc for svc in failures if svc["service"] == subject.service)
                    )
                    down_at = datetime.fromisoformat(svc_data["timestamp"])
                    down_duration = str(now - down_at)

                    await webhook_send(
                        f"nyaaaa~~\n\n{subject.service} works now! it was down for about {down_duration}\n\nGood job! ^^\n\n{subject}",
                        client,
                    )

                    new_healthy.append(subject.service)

        await asyncio.gather(*(fetch(subject) for subject in value))
        batch_write(new_failures)
        batch_delete(new_healthy)


async def new_failure(
    subject: Subject,
    failure_type: str,
    client: httpx.AsyncClient,
    status=0,
    svc_err="None",
):
    await webhook_send(
        f"OOOPSIEEE\n\n{subject.service} had unexpected response of {status}!\nIt is officially {failure_type} - fixx nowww!!!!\n\n{subject}\n\nERROR: {svc_err}",
        client,
    )
    return {
        "service": subject.service,
        "endpoint": subject.endpoint,
        "timestamp": now.isoformat(),
        "type": failure_type,
    }


def batch_write(new_failures: list):
    with table.batch_writer() as batch:
        for failure in new_failures:
            batch.put_item(failure)


def batch_delete(new_healthy: list):
    with table.batch_writer() as batch:
        for healthy in new_healthy:
            batch.delete_item(Key={"service": healthy})


async def webhook_send(message: str, client: httpx.AsyncClient):
    payload = Payload(receiver_id=RECEIVER_ID, message=message)
    sig = hmac.new(
        HMAC_KEY.encode(), payload.model_dump_json().encode(), hashlib.sha256
    ).hexdigest()
    r = None
    try:
        r = await client.post(
            WEBHOOK_URL,
            headers={SIG_HEADER: sig},
            json=payload.model_dump(),
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        msg = f"Error sending a webhook message: {e}"
        if r is not None:
            msg += f"\n{r.text}"
        print(msg)


def lambda_handler(event, context):
    return asyncio.run(main())
