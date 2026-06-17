from agno.models.openai.like import OpenAILike

from agents.local_model import get_local_model


def test_get_local_model_points_to_loopback_shim():
    model = get_local_model()
    assert isinstance(model, OpenAILike)
    assert model.base_url == "http://127.0.0.1:8000/v1"
    assert model.id == "qwen3.5-4b-poe"
