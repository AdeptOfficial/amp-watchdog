import asyncio

import httpx
import pytest

from app.clients.amp import AMPAuthError, AMPClient, AMPConnectionError


async def test_login_cached_across_calls(amp_client, fake_amp):
    await amp_client.get_instances()
    await amp_client.get_instances()
    assert fake_amp.login_count == 1
    await amp_client.close()


async def test_get_instances_parses_payload(amp_client, fake_amp):
    instances = await amp_client.get_instances()
    by_name = {i.instance_name: i for i in instances}
    assert set(by_name) == {"ADS01", "GracefulGardenGnomes01", "LOCKYOURDOOR01", "tsu01"}
    lyd = by_name["LOCKYOURDOOR01"]
    assert lyd.instance_id == "lyd-guid"
    assert lyd.app_state == 50
    assert lyd.running is True
    assert by_name["tsu01"].running is False
    await amp_client.close()


async def test_session_expiry_triggers_single_relogin(amp_client, fake_amp):
    await amp_client.get_instances()
    fake_amp.expire_sessions()
    instances = await amp_client.get_instances()
    assert len(instances) == 4
    assert fake_amp.login_count == 2
    await amp_client.close()


async def test_permission_failure_raises_after_one_retry(amp_client, fake_amp):
    fake_amp.always_unauthorized = True
    with pytest.raises(AMPAuthError):
        await amp_client.get_instances()
    assert fake_amp.login_count == 2  # initial + one retry, then gives up
    await amp_client.close()


async def test_bad_credentials_raise_auth_error(fake_amp):
    client = AMPClient(
        base_url="http://amp.test:8080",
        username="status-reader",
        password="wrong",
        transport=fake_amp.transport(),
    )
    with pytest.raises(AMPAuthError):
        await client.get_instances()
    await client.close()


async def test_network_error_raises_connection_error(amp_client, fake_amp):
    fake_amp.network_down = True
    with pytest.raises(AMPConnectionError):
        await amp_client.get_instances()
    await amp_client.close()


async def test_concurrent_calls_share_one_login(amp_client, fake_amp):
    await asyncio.gather(*(amp_client.get_instances() for _ in range(5)))
    assert fake_amp.login_count == 1
    await amp_client.close()


async def test_non_json_response_raises_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>bad gateway</html>")

    client = AMPClient(
        base_url="http://amp.test:8080",
        username="u",
        password="p",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AMPConnectionError):
        await client.get_instances()
    await client.close()
