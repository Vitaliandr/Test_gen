#тут то, что в тестах подменяем
from sitegen.clients.openrouter import ImageMaker, Llm, chat_json, generate_image


def llm_dep() -> Llm:
    return chat_json


def image_dep() -> ImageMaker:
    return generate_image
