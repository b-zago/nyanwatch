import json  # to serialize the fake subjects list into a JSON string
import httpx  # to create fake responses and exceptions
import respx  # to intercept httpx requests so they never hit the real network
import pytest  # for fixtures and monkeypatching
from unittest.mock import MagicMock  # to fake the DynamoDB batch_writer

import main  # the module we're testing

# one minimal subject — no need to test all 50 real URLs
ONE_SERVICE = [{"service": "test-svc", "endpoint": "https://example.com/health"}]


# autouse=True means this fixture runs automatically before every test in this file
@pytest.fixture(autouse=True)
def setup(monkeypatch):
    respx.post(main.WEBHOOK_URL).mock(httpx.Response(200))
    # pretend no services are currently failing in DynamoDB
    monkeypatch.setattr(main, "failed_services", [])

    # override the SSM parameter so main() only processes our one test URL
    monkeypatch.setattr(
        main, "ssmParameter", {"Parameter": {"Value": json.dumps(ONE_SERVICE)}}
    )

    # MagicMock auto-creates any attribute or method you call on it
    mock_batch = MagicMock()

    # batch_writer() is used as a context manager (with statement), so we need __enter__/__exit__
    mock_batch.__enter__ = MagicMock(
        return_value=mock_batch
    )  # "with batch as b" → b is mock_batch
    mock_batch.__exit__ = MagicMock(
        return_value=False
    )  # clean exit, no exception suppression

    # replace the real table.batch_writer with one that returns our mock — no real DynamoDB calls
    monkeypatch.setattr(main.table, "batch_writer", MagicMock(return_value=mock_batch))

    return mock_batch  # tests receive this so they can assert on put_item / delete_item calls


@respx.mock  # intercept all httpx requests inside this test — any unmocked URL raises an error
def test_healthy_service_writes_nothing(setup):
    # when the endpoint returns 200, register what respx should return instead of a real request
    respx.get("https://example.com/health").mock(httpx.Response(200))

    main.lambda_handler(None, None)  # run the actual code

    setup.put_item.assert_not_called()  # a healthy service should not write a failure to DynamoDB


@respx.mock
def test_timeout_writes_failure(setup):
    # simulate the endpoint taking too long — raises TimeoutException instead of returning a response
    respx.get("https://example.com/health").mock(
        side_effect=httpx.TimeoutException("timeout")
    )

    main.lambda_handler(None, None)

    setup.put_item.assert_called_once()  # one failure should have been written
    assert (
        setup.put_item.call_args[0][0]["type"] == "TIMEOUT"
    )  # with the correct failure type


@respx.mock
def test_non_200_writes_failure(setup):
    # simulate the endpoint being reachable but returning an error status
    respx.get("https://example.com/health").mock(httpx.Response(503))

    main.lambda_handler(None, None)

    setup.put_item.assert_called_once()
    assert setup.put_item.call_args[0][0]["type"] == "NOT_OK"


@respx.mock
def test_came_back_to_life(setup, monkeypatch):
    monkeypatch.setattr(main, "failed_services", ["test-svc"])
    monkeypatch.setattr(
        main,
        "failures",
        [
            {
                "service": "test-svc",
                "endpoint": "https://example.com/health",
                "timestamp": main.now.isoformat(),
                "type": "TIMEOUT",
            }
        ],
    )

    respx.get(ONE_SERVICE[0]["endpoint"]).mock(httpx.Response(200))
    main.lambda_handler(None, None)

    setup.delete_item.assert_called_once()
    assert setup.delete_item.call_args[1]["Key"]["service"] == "test-svc"
