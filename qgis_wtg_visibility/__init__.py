# -*- coding: utf-8 -*-
"""QGIS plugin entrypoint."""


def classFactory(iface):
    from .plugin_main import WtgVisibilityPlugin

    return WtgVisibilityPlugin(iface)
