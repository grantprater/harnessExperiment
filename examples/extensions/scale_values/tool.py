"""Minimal extension entry point; no Reticle dependency is needed."""


def execute(arguments, context):
    return [value * arguments['factor'] for value in arguments['values']]
