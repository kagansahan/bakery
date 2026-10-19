"""
:class:`Tools`: a config section that lists tools (generators, detector simulations, recasters).

A Snakefile imports it explicitly, so the convention is visible where it is used:

.. code-block:: python

    from bakery.tools import Tools

    wf_util.expand_rows("gen", over=Tools("generators", enabled=True))
    wf_util.declare_column("recaster", from_="recasting.name", known=Tools("recasters"))
"""

from .common import parse_bool


class Tools:
    """
    The entries of a config section, read lazily (``load_config`` runs after the recipe is declared).

    The convention: the section is a list of ``{name: ..., enabled: true/false, ...}``. ``name``
    identifies the entry; ``enabled`` is ``false`` when missing (``yes``/``no``/``"false"`` are read
    like ``parse_bool`` does). Entries that are not mappings are skipped.

    :param section: the config section
    :param enabled: ``True`` only enabled entries, ``False`` only disabled ones, ``None`` all
    """

    def __init__(self, section, enabled=None):
        self.section, self.enabled = section, enabled

    def items(self, config):
        out = []
        for item in config.get(self.section) or []:
            if not isinstance(item, dict):
                continue
            if self.enabled is not None and parse_bool(item.get("enabled", False)) != self.enabled:
                continue
            out.append(item)
        return out

    def names(self, config):
        return {i.get("name") for i in self.items(config)}

    def __repr__(self):
        return f"Tools({self.section!r}" + (f", enabled={self.enabled}" if self.enabled is not None else "") + ")"
