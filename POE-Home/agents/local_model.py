from agno.models.openai.like import OpenAILike


def get_local_model() -> OpenAILike:
    return OpenAILike(
        id="qwen3.5-4b-poe",
        base_url="http://127.0.0.1:8000/v1",
        api_key="local",
    )
