import json
from types import SimpleNamespace as NS

from lnrbank.config import Secrets, load_settings
from lnrbank.llm.gigachat import GigaChatProvider, pick_model


class FakeClient:
    def __init__(self, fail_response_format=False):
        self.fail = fail_response_format
        self.requests = []

    def get_models(self):
        return NS(data=[NS(id_="GigaChat"), NS(id_="GigaChat-2-Pro"), NS(id_="GigaChat-2-Max")])

    def chat(self, req):
        self.requests.append(req)
        if req.response_format is not None:
            if self.fail:
                raise RuntimeError("422 response_format unsupported")
            return NS(
                choices=[NS(message=NS(content=json.dumps({"items": []}), function_call=None))]
            )
        return NS(choices=[NS(message=NS(content="", function_call=NS(arguments={"items": []})))])


def provider(client):
    return GigaChatProvider(load_settings(), Secrets(_env_file=None), client=client)


def test_pick_model_prefers_max():
    assert pick_model(["GigaChat", "GigaChat-2-Pro", "GigaChat-2-Max"]) == "GigaChat-2-Max"
    assert pick_model(["GigaChat"]) == "GigaChat"


def test_response_format_path():
    c = FakeClient()
    assert provider(c).complete_json("s", "u", {"type": "object"}) == {"items": []}
    assert c.requests[0].temperature == 0.0


def test_falls_back_to_functions_and_stays_there():
    c = FakeClient(fail_response_format=True)
    p = provider(c)
    assert p.complete_json("s", "u", {"type": "object", "properties": {}}) == {"items": []}
    p.complete_json("s", "u", {"type": "object", "properties": {}})
    assert [r.response_format is not None for r in c.requests] == [True, False, False]
