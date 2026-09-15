"""Decoder compatibility without weakening local output validation."""


def transport_schema(schema):
    """Remove string maxima that can overflow Ollama's grammar expansion.

    Shape, required fields, enums and collection bounds stay in the decoder.
    Callers must validate the response with the original Pydantic model, and
    bound generation with num_predict. This never modifies the source schema.
    """
    def visit(value):
        if isinstance(value, dict):
            return {key: visit(item) for key, item in value.items() if key != 'maxLength'}
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value
    return visit(schema.model_json_schema())
